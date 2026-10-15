"""Scenario tests: completing a partly filled month ("dogenerovanie rozvrhov").

The editor (``AmbulanceScheduleEditView.generateSchedule``) hands the solver
every duty on screen as ``fixed_entries`` and the first editable date as
``generate_from``; "Clear" empties the editable tail before a full
regeneration. So the generator has to:

* keep the history (days before ``generate_from``) exactly,
* keep every manual placement, also one that breaks a rule,
* fill every gap, validly, without new breaches, and
* plan the tail so the *month totals* stay balanced, i.e. compensate for
  an uneven history.

Checked on every solve (``_judge``):

1. Every ``ok`` roster passes the independent oracle (``validate == []``).
2. A planted instance (hidden valid roster) is never refused; a timeout is
   tallied separately.
3. A random/unplanted instance the solver refuses is confirmed by
   ``reference_feasibility`` (``unknown`` counted, never passed).
4. Planted, observed, not stopped at the budget: first-pass cost is at most
   the witness's, within the lock slack.
5. Observed, not stopped at the budget: ``find_improving_moves`` finds no
   ``first_pass`` or ``day_wish`` move.

Scenario groups: (a) fill-in share grid, (a') holes punched into a solved
roster, (b) mid-month regeneration after each change in ``CHANGES``,
(c) history compensation (brute force on tiny months, generic checks and a
water-filling lower bound on larger ones), (d) rule-breaking placements,
(e) idempotence, (f) month chaining Dec -> Jan -> leap Feb, (g) the database
path, (h) the API's month checks.

The default run is a deterministic grid of a few minutes; ``SCHEDULING_STRESS=1``
adds a heavier sweep. At most ``WORKERS`` CBC processes run at a time. The
verdict tables are printed at the end of the module (run with ``-s``); set
``FILL_IN_REPORT=<path>`` to also dump them as JSON.
"""

from __future__ import annotations

import json
import os
import random
import statistics
import unittest
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from types import SimpleNamespace
from typing import Iterable
from unittest import mock

from fastapi import HTTPException

import app.services.schedule_generation_service as generation_service
from app.services.constraint_setting_service import MAX_SHIFTS, REST, ConstraintPolicy

from tests.scheduling_harness.db_builder import InexpressibleInstance, run_db_solver
from tests.scheduling_harness.instances import (
    POLICY_PRESETS,
    Instance,
    Knobs,
    PlantingFailed,
    fill_in_knobs,
    make_instance,
    sample_knobs,
    stress_knobs,
)
from tests.scheduling_harness.known_bugs import db_bug_triggers, known_bug_triggers
from tests.scheduling_harness.oracle import (
    day_wish_cost,
    find_improving_moves,
    first_pass_cost,
    metrics,
    validate,
    violation_codes,
)
from tests.scheduling_harness.reference import brute_force, reference_feasibility
from tests.scheduling_harness.runner import (
    PassRecord,
    SolveOutcome,
    _observer,
    run_solver,
    solve_in_parallel,
)
from tests.scheduling_harness.scenarios import (
    CHANGES,
    carried_week,
    chain_months,
    regenerate,
    repair,
)
from tests.scheduling_harness.semantics import (
    Duty,
    absence_rule,
    balance_lock_slack,
    collide,
    duty_rest,
    month_days,
)

STRESS = os.environ.get("SCHEDULING_STRESS") == "1"
#: CBC processes at once (another agent shares the machine).
WORKERS = 5
#: Seconds per solve for small and medium fill-in instances.
BUDGET = 10
#: Known bugs that make an optimality judgement meaningless for an instance.
_OPTIMALITY_BLOCKERS = {"duplicate_external_dates", "zero_balance_skips_wishes"}
#: Cached properties of ``Instance`` that must be dropped after ``replace``.
_CACHED = ("days", "day_set", "window_days", "history_days", "employee_map", "competence_map", "special_dates")
BREAKING_KINDS = ("two_roles", "inside_rest", "unqualified", "absence", "above_demand")


# --------------------------------------------------------------------------- tallies


@dataclass
class _Tally:
    """Counts for one scenario row of the verdict table."""

    n: int = 0
    ok: int = 0
    timeout: int = 0
    infeasible: int = 0
    infeasible_confirmed: int = 0
    infeasible_unknown: int = 0
    error: int = 0
    planted: int = 0
    planted_refused: int = 0
    valid: int = 0
    history_kept: int = 0
    placements_kept: int = 0
    opt_checked: int = 0
    opt_ok: int = 0
    hit_budget: int = 0
    known_bug: int = 0
    seconds: list[float] = field(default_factory=list)
    notes: Counter = field(default_factory=Counter)


_TALLY: dict[str, _Tally] = defaultdict(_Tally)
_QUALITY: list[dict] = []
_EXTRA: dict[str, list[dict]] = defaultdict(list)


def _fresh(instance: Instance, **changes: object) -> Instance:
    """``dataclasses.replace`` with the instance's cached properties dropped."""
    changed = replace(instance, **changes)
    for name in _CACHED:
        changed.__dict__.pop(name, None)
    return changed


def _plant(seed: int, knobs: Knobs) -> Instance | None:
    """A planted instance, or ``None`` when the planter gave up."""
    try:
        return make_instance(seed, knobs)
    except PlantingFailed:
        return None


def _history(instance: Instance, duties: Iterable[Duty]) -> set[Duty]:
    """The duties before ``generate_from`` (none when the whole month is open)."""
    if instance.generate_from is None:
        return set()
    return {duty for duty in duties if duty[2] < instance.generate_from}


def _judge(
    test: unittest.TestCase,
    scenario: str,
    instance: Instance,
    outcome: SolveOutcome,
    witness: Iterable[Duty] | None = None,
    optimality: bool = True,
) -> dict[str, object]:
    """Record and check one solve; returns what was found.

    ``witness`` defaults to ``instance.witness``; a planted instance must be
    solved, every ``ok`` roster must validate, keep the history exactly and
    keep every placement, and (observed, not at the budget, no known bug)
    pass checks 4 and 5.
    """
    tally = _TALLY[scenario]
    tally.n += 1
    tally.seconds.append(outcome.seconds)
    witness = instance.witness if witness is None else frozenset(witness)
    triggers = known_bug_triggers(instance)
    if triggers:
        tally.known_bug += 1
        for key in triggers:
            tally.notes[f"bug:{key}"] += 1
    found: dict[str, object] = {"status": outcome.status, "triggers": triggers}
    if outcome.hit_budget:
        tally.hit_budget += 1
    if witness is not None:
        tally.planted += 1
    with test.subTest(scenario=scenario, label=instance.label):
        if outcome.status == "error":
            tally.error += 1
            test.fail(f"solver raised: {outcome.error}")
        if outcome.status == "timeout":
            tally.timeout += 1
            return found
        if outcome.status == "infeasible":
            tally.infeasible += 1
            if witness is not None:
                tally.planted_refused += 1
                test.fail(f"planted instance refused: {outcome.issues}")
            verdict, _ = reference_feasibility(instance, time_limit=60)
            if verdict == "infeasible":
                tally.infeasible_confirmed += 1
            elif verdict == "unknown":
                tally.infeasible_unknown += 1
            else:
                test.fail(f"refused but the reference model finds a roster: {outcome.issues}")
            return found
        tally.ok += 1
        roster = set(outcome.assignments)
        violations = validate(instance, roster)
        history_ok = _history(instance, roster) == _history(instance, instance.fixed)
        placements_ok = instance.fixed <= roster
        tally.valid += not violations
        tally.history_kept += history_ok
        tally.placements_kept += placements_ok
        found.update(valid=not violations, history_ok=history_ok, placements_ok=placements_ok)
        test.assertEqual(violations, [], violation_codes(violations))
        test.assertTrue(history_ok, "history changed")
        test.assertTrue(placements_ok, "a placement was dropped")
        if not optimality or outcome.hit_budget or not outcome.passes or triggers & _OPTIMALITY_BLOCKERS:
            return found
        tally.opt_checked += 1
        cost = first_pass_cost(instance, roster)
        found["cost"] = cost
        good = True
        if witness is not None and not validate(instance, witness):
            bound = first_pass_cost(instance, witness)
            found["witness_cost"] = bound
            if cost > bound + balance_lock_slack(bound):
                good = False
                test.fail(f"first pass {cost} above the witness's {bound}")
        # A wish pass that came back with no solution at all (sol_status 0)
        # leaves the first-pass roster in place: wishes are ignored. That is
        # finding fill_in_1 (see WishPassFindsNothingTests); it is tallied
        # here and only the first-pass part of check 5 is applied.
        reasons = ("first_pass", "day_wish")
        if outcome.second_pass is not None and outcome.second_pass.sol_status == 0:
            tally.notes["wish pass found nothing"] += 1
            found["wish_pass_failed"] = True
            reasons = ("first_pass",)
        moves = [
            move
            for move in find_improving_moves(instance, roster, balance_cap=outcome.balance_cap)
            if move.reason in reasons
        ]
        if moves:
            good = False
            test.fail(f"improving moves left: {moves[:3]}")
        tally.opt_ok += good
    return found


def _water_fill_spread(loads: Iterable[int], extra: int) -> int:
    """Smallest possible max-min of ``loads`` after adding ``extra`` units anywhere.

    A lower bound on the month's load spread given a frozen history: it
    ignores qualifications, rest and every other rule.
    """
    values = sorted(loads)
    if not values:
        return 0
    for _ in range(max(0, extra)):
        values[0] += 1
        values.sort()
    return values[-1] - values[0]


def _month_loads(instance: Instance, duties: Iterable[Duty], people: Iterable[int]) -> dict[int, int]:
    """In-month duties per person, zero for those without any."""
    counts = Counter(duty[0] for duty in duties)
    return {user_id: counts.get(user_id, 0) for user_id in people}


def _spread(loads: dict[int, int]) -> int:
    """Max minus min of a load table."""
    return max(loads.values()) - min(loads.values()) if loads else 0


def _observed_db_run(job: tuple[Instance, float, dict]) -> SolveOutcome:
    """``run_db_solver`` with every CBC pass recorded (so ``hit_budget`` is exact)."""
    instance, budget, options = job
    records: list[PassRecord] = []
    with mock.patch.object(generation_service, "_run_solver", _observer(records)):
        try:
            outcome = run_db_solver(instance, budget, **options)
        except InexpressibleInstance as error:
            return SolveOutcome("inexpressible", error=str(error), budget=budget)
    outcome.passes = records
    return outcome


def _chain_job(job: tuple[int, Knobs, int, float]) -> list[tuple[Instance, SolveOutcome]]:
    """Solve a month chain; returns every (instance, outcome) reached."""
    seed, knobs, n_months, budget = job
    outcomes: list[SolveOutcome] = []

    def solve(instance: Instance) -> list[Duty] | None:
        outcome = run_solver(instance, budget, observe=True)
        outcomes.append(outcome)
        return outcome.assignments if outcome.status == "ok" else None

    try:
        chain = chain_months(seed, knobs, n_months, solve)
    except PlantingFailed:
        return []
    return [(instance, outcome) for (instance, _), outcome in zip(chain, outcomes)]


def _pool_map(function, jobs: list) -> list:
    """Map a top-level function over jobs with at most ``WORKERS`` processes."""
    if len(jobs) <= 1:
        return [function(job) for job in jobs]
    with ProcessPoolExecutor(max_workers=min(WORKERS, len(jobs))) as pool:
        return list(pool.map(function, jobs))


# --------------------------------------------------------------------------- (a) share grid


class FillInShareGridTests(unittest.TestCase):
    """(a) 10-90 % of the witness pinned, some whole days pinned, three sizes."""

    def test_share_grid(self) -> None:
        """Every pinned share is completed: history and placements kept, gaps filled."""
        shares = (0.1, 0.3, 0.5, 0.7, 0.9)
        grid: list[tuple[str, float, int, int]] = []
        seeds = 3 if STRESS else 1
        for size in ("small", "medium"):
            for share in shares:
                for full_days in ((0, 3) if STRESS or size == "small" else (0,)):
                    for rep in range(seeds):
                        grid.append((size, share, full_days, rep))
        large_shares = shares if STRESS else (0.7, 0.9)
        for share in large_shares:
            for rep in range(2 if STRESS else 1):
                grid.append(("large", share, 0 if rep == 0 else 3, rep))
        sized: list[tuple[str, Instance]] = []
        for size, share, full_days, rep in grid:
            seed = 10_000 + {"small": 0, "medium": 1, "large": 2}[size] * 1000 + int(share * 100) * 10 + full_days + rep * 3
            knobs = replace(fill_in_knobs(random.Random(seed), share, size), fixed_full_days=full_days)
            instance = _plant(seed, knobs)
            if instance is not None:
                sized.append((size, instance))
        quick = [item for item in sized if item[0] != "large"]
        slow = [item for item in sized if item[0] == "large"]
        outcomes = solve_in_parallel([i for _, i in quick], BUDGET, workers=WORKERS, observe=True)
        outcomes += solve_in_parallel([i for _, i in slow], 30, workers=WORKERS, observe=True)
        for (size, instance), outcome in zip(quick + slow, outcomes):
            share = instance.knobs["fixed_share"]
            _judge(self, f"a: share {share:.1f} {size}", instance, outcome)
        # Planting may fail for a seed now and then; most of the grid must run.
        self.assertGreaterEqual(len(sized), 0.8 * len(grid))


class FillInHolesTests(unittest.TestCase):
    """(a') The editor flow without Clear: a solved month with a few duties deleted."""

    def test_holes_in_a_solved_roster_are_refilled(self) -> None:
        """Delete 5-30 % of a solved roster's tail; the rest is kept, holes filled, no worse."""
        rng = random.Random(77)
        bases: list[Instance] = []
        for seed in range(12 if STRESS else 5):
            size = "small" if seed % 2 == 0 else "medium"
            knobs = replace(sample_knobs(random.Random(500 + seed), size, True), generate_from=None, n_breaking_fixed=0)
            instance = _plant(500 + seed, knobs)
            if instance is not None:
                bases.append(instance)
        solved = solve_in_parallel(bases, 20, workers=WORKERS, observe=True)
        holed: list[tuple[Instance, frozenset[Duty]]] = []
        for base, outcome in zip(bases, solved):
            if outcome.status != "ok":
                continue
            roster = sorted(set(outcome.assignments))
            for share in (0.05, 0.15, 0.3):
                for cut_day in (None, base.days[len(base.days) // 2]):
                    tail = [duty for duty in roster if cut_day is None or duty[2] >= cut_day]
                    holes = set(rng.sample(tail, max(1, int(len(tail) * share))))
                    kept = frozenset(duty for duty in roster if duty not in holes) | base.fixed
                    case = _fresh(
                        base,
                        fixed=kept,
                        generate_from=cut_day,
                        witness=frozenset(roster),
                        label=f"{base.label}+holes{share}@{cut_day}",
                    )
                    holed.append((case, frozenset(roster)))
        outcomes = solve_in_parallel([case for case, _ in holed], BUDGET, workers=WORKERS, observe=True)
        for (case, roster), outcome in zip(holed, outcomes):
            _judge(self, "a': holes in solved roster", case, outcome, witness=roster)
        self.assertGreaterEqual(len(holed), 18)


# --------------------------------------------------------------------------- (b) regenerate


def _new_absences(before: Instance, after: Instance) -> list[tuple[int, date, str]]:
    """Absences ``after`` has that ``before`` did not, with their rule."""
    old = before.employee_map
    found = []
    for employee in after.employees:
        for day in sorted(employee.unavailable_dates - old[employee.id].unavailable_dates):
            found.append((employee.id, day, absence_rule(employee, day)))
    return found


class RegenerationTests(unittest.TestCase):
    """(b) Mid-month regeneration after every change, early / mid / late cut."""

    def test_every_change_at_every_cut(self) -> None:
        """History untouched, the change honoured, a planted month never refused."""
        bases: list[Instance] = []
        plan = [("small", 0), ("small", 1), ("medium", 2)]
        if STRESS:
            plan += [("small", seed) for seed in range(3, 9)] + [("medium", seed) for seed in range(9, 14)] + [("large", 14)]
        for size, seed in plan:
            knobs = replace(sample_knobs(random.Random(900 + seed), size, True), generate_from=None)
            instance = _plant(900 + seed, knobs)
            if instance is not None:
                bases.append(instance)
        solved = solve_in_parallel(bases, 30 if STRESS else 20, workers=WORKERS, observe=True)
        jobs: list[tuple[Instance, Instance, SolveOutcome, str, str]] = []
        for base, outcome in zip(bases, solved):
            _judge(self, "b: base month", base, outcome)
            if outcome.status != "ok":
                continue
            cuts = {"early": base.days[2], "mid": base.days[len(base.days) // 2], "late": base.days[-3]}
            for index, change in enumerate(CHANGES):
                for cut_name, cut in cuts.items():
                    changed = regenerate(base, outcome.assignments, cut, change, seed=index * 7 + len(cut_name))
                    jobs.append((base, changed, outcome, change, cut_name))
        outcomes = solve_in_parallel([job[1] for job in jobs], BUDGET, workers=WORKERS, observe=True)
        honoured: Counter[str] = Counter()
        for (base, changed, base_outcome, change, cut_name), outcome in zip(jobs, outcomes):
            scenario = f"b: {change} @{cut_name}"
            found = _judge(self, scenario, changed, outcome)
            if changed.witness is None:
                _TALLY[scenario].notes["no witness"] += 1
            if outcome.status != "ok":
                continue
            roster = set(outcome.assignments)
            generated = roster - changed.fixed
            policy = changed.effective_policy
            ok = True
            with self.subTest(scenario=scenario, label=changed.label, check="change honoured"):
                for user_id, day, rule in _new_absences(base, changed):
                    worked = any(duty[0] == user_id and duty[2] == day for duty in generated)
                    if worked and policy.is_strict(rule):
                        ok = False
                    if worked and not policy.is_strict(rule):
                        _TALLY[scenario].notes["penalized absence worked"] += 1
                if change == "lower_max":
                    for employee in changed.employees:
                        cap = employee.max_shifts_per_month
                        if cap and cap != base.employee_map[employee.id].max_shifts_per_month:
                            total = sum(1 for duty in roster if duty[0] == employee.id)
                            pinned = sum(1 for duty in changed.fixed if duty[0] == employee.id)
                            if total > max(cap, pinned):
                                if policy.is_strict(MAX_SHIFTS):
                                    ok = False
                                else:
                                    _TALLY[scenario].notes["penalized cap exceeded"] += 1
                self.assertTrue(ok, "the change was not honoured")
            honoured[scenario] += ok
            if change == "none" and not outcome.hit_budget and not base_outcome.hit_budget and outcome.passes:
                # Re-solving the tail with nothing changed: the old roster is a valid
                # completion and was first-pass optimal for the whole month.
                old = set(base_outcome.assignments)
                new_cost = first_pass_cost(changed, roster)
                old_cost = first_pass_cost(changed, old)
                base_new = first_pass_cost(base, roster)
                base_old = first_pass_cost(base, old)
                slack = balance_lock_slack(old_cost) + balance_lock_slack(new_cost)
                _EXTRA["resolve_none"].append({"label": changed.label, "cut": cut_name, "old": old_cost, "new": new_cost})
                with self.subTest(scenario=scenario, label=changed.label, check="equal cost"):
                    if not known_bug_triggers(changed) & _OPTIMALITY_BLOCKERS and not validate(base, roster):
                        self.assertLessEqual(new_cost, old_cost + slack)
                        self.assertGreaterEqual(base_new, base_old - slack)
        for scenario, count in honoured.items():
            _TALLY[scenario].notes["change honoured"] = count
        self.assertGreaterEqual(len(jobs), 50)


# --------------------------------------------------------------------------- (c) compensation


def _skewed(base: Instance, light: set[int], cut: date, seed: int) -> Instance | None:
    """``base`` regenerated from ``cut`` after a history in which ``light`` never worked."""
    variant = _fresh(
        base,
        employees=[replace(e, competence_ids=frozenset()) if e.id in light else e for e in base.employees],
        witness=None,
    )
    roster = repair(variant, seed=seed)
    if roster is None:
        return None
    changed = regenerate(base, roster, cut, "none", seed=seed)
    return _fresh(changed, label=f"{base.label}+skew{sorted(light)}@{cut.day}")


def _tiny_compensation_case(seed: int) -> Instance | None:
    """A tiny planted month whose history is uneven; the window is its last 4-7 days."""
    rng = random.Random(seed)
    month, year = rng.choice([(2, 2028), (8, 2026), (12, 2026), (4, 2026)])
    n_employees = rng.randint(3, 5)
    knobs = Knobs(
        n_employees=n_employees,
        n_competences=rng.choice([1, 1, 2]),
        month=month,
        year=year,
        qualification_density=rng.choice([0.8, 1.0]),
        demand_profile=rng.choice(["flat", "weekday", "sparse"]),
        recovery_profile=rng.choice(["zero", "one", "mixed"]),
        hours_profile=rng.choice(["uniform4", "uniform4", "mixed"]),
        surcharge_profile=rng.choice(["none", "weekend"]),
        preference_mix=rng.choice(["any", "mixed"]),
        unavailability_rate=rng.choice([0.0, 0.1]),
        preferred_rate=rng.choice([0.0, 0.2]),
        max_shifts_mode=rng.choice(["none", "loose"]),
        policy=rng.choice([POLICY_PRESETS["default"], POLICY_PRESETS["heavy_balance"], POLICY_PRESETS["strict_load"]]),
        planted=True,
        max_spares=0,
    )
    base = _plant(seed, knobs)
    if base is None:
        return None
    light = set(rng.sample([e.id for e in base.employees], rng.randint(1, max(1, n_employees // 2))))
    cut = base.days[-rng.randint(4, 7)]
    return _skewed(base, light, cut, seed)


def _larger_compensation_case(seed: int, size: str) -> tuple[Instance, Instance] | None:
    """(base, skewed regeneration) for a small or medium month, cut in the middle."""
    rng = random.Random(seed)
    low, high = {"small": (6, 10), "medium": (12, 20)}[size]
    month, year = rng.choice([(2, 2028), (8, 2026), (12, 2026), (4, 2026), (1, 2027)])
    knobs = Knobs(
        n_employees=rng.randint(low, high),
        n_competences=rng.randint(1, 2 if size == "small" else 3),
        month=month,
        year=year,
        qualification_density=rng.choice([0.6, 0.8, 1.0]),
        demand_profile=rng.choice(["flat", "weekday", "sparse", "mixed"]),
        special_days=rng.choice(["none", "library"]),
        recovery_profile=rng.choice(["zero", "one", "one", "mixed"]),
        hours_profile=rng.choice(["uniform4", "uniform12", "mixed"]),
        surcharge_profile=rng.choice(["none", "weekend"]),
        preference_mix=rng.choice(["any", "mixed"]),
        unavailability_rate=rng.choice([0.0, 0.03]),
        preferred_rate=rng.choice([0.0, 0.05]),
        soft_decline_rate=rng.choice([0.0, 0.05]),
        max_shifts_mode=rng.choice(["none", "loose", "zero"]),
        adjacent_rate=rng.choice([0.0, 0.5]),
        policy=rng.choice([POLICY_PRESETS["default"], POLICY_PRESETS["heavy_balance"], POLICY_PRESETS["strict_load"]]),
        planted=True,
    )
    base = _plant(seed, knobs)
    if base is None:
        return None
    ids = [e.id for e in base.employees if e.competence_ids]
    cut = base.days[rng.choice([10, 14, 18])]
    for share in (3, 4, 6):
        light = set(rng.sample(ids, max(1, len(ids) // share)))
        changed = _skewed(base, light, cut, seed)
        if changed is not None and changed.witness is not None:
            return base, _fresh(changed, knobs={**changed.knobs, "size": size})
    return None


class CompensationTests(unittest.TestCase):
    """(c) Does the tail make up for an uneven history?"""

    def test_tiny_compensation_is_optimal(self) -> None:
        """Brute force over the tail: the solver reaches the best month-total balance."""
        cases = []
        for seed in range(400 if STRESS else 120):
            case = _tiny_compensation_case(seed)
            if case is not None and case.witness is not None:
                cases.append(case)
            if len(cases) >= (120 if STRESS else 40):
                break
        scratch = [_fresh(case, fixed=frozenset(), generate_from=None, label=case.label + "+scratch") for case in cases]
        ignorant = [
            _fresh(case, fixed=frozenset(d for d in case.fixed if d[2] >= case.generate_from), witness=None, label=case.label + "+ignorant")
            for case in cases
        ]
        outcomes = solve_in_parallel(cases + scratch + ignorant, 10, workers=WORKERS, observe=True)
        main, fresh, blind = outcomes[: len(cases)], outcomes[len(cases) : 2 * len(cases)], outcomes[2 * len(cases) :]
        compared = 0
        for case, outcome, scratch_out, blind_out in zip(cases, main, fresh, blind):
            _judge(self, "c: tiny skewed history", case, outcome)
            if outcome.status != "ok":
                continue
            exhaustive = brute_force(case, node_limit=500_000)
            people = sorted(metrics(case, outcome.assignments).eligible_employees)
            history = _history(case, case.fixed)
            row = {
                "kind": "tiny",
                "label": case.label,
                "history_spread": _spread(_month_loads(case, history, people)),
                "solver_spread": _spread(_month_loads(case, outcome.assignments, people)),
                "lower_bound": _water_fill_spread(
                    _month_loads(case, history, people).values(), len(set(outcome.assignments) - history)
                ),
                "scratch_spread": _spread(_month_loads(case, scratch_out.assignments, people)) if scratch_out.status == "ok" else None,
                "blind_spread": _spread(_month_loads(case, history | set(blind_out.assignments), people)) if blind_out.status == "ok" else None,
                "optimum_spread": None,
                "cost_gap": None,
                "hit_budget": outcome.hit_budget,
            }
            with self.subTest(label=case.label, check="brute force"):
                self.assertTrue(exhaustive.feasible or not exhaustive.complete, "brute force calls a planted month infeasible")
                if exhaustive.complete and exhaustive.feasible:
                    row["optimum_spread"] = _spread(_month_loads(case, exhaustive.best_schedule, people))
                    if not outcome.hit_budget and not known_bug_triggers(case) & _OPTIMALITY_BLOCKERS:
                        compared += 1
                        cost = first_pass_cost(case, outcome.assignments)
                        row["cost_gap"] = cost - exhaustive.best_cost
                        self.assertLessEqual(cost, exhaustive.best_cost + balance_lock_slack(exhaustive.best_cost))
                        if abs(cost - exhaustive.best_cost) <= 1e-6:
                            self.assertLessEqual(
                                day_wish_cost(case, outcome.assignments),
                                exhaustive.best_wish + exhaustive.wish_slack,
                            )
            _QUALITY.append(row)
        _TALLY["c: tiny skewed history"].notes["brute-force compared"] = compared
        self.assertGreaterEqual(compared, 25)

    def test_larger_compensation(self) -> None:
        """Small and medium months: checks 4/5, and spreads against a lower bound."""
        cases: list[tuple[Instance, Instance]] = []
        plan = [("small", s) for s in range(8)] + [("medium", s) for s in range(8, 12)]
        if STRESS:
            plan += [("small", s) for s in range(20, 40)] + [("medium", s) for s in range(40, 56)]
        for size, seed in plan:
            pair = _larger_compensation_case(3000 + seed, size)
            if pair is not None:
                cases.append(pair)
        skewed = [pair[1] for pair in cases]
        scratch = [pair[0] for pair in cases]
        blind = [
            _fresh(case, fixed=frozenset(d for d in case.fixed if d[2] >= case.generate_from), witness=None, label=case.label + "+ignorant")
            for case in skewed
        ]
        outcomes = solve_in_parallel(skewed + scratch + blind, 20, workers=WORKERS, observe=True)
        n = len(cases)
        for case, outcome, scratch_out, blind_out in zip(skewed, outcomes[:n], outcomes[n : 2 * n], outcomes[2 * n :]):
            _judge(self, "c: larger skewed history", case, outcome)
            if outcome.status != "ok":
                continue
            people = sorted(metrics(case, outcome.assignments).eligible_employees)
            history = _history(case, case.fixed)
            hist_loads = _month_loads(case, history, people)
            _QUALITY.append(
                {
                    "kind": case.knobs["size"],
                    "label": case.label,
                    "history_spread": _spread(hist_loads),
                    "solver_spread": _spread(_month_loads(case, outcome.assignments, people)),
                    "lower_bound": _water_fill_spread(hist_loads.values(), len(set(outcome.assignments) - history)),
                    "scratch_spread": _spread(_month_loads(case, scratch_out.assignments, people)) if scratch_out.status == "ok" else None,
                    "blind_spread": _spread(_month_loads(case, history | set(blind_out.assignments), people)) if blind_out.status == "ok" else None,
                    "optimum_spread": None,
                    "cost_gap": None,
                    "hit_budget": outcome.hit_budget,
                }
            )
        self.assertGreaterEqual(len(cases), 8)


# --------------------------------------------------------------------------- (d) breaking


class BreakingPlacementTests(unittest.TestCase):
    """(d) Placements that break a rule are kept and planned around."""

    def test_every_breaking_kind(self) -> None:
        """Each kind alone and all together, 1-6 of them: kept, no new breach."""
        instances: list[Instance] = []
        kinds = [(kind,) for kind in BREAKING_KINDS] + [BREAKING_KINDS]
        counts = (1, 3, 6)
        for kind_index, kind in enumerate(kinds):
            for count in counts:
                for rep in range(3 if STRESS else 1):
                    seed = 20_000 + kind_index * 100 + count * 10 + rep
                    size = "medium" if rep == 1 else "small"
                    knobs = replace(
                        sample_knobs(random.Random(seed), size, True),
                        n_breaking_fixed=count,
                        breaking_kinds=kind,
                        generate_from=random.Random(seed).choice([None, "mid"]),
                        fixed_share=random.Random(seed + 1).choice([0.0, 0.5]),
                    )
                    instance = _plant(seed, knobs)
                    if instance is not None:
                        instances.append(instance)
        for seed in range(40 if STRESS else 12):
            instance = _plant(21_000 + seed, stress_knobs(random.Random(21_000 + seed)))
            if instance is not None:
                instances.append(_fresh(instance, label=instance.label + "+stress"))
        outcomes = solve_in_parallel(instances, BUDGET, workers=WORKERS, observe=True)
        for instance, outcome in zip(instances, outcomes):
            kinds_of = instance.knobs.get("breaking_kinds")
            name = "stress_knobs" if instance.label.endswith("+stress") else (
                "all kinds" if len(kinds_of) > 1 else kinds_of[0]
            )
            _judge(self, f"d: breaking {name}", instance, outcome)
        self.assertGreaterEqual(len(instances), 24)


# --------------------------------------------------------------------------- (e) idempotence


class IdempotenceTests(unittest.TestCase):
    """(e) Everything on screen fixed -> the same roster comes back."""

    def test_whole_roster_fixed_returns_it_unchanged(self) -> None:
        """A solved month handed back as placements, from several first editable dates."""
        bases: list[Instance] = []
        for seed in range(10 if STRESS else 4):
            size = ("small", "medium")[seed % 2]
            knobs = replace(sample_knobs(random.Random(4000 + seed), size, True), generate_from=None)
            instance = _plant(4000 + seed, knobs)
            if instance is not None:
                bases.append(instance)
        solved = solve_in_parallel(bases, 20, workers=WORKERS, observe=True)
        cases: list[tuple[Instance, frozenset[Duty]]] = []
        for base, outcome in zip(bases, solved):
            if outcome.status != "ok":
                continue
            for source, roster in (("solver", frozenset(outcome.assignments)), ("witness", base.witness)):
                for cut in (None, base.days[0], base.days[len(base.days) // 2], base.days[-1]):
                    cases.append(
                        (
                            _fresh(base, fixed=roster, generate_from=cut, witness=roster, label=f"{base.label}+all-{source}@{cut}"),
                            roster,
                        )
                    )
        outcomes = solve_in_parallel([case for case, _ in cases], BUDGET, workers=WORKERS, observe=True)
        identical = 0
        for (case, roster), outcome in zip(cases, outcomes):
            _judge(self, "e: whole roster fixed", case, outcome, optimality=False)
            with self.subTest(label=case.label, check="identical"):
                self.assertEqual(outcome.status, "ok")
                self.assertEqual(set(outcome.assignments), set(roster))
                identical += set(outcome.assignments) == set(roster)
        _TALLY["e: whole roster fixed"].notes["identical output"] = identical
        self.assertGreaterEqual(len(cases), 16)


    def test_open_from_day_one_equals_whole_month(self) -> None:
        """generate_from = the 1st (the editor's value with nothing locked) is the same as None."""
        instances = []
        for seed in range(6 if STRESS else 3):
            knobs = replace(fill_in_knobs(random.Random(4500 + seed), 0.3, "small"), generate_from=None)
            instance = _plant(4500 + seed, knobs)
            if instance is not None:
                instances.append(instance)
        pairs = instances + [_fresh(item, generate_from=item.days[0], label=item.label + "@1st") for item in instances]
        outcomes = solve_in_parallel(pairs, BUDGET, workers=WORKERS, observe=True)
        n = len(instances)
        for instance, whole, first in zip(instances, outcomes[:n], outcomes[n:]):
            _judge(self, "e: generate_from = 1st", pairs[instances.index(instance) + n], first)
            if whole.hit_budget or first.hit_budget:
                continue
            with self.subTest(label=instance.label):
                self.assertEqual(whole.status, first.status)
                self.assertEqual(sorted(whole.assignments), sorted(first.assignments))

    def test_fixed_outside_month_is_dropped_by_the_solver(self) -> None:
        """In memory, a placement dated outside the month is ignored (the API refuses it, see (h))."""
        instance = _plant(4600, Knobs(n_employees=6, n_competences=1, planted=True))
        stray = (instance.employees[0].id, instance.competences[0].id, instance.days[-1] + timedelta(days=1))
        outcome = run_solver(_fresh(instance, fixed=instance.fixed | {stray}), BUDGET)
        self.assertEqual(outcome.status, "ok")
        self.assertNotIn(stray, outcome.assignments)
        self.assertEqual(validate(instance, outcome.assignments), [])


class WishPassFindsNothingTests(unittest.TestCase):
    """Finding fill_in_1 (repro: scratchpad/findings/fill_in_1.py)."""

    @unittest.expectedFailure
    def test_wish_pass_returns_a_solution_when_the_first_pass_was_proved(self) -> None:
        """Suspected bug: the second (wishes) pass finds no solution and wishes are dropped.

        Medium planted month (seed 910: 18 people, 4 roles, strict max_shifts
        and overstaff). The balance pass is proved optimal in about a second;
        the wishes pass then gets the remaining budget, yet CBC returns no
        integer solution at all (sol_status 0) -- with a 20 s and a 60 s
        budget alike -- so the solver silently restores the first-pass roster
        and ignores every day wish. The first-pass roster satisfies the
        balance lock by construction, so a feasible point is known; single
        swaps that keep the first-pass cost and gain 10 in day wishes remain.
        Nothing tells the manager that the wishes were skipped. Seen in the
        stress sweep on 3 more instances (one large where the first pass
        had used most of the budget, two medium skewed-history months).
        """
        instance = make_instance(910, replace(sample_knobs(random.Random(910), "medium", True), generate_from=None))
        outcome = run_solver(instance, 5, observe=True)
        self.assertEqual(outcome.status, "ok")
        self.assertTrue(outcome.first_pass.optimal)
        moves = [
            move
            for move in find_improving_moves(instance, outcome.assignments, balance_cap=outcome.balance_cap)
            if move.reason == "day_wish"
        ]
        self.assertEqual(moves, [])
        self.assertNotEqual(outcome.second_pass.sol_status, 0)


class DepartedEmployeeTests(unittest.TestCase):
    """The editor sends every duty on screen; what if one belongs to someone who left?"""

    def test_history_duty_of_a_departed_employee_blocks_regeneration(self) -> None:
        """Documented behaviour (``_detect_fixed_assignment_conflicts``): the solve is refused.

        A person who worked the first half of the month and then left the
        workplace (membership deactivated) still has history duties on the
        screen. The generator refuses the whole month with
        ``fixed_assignment_unknown`` instead of keeping the history as it is,
        so such a month can only be regenerated after deleting worked duties.
        This test pins the current, documented behaviour.
        """
        from app.models.associations import UserAmbulance
        from app.services.schedule_generation_service import (
            ScheduleGenerationError,
            generate_ambulance_monthly_schedule,
        )
        from tests.scheduling_harness.db_builder import fresh_session, materialize

        base = _plant(4700, Knobs(n_employees=8, n_competences=1, planted=True))
        cut = base.days[14]
        changed = regenerate(base, sorted(base.witness), cut, "leave", seed=1)
        leaver = next(
            uid for uid in sorted({d[0] for d in changed.fixed if d[2] < cut})
        )
        with fresh_session() as session:
            world = materialize(changed, session)
            session.query(UserAmbulance).filter(
                UserAmbulance.user_id == world.user_ids[leaver],
                UserAmbulance.ambulance_id == world.ambulance_id,
            ).update({"is_active": False})
            session.flush()
            with self.assertRaises(ScheduleGenerationError) as caught:
                generate_ambulance_monthly_schedule(
                    session, world.ambulance_id, changed.month, changed.year,
                    fixed_entries=world.fixed_entries_for_db(changed), generate_from=cut, time_budget_seconds=5,
                )
        codes = {issue.get("code") for issue in caught.exception.issues}
        self.assertEqual(codes, {"fixed_assignment_unknown"})
        _EXTRA["departed"].append({"issues": len(caught.exception.issues), "codes": sorted(codes)})


# --------------------------------------------------------------------------- (f) chaining


class MonthChainTests(unittest.TestCase):
    """(f) Dec 2027 -> Jan 2028 -> Feb 2028 (leap) with long rests."""

    def test_rest_across_month_boundaries(self) -> None:
        """Each month valid against the carried week; boundary rest checked independently."""
        jobs = []
        variants = [
            Knobs(n_employees=10, n_competences=1, recovery_profile="long", planted=True),
            Knobs(n_employees=14, n_competences=2, recovery_profile="long", special_days="library", planted=True),
            Knobs(n_employees=12, n_competences=2, recovery_profile="mixed", fixed_share=0.5, generate_from="mid", planted=True),
            Knobs(n_employees=16, n_competences=3, recovery_profile="long", demand_profile="weekday",
                  unavailability_rate=0.05, adjacent_rate=0.5, planted=True),
        ]
        seeds = range(4) if STRESS else range(1)
        for seed in seeds:
            for index, knobs in enumerate(variants):
                jobs.append((seed * 10 + index, replace(knobs, month=12, year=2027), 3, float(BUDGET)))
        chains = _pool_map(_chain_job, jobs)
        months = 0
        for chain in chains:
            for position, (instance, outcome) in enumerate(chain):
                months += 1
                _judge(self, "f: chained month", instance, outcome)
                if outcome.status != "ok" or position == 0:
                    continue
                previous, previous_out = chain[position - 1]
                # Spare employees added by the planter are not carried (harness artefact).
                carried = {
                    d for d in carried_week(previous, previous_out.assignments) if d[0] <= instance.knobs["n_employees"]
                }
                with self.subTest(label=instance.label, check="boundary"):
                    self.assertTrue(carried <= instance.adjacent)
                    if not instance.effective_policy.is_strict(REST):
                        continue
                    generated = set(outcome.assignments) - instance.fixed
                    rests = previous.competence_map
                    for earlier in carried:
                        rest = duty_rest(rests, earlier[1], earlier[2])
                        for later in generated:
                            if later[0] == earlier[0]:
                                self.assertFalse(
                                    collide(earlier[2], rest, later[2], duty_rest(instance.competence_map, later[1], later[2])),
                                    f"{later} inside the rest of {earlier} (rest {rest})",
                                )
            if chain:
                self.assertEqual([(i.month, i.year) for i, _ in chain][:3], [(12, 2027), (1, 2028), (2, 2028)][: len(chain)])
                if len(chain) == 3 and chain[2][1].status == "ok":
                    self.assertIn(date(2028, 2, 29), chain[2][0].day_set)
        self.assertGreaterEqual(months, 9)


# --------------------------------------------------------------------------- (g) database


class DatabasePathTests(unittest.TestCase):
    """(g) fixed_entries + generate_from through generate_ambulance_monthly_schedule."""

    def test_db_path_agrees(self) -> None:
        """Same verdict as the in-memory solve, a valid roster, history and placements kept."""
        instances: list[Instance] = []
        for seed in range(16 if STRESS else 6):
            size = "medium" if seed % 3 == 2 else "small"
            knobs = replace(
                fill_in_knobs(random.Random(6000 + seed), None, size),
                generate_from=random.Random(seed).choice(["mid", 8, 20]),
                external_duplicate_rate=0.0,
            )
            instance = _plant(6000 + seed, knobs)
            if instance is not None:
                instances.append(instance)
        # Regenerated months too: the editor's "Clear, then generate" flow.
        base = _plant(6100, Knobs(n_employees=9, n_competences=2, recovery_profile="mixed", planted=True))
        base_out = run_solver(base, BUDGET)
        if base_out.status == "ok":
            for index, change in enumerate(CHANGES):
                instances.append(regenerate(base, base_out.assignments, base.days[12], change, seed=index))
        options = [{"noise": seed % 2 == 0, "foreign_calendar": seed % 3 == 0} for seed in range(len(instances))]
        db = _pool_map(_observed_db_run, [(inst, float(BUDGET), opt) for inst, opt in zip(instances, options)])
        memory = solve_in_parallel(instances, BUDGET, workers=WORKERS, observe=True)
        agreed = 0
        for instance, option, db_out, mem_out in zip(instances, options, db, memory):
            if db_out.status == "inexpressible":
                _TALLY["g: database path"].notes["inexpressible"] += 1
                continue
            if db_bug_triggers(instance, **option) - known_bug_triggers(instance):
                _TALLY["g: database path"].notes["db bug trigger"] += 1
                continue
            _judge(self, "g: database path", instance, db_out)
            with self.subTest(label=instance.label, check="same verdict"):
                if "timeout" not in (db_out.status, mem_out.status):
                    self.assertEqual(db_out.status, mem_out.status)
                    agreed += 1
                if (
                    db_out.status == mem_out.status == "ok"
                    and not db_out.hit_budget
                    and not mem_out.hit_budget
                    and not known_bug_triggers(instance) & _OPTIMALITY_BLOCKERS
                ):
                    a = first_pass_cost(instance, db_out.assignments)
                    b = first_pass_cost(instance, mem_out.assignments)
                    self.assertLessEqual(abs(a - b), balance_lock_slack(a) + balance_lock_slack(b))
        _TALLY["g: database path"].notes["verdict agreed"] = agreed
        self.assertGreaterEqual(agreed, 8)


# --------------------------------------------------------------------------- (h) API


class EndpointMonthCheckTests(unittest.TestCase):
    """(h) POST /ambulances/{id}/schedule/generate rejects dates outside the month."""

    def _call(self, month: int, year: int, fixed: list[tuple[int, int, date]], generate_from: date | None):
        from app.api.schedules import generate_ambulance_schedule_endpoint
        from app.schemas.schedule import ScheduleEntry, ScheduleGenerationRequest

        request = ScheduleGenerationRequest(
            fixed_entries=[ScheduleEntry(user_id=u, competence_id=c, work_date=d) for u, c, d in fixed],
            generate_from=generate_from,
        )
        stub = mock.MagicMock(name="generator")
        with mock.patch("app.api.schedules.generate_ambulance_monthly_schedule", stub):
            try:
                generate_ambulance_schedule_endpoint(month, year, request, SimpleNamespace(id=7), db=mock.MagicMock())
            except HTTPException as error:
                return error.status_code, stub
        return 200, stub

    def test_outside_month_is_rejected_with_422(self) -> None:
        """Entries or generate_from in another month or year never reach the generator."""
        cases = [
            (1, 2028, [(1, 1, date(2027, 12, 31))], None),
            (1, 2028, [(1, 1, date(2028, 2, 1))], None),
            (1, 2028, [(1, 1, date(2027, 1, 15))], None),
            (1, 2028, [(1, 1, date(2028, 1, 5)), (2, 1, date(2028, 2, 5))], None),
            (2, 2028, [], date(2028, 3, 1)),
            (2, 2028, [], date(2027, 2, 15)),
            (2, 2028, [], date(2028, 1, 31)),
            (12, 2026, [(1, 1, date(2026, 12, 1))], date(2027, 1, 1)),
            (13, 2026, [], None),
            (0, 2026, [], None),
            (5, 1999, [], None),
        ]
        for month, year, fixed, start in cases:
            with self.subTest(month=month, year=year, fixed=fixed, start=start):
                code, stub = self._call(month, year, fixed, start)
                self.assertEqual(code, 422)
                stub.assert_not_called()

    def test_inside_month_reaches_the_generator(self) -> None:
        """The positive control: in-month entries and the leap day pass through unchanged."""
        fixed = [(1, 1, date(2028, 2, 1)), (2, 1, date(2028, 2, 29))]
        code, stub = self._call(2, 2028, fixed, date(2028, 2, 29))
        self.assertEqual(code, 200)
        stub.assert_called_once()
        args = stub.call_args.args
        self.assertEqual(args[1:4], (7, 2, 2028))
        self.assertEqual(args[4], fixed)
        self.assertEqual(args[5], date(2028, 2, 29))

    def test_through_http_client(self) -> None:
        """The same 422 through FastAPI routing (body parsing included)."""
        from fastapi.testclient import TestClient

        from app.core.dependencies import get_manager_ambulance
        from app.db.session import get_db
        from app.main import app

        app.dependency_overrides[get_manager_ambulance] = lambda: SimpleNamespace(id=7)
        app.dependency_overrides[get_db] = lambda: mock.MagicMock()
        try:
            client = TestClient(app)
            stub = mock.MagicMock(name="generator")
            with mock.patch("app.api.schedules.generate_ambulance_monthly_schedule", stub):
                response = client.post(
                    "/ambulances/7/schedule/generate?month=1&year=2028",
                    json={"fixed_entries": [{"user_id": 1, "competence_id": 1, "work_date": "2027-12-31"}]},
                )
                self.assertEqual(response.status_code, 422, response.text)
                response = client.post(
                    "/ambulances/7/schedule/generate?month=1&year=2028",
                    json={"generate_from": "2028-02-01"},
                )
                self.assertEqual(response.status_code, 422, response.text)
                response = client.post(
                    "/ambulances/7/schedule/generate?month=2&year=2027",
                    json={"generate_from": "2027-02-29"},
                )
                self.assertEqual(response.status_code, 422, response.text)
                stub.assert_not_called()
        finally:
            app.dependency_overrides.clear()


# --------------------------------------------------------------------------- report


def _percent(part: int, whole: int) -> str:
    return "-" if not whole else f"{100 * part / whole:.0f} %"


def tearDownModule() -> None:  # noqa: N802 - unittest hook
    """Print the verdict and quality tables (and dump them with FILL_IN_REPORT)."""
    lines = [
        "",
        "| Scenario | n | ok | timeout | infeasible (confirmed/unknown) | valid | history kept | placements kept | optimality checked | optimal | hit budget | known-bug inst. | median s | notes |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for scenario in sorted(_TALLY):
        t = _TALLY[scenario]
        notes = ", ".join(f"{k}={v}" for k, v in sorted(t.notes.items()))
        lines.append(
            f"| {scenario} | {t.n} | {t.ok} | {t.timeout} | {t.infeasible} ({t.infeasible_confirmed}/{t.infeasible_unknown}) | "
            f"{_percent(t.valid, t.ok)} | {_percent(t.history_kept, t.ok)} | {_percent(t.placements_kept, t.ok)} | "
            f"{t.opt_checked} | {_percent(t.opt_ok, t.opt_checked)} | {t.hit_budget} | {t.known_bug} | "
            f"{statistics.median(t.seconds) if t.seconds else 0:.2f} | {notes} |"
        )
    if _QUALITY:
        lines += [
            "",
            "| Compensation | n | mean history spread | mean solver spread | mean lower bound | solver = LB | mean optimum spread (tiny) | mean scratch spread | mean blind-tail spread | solver < blind | max cost gap |",
            "|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for kind in ("tiny", "small", "medium"):
            rows = [row for row in _QUALITY if row["kind"] == kind]
            if not rows:
                continue

            def mean(key: str) -> str:
                values = [row[key] for row in rows if row[key] is not None]
                return f"{statistics.mean(values):.2f}" if values else "-"

            gaps = [row["cost_gap"] for row in rows if row["cost_gap"] is not None]
            blind = [row for row in rows if row["blind_spread"] is not None]
            lines.append(
                f"| {kind} | {len(rows)} | {mean('history_spread')} | {mean('solver_spread')} | {mean('lower_bound')} | "
                f"{sum(row['solver_spread'] == row['lower_bound'] for row in rows)} | {mean('optimum_spread')} | "
                f"{mean('scratch_spread')} | {mean('blind_spread')} | "
                f"{sum(row['solver_spread'] < row['blind_spread'] for row in blind)}/{len(blind)} | "
                f"{max(gaps) if gaps else '-'} |"
            )
    print("\n".join(lines))
    path = os.environ.get("FILL_IN_REPORT")
    if path:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "tally": {k: {**v.__dict__, "notes": dict(v.notes)} for k, v in _TALLY.items()},
                    "quality": _QUALITY,
                    "extra": _EXTRA,
                },
                handle,
                default=str,
                indent=1,
            )


if __name__ == "__main__":
    unittest.main()
