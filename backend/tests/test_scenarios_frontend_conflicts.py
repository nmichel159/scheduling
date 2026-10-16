"""The planner's client-side conflict checker against the harness oracle.

``frontend/src/utils/scheduleConflicts.js`` (``analyzeScheduleConflicts``)
decides what the schedule editor paints red or amber. It is bundled for Node
(esbuild when ``frontend/node_modules`` has it, otherwise rolldown, which
Vite 8 ships) into a temporary directory and driven from Python through a
``node`` subprocess, many cases per call.

Its inputs are built exactly the way ``AmbulanceScheduleEditView.jsx`` gets
them: a harness instance is written with ``materialize`` and the four GETs
the view issues are answered by the real FastAPI app through ``TestClient``
(competences of the selected scenario, the employee competence table, the
year's special days, ``/schedule/context``). The shifts are a roster in
database ids.

* :class:`ValidRosterTests` -- valid solver rosters (special days, long and
  mixed rest, duties elsewhere and around the month, placements, penalized
  policies) must show no error-severity conflict, except where a penalized
  rule lets the solver do what the planner calls an error; those are tallied.
* :class:`MutationAgreementTests` -- one violation of each oracle type is
  planted in a valid roster; the checker must flag the matching conflict on
  the right cell, demand cell or row.
* :class:`PolicyBlindSeverityTests` -- minimal expected failures for the
  disagreements found.

Everything is skipped when ``node`` or a bundler is unavailable.
"""

from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
import tempfile
import unittest
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.dependencies import get_current_user
from app.db.session import Base, get_db
from app.main import app
from app.models import Role, User
from app.models.associations import UserRole
from app.services.constraint_setting_service import (
    BUSINESS_TRIP,
    MAX_SHIFTS,
    OVERSTAFF,
    REST,
    SOFT_DECLINE,
    UNAVAILABLE,
    VACATION,
    ConstraintPolicy,
    policy_from_settings,
)
from app.services.schedule_generation_service import SchedulingCompetence, SchedulingEmployee

from tests.scheduling_harness.db_builder import InexpressibleInstance, materialize
from tests.scheduling_harness.instances import (
    POLICY_PRESETS,
    Instance,
    Knobs,
    PlantingFailed,
    make_instance,
    sample_knobs,
)
from tests.scheduling_harness.known_bugs import db_bug_triggers
from tests.scheduling_harness.oracle import eligible, validate, violation_codes
from tests.scheduling_harness.runner import solve_in_parallel
from tests.scheduling_harness.semantics import Duty, absence_rule, duty_rest

STRESS = os.environ.get("SCHEDULING_STRESS") == "1"
WORKERS = 6
BACKEND = Path(__file__).resolve().parents[1]
FRONTEND = BACKEND.parent / "frontend"
ENTRY = FRONTEND / "src" / "utils" / "scheduleConflicts.js"
REPORT_PATH = os.environ.get("FRONTEND_CONFLICTS_REPORT")
_REPORT: dict[str, Any] = {}

#: Checker conflict type for each oracle violation code.
CHECKER_TYPE = {
    "unqualified": "unqualified",
    "absence": "unavailable",
    "double_role": "double_role",
    "other_workplace": "other_workplace",
    "rest": "rest",
    "coverage_under": "understaffed",
    "coverage_over": "overstaffed",
    "coverage_zero_day": "overstaffed",
    "max_shifts": "over_wish",
    "soft_decline": "soft_decline",
}

DRIVER = r"""
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
const bundle = await import(pathToFileURL(process.argv[2]).href);
const cases = JSON.parse(readFileSync(0, 'utf8'));
const out = cases.map((input) => {
  const report = bundle.analyzeScheduleConflicts({ ...input, restDays: new Set(input.restDays) });
  return report.conflicts.map((c) => ({
    type: c.type, severity: c.severity, date: c.date ?? null, userId: c.userId ?? null,
    competenceId: c.competenceId ?? null, secondDate: c.secondDate ?? null,
    cells: c.cells, demandCells: c.demandCells, rows: c.rows,
  }));
});
process.stdout.write(JSON.stringify(out));
"""

BUILD_ESBUILD = r"""
import { pathToFileURL } from 'node:url';
const [, , frontend, entry, outfile] = process.argv;
const esbuild = await import(pathToFileURL(frontend + '/node_modules/esbuild/lib/main.js').href);
await (esbuild.build || esbuild.default.build)({ entryPoints: [entry], bundle: true, format: 'esm', outfile, logLevel: 'silent' });
"""

BUILD_ROLLDOWN = r"""
import { pathToFileURL } from 'node:url';
const [, , frontend, entry, outfile] = process.argv;
const { build } = await import(pathToFileURL(frontend + '/node_modules/rolldown/dist/index.mjs').href);
await build({ input: entry, output: { file: outfile, format: 'esm' }, logLevel: 'silent' });
"""


def _record(section: str, payload: Any) -> None:
    _REPORT[section] = payload
    if REPORT_PATH:
        Path(REPORT_PATH).write_text(json.dumps(_REPORT, indent=2, default=str), encoding="utf-8")


class ConflictChecker:
    """``analyzeScheduleConflicts`` bundled once and run through Node."""

    def __init__(self) -> None:
        self.node = shutil.which("node")
        self.directory = Path(tempfile.mkdtemp(prefix="conflicts-"))
        self.bundle = self.directory / "scheduleConflicts.bundle.mjs"
        self.driver = self.directory / "driver.mjs"
        self.bundler: str | None = None
        self.reason = ""
        if self.node is None:
            self.reason = "node is not installed"
            return
        for name, script, marker in (
            ("esbuild", BUILD_ESBUILD, FRONTEND / "node_modules" / "esbuild" / "lib" / "main.js"),
            ("rolldown", BUILD_ROLLDOWN, FRONTEND / "node_modules" / "rolldown" / "dist" / "index.mjs"),
        ):
            if not marker.exists():
                continue
            builder = self.directory / f"build-{name}.mjs"
            builder.write_text(script, encoding="utf-8")
            result = subprocess.run(
                [self.node, str(builder), FRONTEND.as_posix(), ENTRY.as_posix(), self.bundle.as_posix()],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode == 0 and self.bundle.exists():
                self.bundler = name
                break
        if self.bundler is None:
            self.reason = "neither esbuild nor rolldown could bundle scheduleConflicts.js"
            return
        self.driver.write_text(DRIVER, encoding="utf-8")

    @property
    def available(self) -> bool:
        return self.bundler is not None

    def run(self, cases: list[dict]) -> list[list[dict]]:
        """Conflicts of each case, in order."""
        if not cases:
            return []
        result = subprocess.run(
            [self.node, str(self.driver), str(self.bundle)],
            input=json.dumps(cases),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=600,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr[-2000:])
        return json.loads(result.stdout)


_CHECKER: ConflictChecker | None = None


def checker() -> ConflictChecker:
    global _CHECKER
    if _CHECKER is None:
        _CHECKER = ConflictChecker()
    return _CHECKER


# --- Planner inputs, through the API ---------------------------------------------------


@dataclass
class PlannerCase:
    """One month on the planner, and how to translate its ids back."""

    instance: Instance
    roster: list[Duty]
    payload: dict
    user_ids: dict[int, int]
    competence_ids: dict[int, int]
    label: str
    expect: tuple | None = None

    def cell(self, user_id: int, day: date) -> str:
        return f"{self.user_ids[user_id]}|{day.isoformat()}"

    def demand_cell(self, competence_id: int, day: date) -> str:
        return f"{day.isoformat()}|{self.competence_ids[competence_id]}"


def planner_case(instance: Instance, roster: list[Duty], label: str, from_date: date | None = None,
                 expect: tuple | None = None) -> PlannerCase:
    """Write the instance, ask the API what the editor view asks, shape the input.

    Raises:
        InexpressibleInstance: If the database cannot store the instance.
    """
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        world = materialize(instance, session, noise=True)
        role = Role(code="ADMIN_FC", name="Admin", level=3, is_active=True)
        admin = User(email="admin@conflicts.test", full_name="Admin", is_active=True)
        session.add_all([role, admin])
        session.flush()
        session.add(UserRole(user_id=admin.id, role_id=role.id))
        session.commit()
        app.dependency_overrides[get_db] = lambda: session
        app.dependency_overrides[get_current_user] = lambda: admin
        client = TestClient(app)
        base = f"/ambulances/{world.ambulance_id}"
        month, year = instance.month, instance.year

        def get(path: str, **params: Any) -> Any:
            response = client.get(base + path, params=params)
            if response.status_code != 200:
                raise RuntimeError(f"GET {path}: {response.status_code} {response.text}")
            return response.json()

        competences = sorted(get("/competences"), key=lambda item: item["id"])
        employees = get("/employees/competences", limit=500)
        special = get("/special-days", year=year)
        context = get("/schedule/context", month=month, year=year)
    finally:
        app.dependency_overrides.clear()
        session.close()
        engine.dispose()
    shifts = [
        {
            "id": index + 1,
            "user_id": world.user_ids[user_id],
            "competence_id": world.competence_ids[competence_id],
            "work_date": day.isoformat(),
        }
        for index, (user_id, competence_id, day) in enumerate(sorted(roster, key=lambda d: (d[2], d[1], d[0])))
    ]
    payload = {
        "year": year,
        "month": month - 1,
        "ambulanceId": world.ambulance_id,
        "shifts": shifts,
        "employees": employees,
        "competences": competences,
        "restDays": [entry["day"] for entry in special["entries"] if entry["is_rest_day"]],
        "context": context,
        "fromDate": from_date.isoformat() if from_date else None,
        "editedDates": None,
    }
    return PlannerCase(instance, list(roster), payload, dict(world.user_ids),
                       {k: v for k, v in world.competence_ids.items()}, label, expect)


def _penalized(instance: Instance, code: str) -> bool:
    return not instance.effective_policy.is_strict(code)


def explain_error(case: PlannerCase, conflict: dict) -> str | None:
    """Why a valid roster can carry this error conflict, if a penalized rule allows it."""
    instance = case.instance
    back_user = {v: k for k, v in case.user_ids.items()}
    on_screen = [
        duty
        for cell in conflict["cells"]
        for duty in case.roster
        if f"{case.user_ids[duty[0]]}|{duty[2].isoformat()}" == cell
    ]
    if on_screen and all(duty in instance.fixed for duty in on_screen):
        # Manual placements are kept whatever they break; the planner is right to flag them.
        return "manual_placement"
    if conflict["type"] == "unavailable" and conflict["userId"] in back_user:
        employee = instance.employee_map[back_user[conflict["userId"]]]
        day = date.fromisoformat(conflict["date"])
        rule = absence_rule(employee, day)
        if rule is not None and _penalized(instance, rule):
            return f"penalized_{rule}"
    if conflict["type"] == "rest" and _penalized(instance, REST):
        return "penalized_rest"
    return None


# --- (a) Valid solver rosters --------------------------------------------------------------


def _valid_sweep_knobs(rng: random.Random, index: int) -> Knobs:
    """Feature-rich planted knobs; every fourth instance a penalized policy."""
    knobs = sample_knobs(rng, "small", planted=True)
    feature = index % 6
    knobs = replace(
        knobs,
        n_breaking_fixed=0,
        adjacent_retired_competence=False,
        external_duplicate_rate=0.0,
        max_spares=None,
    )
    if feature == 0:
        knobs = replace(knobs, special_days="library", special_slot_differs=True, month=12, year=2026)
    elif feature == 1:
        knobs = replace(knobs, recovery_profile="long", external_rate=0.04, adjacent_rate=0.9)
    elif feature == 2:
        knobs = replace(knobs, recovery_profile="mixed", special_days="mixed", generate_from="mid", n_fixed=4)
    elif feature == 3:
        knobs = replace(knobs, policy=POLICY_PRESETS["penalized_all"], witness_keeps_rest=False,
                        unavailability_rate=0.15, absence_mix=(0.4, 0.3, 0.3), recovery_profile="long",
                        external_rate=0.03)
    elif feature == 4:
        knobs = replace(knobs, policy=POLICY_PRESETS[rng.choice(["penalized_absences", "penalized_rest",
                                                                  "cheap_penalties"])],
                        unavailability_rate=0.15, vacation_block_rate=0.3)
    else:
        knobs = replace(knobs, policy=POLICY_PRESETS["strict_everything"], max_shifts_mode="tight",
                        soft_decline_rate=0.1, external_rate=0.03)
    return knobs


def _solved_valid(count: int, seed_base: int, budget: float) -> tuple[list[tuple[Instance, list[Duty]]], Counter]:
    """Planted instances, solved in parallel, kept when the roster validates."""
    instances: list[Instance] = []
    skipped: Counter = Counter()
    for index in range(count):
        rng = random.Random(seed_base + index)
        try:
            instance = make_instance(seed_base + index, _valid_sweep_knobs(rng, index))
        except PlantingFailed:
            skipped["planting_failed"] += 1
            continue
        if db_bug_triggers(instance) - {"penalized_rest_month_end", "balance_lock_drift"}:
            skipped["known_bug_trigger"] += 1
            continue
        instances.append(instance)
    outcomes = solve_in_parallel(instances, budget, workers=WORKERS)
    solved = []
    for instance, outcome in zip(instances, outcomes):
        if outcome.status != "ok":
            skipped[f"solver_{outcome.status}"] += 1
            continue
        if validate(instance, outcome.assignments):
            skipped["invalid_roster"] += 1
            continue
        solved.append((instance, outcome.assignments))
    return solved, skipped


class ValidRosterTests(unittest.TestCase):
    """A roster the oracle accepts shows no error conflict the policy does not explain."""

    @classmethod
    def setUpClass(cls) -> None:
        if not checker().available:
            raise unittest.SkipTest(checker().reason)
        count = 180 if STRESS else 36
        cls.solved, cls.skipped = _solved_valid(count, 91000, 20.0)
        cls.cases: list[PlannerCase] = []
        for instance, roster in cls.solved:
            try:
                cls.cases.append(planner_case(instance, roster, instance.label, instance.generate_from))
            except InexpressibleInstance:
                cls.skipped["inexpressible"] += 1
        cls.results = checker().run([case.payload for case in cls.cases])

    def test_no_unexplained_error_conflict(self) -> None:
        by_type: Counter = Counter()
        explained: Counter = Counter()
        warnings: Counter = Counter()
        unexplained: list[str] = []
        rosters_with_policy_errors = 0
        for case, conflicts in zip(self.cases, self.results):
            policy_error = False
            for conflict in conflicts:
                if conflict["severity"] != "error":
                    warnings[conflict["type"]] += 1
                    continue
                by_type[conflict["type"]] += 1
                reason = explain_error(case, conflict)
                if reason is None:
                    unexplained.append(f"{case.label}: {conflict}")
                else:
                    explained[reason] += 1
                    policy_error = True
            rosters_with_policy_errors += policy_error
        _record(
            "valid_rosters",
            {
                "rosters": len(self.cases),
                "skipped": dict(self.skipped),
                "error_conflicts_by_type": dict(by_type),
                "explained_by_penalized_rule": dict(explained),
                "rosters_with_policy_errors": rosters_with_policy_errors,
                "warnings_by_type": dict(warnings),
                "unexplained": unexplained[:20],
            },
        )
        self.assertGreater(len(self.cases), 20)
        self.assertEqual(unexplained, [])


# --- (b) One planted violation per oracle type ---------------------------------------------


def _with_employee(instance: Instance, user_id: int, **changes: Any) -> Instance:
    employees = [replace(e, **changes) if e.id == user_id else e for e in instance.employees]
    return replace(instance, employees=employees)


def _with_policy(instance: Instance, **rules: tuple[bool, float]) -> Instance:
    merged = {code: (rule.strict, rule.weight) for code, rule in instance.effective_policy.rules.items()}
    merged.update(rules)
    return replace(instance, policy=policy_from_settings(merged))


def _generated(instance: Instance, roster: list[Duty]) -> list[Duty]:
    fixed = set(instance.fixed)
    window = set(instance.window_days)
    return sorted(duty for duty in roster if duty not in fixed and duty[2] in window)


def mutations(instance: Instance, roster: list[Duty]) -> list[tuple[str, Instance, list[Duty], tuple]]:
    """``(oracle kind, instance, roster, expected)`` for each mutation that applies.

    ``expected`` is ``('cell', user, date)``, ``('demand', competence, date)``
    or ``('row', user)`` in instance ids.
    """
    found: list[tuple[str, Instance, list[Duty], tuple]] = []
    generated = _generated(instance, roster)
    if not generated:
        return found
    duty = generated[len(generated) // 2]
    user_id, competence_id, day = duty
    others = [item for item in roster if item != duty]

    # unqualified: someone without the role, otherwise free, takes the duty.
    for employee in instance.employees:
        if competence_id in employee.competence_ids:
            continue
        widened = _with_employee(instance, employee.id, competence_ids=employee.competence_ids | {competence_id})
        if eligible(widened, employee.id, competence_id, day, others):
            found.append(("unqualified", instance, others + [(employee.id, competence_id, day)],
                          ("cell", employee.id, day)))
            break
    # absence: a strict absence recorded on the duty's day.
    strict_rules = [rule for rule in (UNAVAILABLE, VACATION, BUSINESS_TRIP)
                    if instance.effective_policy.is_strict(rule)]
    employee = instance.employee_map[user_id]
    if strict_rules and day not in employee.preferred_dates | employee.soft_declined_dates:
        rule = strict_rules[day.day % len(strict_rules)]
        changed = _with_employee(
            instance, user_id,
            unavailable_dates=employee.unavailable_dates | {day},
            absence_rules=tuple(i for i in employee.absence_rules if i[0] != day) + ((day, rule),),
        )
        found.append(("absence", changed, list(roster), ("cell", user_id, day)))
    # double_role: someone working that day in another role also takes this one.
    done = False
    for taken in generated:
        for other in generated:
            if other[2] != taken[2] or other[0] == taken[0] or other[1] == taken[1]:
                continue
            remaining = [item for item in roster if item != taken]
            rest = [item for item in remaining if item != other]
            if eligible(instance, other[0], taken[1], taken[2], rest):
                found.append(("double_role", instance, remaining + [(other[0], taken[1], taken[2])],
                              ("cell", other[0], taken[2])))
                done = True
                break
        if done:
            break
    # other_workplace: booked elsewhere the same day, earning no rest.
    if day not in employee.externally_scheduled_dates:
        changed = _with_employee(
            instance, user_id,
            externally_scheduled_dates=employee.externally_scheduled_dates | {day},
            external_commitments=employee.external_commitments + ((day, 0),),
        )
        found.append(("other_workplace", changed, list(roster), ("cell", user_id, day)))
    if instance.effective_policy.is_strict(REST):
        # The planner checks rest only between duties in its own grid, never
        # against a saved duty elsewhere, so only that case is planted here.
        # rest, in the output: the duty right after one's own, inside its rest.
        relaxed = _with_policy(instance, rest=(False, 1000.0))
        done = False
        for first in generated:
            reach = duty_rest(instance.competence_map, first[1], first[2])
            for later in generated:
                if later[0] == first[0] or not first[2] < later[2] <= first[2] + timedelta(days=reach):
                    continue
                rest = [item for item in roster if item != later]
                if eligible(relaxed, first[0], later[1], later[2], rest):
                    found.append(("rest", instance, rest + [(first[0], later[1], later[2])],
                                  ("cell", first[0], later[2])))
                    done = True
                    break
            if done:
                break
    # coverage, short: drop the duty.
    found.append(("coverage_under", instance, others, ("demand", competence_id, day)))
    # coverage, over, under a strict overstaff rule.
    strict_over = _with_policy(instance, overstaff=(True, 1000.0))
    done = False
    for over_day in instance.window_days:
        for competence in instance.competences:
            if competence.required_on(over_day) == 0:
                continue
            for candidate in instance.employees:
                if eligible(strict_over, candidate.id, competence.id, over_day, roster):
                    found.append(("coverage_over", strict_over, roster + [(candidate.id, competence.id, over_day)],
                                  ("demand", competence.id, over_day)))
                    done = True
                    break
            if done:
                break
        if done:
            break
    # coverage, zero day: the role asks for nobody on that weekday.
    competence = instance.competence_map[competence_id]
    if day not in competence.special_dates:
        counts = list(competence.weekday_required_counts)
        counts[day.weekday()] = 0
        zeroed = replace(competence, weekday_required_counts=tuple(counts))
        changed = replace(instance, competences=[zeroed if c.id == competence_id else c for c in instance.competences])
        found.append(("coverage_zero_day", changed, list(roster), ("demand", competence_id, day)))
    # max_shifts, strict, one below what someone got.
    totals = Counter(d[0] for d in roster)
    placed = Counter(d[0] for d in instance.fixed)
    for candidate, total in sorted(totals.items()):
        if total >= 2 and placed[candidate] < total:
            changed = _with_employee(_with_policy(instance, max_shifts=(True, 1000.0)), candidate,
                                     max_shifts_per_month=total - 1)
            found.append(("max_shifts", changed, list(roster), ("row", candidate)))
            break
    # soft_decline, strict.
    if day not in employee.unavailable_dates | employee.preferred_dates:
        changed = _with_employee(_with_policy(instance, soft_decline=(True, 10.0)), user_id,
                                 soft_declined_dates=employee.soft_declined_dates | {day})
        found.append(("soft_decline", changed, list(roster), ("cell", user_id, day)))
    return found


#: The oracle code each mutation kind must produce.
ORACLE_CODE = {
    "unqualified": "unqualified",
    "absence": "absence",
    "double_role": "double_role",
    "other_workplace": "other_workplace",
    "rest": "rest",
    "coverage_under": "coverage",
    "coverage_over": "coverage",
    "coverage_zero_day": "coverage",
    "max_shifts": "max_shifts",
    "soft_decline": "soft_decline",
}


def matches(case: PlannerCase, conflict: dict, kind: str) -> bool:
    """Whether a checker conflict is the one the planted violation calls for."""
    if conflict["type"] != CHECKER_TYPE[kind]:
        return False
    where = case.expect
    if where[0] == "cell":
        return case.cell(where[1], where[2]) in conflict["cells"]
    if where[0] == "demand":
        return case.demand_cell(where[1], where[2]) in conflict["demandCells"]
    return case.user_ids[where[1]] in conflict["rows"]


class MutationAgreementTests(unittest.TestCase):
    """Each oracle violation type is flagged by the checker on the right cell."""

    @classmethod
    def setUpClass(cls) -> None:
        if not checker().available:
            raise unittest.SkipTest(checker().reason)
        count = 60 if STRESS else 14
        solved, _ = _solved_valid(count, 93000, 20.0)
        # Strict-rest instances only: a mutation must break exactly one rule.
        cls.cases: list[PlannerCase] = []
        cls.kinds: list[str] = []
        cls.rejected: Counter = Counter()
        for instance, roster in solved:
            if not instance.effective_policy.is_strict(REST):
                continue
            for kind, changed, mutated, expect in mutations(instance, roster):
                codes = violation_codes(validate(changed, mutated))
                if codes != {ORACLE_CODE[kind]}:
                    cls.rejected[kind] += 1
                    continue
                try:
                    cls.cases.append(planner_case(changed, mutated, f"{instance.label}:{kind}",
                                                  changed.generate_from, expect))
                except InexpressibleInstance:
                    cls.rejected[f"{kind}_inexpressible"] += 1
                    continue
                cls.kinds.append(kind)
        cls.results = checker().run([case.payload for case in cls.cases])

    def test_the_checker_flags_each_violation_where_it_is(self) -> None:
        table: dict[str, Counter] = defaultdict(Counter)
        misses: list[str] = []
        for kind, case, conflicts in zip(self.kinds, self.cases, self.results):
            row = table[kind]
            row["cases"] += 1
            hits = [c for c in conflicts if matches(case, c, kind)]
            if hits:
                row["flagged"] += 1
                row[f"severity_{hits[0]['severity']}"] += 1
            else:
                misses.append(f"{case.label}: expected {CHECKER_TYPE[kind]} at {case.expect}; got "
                              f"{[(c['type'], c['cells'] or c['demandCells'] or c['rows']) for c in conflicts][:6]}")
            extra_errors = [c for c in conflicts if c["severity"] == "error" and c not in hits]
            row["other_errors_explained"] += sum(1 for c in extra_errors if explain_error(case, c))
            row["other_errors_unexplained"] += sum(1 for c in extra_errors if not explain_error(case, c))
        _record("mutations", {kind: dict(row) for kind, row in table.items()} | {"rejected": dict(self.rejected)})
        for kind in ORACLE_CODE:
            self.assertGreater(table[kind]["cases"], 0, kind)
        self.assertEqual(misses, [])

    def test_hard_rule_violations_are_errors(self) -> None:
        """Rules that are always hard (or strict here) must be painted as errors."""
        hard = {"unqualified", "absence", "double_role", "other_workplace", "rest", "coverage_under",
                "coverage_zero_day"}
        wrong: list[str] = []
        for kind, case, conflicts in zip(self.kinds, self.cases, self.results):
            if kind not in hard:
                continue
            hits = [c for c in conflicts if matches(case, c, kind)]
            if hits and all(c["severity"] != "error" for c in hits):
                wrong.append(f"{case.label}: {hits[0]}")
        self.assertEqual(wrong, [])


# --- Disagreements, as minimal expected failures -------------------------------------------


def _competence(competence_id: int = 1, rest: int = 1) -> SchedulingCompetence:
    return SchedulingCompetence(
        id=competence_id,
        name=f"Role {competence_id}",
        required_count=1,
        weekday_required_counts=(1,) * 7,
        special_day_required_count=1,
        special_dates=frozenset(),
        weekday_recovery_days=(rest,) * 7,
        special_day_recovery_days=rest,
        weekday_is_surcharge=(False, False, False, False, False, True, True),
        special_day_is_surcharge=True,
        weekday_shift_hours=(4.0,) * 7,
        special_day_shift_hours=4.0,
    )


def _employee(user_id: int, **extra: Any) -> SchedulingEmployee:
    values = dict(
        id=user_id,
        email=f"u{user_id}@conflicts.test",
        full_name=f"User {user_id}",
        competence_ids=frozenset({1}),
        unavailable_dates=frozenset(),
        externally_scheduled_dates=frozenset(),
    )
    values.update(extra)
    return SchedulingEmployee(**values)


def penalized_vacation_instance() -> Instance:
    """One person, on a penalized vacation on 10 August: the solver must use them."""
    vacation = date(2026, 8, 10)
    return Instance(
        employees=[_employee(1, unavailable_dates=frozenset({vacation}), absence_rules=((vacation, VACATION),))],
        competences=[_competence(rest=0)],
        month=8,
        year=2026,
        policy=policy_from_settings({VACATION: (False, 1000.0)}),
        label="penalized-vacation",
    )


def strict_overstaff_instance() -> tuple[Instance, list[Duty]]:
    """Two people, one per day asked, overstaffing strict; a roster with one surplus."""
    instance = Instance(
        employees=[_employee(1), _employee(2)],
        competences=[_competence(rest=0)],
        month=8,
        year=2026,
        policy=policy_from_settings({OVERSTAFF: (True, 1000.0)}),
        label="strict-overstaff",
    )
    roster = [(1 + day.day % 2, 1, day) for day in instance.days] + [(1, 1, date(2026, 8, 1))]
    return instance, roster


class PolicyBlindSeverityTests(unittest.TestCase):
    """The planner's severities ignore the workplace's rule settings."""

    def setUp(self) -> None:
        if not checker().available:
            self.skipTest(checker().reason)

    @unittest.expectedFailure
    def test_a_penalized_absence_the_solver_used_is_not_an_error(self) -> None:
        """Suspected frontend bug: a penalized absence is shown as a hard error.

        With VACATION penalized (README "Scheduling rules per workplace": the
        generator *may* break a penalized rule, paying its weight), a valid
        generated roster puts the only qualified person on their vacation
        day. ``analyzeScheduleConflicts`` hard-codes ``unavailable`` as
        ``error`` (it never reads the constraint settings), so the editor
        paints the generator's own legal choice red, the same as a manual
        breach of a strict rule.
        """
        instance = penalized_vacation_instance()
        from tests.scheduling_harness.runner import run_solver

        outcome = run_solver(instance, 10)
        self.assertEqual(outcome.status, "ok")
        self.assertEqual(validate(instance, outcome.assignments), [])
        case = planner_case(instance, outcome.assignments, instance.label)
        conflicts = checker().run([case.payload])[0]
        self.assertEqual([c for c in conflicts if c["severity"] == "error"], [])

    @unittest.expectedFailure
    def test_a_strict_overstaff_breach_is_an_error(self) -> None:
        """Suspected frontend bug: a breach of a strict overstaff rule is only a warning.

        With OVERSTAFF strict the generator treats a surplus as forbidden
        (oracle code ``coverage``), but the planner always paints
        ``overstaffed`` amber, so a manager can save an illegal surplus
        without seeing an error. The same holds for a strict monthly maximum
        (``over_wish``) and a strict "rather not" (``soft_decline``).
        """
        instance, roster = strict_overstaff_instance()
        self.assertEqual(violation_codes(validate(instance, roster)), {"coverage"})
        case = planner_case(instance, roster, instance.label)
        conflicts = checker().run([case.payload])[0]
        surplus = [c for c in conflicts if c["type"] == "overstaffed"]
        self.assertTrue(surplus)
        self.assertEqual({c["severity"] for c in surplus}, {"error"})


if __name__ == "__main__":
    unittest.main()
