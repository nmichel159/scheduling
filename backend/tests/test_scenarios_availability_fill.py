"""Scenario tests: how full the employees' calendars are.

The dimension under test is availability ("rozne vyplnenia od ludi"): the
share of days people cannot work (single absences of the three kinds,
vacation and business-trip blocks, a holiday crowd when the blocks cluster),
and how many day wishes ("want to" / "rather not") they leave on the days
that remain.

What is checked, on every solve:

1. Every ``ok`` roster passes the independent oracle (``validate == []``).
2. A planted instance (one with a hidden valid roster) is never refused.
3. A random instance the solver calls infeasible is confirmed by the
   independent reference model (``reference_feasibility``); ``unknown`` is a
   failed confirmation and is counted, never passed silently.
4. Planted, observed and not stopped at the budget: the solver's first-pass
   cost is at most the witness's, within the lock slack.
5. Observed and not stopped at the budget: no single reassignment, drop or
   swap lowers the first-pass cost (``first_pass``) or gains a day wish
   within the locked balance (``day_wish``).

On top of that, along the availability axis:

* Penalized absences (weights 1000/500/2000) on a planted instance whose
  witness has no breach: relaxing a strict absence to a penalized one can
  only lower the optimum, and a breach must pay for itself in first-pass
  cost.
* Fill monotonicity: adding strict absences on days the optimal roster does
  not use keeps the optimum; removing absences can only lower it.
* The database loader reads the three absence kinds the same way the
  in-memory input states them.

The default run is a small, deterministic grid (about three and a half minutes on a quiet
machine). ``SCHEDULING_STRESS=1`` enables a heavier sweep over small, medium
and some large instances. At most six CBC processes run at a time.

Set ``AVAILABILITY_FILL_REPORT=<path>`` to dump every run as JSON; the
summary tables are printed at the end of the module either way.
"""

from __future__ import annotations

import json
import os
import random
import statistics
import unittest
from collections import defaultdict
from dataclasses import asdict, dataclass, field, replace
from datetime import date
from typing import Iterable

from app.services.constraint_setting_service import (
    BUSINESS_TRIP,
    UNAVAILABLE,
    VACATION,
    policy_from_settings,
)
from app.services.schedule_generation_service import SchedulingEmployee

from tests.scheduling_harness.db_builder import run_db_solver
from tests.scheduling_harness.instances import (
    POLICY_PRESETS,
    Instance,
    Knobs,
    PlantingFailed,
    make_instance,
)
from tests.scheduling_harness.known_bugs import known_bug_triggers
from tests.scheduling_harness.oracle import (
    find_improving_moves,
    first_pass_cost,
    metrics,
    validate,
    violation_codes,
)
from tests.scheduling_harness.reference import reference_feasibility
from tests.scheduling_harness.runner import SolveOutcome, run_solver, solve_in_parallel
from tests.scheduling_harness.semantics import Duty, absence_rule, balance_lock_slack

STRESS = os.environ.get("SCHEDULING_STRESS") == "1"
REPORT_PATH = os.environ.get("AVAILABILITY_FILL_REPORT")

#: The fill levels: chance per employee and day of a single absence.
FILL_LEVELS = (0.0, 0.1, 0.2, 0.3, 0.45, 0.6, 0.75, 0.9)
#: CBC processes at once (one other agent shares the machine).
WORKERS = 6
#: Time budget per solve, by size.
BUDGETS = {"small": 10.0, "medium": 20.0, "large": 40.0}
#: Candidate moves examined by ``find_improving_moves``, by size.
MOVE_CHECKS = {"small": 20000, "medium": 8000, "large": 3000}
#: ``(n_employees, n_competences)`` ranges per size.
SIZE_RANGES = {
    "small": ((5, 10), (1, 2)),
    "medium": ((12, 22), (2, 3)),
    "large": ((25, 40), (3, 4)),
}
ABSENCE_MIXES = (
    (1.0, 0.0, 0.0),
    (0.5, 0.3, 0.2),
    (0.0, 1.0, 0.0),
    (0.0, 0.0, 1.0),
    (1 / 3, 1 / 3, 1 / 3),
)
WISH_RATES = (0.0, 0.1, 0.25, 0.5)
WISH_PATTERNS = ("iid", "weekday", "crowd")
#: Absences relaxed to penalties, with exactly one rule strict as a control.
PARTLY_PENALIZED = {VACATION: (False, 1000.0)}


# --- Records --------------------------------------------------------------


@dataclass
class _Run:
    """What one solve did, for the summary tables."""

    family: str
    size: str
    fill: float
    planted: bool
    label: str
    status: str
    seconds: float
    hit_budget: bool
    reference: str | None = None
    preferred_honored: int = 0
    preferred_opportunities: int = 0
    soft_declined_worked: int = 0
    soft_declined_days: int = 0
    absence_breaches: int = 0
    witness_breaches: int | None = None
    optimality_checked: bool = False
    wish_pass_empty: bool = False
    triggers: list[str] = field(default_factory=list)
    tags: dict = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)


_RUNS: list[_Run] = []


def wish_pass_empty(outcome: SolveOutcome) -> bool:
    """Whether the second (wish) pass ended with no roster at all (PuLP status 0).

    The solver then falls back to the first-pass roster and drops every day
    wish. It happens when that pass runs out of time before CBC finds any
    feasible point (see ``WishPassStallTests``), so it is a budget hit even
    though ``SolveOutcome.hit_budget`` only counts status 2.
    """
    second = outcome.second_pass
    return second is not None and second.sol_status == 0


def budget_hit(outcome: SolveOutcome) -> bool:
    """Whether the run may have been cut short by its time budget.

    ``hit_budget`` of an observed run counts passes that stopped with a
    roster (status 2); a wish pass that found nothing in time (status 0) and
    a run that used 90 % of its wall-clock budget count as well.
    """
    if outcome.hit_budget or wish_pass_empty(outcome):
        return True
    return outcome.budget is not None and outcome.seconds >= 0.9 * outcome.budget


# --- Instances ------------------------------------------------------------


def _knobs(seed: int, fill: float, size: str, planted: bool, **overrides: object) -> Knobs:
    """Deterministic knobs for one cell of the availability grid.

    Everything outside the availability dimension is drawn from a small,
    calm range (no manual placements, no maxima, no duties elsewhere) so the
    fill level is what decides the outcome. ``overrides`` replace any knob.
    """
    rng = random.Random(f"availability-fill/{seed}/{fill}/{size}/{planted}")
    (low_e, high_e), (low_k, high_k) = SIZE_RANGES[size]
    month, year = rng.choice([(2, 2027), (4, 2026), (8, 2026), (12, 2026), (2, 2028)])
    knobs = Knobs(
        n_employees=rng.randint(low_e, high_e),
        n_competences=rng.randint(low_k, high_k),
        month=month,
        year=year,
        qualification_density=rng.choice([0.6, 0.8, 1.0]),
        demand_profile=rng.choice(["flat", "weekday", "sparse", "mixed"]),
        special_days=rng.choice(["none", "library"]),
        recovery_profile=rng.choice(["zero", "one", "one", "mixed"]),
        hours_profile=rng.choice(["uniform4", "mixed"]),
        unavailability_rate=fill,
        absence_mix=rng.choice(ABSENCE_MIXES),
        vacation_block_rate=rng.choice([0.0, 0.2, 0.4]),
        block_cluster=rng.random() < 0.5,
        preferred_rate=rng.choice(WISH_RATES),
        soft_decline_rate=rng.choice(WISH_RATES),
        wish_pattern=rng.choice(WISH_PATTERNS),
        planted=planted,
        max_spares=6 if planted else None,
    )
    return replace(knobs, **overrides)


def _build(seed: int, knobs: Knobs) -> Instance | None:
    """``make_instance``, or ``None`` when the planter needs too many spares."""
    try:
        return make_instance(seed, knobs)
    except PlantingFailed:
        return None


def _with_policy(instance: Instance, settings: dict, suffix: str) -> Instance:
    """The same instance under another policy (the witness stays the same)."""
    knobs = dict(instance.knobs)
    knobs["policy"] = settings
    return replace(
        instance,
        policy=policy_from_settings(settings),
        label=f"{instance.label}-{suffix}",
        knobs=knobs,
    )


def _with_absences(instance: Instance, absences: dict[int, dict[date, str]]) -> Instance:
    """The instance with each employee's absences replaced by ``absences[id]``."""
    employees: list[SchedulingEmployee] = []
    for employee in instance.employees:
        own = absences.get(employee.id)
        if own is None:
            employees.append(employee)
            continue
        employees.append(
            replace(
                employee,
                unavailable_dates=frozenset(own),
                absence_rules=tuple(sorted(own.items())),
            )
        )
    return replace(instance, employees=employees)


def _absences_of(instance: Instance) -> dict[int, dict[date, str]]:
    """Every employee's absences with their rule."""
    return {
        employee.id: {
            day: absence_rule(employee, day) or UNAVAILABLE for day in employee.unavailable_dates
        }
        for employee in instance.employees
    }


def _free_days(instance: Instance, roster: Iterable[Duty]) -> list[tuple[int, date]]:
    """``(user, day)`` pairs with no record at all and no duty in ``roster``."""
    worked = {(duty[0], duty[2]) for duty in roster}
    worked |= {(duty[0], duty[2]) for duty in instance.fixed | instance.adjacent}
    free: list[tuple[int, date]] = []
    for employee in instance.employees:
        taken = (
            employee.unavailable_dates
            | employee.externally_scheduled_dates
            | employee.preferred_dates
            | employee.soft_declined_dates
        )
        for day in instance.days:
            if day not in taken and (employee.id, day) not in worked:
                free.append((employee.id, day))
    return free


def _wish_counts(instance: Instance) -> tuple[int, int]:
    """Total "want to" and "rather not" days across employees."""
    return (
        sum(len(employee.preferred_dates) for employee in instance.employees),
        sum(len(employee.soft_declined_dates) for employee in instance.employees),
    )


# --- Checks ---------------------------------------------------------------


def _record(
    family: str,
    size: str,
    fill: float,
    instance: Instance,
    outcome: SolveOutcome,
    *,
    witness: Iterable[Duty] | None = None,
    confirm_infeasible: bool = True,
    move_checks: int | None = None,
    tags: dict | None = None,
) -> _Run:
    """Apply the generic checks to one outcome and record it.

    ``witness`` (planted instances) enables checks 2 and 4. Problems are
    stored on the record; the caller asserts there are none.
    """
    triggers = sorted(known_bug_triggers(instance))
    run = _Run(
        family=family,
        size=size,
        fill=fill,
        planted=witness is not None,
        label=instance.label,
        status=outcome.status,
        seconds=round(outcome.seconds, 3),
        hit_budget=budget_hit(outcome),
        wish_pass_empty=wish_pass_empty(outcome),
        triggers=triggers,
        tags=dict(tags or {}),
    )
    run.soft_declined_days = _wish_counts(instance)[1]
    if witness is not None:
        run.witness_breaches = sum(metrics(instance, witness).absence_breaches.values())
    if outcome.status == "error":
        run.problems.append(f"solver error: {outcome.error}")
    elif outcome.status == "infeasible":
        if witness is not None:
            run.problems.append(f"planted instance refused: {outcome.error} {sorted(outcome.issue_codes)}")
        elif confirm_infeasible:
            verdict, _roster = reference_feasibility(
                instance, time_limit=120 if size == "large" else 60
            )
            run.reference = verdict
            if verdict == "feasible":
                run.problems.append(
                    f"called infeasible ({sorted(outcome.issue_codes)}) but the reference found a roster"
                )
    elif outcome.status == "ok":
        broken = validate(instance, outcome.assignments)
        if broken:
            run.problems.append(f"invalid roster: {sorted(violation_codes(broken))}")
        else:
            found = metrics(instance, outcome.assignments)
            run.preferred_honored = found.preferred_honored
            run.preferred_opportunities = found.preferred_opportunities
            run.soft_declined_worked = found.soft_declined_worked
            run.absence_breaches = sum(found.absence_breaches.values())
            if outcome.passes and not budget_hit(outcome):
                run.optimality_checked = True
                cost = first_pass_cost(instance, outcome.assignments)
                if witness is not None:
                    planted_cost = first_pass_cost(instance, witness)
                    if cost > planted_cost + balance_lock_slack(planted_cost):
                        run.problems.append(
                            f"first-pass cost {cost:.6f} above the witness's {planted_cost:.6f}"
                        )
                if "zero_balance_skips_wishes" not in triggers:
                    moves = find_improving_moves(
                        instance,
                        outcome.assignments,
                        max_checks=move_checks or MOVE_CHECKS[size],
                        balance_cap=outcome.balance_cap,
                    )
                    for move in moves:
                        if move.reason in ("first_pass", "day_wish"):
                            run.problems.append(
                                f"{move.reason} move {move.kind} -{move.removed} +{move.added} "
                                f"(first pass {move.first_pass_delta:+.4f}, wish {move.day_wish_delta:+.2f})"
                            )
                            break
    _RUNS.append(run)
    return run


def _problems(runs: Iterable[_Run]) -> list[str]:
    """Every recorded problem, labelled."""
    return [f"{run.label} [{run.family}, fill {run.fill}]: {problem}" for run in runs for problem in run.problems]


def _solve(instances: list[Instance], size: str) -> list[SolveOutcome]:
    """Observed solves, six at a time."""
    return solve_in_parallel(instances, BUDGETS[size], workers=WORKERS, observe=True)


# --- Families ---------------------------------------------------------------


def _frontier(
    test: unittest.TestCase,
    family: str,
    size: str,
    seeds: Iterable[int],
    planted: bool,
    policy: dict | None = None,
    levels: Iterable[float] = FILL_LEVELS,
    **overrides: object,
) -> list[_Run]:
    """Solve one instance per (fill level, seed) and apply the generic checks."""
    cells: list[tuple[float, Instance]] = []
    for fill in levels:
        for seed in seeds:
            knobs = _knobs(seed, fill, size, planted, policy=policy, **overrides)
            instance = _build(seed, knobs)
            if instance is not None:
                cells.append((fill, instance))
    outcomes = _solve([instance for _fill, instance in cells], size)
    runs = [
        _record(family, size, fill, instance, outcome, witness=instance.witness)
        for (fill, instance), outcome in zip(cells, outcomes)
    ]
    test.assertTrue(runs, "no instance could be built")
    return runs


def _penalized_pairs(
    test: unittest.TestCase,
    family: str,
    size: str,
    seeds: Iterable[int],
    presets: Iterable[str],
    levels: Iterable[float],
) -> list[_Run]:
    """Strict absences against the same instance with absences penalized.

    The instance is planted under strict absences, so its witness has no
    breach; relaxing the rule keeps the witness valid. Relaxing can only lower
    the optimum: the penalized roster may cost at most what the strict
    roster costs under the penalized policy, and a breach (1000 by default)
    must be paid for by a first-pass saving at least that large.
    """
    cells: list[tuple[float, str, Instance, Instance]] = []
    for fill in levels:
        for seed in seeds:
            base = _build(seed, _knobs(seed, fill, size, True))
            if base is None:
                continue
            for preset in presets:
                relaxed = _with_policy(base, POLICY_PRESETS[preset], preset)
                test.assertEqual(validate(relaxed, relaxed.witness), [], relaxed.label)
                cells.append((fill, preset, base, relaxed))
    outcomes = _solve(
        [instance for _fill, _preset, base, relaxed in cells for instance in (base, relaxed)], size
    )
    runs: list[_Run] = []
    for index, (fill, preset, base, relaxed) in enumerate(cells):
        strict_out, relaxed_out = outcomes[2 * index], outcomes[2 * index + 1]
        _record(f"{family}-strict", size, fill, base, strict_out, witness=base.witness, tags={"preset": preset})
        run = _record(
            family, size, fill, relaxed, relaxed_out, witness=relaxed.witness, tags={"preset": preset}
        )
        runs.append(run)
        if run.problems or relaxed_out.status != "ok":
            continue
        if strict_out.status != "ok" or budget_hit(strict_out) or budget_hit(relaxed_out):
            continue
        relaxed_cost = first_pass_cost(relaxed, relaxed_out.assignments)
        strict_cost = first_pass_cost(relaxed, strict_out.assignments)
        run.tags["strict_cost"] = strict_cost
        run.tags["relaxed_cost"] = relaxed_cost
        if relaxed_cost > strict_cost + balance_lock_slack(strict_cost):
            run.problems.append(
                f"relaxing absences raised the optimum: {relaxed_cost:.6f} > strict {strict_cost:.6f}"
            )
        if run.absence_breaches:
            run.tags["breach_saving"] = strict_cost - relaxed_cost
    return runs


def _monotone(
    test: unittest.TestCase, size: str, seeds: Iterable[int], levels: Iterable[float]
) -> list[_Run]:
    """Fill monotonicity of the optimum.

    From a solved planted instance: (a) strict absences added on 30 % of the
    days nobody has a record and the roster does not use keep the optimum
    (the roster stays valid and nothing better appears); (b) half of the
    absences removed can only lower it.
    """
    bases: list[tuple[float, int, Instance]] = []
    for fill in levels:
        for seed in seeds:
            base = _build(seed, _knobs(seed, fill, size, True))
            if base is not None:
                bases.append((fill, seed, base))
    first = _solve([base for _fill, _seed, base in bases], size)
    variants: list[tuple[float, Instance, Instance, SolveOutcome, str]] = []
    for (fill, seed, base), outcome in zip(bases, first):
        _record("monotone-base", size, fill, base, outcome, witness=base.witness)
        if outcome.status != "ok" or budget_hit(outcome) or validate(base, outcome.assignments):
            continue
        rng = random.Random(f"monotone/{seed}/{fill}/{size}")
        absences = _absences_of(base)
        free = _free_days(base, outcome.assignments)
        added = {user: dict(days) for user, days in absences.items()}
        for user, day in rng.sample(free, round(0.3 * len(free))):
            added[user][day] = UNAVAILABLE
        fuller = replace(_with_absences(base, added), label=f"{base.label}-fuller")
        test.assertEqual(validate(fuller, outcome.assignments), [], fuller.label)
        fewer_map = {
            user: {day: rule for day, rule in days.items() if rng.random() < 0.5}
            for user, days in absences.items()
        }
        emptier = replace(_with_absences(base, fewer_map), label=f"{base.label}-emptier")
        emptier = replace(emptier, witness=frozenset(outcome.assignments))
        test.assertEqual(validate(emptier, outcome.assignments), [], emptier.label)
        variants.append((fill, base, fuller, outcome, "fuller"))
        variants.append((fill, base, emptier, outcome, "emptier"))
    second = _solve([variant for _fill, _base, variant, _out, _kind in variants], size)
    runs: list[_Run] = []
    for (fill, base, variant, base_out, kind), outcome in zip(variants, second):
        run = _record(
            f"monotone-{kind}",
            size,
            fill,
            variant,
            outcome,
            witness=frozenset(base_out.assignments),
            tags={"kind": kind},
        )
        runs.append(run)
        if outcome.status != "ok" or budget_hit(outcome) or run.problems:
            continue
        before = first_pass_cost(base, base_out.assignments)
        after = first_pass_cost(variant, outcome.assignments)
        run.tags["delta"] = after - before
        if kind == "fuller" and before > after + balance_lock_slack(after):
            run.problems.append(
                f"more absences lowered the optimum: {after:.6f} < {before:.6f} (the earlier run missed it)"
            )
    return runs


# --- Summary --------------------------------------------------------------


def _median(values: list[float]) -> float | None:
    """The median, or ``None`` for no values."""
    return statistics.median(values) if values else None


def _rate(numerator: float, denominator: float) -> str:
    """A percentage, or a dash."""
    return f"{100 * numerator / denominator:.1f} %" if denominator else "-"


def _summary(runs: list[_Run]) -> str:
    """Markdown tables of the recorded runs."""
    lines: list[str] = []
    families = sorted({run.family for run in runs})
    lines.append("| family | size | fill | n | ok | infeasible (confirmed / unknown) | timeout | budget hit (wish pass empty) | median s | p90 s | pref honored / opp | soft worked / days | breaches | problems |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    groups: dict[tuple[str, str, float], list[_Run]] = defaultdict(list)
    for run in runs:
        groups[(run.family, run.size, run.fill)].append(run)
    for family in families:
        for (fam, size, fill), group in sorted(groups.items()):
            if fam != family:
                continue
            ok = [run for run in group if run.status == "ok"]
            infeasible = [run for run in group if run.status == "infeasible"]
            confirmed = sum(1 for run in infeasible if run.reference == "infeasible")
            unknown = sum(1 for run in infeasible if run.reference == "unknown")
            seconds = sorted(run.seconds for run in group)
            p90 = seconds[min(len(seconds) - 1, int(0.9 * len(seconds)))] if seconds else 0
            honored = sum(run.preferred_honored for run in ok)
            opportunities = sum(run.preferred_opportunities for run in ok)
            worked = sum(run.soft_declined_worked for run in ok)
            soft_days = sum(run.soft_declined_days for run in ok)
            lines.append(
                f"| {family} | {size} | {fill} | {len(group)} | {len(ok)} ({_rate(len(ok), len(group))}) "
                f"| {len(infeasible)} ({confirmed} / {unknown}) "
                f"| {sum(1 for run in group if run.status == 'timeout')} "
                f"| {sum(1 for run in group if run.hit_budget)} ({sum(1 for run in group if run.wish_pass_empty)}) "
                f"| {_median(seconds) or 0:.2f} | {p90:.2f} "
                f"| {honored}/{opportunities} ({_rate(honored, opportunities)}) "
                f"| {worked}/{soft_days} "
                f"| {sum(run.absence_breaches for run in ok)} "
                f"| {sum(len(run.problems) for run in group)} |"
            )
    return "\n".join(lines)


def tearDownModule() -> None:  # noqa: N802 - unittest hook
    """Print the summary tables and optionally dump every run as JSON."""
    if not _RUNS:
        return
    print("\n\n## Availability fill summary\n")
    print(_summary(_RUNS))
    if REPORT_PATH:
        with open(REPORT_PATH, "w", encoding="utf-8") as handle:
            json.dump([asdict(run) for run in _RUNS], handle, indent=1, default=str)


# --- Tests ----------------------------------------------------------------


class AvailabilityFrontierTests(unittest.TestCase):
    """Feasibility along the fill axis, every verdict cross-checked."""

    def test_random_small_frontier_strict_absences(self) -> None:
        """Random small instances, default policy: every refusal is confirmed by the reference."""
        runs = _frontier(self, "random-strict", "small", range(6), planted=False)
        self.assertEqual(_problems(runs), [])
        self.assertEqual(sum(1 for run in runs if run.status == "error"), 0)
        # Sanity of the grid itself: the empty calendar is mostly feasible, the
        # 90 % one mostly not.
        empty = [run for run in runs if run.fill == 0.0]
        full = [run for run in runs if run.fill == 0.9]
        self.assertGreater(sum(run.status == "ok" for run in empty), len(empty) / 2)
        self.assertLess(sum(run.status == "ok" for run in full), len(full) / 2)

    def test_random_small_frontier_penalized_absences(self) -> None:
        """Penalized absences are not hard: the capacity pre-check must not count them as gone."""
        runs = _frontier(
            self, "random-penalized", "small", range(6), planted=False,
            policy=POLICY_PRESETS["penalized_absences"],
        )
        self.assertEqual(_problems(runs), [])

    def test_random_small_frontier_one_kind_penalized(self) -> None:
        """Only vacations penalized: plain absences and business trips stay hard per rule."""
        runs = _frontier(
            self, "random-vacation-penalized", "small", range(4), planted=False,
            policy=PARTLY_PENALIZED, absence_mix=(1 / 3, 1 / 3, 1 / 3),
            levels=(0.2, 0.45, 0.75),
        )
        self.assertEqual(_problems(runs), [])

    def test_random_small_frontier_strict_soft_decline(self) -> None:
        """A strict "rather not" acts like one more absence; refusals are confirmed."""
        runs = _frontier(
            self, "random-strict-soft", "small", range(4), planted=False,
            policy=POLICY_PRESETS["strict_wishes"], soft_decline_rate=0.5,
            levels=(0.0, 0.2, 0.45),
        )
        self.assertEqual(_problems(runs), [])

    def test_planted_small_never_refused(self) -> None:
        """Planted small instances at every fill level, blocks clustered or not."""
        runs = _frontier(self, "planted", "small", range(5), planted=True)
        self.assertEqual(_problems(runs), [])
        self.assertTrue(all(run.status in ("ok", "timeout") for run in runs))

    def test_planted_small_holiday_crowd(self) -> None:
        """Clustered vacation blocks on top of single absences (everyone off the same week)."""
        runs = _frontier(
            self, "planted-crowd", "small", range(3), planted=True,
            vacation_block_rate=0.6, block_cluster=True, levels=(0.0, 0.3, 0.6),
        )
        self.assertEqual(_problems(runs), [])

    def test_planted_medium_never_refused(self) -> None:
        """Planted medium instances at every fill level."""
        runs = _frontier(self, "planted", "medium", range(2), planted=True)
        self.assertEqual(_problems(runs), [])


class WishQualityTests(unittest.TestCase):
    """Day wishes along the fill axis: the second pass leaves no single-move gain."""

    def test_wish_patterns_against_fill(self) -> None:
        """Every wish pattern, wishes at 25 %, fill from empty to 75 %."""
        runs: list[_Run] = []
        for pattern in WISH_PATTERNS:
            runs += _frontier(
                self, f"wishes-{pattern}", "small", range(2), planted=True,
                preferred_rate=0.25, soft_decline_rate=0.25, wish_pattern=pattern,
                levels=(0.0, 0.2, 0.45, 0.75),
            )
        self.assertEqual(_problems(runs), [])
        checked = sum(1 for run in runs if run.optimality_checked)
        self.assertGreater(checked, len(runs) / 2, "too many runs stopped at the budget")


class PenalizedAbsenceTests(unittest.TestCase):
    """Breaches of penalized absences happen only when they pay for themselves."""

    def test_relaxing_absences_never_raises_the_optimum(self) -> None:
        """Planted small instances (witness without breach), strict vs penalized absences."""
        runs = _penalized_pairs(
            self, "penalized", "small", range(3), ("penalized_absences", "penalized_all"),
            (0.2, 0.45, 0.75, 0.9),
        )
        self.assertEqual(_problems(runs), [])


class FillMonotonicityTests(unittest.TestCase):
    """More absences cannot improve the optimum; absences away from the roster change nothing."""

    def test_adding_and_removing_absences(self) -> None:
        """Planted small instances at four fill levels."""
        runs = _monotone(self, "small", range(2), (0.1, 0.3, 0.45, 0.6))
        self.assertEqual(_problems(runs), [])


class DatabaseAbsenceKindTests(unittest.TestCase):
    """The loader reads cannot / vacation / business trip like the in-memory input."""

    def test_absence_kinds_through_the_database(self) -> None:
        """Planted high-fill instances with all three kinds, strict and partly penalized."""
        problems: list[str] = []
        for seed, fill, settings in (
            (0, 0.45, None),
            (1, 0.75, None),
            (2, 0.45, PARTLY_PENALIZED),
            (3, 0.6, POLICY_PRESETS["penalized_absences"]),
        ):
            knobs = _knobs(
                seed, fill, "small", True, absence_mix=(1 / 3, 1 / 3, 1 / 3),
                vacation_block_rate=0.3, block_mix=(1 / 3, 1 / 3, 1 / 3),
            )
            instance = _build(seed, knobs)
            if instance is None:
                continue
            if settings is not None:
                instance = _with_policy(instance, settings, "db")
            memory = run_solver(instance, BUDGETS["small"], observe=True)
            database = run_db_solver(instance, BUDGETS["small"])
            _record("db-memory", "small", fill, instance, memory, witness=instance.witness)
            run = _record("db", "small", fill, instance, database, witness=instance.witness)
            problems += [f"{instance.label}: {problem}" for problem in run.problems]
            if memory.status != database.status:
                problems.append(f"{instance.label}: memory {memory.status} vs database {database.status}")
            elif memory.status == "ok" and not budget_hit(memory) and not budget_hit(database):
                here = first_pass_cost(instance, memory.assignments)
                there = first_pass_cost(instance, database.assignments)
                if abs(here - there) > balance_lock_slack(min(here, there)):
                    problems.append(f"{instance.label}: first pass {here:.6f} in memory vs {there:.6f} via the database")
        self.assertEqual(problems, [])


class WishPassStallTests(unittest.TestCase):
    """Suspected new problem: the wish pass finds nothing in time and wishes are dropped."""

    @unittest.expectedFailure
    def test_wish_pass_returns_a_roster_on_a_small_month(self) -> None:
        """The second pass should at least keep the first-pass roster as its incumbent.

        Planted small month (10 people, 2 roles, December 2026, 10 % absences,
        25 % "rather not" days on one weekday each). The first pass is proved
        optimal in about a second; the second pass, started without the
        first-pass roster although it satisfies the balance lock, finds no
        feasible point in its remaining 8 s (PuLP status 0, also with a 20 s
        budget). The solver falls back to the balanced roster and ignores
        every "rather not" wish, while a swap at equal first-pass cost that
        the oracle finds saves one of them (repro:
        ``scratchpad/findings/availability_fill_1.py``).
        """
        instance = make_instance(2, _knobs(2, 0.1, "small", True))
        outcome = run_solver(instance, 10.0, observe=True)
        self.assertEqual(outcome.status, "ok")
        self.assertIsNotNone(outcome.second_pass)
        self.assertIn(outcome.second_pass.sol_status, (1, 2), "the wish pass found no roster")


@unittest.skipUnless(STRESS, "set SCHEDULING_STRESS=1 for the heavy sweep")
class AvailabilityStressTests(unittest.TestCase):
    """The heavier sweep: more seeds, medium and some large instances."""

    def test_stress_random_frontier(self) -> None:
        """Random small (12 seeds) and medium (5 seeds) instances, strict and penalized absences."""
        runs = _frontier(self, "random-strict", "small", range(100, 112), planted=False)
        runs += _frontier(self, "random-strict", "medium", range(100, 105), planted=False)
        runs += _frontier(
            self, "random-penalized", "small", range(100, 108), planted=False,
            policy=POLICY_PRESETS["penalized_absences"],
        )
        runs += _frontier(
            self, "random-strict-utilization", "medium", range(100, 103), planted=False,
            target_utilization=0.5,
        )
        self.assertEqual(_problems(runs), [])

    def test_stress_planted_frontier(self) -> None:
        """Planted small (10 seeds), medium (4 seeds) and large (1 seed) instances."""
        runs = _frontier(self, "planted", "small", range(100, 110), planted=True)
        runs += _frontier(self, "planted", "medium", range(100, 104), planted=True)
        runs += _frontier(
            self, "planted", "large", range(100, 101), planted=True,
            levels=(0.0, 0.2, 0.45, 0.75),
        )
        runs += _frontier(
            self, "planted-crowd", "medium", range(100, 102), planted=True,
            vacation_block_rate=0.6, block_cluster=True, levels=(0.0, 0.3, 0.6),
        )
        self.assertEqual(_problems(runs), [])

    def test_stress_wishes(self) -> None:
        """Every pattern and wish rate, small and medium."""
        runs: list[_Run] = []
        for pattern in WISH_PATTERNS:
            for rate in (0.1, 0.5):
                runs += _frontier(
                    self, f"wishes-{pattern}", "small", range(100, 103), planted=True,
                    preferred_rate=rate, soft_decline_rate=rate, wish_pattern=pattern,
                    levels=(0.0, 0.2, 0.45, 0.75),
                )
            runs += _frontier(
                self, f"wishes-{pattern}", "medium", range(100, 101), planted=True,
                preferred_rate=0.25, soft_decline_rate=0.25, wish_pattern=pattern,
                levels=(0.0, 0.3, 0.6),
            )
        self.assertEqual(_problems(runs), [])

    def test_stress_penalized(self) -> None:
        """Strict vs penalized absences, small (8 seeds) and medium (2 seeds)."""
        runs = _penalized_pairs(
            self, "penalized", "small", range(100, 108), ("penalized_absences", "penalized_all"),
            (0.1, 0.3, 0.6, 0.9),
        )
        runs += _penalized_pairs(
            self, "penalized", "medium", range(100, 102), ("penalized_absences",), (0.2, 0.6),
        )
        self.assertEqual(_problems(runs), [])

    def test_stress_monotone(self) -> None:
        """Fill monotonicity, small (5 seeds) and medium (1 seed)."""
        runs = _monotone(self, "small", range(100, 105), (0.1, 0.3, 0.45, 0.6, 0.75))
        runs += _monotone(self, "medium", range(100, 101), (0.2, 0.45))
        self.assertEqual(_problems(runs), [])


if __name__ == "__main__":
    unittest.main()
