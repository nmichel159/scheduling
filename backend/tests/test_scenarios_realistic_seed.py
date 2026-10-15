"""The demo hospital, seeded by the real generator, judged by the harness.

``config_1`` seeds I.KAIM (57 people, 7 roles), II.KAIM, KDAIM and the urgent
KUM, whose people are borrowed from both KAIMs, and builds every month of
2026 up to October with ``generate_ambulance_monthly_schedule`` -- 40 months
solved by the real MILP, each against the duties already stored. The seed is
run into an in-memory SQLite database (as ``tests/test_database_reset.py``
does) with ``solve_monthly_schedule`` wrapped to record every month's input,
output and CBC passes. Each month then becomes a harness ``Instance``:

* every roster must validate,
* per department-month quality metrics are tabulated,
* the seeded rosters (and a re-solved sample) must leave no improving move
  the solver should have found (generic check 5; skipped when a pass hit
  its time budget),
* all seeded schedules must be consistent hospital-wide (no one twice a day
  anywhere, rest after a duty elsewhere, membership, qualification,
  absences), checked by an independent reader written here.

Seeding all 40 months takes about 200 s, so the default run seeds the same
profile restricted to January-March (12 months; months before the last are
solved against exactly what the full seed gives them). ``config_2`` declares
no generated schedules at all, so it is only checked for consistency.
``SCHEDULING_STRESS=1`` seeds the full ``config_1`` and ``config_2``.
"""

from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import statistics
import unittest
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from time import perf_counter
from typing import Any
from unittest import mock

from pulp import value
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.services.schedule_generation_service as generation_service
from app.db import seed
from app.db.session import Base
from app.models import (
    Ambulance,
    Competence,
    CompetenceScenario,
    CompetenceWeekdayRequirement,
    Schedule,
    SpecialDay,
    Unavailability,
    User,
)
from app.models.associations import UserAmbulance, UserCompetence
from app.services.special_day_service import library_rest_days

from tests.scheduling_harness.instances import Instance
from tests.scheduling_harness.oracle import find_improving_moves, first_pass_cost, metrics, validate
from tests.scheduling_harness.runner import PassRecord, solve_in_parallel
from tests.scheduling_harness.semantics import Duty, as_duties, balance_lock_slack

STRESS = os.environ.get("SCHEDULING_STRESS") == "1"
WORKERS = 6
REPORT_PATH = os.environ.get("REALISTIC_SEED_REPORT")
#: Months of 2026 the default run seeds (every workplace).
DEFAULT_MONTHS = (1, 2, 3)
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
#: Reasons that are wishes, not absences (the loader's exact spellings).
WISH_REASONS = {"PREFERRED", "SOFT_DECLINE"}
DEFAULT_REST = 1

_REPORT: dict[str, Any] = {}


def _record(section: str, payload: Any) -> None:
    _REPORT[section] = payload
    if REPORT_PATH:
        Path(REPORT_PATH).write_text(json.dumps(_REPORT, indent=2, default=str), encoding="utf-8")


def _proved(passes: list[PassRecord]) -> bool:
    """Every CBC pass ended proved optimal (status 0 "nothing found in time" counts as a budget hit)."""
    return bool(passes) and all(record.optimal for record in passes)


@dataclass
class SeededMonth:
    """One generated month as the seed solved it."""

    ambulance: str
    instance: Instance
    roster: list[Duty]
    seconds: float
    passes: list[PassRecord]

    @property
    def hit_budget(self) -> bool:
        """Some pass ended unproved (stopped early, or nothing found in time)."""
        return not _proved(self.passes)

    @property
    def balance_cap(self) -> float | None:
        first = next((r for r in self.passes if r.kind == "balance"), None)
        if first is None or first.objective is None:
            return None
        return first.objective + balance_lock_slack(first.objective)


@dataclass
class SeedRun:
    """A seeded database and everything recorded on the way."""

    engine: Any
    factory: Any
    months: list[SeededMonth] = field(default_factory=list)
    seconds: float = 0.0


def _profile(config_name: str, months: tuple[int, ...] | None) -> dict:
    """The profile, optionally restricted to some months of generation."""
    profile = copy.deepcopy(seed.SEED_CONFIGS[config_name])
    if months is not None and "generated_schedules" in profile:
        profile["generated_schedules"] = [
            request for request in profile["generated_schedules"] if request["month"] in months
        ]
    return profile


def seed_and_record(config_name: str, months: tuple[int, ...] | None = None) -> SeedRun:
    """Seed into a fresh in-memory database, recording every generated month."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    profile = _profile(config_name, months)
    requests = list(profile.get("generated_schedules", []))
    run = SeedRun(engine, factory)
    original_solve = generation_service.solve_monthly_schedule
    original_cbc = generation_service._run_solver
    passes: list[PassRecord] = []

    def observed(problem, seconds, close_enough=None):
        original_cbc(problem, seconds, close_enough)
        objective = value(problem.objective) if problem.objective is not None else None
        passes.append(
            PassRecord(
                kind="balance" if close_enough is None and not passes else "wishes",
                objective=float(objective) if objective is not None else None,
                sol_status=int(problem.sol_status),
                time_limit=float(seconds),
                close_enough=close_enough,
            )
        )

    def wrapper(*args, **kwargs):
        call = dict(zip(SOLVER_ARGUMENT_NAMES, args))
        call.update(kwargs)
        passes.clear()
        started = perf_counter()
        result = original_solve(**call)
        request = requests[len(run.months)]
        instance = Instance(
            employees=list(call["employees"]),
            competences=list(call["competences"]),
            month=call["month"],
            year=call["year"],
            adjacent=frozenset(call["adjacent_assignments"]),
            fixed=frozenset(call["fixed_assignments"]),
            generate_from=call["generate_from"],
            policy=call["constraints"],
            label=f"{request['ambulance_name']} {call['year']}-{call['month']:02d}",
        )
        run.months.append(
            SeededMonth(request["ambulance_name"], instance, as_duties(result), perf_counter() - started,
                        list(passes))
        )
        return result

    name = f"{config_name}_harness"
    started = perf_counter()
    with mock.patch.dict(seed.SEED_CONFIGS, {name: profile}), \
            mock.patch.object(seed, "engine", engine), \
            mock.patch.object(seed, "SessionLocal", factory), \
            mock.patch.object(generation_service, "solve_monthly_schedule", wrapper), \
            mock.patch.object(generation_service, "_run_solver", observed), \
            contextlib.redirect_stdout(io.StringIO()):
        seed.seed_db(name)
    run.seconds = perf_counter() - started
    return run


# --- Hospital-wide consistency, read independently ---------------------------------------


def hospital_violations(session: Session) -> tuple[list[str], Counter]:
    """Every rule that must hold across workplaces, over all active duties.

    Rest is read from each workplace's selected scenario row for the duty's
    slot (the default one day when it has none), the slot from that
    workplace's own calendar: the holiday library plus its overrides.
    """
    stats: Counter = Counter()
    problems: list[str] = []
    names = {a.id: a.name for a in session.query(Ambulance).all()}
    selected: dict[int, int] = {}
    for scenario in session.query(CompetenceScenario).filter(CompetenceScenario.is_active.is_(True)).order_by(
        CompetenceScenario.id
    ):
        if scenario.ambulance_id not in selected or scenario.is_selected:
            selected[scenario.ambulance_id] = scenario.id
    rows_by_slot: dict[tuple[int, int], int] = {}
    competence_ambulance = {c.id: c.ambulance_id for c in session.query(Competence).all()}
    for row in session.query(CompetenceWeekdayRequirement).all():
        if selected.get(competence_ambulance.get(row.competence_id)) == row.scenario_id:
            rows_by_slot[(row.competence_id, row.weekday)] = row.recovery_days
    overrides: dict[int, dict[date, bool]] = defaultdict(dict)
    for override in session.query(SpecialDay).all():
        overrides[override.ambulance_id][override.day] = bool(override.is_rest_day)
    library_cache: dict[int, set[date]] = {}

    def is_rest_day(ambulance_id: int, day: date) -> bool:
        if day in overrides[ambulance_id]:
            return overrides[ambulance_id][day]
        if day.year not in library_cache:
            library_cache[day.year] = set(library_rest_days(day.year))
        return day in library_cache[day.year]

    def rest_of(ambulance_id: int, competence_id: int, day: date) -> int:
        slot = 7 if is_rest_day(ambulance_id, day) else day.weekday()
        if (competence_id, slot) in rows_by_slot:
            return rows_by_slot[(competence_id, slot)]
        if slot == 7 and (competence_id, 6) in rows_by_slot:
            return rows_by_slot[(competence_id, 6)]
        return DEFAULT_REST

    members = {
        (m.user_id, m.ambulance_id)
        for m in session.query(UserAmbulance).filter(UserAmbulance.is_active.is_(True))
    }
    qualified = {
        (q.user_id, q.competence_id)
        for q in session.query(UserCompetence).filter(UserCompetence.is_active.is_(True))
    }
    absent = {
        (u.user_id, u.date_absent)
        for u in session.query(Unavailability).filter(Unavailability.is_active.is_(True))
        if (u.reason or "") not in WISH_REASONS
    }
    active_users = {u.id for u in session.query(User).filter(User.is_active.is_(True))}
    duties = (
        session.query(Schedule.user_id, Schedule.ambulance_id, Schedule.competence_id, Schedule.work_date)
        .filter(Schedule.is_active.is_(True))
        .all()
    )
    by_user: dict[int, list[tuple[date, int, int]]] = defaultdict(list)
    for user_id, ambulance_id, competence_id, day in duties:
        stats["duties"] += 1
        by_user[user_id].append((day, ambulance_id, competence_id))
        if user_id not in active_users:
            problems.append(f"inactive user {user_id} on {day}")
        if (user_id, ambulance_id) not in members:
            problems.append(f"{user_id} not a member of {names[ambulance_id]} on {day}")
        if (user_id, competence_id) not in qualified:
            problems.append(f"{user_id} unqualified in {competence_id} at {names[ambulance_id]} on {day}")
        if (user_id, day) in absent:
            problems.append(f"{user_id} absent but on duty at {names[ambulance_id]} on {day}")
    for user_id, items in by_user.items():
        items.sort()
        workplaces = {a for _d, a, _c in items}
        if len(workplaces) > 1:
            stats["people_on_several_workplaces"] += 1
        for index, (day, ambulance_id, competence_id) in enumerate(items):
            rest = rest_of(ambulance_id, competence_id, day)
            for later_day, later_ambulance, _later in items[index + 1:]:
                if later_day == day:
                    problems.append(f"{user_id} twice on {day}: {names[ambulance_id]}, {names[later_ambulance]}")
                elif later_day <= day + timedelta(days=rest):
                    problems.append(
                        f"{user_id} rest: {names[ambulance_id]} {day} (+{rest}) then {names[later_ambulance]} "
                        f"{later_day}"
                    )
                else:
                    if later_ambulance != ambulance_id:
                        stats["cross_workplace_neighbours"] += 1
                    break
    return problems, stats


# --- Tables ------------------------------------------------------------------------------


def month_row(month: SeededMonth) -> dict[str, Any]:
    """Quality numbers of one department-month."""
    m = metrics(month.instance, month.roster)
    loads = [load.total for load in m.loads.values()]
    return {
        "department": month.ambulance,
        "month": month.instance.month,
        "people": len(month.instance.employees),
        "roles": len(month.instance.competences),
        "duties": len(month.roster),
        "load_min": min(loads) if loads else 0,
        "load_max": max(loads) if loads else 0,
        "load_spread": m.load_spread,
        "load_stdev": round(m.load_stdev, 2),
        "hours_spread": round(m.hours_spread, 2),
        "preferred": f"{m.preferred_honored}/{m.preferred_opportunities}",
        "soft_declined_worked": m.soft_declined_worked,
        "over_max": sum(m.over_max.values()),
        "min_gap": m.min_gap,
        "tightest_gaps": m.tightest_gaps,
        "solve_s": round(month.seconds, 1),
        "hit_budget": month.hit_budget,
    }


def markdown(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    keys = list(rows[0])
    lines = ["| " + " | ".join(keys) + " |", "|" + "---|" * len(keys)]
    lines += ["| " + " | ".join(str(row[k]) for k in keys) + " |" for row in rows]
    return "\n".join(lines)


class RealisticSeedTests(unittest.TestCase):
    """config_1, as seeded by the real MILP."""

    seeded: SeedRun

    @classmethod
    def setUpClass(cls) -> None:
        cls.seeded = seed_and_record("config_1", None if STRESS else DEFAULT_MONTHS)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.seeded.engine.dispose()

    def test_every_month_was_generated(self) -> None:
        expected_months = 40 if STRESS else 4 * len(DEFAULT_MONTHS)
        self.assertEqual(len(self.seeded.months), expected_months)
        per_department = Counter(month.ambulance for month in self.seeded.months)
        self.assertEqual(set(per_department), {"I.KAIM", "II.KAIM", "KDAIM", "KUM"})
        ikaim = [m for m in self.seeded.months if m.ambulance == "I.KAIM"]
        self.assertEqual({len(m.instance.employees) for m in ikaim}, {57})
        _record("seeding", {"config": "config_1", "months": len(self.seeded.months),
                            "seconds": round(self.seeded.seconds, 1),
                            "solve_seconds": round(sum(m.seconds for m in self.seeded.months), 1),
                            "hit_budget": sum(m.hit_budget for m in self.seeded.months)})

    def test_every_roster_validates(self) -> None:
        problems = []
        for month in self.seeded.months:
            found = validate(month.instance, month.roster)
            if found:
                problems.append(f"{month.instance.label}: {found[:3]}")
        self.assertEqual(problems, [])

    def test_quality_table(self) -> None:
        rows = [month_row(month) for month in self.seeded.months]
        table = markdown(rows)
        print("\n" + table)
        _record("quality", rows)
        for row in rows:
            self.assertEqual(row["over_max"], 0, row)
            self.assertGreaterEqual(row["min_gap"] or 2, 2, row)

    def test_seeded_rosters_leave_no_improving_move(self) -> None:
        """Generic check 5 on every seeded month that proved both passes."""
        tally: Counter = Counter()
        problems: list[str] = []
        started = perf_counter()
        for month in self.seeded.months:
            if month.hit_budget or month.balance_cap is None:
                tally["skipped_hit_budget"] += 1
                continue
            tally["checked"] += 1
            cost = first_pass_cost(month.instance, month.roster)
            if cost > month.balance_cap + 1e-6:
                problems.append(f"{month.instance.label}: first-pass cost {cost} above the lock {month.balance_cap}")
            for move in find_improving_moves(
                month.instance, month.roster, max_checks=3000 if not STRESS else 12000,
                balance_cap=month.balance_cap,
            ):
                tally[move.reason] += 1
                if move.reason in ("first_pass", "day_wish"):
                    problems.append(f"{month.instance.label}: {move}")
        tally["seconds"] = round(perf_counter() - started)
        _record("seeded_moves", dict(tally))
        self.assertEqual(problems, [])

    def test_resolved_sample(self) -> None:
        """Re-solving a sample in memory agrees on the first pass and leaves no move."""
        by_department: dict[str, list[SeededMonth]] = defaultdict(list)
        for month in self.seeded.months:
            by_department[month.ambulance].append(month)
        sample = [months[-1] for months in by_department.values()]
        if STRESS:
            sample += [months[len(months) // 2] for months in by_department.values()]
        outcomes = solve_in_parallel([m.instance for m in sample], 60, workers=min(WORKERS, len(sample)),
                                     observe=True)
        rows = []
        problems = []
        for month, outcome in zip(sample, outcomes):
            self.assertEqual(outcome.status, "ok", month.instance.label)
            self.assertEqual(validate(month.instance, outcome.assignments), [])
            seeded_first = next((r.objective for r in month.passes if r.kind == "balance"), None)
            row = {
                "month": month.instance.label,
                "seeded_first_pass": seeded_first,
                "resolved_first_pass": outcome.first_pass_objective,
                "resolved_s": round(outcome.seconds, 1),
                "proved": _proved(outcome.passes),
                "moves": 0,
            }
            if _proved(outcome.passes) and not month.hit_budget and seeded_first is not None:
                if abs(outcome.first_pass_objective - seeded_first) > balance_lock_slack(seeded_first):
                    problems.append(f"{month.instance.label}: first pass {seeded_first} vs {outcome.first_pass_objective}")
            if _proved(outcome.passes):
                moves = find_improving_moves(month.instance, outcome.assignments, max_checks=3000,
                                             balance_cap=outcome.balance_cap)
                row["moves"] = len(moves)
                problems += [f"{month.instance.label}: {m}" for m in moves if m.reason in ("first_pass", "day_wish")]
            rows.append(row)
        _record("resolved", rows)
        self.assertEqual(problems, [])

    def test_hospital_wide_consistency(self) -> None:
        with self.seeded.factory() as session:
            problems, stats = hospital_violations(session)
            approved = session.query(Schedule).filter(Schedule.is_approved.is_(True)).count()
            drafts = session.query(Schedule).filter(Schedule.is_approved.is_(False)).count()
        stats["approved"] = approved
        stats["drafts"] = drafts
        _record("hospital_config_1", {"problems": len(problems), **dict(stats)})
        self.assertGreater(stats["people_on_several_workplaces"], 0)
        self.assertEqual(problems, [])


class SecondProfileTests(unittest.TestCase):
    """config_2: hand-written schedules, no generated month (seeds in 0.1 s)."""

    problems: list[str]

    @classmethod
    def setUpClass(cls) -> None:
        seeded = seed_and_record("config_2")
        try:
            cls.months = seeded.months
            with seeded.factory() as session:
                cls.problems, stats = hospital_violations(session)
        finally:
            seeded.engine.dispose()
        cls.rule_issues = [p for p in cls.problems if " twice on " in p]
        cls.data_issues = [p for p in cls.problems if p not in cls.rule_issues]
        _record("hospital_config_2", {"rule_issues": len(cls.rule_issues), "data_issues": len(cls.data_issues),
                                      "examples": cls.problems[:6], "seconds": round(seeded.seconds, 1),
                                      **dict(stats)})

    def test_config_2_generates_nothing_and_keeps_the_hospital_rules(self) -> None:
        """No month is generated, and nobody is booked twice on one day."""
        self.assertEqual(self.months, [])
        self.assertEqual(self.rule_issues, [])

    @unittest.expectedFailure
    def test_config_2_duties_are_held_by_qualified_members(self) -> None:
        """Seed data issue: config_2's hand-written SCHEDULES ignore the rules.

        ``base.SCHEDULES`` places duties at ambulancia1-4 on people who are
        neither active members of that workplace nor hold the competence
        (config_2 declares no ``user_competence_assignments``), and books one
        account on consecutive days at different workplaces inside the
        default one-day rest, so the demo database opens with rosters the
        planner flags and the generator would never produce.
        """
        self.assertEqual(self.data_issues, [])


if __name__ == "__main__":
    unittest.main()
