"""Database, service and API end-to-end scenarios of the schedule generator.

The in-memory solver is exercised elsewhere; here the very same problems go
through the application's own storage and entry points:

* :class:`DbPathAgreementTests` -- harness instances written with
  ``materialize`` (noise rows, a foreign calendar, all three scenario modes)
  and solved through ``generate_ambulance_monthly_schedule`` must agree with
  the in-memory solve on status, validity and first-pass cost.
* :class:`SpecialDayTests` -- the Slovak public-holiday library and the
  workplace's own overrides (``set_special_day`` / ``clear_special_day``)
  decide exactly which dates are staffed and rested from the special slot.
* :class:`ScenarioSwitchTests` -- two scenarios on one workplace; switching
  the selected one changes what the solver reads and what it staffs.
* :class:`ApiEndToEndTests` -- ``POST /ambulances/{id}/schedule/generate``
  through FastAPI's ``TestClient``: 200 with a valid roster, 409 with
  structured issues, 422 on bad input, then save + approve, and the next
  month reads the saved tail as adjacent duties.
* :class:`AutomaticGenerationTests` -- ``run_automatic_generation`` over
  four workplaces sharing staff (one urgent), checked month by month with the
  oracle and hospital-wide by an independent checker written here.

A heavier sweep runs with ``SCHEDULING_STRESS=1``.
"""

from __future__ import annotations

import json
import os
import random
import unittest
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Iterator
from unittest import mock

from fastapi.testclient import TestClient
from pulp import value
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.services.schedule_generation_service as generation_service
from app.core.dependencies import get_current_user
from app.db.session import Base, get_db
from app.main import app
from app.models import (
    Ambulance,
    Competence,
    CompetenceScenario,
    CompetenceWeekdayRequirement,
    Role,
    Schedule,
    SpecialDay,
    Unavailability,
    User,
)
from app.models.associations import UserAmbulance, UserCompetence, UserRole
from app.models.automatic_schedule_generation_run import AutomaticScheduleGenerationRun
from app.schemas.competence import CompetenceUpdate
from app.schemas.competence import CompetenceWeekdayRequirementData as SlotData
from app.schemas.competence_scenario import CompetenceScenarioCreate, CompetenceScenarioUpdate
from app.services.automatic_schedule_generation_service import (
    ordered_ambulances,
    run_automatic_generation,
)
from app.services.competence_scenario_service import (
    create_scenario,
    get_selected_scenario,
    update_scenario,
)
from app.services.competence_service import update_competence
from app.services.schedule_generation_service import (
    ScheduleGenerationError,
    generate_ambulance_monthly_schedule,
)
from app.services.special_day_service import (
    clear_special_day,
    library_rest_days,
    rest_days_between,
    set_special_day,
)

from tests.scheduling_harness.db_builder import (
    InexpressibleInstance,
    fresh_session,
    materialize,
    run_db_solver,
)
from tests.scheduling_harness.instances import (
    Instance,
    Knobs,
    PlantingFailed,
    make_instance,
    pigeonhole_instance,
    sample_knobs,
)
from tests.scheduling_harness.known_bugs import db_bug_triggers
from tests.scheduling_harness.oracle import (
    find_improving_moves,
    first_pass_cost,
    validate,
)
from tests.scheduling_harness.reference import reference_feasibility
from tests.scheduling_harness.runner import PassRecord, SolveOutcome, run_solver
from tests.scheduling_harness.semantics import Duty, balance_lock_slack

STRESS = os.environ.get("SCHEDULING_STRESS") == "1"
#: Never more CBC processes than this at once (another agent shares the machine).
WORKERS = 6
#: Optional JSON file the measured numbers are written to.
REPORT_PATH = os.environ.get("DB_END_TO_END_REPORT")
#: Per-workplace solver budget during automatic generation (the server's own is 7200 s).
AUTOMATIC_BUDGET_SECONDS = 8

#: Days of rest the ``holidays`` library gives Slovakia in 2026. The 2024
#: amendment made 8 May, 1 and 15 September, 28 October and 17 November
#: worked state holidays (see ``special_day_service``), so they are absent.
LIBRARY_2026 = frozenset(
    {
        date(2026, 1, 1),
        date(2026, 1, 6),
        date(2026, 4, 3),
        date(2026, 4, 6),
        date(2026, 5, 1),
        date(2026, 7, 5),
        date(2026, 8, 29),
        date(2026, 11, 1),
        date(2026, 12, 24),
        date(2026, 12, 25),
        date(2026, 12, 26),
    }
)
#: State holidays the library lists as worked days in 2026.
WORKED_STATE_HOLIDAYS_2026 = frozenset(
    {date(2026, 5, 8), date(2026, 9, 1), date(2026, 9, 15), date(2026, 10, 28), date(2026, 11, 17)}
)

SOLVER_ARGUMENT_NAMES = [
    "employees",
    "competences",
    "month",
    "year",
    "adjacent_assignments",
    "fixed_assignments",
    "generate_from",
    "time_budget_seconds",
    "constraints",
]

_REPORT: dict[str, Any] = {}


def _record(section: str, payload: Any) -> None:
    """Keep measured numbers for the report and dump them when asked."""
    _REPORT[section] = payload
    if REPORT_PATH:
        Path(REPORT_PATH).write_text(json.dumps(_REPORT, indent=2, default=str), encoding="utf-8")


# --- Observed solving -------------------------------------------------------------------


def _observer(records: list[PassRecord]) -> Callable:
    """A stand-in for the solver's CBC call that records how each pass ended."""
    original = generation_service._run_solver

    def observed(problem, seconds, close_enough=None):
        original(problem, seconds, close_enough)
        objective = value(problem.objective) if problem.objective is not None else None
        records.append(
            PassRecord(
                kind="balance" if close_enough is None and not records else "wishes",
                objective=float(objective) if objective is not None else None,
                sol_status=int(problem.sol_status),
                time_limit=float(seconds),
                close_enough=close_enough,
            )
        )

    return observed


def _proved(outcome: SolveOutcome) -> bool:
    """Every CBC pass of an observed run ended proved optimal.

    Stricter than ``SolveOutcome.hit_budget``, which only sees passes that
    stopped with a feasible answer (status 2): a second pass that runs out of
    time with nothing found ends with status 0, and the solver then quietly
    returns the first-pass roster with every day wish ignored.
    """
    return bool(outcome.passes) and all(record.optimal for record in outcome.passes)


def _solve_job(job: tuple[str, Instance, float, dict]) -> SolveOutcome:
    """Worker body: one observed solve, in memory or through the database.

    An instance the database cannot store comes back as status
    ``'inexpressible'``.
    """
    where, instance, budget, options = job
    if where == "memory":
        return run_solver(instance, budget, observe=True)
    records: list[PassRecord] = []
    with mock.patch.object(generation_service, "_run_solver", _observer(records)):
        try:
            outcome = run_db_solver(instance, budget, **options)
        except InexpressibleInstance as error:
            return SolveOutcome("inexpressible", error=str(error), budget=budget)
    outcome.passes = records
    return outcome


def _solve_many(jobs: list[tuple[str, Instance, float, dict]]) -> list[SolveOutcome]:
    """Run jobs in at most ``WORKERS`` processes, outcomes in input order."""
    if len(jobs) <= 1:
        return [_solve_job(job) for job in jobs]
    with ProcessPoolExecutor(max_workers=WORKERS) as pool:
        return list(pool.map(_solve_job, jobs))


def _recording_solver(calls: list[dict]) -> Callable:
    """Wrap ``solve_monthly_schedule``: record every call's input and output."""
    original = generation_service.solve_monthly_schedule

    def wrapper(*args, **kwargs):
        call = dict(zip(SOLVER_ARGUMENT_NAMES, args))
        call.update(kwargs)
        entry: dict[str, Any] = {"call": call, "result": None, "error": None}
        calls.append(entry)
        try:
            entry["result"] = original(**call)
        except ScheduleGenerationError as error:
            entry["error"] = error
            raise
        return entry["result"]

    return wrapper


def _instance_from_call(call: dict, label: str) -> Instance:
    """The harness instance describing exactly what the loader handed the solver."""
    return Instance(
        employees=list(call["employees"]),
        competences=list(call["competences"]),
        month=call["month"],
        year=call["year"],
        adjacent=frozenset(call["adjacent_assignments"]),
        fixed=frozenset(call["fixed_assignments"]),
        generate_from=call["generate_from"],
        policy=call["constraints"],
        label=label,
    )


def _capture_input(session: Session, ambulance_id: int, month: int, year: int) -> dict:
    """What the loader would hand the solver, without solving."""
    captured: dict[str, Any] = {}

    def capture(*args, **kwargs):
        captured.update(dict(zip(SOLVER_ARGUMENT_NAMES, args)))
        captured.update(kwargs)
        return []

    with mock.patch.object(generation_service, "solve_monthly_schedule", side_effect=capture):
        generate_ambulance_monthly_schedule(session, ambulance_id, month, year)
    return captured


def _static_session() -> tuple[Any, Session]:
    """A single-connection in-memory database usable from TestClient threads."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)()


def _month_days(month: int, year: int) -> list[date]:
    first = date(year, month, 1)
    days = []
    day = first
    while day.month == month:
        days.append(day)
        day += timedelta(days=1)
    return days


def _week(count: int, recovery: int, hours: float = 4.0, special: int | None = None,
          special_recovery: int | None = None) -> list[SlotData]:
    """Eight slots: every weekday the same, the special slot optionally different."""
    slots = [
        SlotData(weekday=slot, required_count=count, recovery_days=recovery, shift_hours=hours,
                 is_surcharge=slot >= 5)
        for slot in range(7)
    ]
    slots.append(
        SlotData(
            weekday=7,
            required_count=count if special is None else special,
            recovery_days=recovery if special_recovery is None else special_recovery,
            shift_hours=hours,
            is_surcharge=True,
        )
    )
    return slots


def _add_scenario_rows(session: Session, competence_id: int, scenario_id: int, slots: list[SlotData]) -> None:
    for slot in slots:
        session.add(
            CompetenceWeekdayRequirement(
                competence_id=competence_id,
                scenario_id=scenario_id,
                weekday=slot.weekday,
                required_count=slot.required_count,
                is_surcharge=slot.is_surcharge,
                recovery_days=slot.recovery_days,
                shift_hours=slot.shift_hours,
            )
        )


def _simple_workplace(
    session: Session,
    n_people: int,
    slots_by_competence: list[list[SlotData]],
    name: str = "Clinic",
    isurgent: bool = False,
) -> tuple[int, list[int], list[int], int]:
    """A workplace with one selected scenario and fully qualified staff.

    Returns ``(ambulance_id, user_ids, competence_ids, scenario_id)``.
    """
    ambulance = Ambulance(name=name, is_active=True, isurgent=isurgent)
    session.add(ambulance)
    session.flush()
    users = [
        User(email=f"{name.lower()}-{index}@e2e.test", full_name=f"{name} {index}", is_active=True)
        for index in range(n_people)
    ]
    session.add_all(users)
    competences = [
        Competence(name=f"{name} role {index}", required_count=1, ambulance_id=ambulance.id, is_active=True)
        for index in range(len(slots_by_competence))
    ]
    session.add_all(competences)
    scenario = CompetenceScenario(name="Base", ambulance_id=ambulance.id, is_selected=True, is_active=True)
    session.add(scenario)
    session.flush()
    for competence, slots in zip(competences, slots_by_competence):
        _add_scenario_rows(session, competence.id, scenario.id, slots)
    for user in users:
        session.add(UserAmbulance(user_id=user.id, ambulance_id=ambulance.id, is_active=True))
        for competence in competences:
            session.add(UserCompetence(user_id=user.id, competence_id=competence.id, is_active=True))
    session.commit()
    return ambulance.id, [user.id for user in users], [c.id for c in competences], scenario.id


# --- (a) The database path agrees with the in-memory solver --------------------------------

SCENARIO_MODES = ("full", "no_special_slot", "none")


def _mode_knobs(knobs: Knobs, mode: str) -> Knobs:
    """Adapt sampled knobs so the chosen scenario mode can store them."""
    if mode == "no_special_slot":
        return replace(knobs, special_slot_differs=False, target_utilization=None, zero_demand_competences=0)
    if mode == "none":
        return replace(
            knobs,
            demand_profile="flat",
            recovery_profile="one",
            hours_profile="uniform4",
            surcharge_profile="weekend",
            special_slot_differs=False,
            target_utilization=None,
            zero_demand_competences=0,
        )
    return knobs


@dataclass
class AgreementCase:
    """One instance solved both ways."""

    seed: int
    mode: str
    instance: Instance
    planted: bool
    size: str
    options: dict = field(default_factory=dict)


def _agreement_cases(seeds: range, sizes: tuple[str, ...]) -> tuple[list[AgreementCase], Counter]:
    """Seeds become instances; ``mode`` cycles through the scenario modes."""
    cases: list[AgreementCase] = []
    skipped: Counter = Counter()
    for seed in seeds:
        rng = random.Random(7000 + seed)
        size = sizes[seed % len(sizes)]
        planted = seed % 3 != 0
        mode = SCENARIO_MODES[(seed // 3) % 3]
        knobs = _mode_knobs(sample_knobs(rng, size, planted=planted), mode)
        try:
            instance = make_instance(7000 + seed, knobs)
        except PlantingFailed:
            skipped["planting_failed"] += 1
            continue
        # Noise adds an unselected scenario. A workplace with no selected one
        # reads its oldest scenario (``get_selected_scenario``), so under
        # ``none`` the noise scenario itself would be read -- a state the
        # application never creates (its first scenario is always selected).
        options = {"scenario": mode, "noise": mode != "none", "foreign_calendar": True}
        if db_bug_triggers(instance, **options) - {"penalized_rest_month_end", "balance_lock_drift"}:
            skipped["known_bug_trigger"] += 1
            continue
        cases.append(AgreementCase(seed, mode, instance, planted, size, options))
    return cases, skipped


class DbPathAgreementTests(unittest.TestCase):
    """``generate_ambulance_monthly_schedule`` solves exactly the in-memory problem."""

    @classmethod
    def setUpClass(cls) -> None:
        if STRESS:
            seeds, sizes, budget = range(150), ("small", "small", "medium"), 40.0
        else:
            seeds, sizes, budget = range(36), ("small",), 20.0
        cls.budget = budget
        cls.cases, cls.skipped = _agreement_cases(seeds, sizes)
        jobs: list[tuple[str, Instance, float, dict]] = []
        for case in cls.cases:
            jobs.append(("memory", case.instance, budget, {}))
            jobs.append(("db", case.instance, budget, case.options))
        started = perf_counter()
        outcomes = _solve_many(jobs)
        cls.wall = perf_counter() - started
        cls.pairs = [(case, outcomes[2 * i], outcomes[2 * i + 1]) for i, case in enumerate(cls.cases)]

    def test_status_validity_and_cost_agree(self) -> None:
        """Same verdict both ways; valid rosters; equal first-pass cost when both proved."""
        tally: Counter = Counter()
        by_mode: dict[str, Counter] = defaultdict(Counter)
        problems: list[str] = []
        unconfirmed = 0
        for case, memory, db in self.pairs:
            label = f"seed={case.seed} mode={case.mode} {case.instance.label}"
            mode_tally = by_mode[case.mode]
            if db.status == "inexpressible":
                tally["inexpressible"] += 1
                mode_tally["inexpressible"] += 1
                continue
            mode_tally["solved"] += 1
            mode_tally[f"db_{db.status}"] += 1
            tally[f"memory_{memory.status}/db_{db.status}"] += 1
            if db.status == "error" or memory.status == "error":
                problems.append(f"{label}: error memory={memory.error} db={db.error}")
                continue
            if case.planted:
                for where, outcome in (("memory", memory), ("db", db)):
                    if outcome.status == "infeasible":
                        problems.append(f"{label}: planted instance called infeasible ({where})")
            if {memory.status, db.status} == {"ok", "infeasible"}:
                problems.append(f"{label}: status disagrees memory={memory.status} db={db.status}")
            if memory.status == db.status == "infeasible" and not case.planted:
                verdict, _ = reference_feasibility(case.instance, time_limit=60)
                tally[f"reference_{verdict}"] += 1
                if verdict == "unknown":
                    unconfirmed += 1
                elif verdict != "infeasible":
                    problems.append(f"{label}: both said infeasible, reference says {verdict}")
            for where, outcome in (("memory", memory), ("db", db)):
                if outcome.status != "ok":
                    continue
                violations = validate(case.instance, outcome.assignments)
                if violations:
                    problems.append(f"{label} ({where}): {violations[:3]}")
            if memory.status == db.status == "ok" and _proved(memory) and _proved(db):
                tally["cost_compared"] += 1
                cost_memory = first_pass_cost(case.instance, memory.assignments)
                cost_db = first_pass_cost(case.instance, db.assignments)
                if abs(cost_memory - cost_db) > balance_lock_slack(max(cost_memory, cost_db)):
                    problems.append(f"{label}: first-pass cost memory={cost_memory} db={cost_db}")
                if case.planted and case.instance.witness is not None:
                    witness_cost = first_pass_cost(case.instance, case.instance.witness)
                    if cost_db > witness_cost + balance_lock_slack(witness_cost):
                        problems.append(f"{label}: db cost {cost_db} above witness {witness_cost}")
            for outcome in (memory, db):
                if outcome.status == "ok" and not _proved(outcome):
                    tally["not_proved"] += 1
        _record(
            "agreement",
            {
                "pairs": len(self.pairs),
                "skipped": dict(self.skipped),
                "tally": dict(tally),
                "by_mode": {mode: dict(counts) for mode, counts in by_mode.items()},
                "reference_unknown": unconfirmed,
                "wall_seconds": round(self.wall, 1),
            },
        )
        self.assertGreater(tally["cost_compared"], len(self.pairs) // 3, tally)
        self.assertEqual(problems, [])

    def test_db_rosters_leave_no_improving_move(self) -> None:
        """Generic check 5 on the database rosters, against their own observed lock."""
        moves: Counter = Counter()
        problems: list[str] = []
        checked = 0
        for case, _memory, db in self.pairs:
            if db.status != "ok" or not _proved(db) or db.balance_cap is None:
                continue
            checked += 1
            found = find_improving_moves(
                case.instance, db.assignments, max_checks=4000, balance_cap=db.balance_cap
            )
            for move in found:
                moves[move.reason] += 1
                if move.reason in ("first_pass", "day_wish"):
                    problems.append(f"seed={case.seed} mode={case.mode}: {move}")
        _record("db_moves", {"checked": checked, "moves": dict(moves)})
        self.assertGreater(checked, 0)
        self.assertEqual(problems, [])


# --- (b) Slovak public holidays and the workplace's overrides ------------------------------


class SpecialDayTests(unittest.TestCase):
    """The special slot applies on exactly the workplace's days of rest."""

    def test_library_matches_the_documented_2026_calendar(self) -> None:
        """What the library calls a day of rest in 2026, and what it works."""
        self.assertEqual(frozenset(library_rest_days(2026)), LIBRARY_2026)
        self.assertTrue(WORKED_STATE_HOLIDAYS_2026.isdisjoint(library_rest_days(2026)))

    def test_every_month_of_2026_staffs_holidays_from_the_special_slot(self) -> None:
        """One extra person on every library holiday, never on any other date."""
        staffed: dict[int, int] = {}
        for month in range(1, 13):
            with fresh_session() as session:
                ambulance_id, _users, competence_ids, _scenario = _simple_workplace(
                    session, 9, [_week(1, 0, special=2, special_recovery=3)]
                )
                captured = _capture_input(session, ambulance_id, month, 2026)
                days = _month_days(month, 2026)
                span = {days[0] - timedelta(days=d) for d in range(1, 8)} | {
                    days[-1] + timedelta(days=d) for d in range(1, 8)
                } | set(days)
                library = set(library_rest_days(2025)) | set(library_rest_days(2026)) | set(library_rest_days(2027))
                competence = captured["competences"][0]
                self.assertEqual(set(competence.special_dates) & span, library & span, month)
                for day in sorted(span):
                    self.assertEqual(competence.recovery_days_on(day), 3 if day in library else 0, day)
                response = generate_ambulance_monthly_schedule(
                    session, ambulance_id, month, 2026, time_budget_seconds=3
                )
                per_day = Counter(entry.work_date for entry in response.entries)
                expected = {day: 2 if day in LIBRARY_2026 else 1 for day in days}
                self.assertEqual(dict(per_day), expected, month)
                staffed[month] = sum(1 for day in days if per_day[day] == 2)
        self.assertEqual(sum(staffed.values()), len(LIBRARY_2026))
        _record("library_months", staffed)

    def test_harness_library_instances_through_the_database(self) -> None:
        """Planted ``special_days='library'`` instances solve validly through the loader."""
        jobs = []
        months = range(1, 13) if STRESS else (1, 4, 5, 8, 12)
        for month in months:
            knobs = Knobs(
                month=month,
                year=2026,
                n_employees=8,
                n_competences=2,
                special_days="library",
                recovery_profile="mixed",
                hours_profile="mixed",
                demand_profile="weekday",
                unavailability_rate=0.05,
                external_rate=0.03,
                adjacent_rate=0.4,
                planted=True,
            )
            instance = make_instance(500 + month, knobs)
            self.assertEqual(
                instance.special_dates & instance.day_set, LIBRARY_2026 & instance.day_set
            )
            jobs.append(("db", instance, 20.0, {"noise": True, "foreign_calendar": True}))
        outcomes = _solve_many(jobs)
        for (_where, instance, _budget, _options), outcome in zip(jobs, outcomes):
            with self.subTest(month=instance.month):
                self.assertEqual(outcome.status, "ok", outcome.error)
                self.assertEqual(validate(instance, outcome.assignments), [])

    def test_overrides_move_the_special_slot_and_reset_restores_the_library(self) -> None:
        """Added and removed days of rest, one in the margin before the month."""
        with fresh_session() as session:
            ambulance_id, users, competence_ids, _ = _simple_workplace(
                session, 7, [_week(1, 0, special=2, special_recovery=4)]
            )
            margin_day = date(2026, 4, 28)
            veteran = users[0]
            session.add(
                Schedule(
                    user_id=veteran,
                    ambulance_id=ambulance_id,
                    competence_id=competence_ids[0],
                    work_date=margin_day,
                    is_active=True,
                )
            )
            session.commit()

            self.assertIsNone(set_special_day(session, ambulance_id, date(2026, 5, 1), True, "Library"))
            self.assertIsNotNone(set_special_day(session, ambulance_id, date(2026, 5, 8), True, "Victory"))
            self.assertIsNotNone(set_special_day(session, ambulance_id, date(2026, 5, 1), False))
            self.assertIsNotNone(set_special_day(session, ambulance_id, margin_day, True, "Closed"))
            self.assertEqual(session.query(SpecialDay).count(), 3)

            captured = _capture_input(session, ambulance_id, 5, 2026)
            competence = captured["competences"][0]
            self.assertIn(date(2026, 5, 8), competence.special_dates)
            self.assertNotIn(date(2026, 5, 1), competence.special_dates)
            self.assertIn(margin_day, competence.special_dates)
            self.assertEqual(competence.recovery_days_on(margin_day), 4)

            response = generate_ambulance_monthly_schedule(session, ambulance_id, 5, 2026, time_budget_seconds=10)
            per_day = Counter(entry.work_date for entry in response.entries)
            self.assertEqual(per_day[date(2026, 5, 8)], 2)
            self.assertEqual(per_day[date(2026, 5, 1)], 1)
            self.assertEqual(sum(per_day.values()), 31 + 1)
            veteran_days = {entry.work_date for entry in response.entries if entry.user_id == veteran}
            # The margin duty rests from the special slot: 4 days, through 2 May.
            self.assertFalse(veteran_days & {date(2026, 5, 1), date(2026, 5, 2)}, veteran_days)

            clear_special_day(session, ambulance_id, date(2026, 5, 8))
            clear_special_day(session, ambulance_id, date(2026, 5, 1))
            clear_special_day(session, ambulance_id, margin_day)
            self.assertEqual(session.query(SpecialDay).count(), 0)
            back = _capture_input(session, ambulance_id, 5, 2026)["competences"][0]
            self.assertIn(date(2026, 5, 1), back.special_dates)
            self.assertNotIn(date(2026, 5, 8), back.special_dates)
            self.assertEqual(back.recovery_days_on(margin_day), 0)
            response = generate_ambulance_monthly_schedule(session, ambulance_id, 5, 2026, time_budget_seconds=10)
            per_day = Counter(entry.work_date for entry in response.entries)
            self.assertEqual((per_day[date(2026, 5, 1)], per_day[date(2026, 5, 8)]), (2, 1))


class SpecialSlotFallbackTests(unittest.TestCase):
    """A competence saved with the seven weekdays only (no special-slot row)."""

    @unittest.expectedFailure
    def test_holiday_surcharge_matches_what_the_editor_shows(self) -> None:
        """Suspected bug: the loader and the editor disagree on a missing slot 7.

        ``CompetenceCreate`` explicitly accepts the seven weekdays alone (the
        pre-special-day client shape) and then stores no slot-7 row. The
        competence API (``competence_service.weekly_parameters``) and the
        planner (``normalizeWeekdayRequirements``) then show the day of rest
        as surcharged "whatever Sunday says, a day of rest being surcharged
        by definition". The generator's loader (``_slot_value``) answers the
        missing slot with Sunday's row instead, so with an unsurcharged
        Sunday every public holiday is balanced as an ordinary duty -- not
        what the manager sees on the competence screen.
        """
        from app.schemas.competence import CompetenceCreate
        from app.services.competence_scenario_service import ensure_selected_scenario
        from app.services.competence_service import create_competence, list_competence_responses

        with fresh_session() as session:
            ambulance = Ambulance(name="Seven slots", is_active=True)
            session.add(ambulance)
            session.commit()
            ensure_selected_scenario(session, ambulance.id)
            week = [SlotData(weekday=slot, required_count=1, recovery_days=1, shift_hours=4.0, is_surcharge=False)
                    for slot in range(7)]
            create_competence(session, ambulance.id, CompetenceCreate(name="Role", weekday_requirements=week))
            shown = list_competence_responses(session, ambulance.id)[0].weekday_requirements[7].is_surcharge
            loaded = _capture_input(session, ambulance.id, 5, 2026)["competences"][0]
            self.assertTrue(shown)
            self.assertEqual(loaded.is_surcharge_on(date(2026, 5, 1)), shown)


# --- (c) Two scenarios on one workplace -----------------------------------------------------


class ScenarioSwitchTests(unittest.TestCase):
    """Switching the selected scenario switches what the solver reads."""

    def test_switching_scenarios_switches_the_solver_input_and_roster(self) -> None:
        with fresh_session() as session:
            ambulance_id, _users, competence_ids, base_id = _simple_workplace(
                session, 12, [_week(1, 1), _week(1, 0)]
            )
            busy = create_scenario(
                session, ambulance_id, CompetenceScenarioCreate(name="Busy", copy_from_scenario_id=base_id)
            )
            self.assertFalse(busy.is_selected)
            busy_slots = _week(2, 0)
            busy_slots[4] = SlotData(weekday=4, required_count=3, recovery_days=2, shift_hours=12.0, is_surcharge=True)
            update_competence(
                session, competence_ids[0], ambulance_id, CompetenceUpdate(weekday_requirements=busy_slots), busy.id
            )

            def staffed(month: int = 6) -> tuple[Counter, Any]:
                captured = _capture_input(session, ambulance_id, month, 2026)
                response = generate_ambulance_monthly_schedule(
                    session, ambulance_id, month, 2026, time_budget_seconds=5
                )
                counts = Counter(
                    (entry.competence_id, entry.work_date.weekday()) for entry in response.entries
                )
                return counts, captured

            june = _month_days(6, 2026)
            fridays = sum(1 for day in june if day.weekday() == 4)
            weekdays = Counter(day.weekday() for day in june)

            counts, captured = staffed()
            self.assertEqual(get_selected_scenario(session, ambulance_id).id, base_id)
            self.assertEqual(captured["competences"][0].recovery_days_on(date(2026, 6, 5)), 1)
            self.assertEqual(counts[(competence_ids[0], 4)], fridays)

            update_scenario(session, busy.id, ambulance_id, CompetenceScenarioUpdate(is_selected=True))
            counts, captured = staffed()
            loaded = captured["competences"][0]
            self.assertEqual(loaded.recovery_days_on(date(2026, 6, 5)), 2)
            self.assertEqual(loaded.shift_hours_on(date(2026, 6, 5)), 12.0)
            self.assertEqual(loaded.recovery_days_on(date(2026, 6, 4)), 0)
            self.assertEqual(counts[(competence_ids[0], 4)], 3 * fridays)
            self.assertEqual(counts[(competence_ids[0], 0)], 2 * weekdays[0])
            # The second competence was copied, not edited: unchanged.
            self.assertEqual(counts[(competence_ids[1], 0)], weekdays[0])
            ordered = ordered_ambulances(session, 2026, 6)
            self.assertEqual([item.id for item in ordered], [ambulance_id])

            update_scenario(session, base_id, ambulance_id, CompetenceScenarioUpdate(is_selected=True))
            counts, captured = staffed()
            self.assertEqual(captured["competences"][0].recovery_days_on(date(2026, 6, 5)), 1)
            self.assertEqual(counts[(competence_ids[0], 4)], fridays)


# --- (d) The HTTP endpoint -------------------------------------------------------------------


class ApiEndToEndTests(unittest.TestCase):
    """``POST /ambulances/{id}/schedule/generate`` and what follows it."""

    def setUp(self) -> None:
        self.engine, self.db = _static_session()
        role = Role(code="ADMIN_E2E", name="Admin", level=3, is_active=True)
        self.admin = User(email="admin@e2e.test", full_name="Admin", is_active=True)
        self.db.add_all([role, self.admin])
        self.db.flush()
        self.db.add(UserRole(user_id=self.admin.id, role_id=role.id))
        self.db.commit()
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_current_user] = lambda: self.admin
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.db.close()
        self.engine.dispose()

    def _generate(self, ambulance_id: int, month: int, year: int, body: dict | None = None):
        return self.client.post(
            f"/ambulances/{ambulance_id}/schedule/generate",
            params={"month": month, "year": year},
            json=body if body is not None else {"time_budget_seconds": 5},
        )

    def test_generate_save_approve_and_the_next_month_reads_the_tail(self) -> None:
        instance = make_instance(
            31,
            Knobs(
                n_employees=9,
                n_competences=2,
                month=8,
                year=2026,
                recovery_profile="mixed",
                hours_profile="mixed",
                special_days="library",
                unavailability_rate=0.05,
                preferred_rate=0.05,
                soft_decline_rate=0.05,
                external_rate=0.02,
                planted=True,
            ),
        )
        world = materialize(instance, self.db, noise=True)
        calls: list[dict] = []
        with mock.patch.object(generation_service, "solve_monthly_schedule", _recording_solver(calls)):
            response = self._generate(world.ambulance_id, 8, 2026)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual((body["month"], body["year"]), (8, 2026))
        self.assertEqual(body["assignment_count"], len(body["entries"]))
        august = world.to_instance_tuples(
            [(e["user_id"], e["competence_id"], date.fromisoformat(e["work_date"])) for e in body["entries"]]
        )
        self.assertEqual(validate(instance, august), [])
        self.assertEqual(self.db.query(Schedule).filter(Schedule.ambulance_id == world.ambulance_id,
                                                         Schedule.work_date >= date(2026, 8, 1)).count(), 0)

        saved = self.client.put(
            f"/ambulances/{world.ambulance_id}/schedule",
            params={"month": 8, "year": 2026},
            json={"entries": [
                {"user_id": e["user_id"], "competence_id": e["competence_id"], "work_date": e["work_date"]}
                for e in body["entries"]
            ]},
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        approved = self.client.post(
            f"/ambulances/{world.ambulance_id}/schedule/approve", params={"month": 8, "year": 2026}
        )
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertTrue(approved.json()["is_approved"])
        self.assertEqual(approved.json()["approved_entry_count"], len(body["entries"]))

        calls.clear()
        with mock.patch.object(generation_service, "solve_monthly_schedule", _recording_solver(calls)):
            september = self._generate(world.ambulance_id, 9, 2026)
        self.assertEqual(september.status_code, 200, september.text)
        call = calls[-1]["call"]
        tail = {
            (e["user_id"], e["competence_id"], date.fromisoformat(e["work_date"]))
            for e in body["entries"]
            if date.fromisoformat(e["work_date"]) >= date(2026, 8, 25)
        }
        self.assertTrue(tail)
        self.assertTrue(tail <= set(call["adjacent_assignments"]))
        next_instance = _instance_from_call(call, "september")
        roster = [
            (e["user_id"], e["competence_id"], date.fromisoformat(e["work_date"]))
            for e in september.json()["entries"]
        ]
        self.assertEqual(validate(next_instance, roster), [])
        # Independent of the oracle: nobody starts September inside an August rest.
        competences = {c.id: c for c in next_instance.competences}
        for user_id, competence_id, day in tail:
            rest = competences[competence_id].recovery_days_on(day)
            for user, _competence, work_date in roster:
                if user == user_id:
                    self.assertFalse(day < work_date <= day + timedelta(days=rest), (user_id, day, work_date))

    def test_infeasible_month_answers_409_with_structured_issues(self) -> None:
        world = materialize(pigeonhole_instance(), self.db)
        response = self._generate(world.ambulance_id, pigeonhole_instance().month, pigeonhole_instance().year)
        self.assertEqual(response.status_code, 409, response.text)
        detail = response.json()["detail"]
        self.assertIsInstance(detail["message"], str)
        self.assertTrue(detail["issues"])
        for issue in detail["issues"]:
            self.assertIn("code", issue)
        self.assertIn("insufficient_qualified_staff", {issue["code"] for issue in detail["issues"]})
        self.assertEqual(self.db.query(Schedule).count(), 0)

    def test_bad_input_answers_422(self) -> None:
        instance = make_instance(3, Knobs(n_employees=5, month=8, year=2026, planted=True))
        world = materialize(instance, self.db)
        user = world.user_ids[instance.employees[0].id]
        competence = world.competence_ids[instance.competences[0].id]
        cases = {
            "month 13": ({"month": 13, "year": 2026}, {}),
            "year 1999": ({"month": 8, "year": 1999}, {}),
            "budget too small": ({"month": 8, "year": 2026}, {"time_budget_seconds": 2}),
            "budget too large": ({"month": 8, "year": 2026}, {"time_budget_seconds": 5000}),
            "fixed entry outside month": (
                {"month": 8, "year": 2026},
                {"fixed_entries": [{"user_id": user, "competence_id": competence, "work_date": "2026-09-01"}]},
            ),
            "generate_from outside month": ({"month": 8, "year": 2026}, {"generate_from": "2026-07-31"}),
            "malformed date": ({"month": 8, "year": 2026}, {"generate_from": "2026-08-32"}),
        }
        for name, (params, body) in cases.items():
            with self.subTest(name):
                response = self.client.post(
                    f"/ambulances/{world.ambulance_id}/schedule/generate", params=params, json=body
                )
                self.assertEqual(response.status_code, 422, response.text)
        missing = self.client.post(
            f"/ambulances/{world.ambulance_id + 999}/schedule/generate", params={"month": 8, "year": 2026}, json={}
        )
        self.assertEqual(missing.status_code, 404)

    def test_fixed_entries_and_generate_from_over_http(self) -> None:
        """Manual placements are kept and the history is not rewritten."""
        instance = make_instance(
            44,
            Knobs(n_employees=8, n_competences=2, month=10, year=2026, recovery_profile="mixed",
                  generate_from=12, keep_history=1.0, n_fixed=3, planted=True),
        )
        world = materialize(instance, self.db, noise=True)
        body = {
            "time_budget_seconds": 10,
            "generate_from": instance.generate_from.isoformat(),
            "fixed_entries": [
                {"user_id": u, "competence_id": c, "work_date": d.isoformat()}
                for u, c, d in world.fixed_entries_for_db(instance)
            ],
        }
        response = self._generate(world.ambulance_id, 10, 2026, body)
        self.assertEqual(response.status_code, 200, response.text)
        roster = world.to_instance_tuples(
            [(e["user_id"], e["competence_id"], date.fromisoformat(e["work_date"])) for e in response.json()["entries"]]
        )
        self.assertEqual(validate(instance, roster), [])


# --- (e) Automatic generation over a hospital ---------------------------------------------


@dataclass
class Hospital:
    """What the test wrote, kept so the hospital-wide check never asks the app."""

    names: dict[int, str] = field(default_factory=dict)
    urgent: set[int] = field(default_factory=set)
    demand: dict[int, int] = field(default_factory=dict)
    members: dict[int, set[int]] = field(default_factory=dict)
    slots: dict[int, dict[int, tuple[int, int, float]]] = field(default_factory=dict)
    competence_ambulance: dict[int, int] = field(default_factory=dict)
    qualified: set[tuple[int, int]] = field(default_factory=set)
    rest_days: dict[int, set[date]] = field(default_factory=dict)
    hard_absences: set[tuple[int, date]] = field(default_factory=set)


def _library_between(first: date, last: date) -> set[date]:
    found: set[date] = set()
    for year in range(first.year, last.year + 1):
        found |= {day for day in library_rest_days(year) if first <= day <= last}
    return found


def _build_hospital(session: Session, seed: int, months: list[tuple[int, int]],
                    infeasible_small: bool = False) -> Hospital:
    """Four workplaces sharing staff: big, mid, small and an urgent one.

    The urgent workplace's staff all come from the big and the mid one, and
    every member of it holds both of its roles. Each workplace has its own
    calendar override, and slots differ in count, rest and hours.
    """
    rng = random.Random(seed)
    hospital = Hospital()
    people = [
        User(email=f"p{index}@hospital.test", full_name=f"Person {index}", is_active=True,
             max_shifts_per_month=rng.choice([None, None, 0, 12]))
        for index in range(32)
    ]
    session.add_all(people)
    session.flush()
    ids = [person.id for person in people]
    plan = [
        ("Big", False, ids[0:14], [(2, (0, 1, 2)), (1, (1, 2))]),
        ("Mid", False, ids[11:23], [(1, (1,)), (1, (0, 1))]),
        ("Small", False, ids[21:27] if not infeasible_small else ids[21:22], [(1, (1,))]),
        ("Urgent", True, ids[2:8] + ids[14:18] + ids[27:32], [(1, (1,)), (1, (0, 1))]),
    ]
    first = date(months[0][1], months[0][0], 1) - timedelta(days=8)
    last_month = months[-1]
    last = _month_days(*last_month)[-1] + timedelta(days=8)
    library = _library_between(first, last)
    for name, urgent, members, roles in plan:
        ambulance = Ambulance(name=name, is_active=True, isurgent=urgent)
        session.add(ambulance)
        session.flush()
        hospital.names[ambulance.id] = name
        if urgent:
            hospital.urgent.add(ambulance.id)
        hospital.members[ambulance.id] = set(members)
        scenario = CompetenceScenario(name="Base", ambulance_id=ambulance.id, is_selected=True, is_active=True)
        session.add(scenario)
        session.flush()
        competence_rows = []
        for index, (count, recoveries) in enumerate(roles):
            competence = Competence(name=f"{name} {index}", required_count=1, ambulance_id=ambulance.id,
                                    is_active=True)
            session.add(competence)
            session.flush()
            competence_rows.append(competence)
            hospital.competence_ambulance[competence.id] = ambulance.id
            table: dict[int, tuple[int, int, float]] = {}
            for slot in range(8):
                weekend = slot >= 5
                slot_count = count if not (weekend and count > 1) else count - 1
                recovery = rng.choice(recoveries) if slot < 7 else max(recoveries)
                hours = rng.choice([4.0, 8.0, 12.0]) if slot < 7 else 12.0
                table[slot] = (slot_count, recovery, hours)
                session.add(CompetenceWeekdayRequirement(
                    competence_id=competence.id, scenario_id=scenario.id, weekday=slot,
                    required_count=slot_count, is_surcharge=slot >= 5, recovery_days=recovery,
                    shift_hours=hours))
            hospital.slots[competence.id] = table
        for user_id in members:
            session.add(UserAmbulance(user_id=user_id, ambulance_id=ambulance.id, is_active=True))
            held = [c for c in competence_rows if urgent or rng.random() < 0.8] or [competence_rows[0]]
            if name == "Small":
                held = competence_rows
            for competence in held:
                session.add(UserCompetence(user_id=user_id, competence_id=competence.id, is_active=True))
                hospital.qualified.add((user_id, competence.id))
        # Each workplace corrects the library its own way.
        override_day = date(months[0][1], months[0][0], 10 + len(hospital.names))
        session.add(SpecialDay(ambulance_id=ambulance.id, day=override_day, is_rest_day=True, name="Own"))
        removed = sorted(library)[len(hospital.names) % max(1, len(library))] if library else None
        overrides = {override_day: True}
        if removed is not None and name in ("Mid", "Urgent"):
            session.add(SpecialDay(ambulance_id=ambulance.id, day=removed, is_rest_day=False))
            overrides[removed] = False
        rest = set(library)
        for day, is_rest in overrides.items():
            (rest.add if is_rest else rest.discard)(day)
        hospital.rest_days[ambulance.id] = rest
    for user_id in ids:
        for month, year in months:
            for day in _month_days(month, year):
                if rng.random() < 0.04:
                    reason = rng.choice(["UNAVAILABLE", "VACATION", "SOFT_DECLINE", "PREFERRED"])
                    session.add(Unavailability(user_id=user_id, date_absent=day, reason=reason, is_active=True))
                    if reason in ("UNAVAILABLE", "VACATION"):
                        hospital.hard_absences.add((user_id, day))
    session.commit()
    for ambulance_id in hospital.names:
        total = 0
        for competence_id, ambulance in hospital.competence_ambulance.items():
            if ambulance != ambulance_id:
                continue
            for day in _month_days(*months[0]):
                slot = 7 if day in hospital.rest_days[ambulance_id] else day.weekday()
                total += hospital.slots[competence_id][slot][0]
        hospital.demand[ambulance_id] = total
    return hospital


def _hospital_violations(session: Session, hospital: Hospital, first: date, last: date) -> list[str]:
    """Independent hospital-wide check over every active duty between two dates.

    Rest comes from the tables the test wrote, each duty read on its own
    workplace's calendar: no person on two workplaces (or two roles) the same
    day, nobody starting a duty on a day an earlier one still holds, only
    members and qualified people, nobody on a hard absence.
    """
    rows = (
        session.query(Schedule.user_id, Schedule.ambulance_id, Schedule.competence_id, Schedule.work_date)
        .filter(Schedule.is_active.is_(True), Schedule.work_date.between(first, last))
        .all()
    )
    problems: list[str] = []
    by_user: dict[int, list[tuple[date, int, int]]] = defaultdict(list)
    for user_id, ambulance_id, competence_id, work_date in rows:
        by_user[user_id].append((work_date, ambulance_id, competence_id))
        if user_id not in hospital.members[ambulance_id]:
            problems.append(f"non-member {user_id} at {hospital.names[ambulance_id]} {work_date}")
        if (user_id, competence_id) not in hospital.qualified:
            problems.append(f"unqualified {user_id} in {competence_id} {work_date}")
        if (user_id, work_date) in hospital.hard_absences:
            problems.append(f"absent {user_id} worked {work_date}")
    for user_id, duties in by_user.items():
        duties.sort()
        for index, (day, ambulance_id, competence_id) in enumerate(duties):
            slot = 7 if day in hospital.rest_days[ambulance_id] else day.weekday()
            rest = hospital.slots[competence_id][slot][1]
            for later_day, later_ambulance, _later_competence in duties[index + 1:]:
                if later_day == day:
                    problems.append(
                        f"user {user_id} twice on {day}: {hospital.names[ambulance_id]} and "
                        f"{hospital.names[later_ambulance]}"
                    )
                elif later_day <= day + timedelta(days=rest):
                    problems.append(
                        f"user {user_id} rest: {hospital.names[ambulance_id]} {day} (rest {rest}) then "
                        f"{hospital.names[later_ambulance]} {later_day}"
                    )
                else:
                    break
    return problems


class AutomaticOrderingDemandTests(unittest.TestCase):
    """How automatic generation sizes a workplace."""

    @unittest.expectedFailure
    def test_holiday_demand_counts_towards_the_size(self) -> None:
        """Suspected bug (low): the ordering ignores the special-day slot.

        ``_monthly_demand`` is documented as "the target month's required duty
        slots" but reads every date from its weekday row, also the days of
        rest that the generator staffs from slot 7. In December 2026 (24-26
        are holidays) a workplace asking 1 a day and 12 on holidays needs
        28 + 36 = 64 duties, one asking 2 a day and none on holidays
        28 * 2 = 56; the first is the larger one but is generated second.
        """
        with fresh_session() as session:
            holiday_heavy, *_ = _simple_workplace(session, 14, [_week(1, 0, special=12)], name="Holiday")
            steady, *_ = _simple_workplace(session, 14, [_week(2, 0, special=0)], name="Steady")
            for ambulance_id in (holiday_heavy, steady):
                captured = _capture_input(session, ambulance_id, 12, 2026)
                competence = captured["competences"][0]
                needed = sum(competence.required_on(day) for day in _month_days(12, 2026))
                self.assertEqual(needed, 64 if ambulance_id == holiday_heavy else 56)
            order = [item.id for item in ordered_ambulances(session, 2026, 12)]
            self.assertEqual(order, [holiday_heavy, steady])


class AutomaticGenerationTests(unittest.TestCase):
    """``run_automatic_generation`` over workplaces sharing their people."""

    def _run_months(self, seed: int, months: list[tuple[int, int]], infeasible_small: bool = False) -> dict:
        with fresh_session() as session:
            hospital = _build_hospital(session, seed, months, infeasible_small)
            calls: list[dict] = []
            results = []
            passes: list[PassRecord] = []
            started = perf_counter()
            # The server default is two hours per workplace; validity, not
            # optimality, is what is checked here.
            with mock.patch.object(generation_service, "solve_monthly_schedule", _recording_solver(calls)), \
                    mock.patch.object(generation_service, "_run_solver", _observer(passes)), \
                    mock.patch.object(generation_service.settings, "SCHEDULE_SOLVER_TIME_LIMIT_SECONDS",
                                      AUTOMATIC_BUDGET_SECONDS):
                for month, year in months:
                    results.append(run_automatic_generation(session, year, month))
            wall = perf_counter() - started
            expected_order = sorted(
                hospital.names,
                key=lambda a: (a in hospital.urgent, -hospital.demand[a], -len(hospital.members[a]), a),
            )
            first = date(months[0][1], months[0][0], 1)
            last = _month_days(*months[-1])[-1]
            violations = _hospital_violations(session, hospital, first, last)
            invalid: list[str] = []
            solved = 0
            for index, entry in enumerate(calls):
                if entry["result"] is None:
                    continue
                solved += 1
                instance = _instance_from_call(entry["call"], f"call {index}")
                found = validate(instance, entry["result"])
                if found:
                    invalid.append(f"call {index} month {instance.month}: {found[:3]}")
            runs = session.query(AutomaticScheduleGenerationRun).order_by(AutomaticScheduleGenerationRun.id).all()
            drafts = session.query(Schedule).filter(Schedule.is_approved.is_(True)).count()
            return {
                "hospital": hospital,
                "results": results,
                "expected_order": expected_order,
                "violations": violations,
                "invalid": invalid,
                "solved": solved,
                "runs": [(run.status, run.summary) for run in runs],
                "approved_rows": drafts,
                "wall": wall,
                "stopped_early_passes": sum(record.stopped_early for record in passes),
            }

    def test_four_workplaces_two_months(self) -> None:
        """Ordering, every month valid, and hospital-wide rules across both months."""
        seeds = range(4) if STRESS else range(1)
        summary = []
        for seed in seeds:
            outcome = self._run_months(seed, [(11, 2026), (12, 2026)])
            with self.subTest(seed=seed):
                hospital = outcome["hospital"]
                for result in outcome["results"]:
                    self.assertIsNotNone(result)
                    self.assertEqual(list(result.ordered_ambulance_ids), outcome["expected_order"])
                    self.assertEqual(result.ordered_ambulance_ids[-1], next(iter(hospital.urgent)))
                    self.assertEqual(result.failed_ambulance_ids, ())
                self.assertEqual([status for status, _ in outcome["runs"]], ["COMPLETED", "COMPLETED"])
                self.assertEqual(outcome["solved"], 8)
                self.assertEqual(outcome["invalid"], [])
                self.assertEqual(outcome["violations"], [])
                self.assertEqual(outcome["approved_rows"], 0)
            summary.append({"seed": seed, "wall": round(outcome["wall"], 1), "solved": outcome["solved"],
                            "stopped_early_passes": outcome["stopped_early_passes"],
                            "violations": len(outcome["violations"]), "invalid": len(outcome["invalid"])})
        _record("automatic", summary)

    def test_a_failing_workplace_leaves_the_others_saved(self) -> None:
        """One infeasible workplace: PARTIAL run, its failure recorded, the rest consistent."""
        outcome = self._run_months(11, [(11, 2026)], infeasible_small=True)
        result = outcome["results"][0]
        hospital = outcome["hospital"]
        small = next(a for a, name in hospital.names.items() if name == "Small")
        self.assertEqual(result.failed_ambulance_ids, (small,))
        self.assertEqual(len(result.successful_ambulance_ids), 3)
        status, run_summary = outcome["runs"][0]
        self.assertEqual(status, "PARTIAL")
        failure = run_summary["failures"][0]
        self.assertEqual(failure["ambulance_id"], small)
        self.assertTrue(failure["issues"])
        self.assertEqual(outcome["invalid"], [])
        self.assertEqual(outcome["violations"], [])


if __name__ == "__main__":
    unittest.main()
