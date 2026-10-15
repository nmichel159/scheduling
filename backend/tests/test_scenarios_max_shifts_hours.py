"""Scenario tests: the monthly duty maximum, duty hours and duty-kind preferences.

Dimension "max hodin/sluzieb": every ``max_shifts_mode`` of the harness
(none, zero, loose, tight, below, hetero, starved, mixed) under a strict and
a penalized monthly maximum (weights 0.5, 10, 1000 and 100000), crossed with
the hours profiles (uniform4, uniform12, mixed, fractional) and the duty-kind
preference mixes (any, surcharge, standard, mixed).

Generic checks on every solve:

1. every ``ok`` roster passes ``oracle.validate``;
2. a planted instance is never called infeasible;
3. an ``infeasible`` verdict on a random instance is confirmed by
   ``reference_feasibility`` (``unknown`` is tallied, never passed);
4. planted and not stopped at the budget: first-pass cost at most the
   witness's plus the lock slack;
5. observed and not stopped at the budget: ``find_improving_moves`` finds no
   ``first_pass`` or ``day_wish`` move.

On top of that:

* a strict maximum is never exceeded beyond the person's own placements
  (checked by this file's own count, not only by ``validate``), and a cap
  below the own placements leaves the person exactly those placements;
* 0 and ``None`` both mean "no limit": the optimum equals the uncapped one;
* under a penalized maximum the total excess is compared with the minimum an
  independent MILP written here can reach (hard rules + minimize the total
  excess). A larger solver excess is accepted only when the same MILP, with
  the excess bounded by that minimum and the documented first-pass
  objective, proves the solver's roster at least as cheap overall. The
  same MILP also checks first-pass optimality directly;
* starved months spread the unavoidable overflow evenly;
* hours fairness with mixed and fractional duty lengths (brute force on
  tiny instances, the exact MILP on small ones);
* the duty-kind tilt: of two people with identical availability, the
  surcharge-minded one never ends up with more standard duties *and* fewer
  surcharge duties than the standard-minded one (exchanging their whole
  rosters would then be strictly cheaper), and in a symmetric month the
  surcharge-minded get more surcharge duties while totals stay within one.

The default run is deterministic and takes a few minutes; the heavier sweep
runs only with ``SCHEDULING_STRESS=1``. At most six CBC processes run at
once. Known solver bugs (``known_bugs.py``) are tallied, never reported.
``MAX_SHIFTS_HOURS_REPORT=<path>`` dumps every record as JSON.
"""

from __future__ import annotations

import json
import math
import os
import random
import statistics
import time
import unittest
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, field, replace
from datetime import date, timedelta
from itertools import count
from typing import Any, Callable, Iterable

from pulp import (
    LpMinimize,
    LpProblem,
    LpStatusInfeasible,
    LpStatusOptimal,
    LpVariable,
    PULP_CBC_CMD,
    lpSum,
    value,
)

from app.services.constraint_setting_service import (
    BALANCE,
    MAX_SHIFTS,
    OVERSTAFF,
    REST,
    SOFT_DECLINE,
    policy_from_settings,
)

from tests.scheduling_harness.instances import (
    Instance,
    Knobs,
    PlantingFailed,
    make_instance,
    symmetric_instance,
    tiny_knobs,
)
from tests.scheduling_harness.known_bugs import known_bug_triggers
from tests.scheduling_harness.oracle import (
    day_wish_cost,
    find_improving_moves,
    first_pass_cost,
    metrics,
    validate,
    violation_codes,
)
from tests.scheduling_harness.reference import brute_force, reference_feasibility
from tests.scheduling_harness.runner import SolveOutcome, solve_in_parallel
from tests.scheduling_harness.semantics import (
    ANY_KIND_UNIT,
    HOURS_UNIT,
    TOTAL_UNIT,
    Duty,
    absence_rule,
    balance_lock_slack,
    demand,
    duty_rest,
    external_duties,
    fixed_counts,
    kind_units,
    touches,
)

STRESS = os.environ.get("SCHEDULING_STRESS") == "1"
REPORT_PATH = os.environ.get("MAX_SHIFTS_HOURS_REPORT")

#: At most this many CBC processes at once (one other agent shares the machine).
WORKERS = 6
BUDGET = 10.0
EXACT_LIMIT = 40.0

MODES = ("none", "zero", "loose", "tight", "below", "hetero", "starved", "mixed")
CAPPING_MODES = ("tight", "below", "hetero", "starved", "mixed")
HOURS_PROFILES = ("uniform4", "uniform12", "mixed", "fractional")
PREFERENCE_MIXES = ("any", "surcharge", "standard", "mixed")
PENALIZED_WEIGHTS = (0.5, 10.0, 1000.0, 100000.0)

_names = count()


# --- Records -------------------------------------------------------------------------------


@dataclass
class Run:
    """What one solve showed, for the summary tables."""

    family: str
    label: str
    mode: str = ""
    hours: str = ""
    prefs: str = ""
    policy: str = ""
    planted: bool = False
    status: str = ""
    seconds: float = 0.0
    hit_budget: bool = False
    reference: str | None = None
    capped: int = 0
    excess: int | None = None
    min_excess: int | None = None
    load_spread: int | None = None
    hours_spread: float | None = None
    optimality_checked: bool = False
    triggers: list[str] = field(default_factory=list)
    tags: dict = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)


RUNS: list[Run] = []


# --- Small helpers -------------------------------------------------------------------------


def policy_name(strict: bool, weight: float) -> str:
    """A short label for one monthly-maximum setting."""
    return "strict" if strict else f"pen{weight:g}"


def in_month(instance: Instance, duties: Iterable[Duty]) -> list[Duty]:
    """The duties dated inside the instance's month."""
    days = instance.day_set
    return [duty for duty in duties if duty[2] in days]


def loads(instance: Instance, duties: Iterable[Duty]) -> Counter[int]:
    """In-month duties per user: what the monthly maximum counts."""
    return Counter(duty[0] for duty in in_month(instance, duties))


def excess_by_user(instance: Instance, duties: Iterable[Duty]) -> dict[int, int]:
    """Duties above the monthly maximum per capped user (0 / None = no cap)."""
    load = loads(instance, duties)
    return {
        employee.id: max(0, load[employee.id] - employee.max_shifts_per_month)
        for employee in instance.employees
        if employee.max_shifts_per_month
    }


def total_excess(instance: Instance, duties: Iterable[Duty]) -> int:
    """Duties above everyone's monthly maximum, summed."""
    return sum(excess_by_user(instance, duties).values())


def strict_cap_breaches(instance: Instance, duties: Iterable[Duty]) -> list[tuple[int, int, int]]:
    """``(user, duties, allowed)`` for every strict maximum the roster exceeds.

    Written from the README, not via ``validate``: a strict maximum allows
    ``max(cap, own placements in the month)`` duties; 0 or ``None`` allows
    anything.
    """
    if not instance.effective_policy.is_strict(MAX_SHIFTS):
        return []
    load = loads(instance, duties)
    placed = loads(instance, instance.fixed)
    found = []
    for employee in instance.employees:
        cap = employee.max_shifts_per_month
        if not cap:
            continue
        allowed = max(cap, placed[employee.id])
        if load[employee.id] > allowed:
            found.append((employee.id, load[employee.id], allowed))
    return found


def with_caps(instance: Instance, caps: dict[int, int | None], suffix: str) -> Instance:
    """The instance with some monthly maxima replaced."""
    employees = [
        replace(employee, max_shifts_per_month=caps[employee.id])
        if employee.id in caps
        else employee
        for employee in instance.employees
    ]
    return replace(instance, employees=employees, label=f"{instance.label}-{suffix}")


def with_policy(instance: Instance, settings: dict, suffix: str) -> Instance:
    """The same instance under other rule settings."""
    knobs = dict(instance.knobs)
    knobs["policy"] = settings
    return replace(
        instance,
        policy=policy_from_settings(settings),
        label=f"{instance.label}-{suffix}",
        knobs=knobs,
    )


def build(seed: int, knobs: Knobs) -> Instance | None:
    """``make_instance``, or ``None`` when the planter gives up."""
    try:
        return make_instance(seed, knobs)
    except PlantingFailed:
        return None


def sweep_knobs(
    seed: int,
    mode: str,
    hours: str,
    prefs: str,
    strict: bool,
    weight: float,
    planted: bool,
    size: str = "small",
    **overrides: Any,
) -> Knobs:
    """Deterministic knobs for one cell of the maximum x hours x preference grid."""
    rng = random.Random(f"msh/{seed}/{mode}/{hours}/{prefs}/{strict}/{weight}/{planted}/{size}")
    if size == "small":
        employees, roles = rng.randint(5, 9), rng.randint(1, 2)
    else:
        employees, roles = rng.randint(12, 20), rng.randint(2, 3)
    month, year = rng.choice([(2, 2027), (4, 2026), (8, 2026), (12, 2026), (2, 2028)])
    knobs = Knobs(
        n_employees=employees,
        n_competences=roles,
        month=month,
        year=year,
        qualification_density=rng.choice([0.6, 0.8, 1.0]),
        demand_profile=rng.choice(["flat", "weekday", "sparse", "heavy"]),
        special_days=rng.choice(["none", "library", "random"]),
        recovery_profile=rng.choice(["zero", "one", "one", "mixed"]),
        hours_profile=hours,
        surcharge_profile=rng.choice(["weekend", "weekend", "random"]),
        unavailability_rate=rng.choice([0.0, 0.05, 0.1]),
        vacation_block_rate=rng.choice([0.0, 0.2]),
        preferred_rate=rng.choice([0.0, 0.05]),
        soft_decline_rate=rng.choice([0.0, 0.05]),
        max_shifts_mode=mode,
        preference_mix=prefs,
        external_rate=rng.choice([0.0, 0.0, 0.03]),
        adjacent_rate=rng.choice([0.0, 0.5]),
        n_fixed=rng.choice([0, 0, 3]),
        policy={MAX_SHIFTS: (strict, weight)},
        planted=planted,
        max_spares=6 if planted else None,
    )
    return replace(knobs, **overrides)


def parallel_map(function: Callable, items: list) -> list:
    """``map`` over at most :data:`WORKERS` processes (one CBC each)."""
    if len(items) <= 1:
        return [function(item) for item in items]
    with ProcessPoolExecutor(max_workers=WORKERS) as pool:
        return list(pool.map(function, items, chunksize=1))


def solve(instances: list[Instance], budget: float = BUDGET) -> list[SolveOutcome]:
    """Observed solves, at most six at once."""
    return solve_in_parallel(instances, budget, workers=WORKERS, observe=True)


def budget_hit(outcome: SolveOutcome) -> bool:
    """Whether the run may have been cut short by its time budget.

    ``hit_budget`` of an observed run counts passes that stopped with a
    roster (status 2). A wish pass that found nothing in time (status 0,
    after which the solver silently returns the first-pass roster) and a run
    that used 90 % of its wall-clock budget count as well.
    """
    second = outcome.second_pass
    if outcome.hit_budget or (second is not None and second.sol_status == 0):
        return True
    return outcome.budget is not None and outcome.seconds >= 0.9 * outcome.budget


# --- An independent exact model ------------------------------------------------------------


@dataclass
class ExactResult:
    """What :func:`exact_model` found."""

    status: str
    objective: float | None = None
    roster: frozenset[Duty] | None = None
    seconds: float = 0.0


def candidate_duties(instance: Instance) -> dict[Duty, bool]:
    """Every duty the month could hold, mapped to whether it is a placement.

    Written here from the README's rules: the window, a role that asks for
    somebody, qualification, not on a day worked elsewhere, no strict absence
    or strict "rather not", and (rest is strict) no collision with a duty
    around the month or elsewhere. Collisions among the month's own duties
    are left to the model's per-day cliques.
    """
    policy = instance.effective_policy
    competences = instance.competence_map
    days = instance.day_set
    found: dict[Duty, bool] = {duty: True for duty in instance.fixed if duty[2] in days}
    soft_strict = policy.is_strict(SOFT_DECLINE)
    for employee in instance.employees:
        outside = [
            (work_date, duty_rest(competences, competence_id, work_date))
            for user_id, competence_id, work_date in instance.adjacent
            if user_id == employee.id
        ] + external_duties(employee, instance.competences)
        for competence in instance.competences:
            if competence.id not in employee.competence_ids:
                continue
            for work_date in instance.window_days:
                if competence.required_on(work_date) == 0:
                    continue
                if work_date in employee.externally_scheduled_dates:
                    continue
                rule = absence_rule(employee, work_date)
                if rule is not None and policy.is_strict(rule):
                    continue
                if soft_strict and work_date in employee.soft_declined_dates:
                    continue
                rest = int(competence.recovery_days_on(work_date))
                if any(touches(work_date, rest, other, other_rest) for other, other_rest in outside):
                    continue
                found.setdefault((employee.id, competence.id, work_date), False)
    return found


def _ladder(problem: LpProblem, quantity, unit: float, top: int) -> LpVariable | None:
    """An epigraph variable of the documented convex ladder ``unit * L(q)``.

    ``L(q) = k^2 + (2k + 1)(q - k)`` on step ``k`` is the maximum of those
    lines over ``k = 0 .. top`` (``top`` at least the largest possible
    ``q``). Deliberately not the solver's level-variable formulation.
    """
    if unit <= 0:
        return None
    cost = LpVariable(f"ladder_{next(_names)}", lowBound=0)
    for k in range(top + 1):
        problem += cost >= unit * ((2 * k + 1) * quantity - k * k - k)
    return cost


def exact_model(
    instance: Instance,
    objective: str,
    time_limit: float = EXACT_LIMIT,
    excess_at_most: int | None = None,
    load_spread_at_most: int | None = None,
) -> ExactResult:
    """Solve the instance exactly under ``objective``.

    ``objective`` is ``"excess"`` (total duties above the penalized maxima),
    ``"first_pass"`` (the documented first-pass objective: four ladders,
    penalized maximum, overstaffing, penalized absences) or
    ``"hours_spread"`` (largest minus smallest hours among employees with a
    possible duty). ``excess_at_most`` bounds the total excess and
    ``load_spread_at_most`` the spread of duty counts among the same people
    (``hours_spread`` only). Rest must be
    strict. The returned roster is re-validated with ``oracle.validate``.
    """
    started = time.perf_counter()
    policy = instance.effective_policy
    if not policy.is_strict(REST):
        raise ValueError("exact_model needs a strict rest rule")
    competences = instance.competence_map
    candidates = candidate_duties(instance)
    problem = LpProblem(f"exact_{next(_names)}", LpMinimize)
    pick = {duty: LpVariable(f"x_{index}", cat="Binary") for index, duty in enumerate(sorted(candidates))}
    for duty, placed in candidates.items():
        if placed:
            problem += pick[duty] == 1

    by_slot: dict[tuple[int, date], list[Duty]] = defaultdict(list)
    by_user: dict[int, list[Duty]] = defaultdict(list)
    for duty in candidates:
        by_slot[(duty[1], duty[2])].append(duty)
        by_user[duty[0]].append(duty)

    placed_counts = fixed_counts(duty for duty, placed in candidates.items() if placed)
    overstaff_strict = policy.is_strict(OVERSTAFF)
    overstaff_terms = []
    for work_date in instance.window_days:
        for competence in instance.competences:
            needed = demand(competence, work_date, placed_counts)
            slot = by_slot.get((competence.id, work_date), [])
            if not slot:
                if needed > 0:
                    return ExactResult("infeasible", seconds=time.perf_counter() - started)
                continue
            staff = lpSum(pick[duty] for duty in slot)
            if overstaff_strict:
                problem += staff == needed
            else:
                problem += staff >= needed
                overstaff_terms.append(staff - needed)

    # One duty a day and strict rest in one family of cliques: on every day a
    # person may hold (start or still rest from) at most one duty, or as many
    # as their placements already hold there.
    for user_id, own in by_user.items():
        holding: dict[date, list[Duty]] = defaultdict(list)
        for duty in own:
            rest = duty_rest(competences, duty[1], duty[2])
            for offset in range(rest + 1):
                holding[duty[2] + timedelta(days=offset)].append(duty)
        for day, duties in holding.items():
            if len(duties) > 1:
                placed = sum(1 for duty in duties if candidates[duty])
                problem += lpSum(pick[duty] for duty in duties) <= max(1, placed)

    max_strict = policy.is_strict(MAX_SHIFTS)
    excess_vars = []
    for employee in instance.employees:
        cap = employee.max_shifts_per_month
        own = [duty for duty in by_user.get(employee.id, []) if duty[2] in instance.day_set]
        if not cap or not own:
            continue
        load = lpSum(pick[duty] for duty in own)
        if max_strict:
            placed = sum(1 for duty in own if candidates[duty])
            problem += load <= max(cap, placed)
        else:
            excess = LpVariable(f"excess_{employee.id}_{next(_names)}", lowBound=0)
            problem += excess >= load - cap
            excess_vars.append(excess)
    if excess_at_most is not None and excess_vars:
        problem += lpSum(excess_vars) <= excess_at_most

    terms = []
    if objective == "excess":
        terms.append(lpSum(excess_vars))
    elif objective == "first_pass":
        scale = policy.weight(BALANCE) / TOTAL_UNIT
        demanded = sum(
            int(competence.required_on(day))
            for competence in instance.competences
            for day in instance.window_days
        )
        demanded_hours = sum(
            int(competence.required_on(day)) * float(competence.shift_hours_on(day))
            for competence in instance.competences
            for day in instance.window_days
        )
        step = demanded_hours / demanded if demanded else 0.0
        for employee in instance.employees:
            own = [duty for duty in by_user.get(employee.id, []) if duty[2] in instance.day_set]
            if not own:
                continue
            surcharge_of = [competences[d[1]].is_surcharge_on(d[2]) for d in own]
            hours_of = [float(competences[d[1]].shift_hours_on(d[2])) for d in own]
            total = lpSum(pick[d] for d in own)
            surcharge = lpSum(pick[d] for d, flag in zip(own, surcharge_of) if flag)
            standard = lpSum(pick[d] for d, flag in zip(own, surcharge_of) if not flag)
            top = len(own) + 1
            surcharge_unit, standard_unit = kind_units(employee.shift_preference)
            for quantity, unit in (
                (total, TOTAL_UNIT * scale),
                (surcharge, surcharge_unit * scale),
                (standard, standard_unit * scale),
            ):
                cost = _ladder(problem, quantity, unit, top)
                if cost is not None:
                    terms.append(cost)
            if step > 0:
                hours = lpSum(h * pick[d] for d, h in zip(own, hours_of))
                cost = _ladder(
                    problem, hours * (1.0 / step), HOURS_UNIT * scale, int(math.ceil(sum(hours_of) / step)) + 1
                )
                if cost is not None:
                    terms.append(cost)
            for duty in own:
                if candidates[duty]:
                    continue
                rule = absence_rule(employee, duty[2])
                if rule is not None and not policy.is_strict(rule):
                    terms.append(policy.weight(rule) * pick[duty])
        if not max_strict and policy.weight(MAX_SHIFTS) > 0:
            terms.append(policy.weight(MAX_SHIFTS) * lpSum(excess_vars))
        if not overstaff_strict and policy.weight(OVERSTAFF) > 0:
            terms.append(policy.weight(OVERSTAFF) * lpSum(overstaff_terms))
    elif objective == "hours_spread":
        high = LpVariable(f"high_{next(_names)}")
        low = LpVariable(f"low_{next(_names)}")
        for user_id, own in by_user.items():
            load = lpSum(float(competences[d[1]].shift_hours_on(d[2])) * pick[d] for d in own)
            problem += high >= load
            problem += low <= load
        if load_spread_at_most is not None:
            most = LpVariable(f"most_{next(_names)}")
            least = LpVariable(f"least_{next(_names)}")
            for own in by_user.values():
                problem += most >= lpSum(pick[d] for d in own)
                problem += least <= lpSum(pick[d] for d in own)
            problem += most - least <= load_spread_at_most
        terms.append(high - low)
    else:
        raise ValueError(f"unknown objective {objective!r}")

    problem += lpSum(terms)
    problem.solve(PULP_CBC_CMD(msg=False, timeLimit=max(1, int(time_limit)), gapRel=1e-9))
    seconds = time.perf_counter() - started
    if problem.status == LpStatusOptimal and problem.sol_status == 1:
        roster = frozenset(duty for duty, variable in pick.items() if (variable.varValue or 0) > 0.5)
        broken = validate(instance, roster)
        if broken:
            raise AssertionError(f"exact model bug: roster breaks {sorted(violation_codes(broken))}")
        found = float(value(problem.objective) or 0.0)
        if objective == "first_pass":
            # The model is only trusted where it prices rosters like the oracle.
            priced = first_pass_cost(instance, roster)
            if abs(priced - found) > 1e-4 + 1e-7 * abs(priced):
                raise AssertionError(f"exact model bug: objective {found} vs oracle {priced}")
        return ExactResult("optimal", found, roster, seconds)
    if problem.status == LpStatusInfeasible:
        return ExactResult("infeasible", seconds=seconds)
    return ExactResult("unknown", seconds=seconds)


def _exact_job(job: tuple[Instance, str, int | None]) -> ExactResult:
    """Worker body for :func:`parallel_map`."""
    instance, objective, bound = job
    #: Minimising a spread is a hard MILP for CBC; it is only reported, so it gets less time.
    limit = 20.0 if objective == "hours_spread" else EXACT_LIMIT
    return exact_model(instance, objective, time_limit=limit, excess_at_most=bound)


# --- Generic checks ------------------------------------------------------------------------


def judge(
    family: str,
    instance: Instance,
    outcome: SolveOutcome,
    *,
    witness: Iterable[Duty] | None = None,
    planted: bool | None = None,
    move_checks: int = 8000,
    **tags: Any,
) -> Run:
    """Apply generic checks 1-5 and the strict-cap check; record the run."""
    triggers = sorted(known_bug_triggers(instance))
    knobs = instance.knobs
    policy = instance.effective_policy
    witness = instance.witness if witness is None else frozenset(witness)
    run = Run(
        family=family,
        label=instance.label,
        mode=str(knobs.get("max_shifts_mode", tags.pop("mode", ""))),
        hours=str(knobs.get("hours_profile", tags.pop("hours", ""))),
        prefs=str(knobs.get("preference_mix", tags.pop("prefs", ""))),
        policy=policy_name(policy.is_strict(MAX_SHIFTS), policy.weight(MAX_SHIFTS)),
        planted=witness is not None if planted is None else planted,
        status=outcome.status,
        seconds=round(outcome.seconds, 3),
        hit_budget=budget_hit(outcome),
        capped=sum(1 for employee in instance.employees if employee.max_shifts_per_month),
        triggers=triggers,
        tags=dict(tags),
    )
    if outcome.status == "error":
        run.problems.append(f"solver error: {outcome.error}")
    elif outcome.status == "infeasible":
        if witness is not None:
            run.problems.append(f"planted instance refused: {sorted(outcome.issue_codes)}")
        else:
            verdict, _roster = reference_feasibility(instance, time_limit=60)
            run.reference = verdict
            if verdict == "feasible":
                run.problems.append(f"called infeasible ({sorted(outcome.issue_codes)}), reference found a roster")
    elif outcome.status == "ok":
        broken = validate(instance, outcome.assignments)
        if broken and "duplicate_external_dates" not in triggers:
            run.problems.append(f"invalid roster: {sorted(violation_codes(broken))}")
        breaches = strict_cap_breaches(instance, outcome.assignments)
        if breaches:
            run.problems.append(f"strict maximum exceeded: {breaches[:3]}")
        found = metrics(instance, outcome.assignments)
        run.excess = total_excess(instance, outcome.assignments)
        run.load_spread = found.load_spread
        run.hours_spread = round(found.hours_spread, 3)
        if not broken and outcome.passes and not budget_hit(outcome):
            run.optimality_checked = True
            cost = first_pass_cost(instance, outcome.assignments)
            if witness is not None:
                planted_cost = first_pass_cost(instance, witness)
                if cost > planted_cost + balance_lock_slack(planted_cost):
                    run.problems.append(f"first pass {cost:.6f} above the witness's {planted_cost:.6f}")
            for move in find_improving_moves(
                instance, outcome.assignments, max_checks=move_checks, balance_cap=outcome.balance_cap
            ):
                if move.reason == "first_pass" or (
                    move.reason == "day_wish" and "zero_balance_skips_wishes" not in triggers
                ):
                    run.problems.append(
                        f"{move.reason} move {move.kind} -{move.removed} +{move.added} "
                        f"(first pass {move.first_pass_delta:+.4f}, wish {move.day_wish_delta:+.2f})"
                    )
                    break
    elif outcome.status == "timeout" and witness is not None:
        run.tags["planted_timeout"] = True
    RUNS.append(run)
    return run


def problems_of(runs: Iterable[Run]) -> list[str]:
    """Every recorded problem, labelled."""
    return [f"{run.label} [{run.family} {run.policy}]: {problem}" for run in runs for problem in run.problems]


# --- Reporting -----------------------------------------------------------------------------


def _summary() -> str:
    """Markdown tables of every recorded run."""
    lines = [
        "| family | policy | n | ok | infeasible (confirmed/unknown) | timeout | budget hit | median s | opt checked | excess (sum) | problems |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    groups: dict[tuple[str, str], list[Run]] = defaultdict(list)
    for run in RUNS:
        groups[(run.family, run.policy)].append(run)
    for (family, policy), group in sorted(groups.items()):
        infeasible = [run for run in group if run.status == "infeasible"]
        lines.append(
            f"| {family} | {policy} | {len(group)} | {sum(run.status == 'ok' for run in group)} "
            f"| {len(infeasible)} ({sum(run.reference == 'infeasible' for run in infeasible)}/"
            f"{sum(run.reference == 'unknown' for run in infeasible)}) "
            f"| {sum(run.status == 'timeout' for run in group)} | {sum(run.hit_budget for run in group)} "
            f"| {statistics.median(run.seconds for run in group):.2f} "
            f"| {sum(run.optimality_checked for run in group)} "
            f"| {sum(run.excess or 0 for run in group)} | {sum(len(run.problems) for run in group)} |"
        )
    return "\n".join(lines)


def tearDownModule() -> None:  # noqa: N802 - unittest hook
    """Print the summary tables and optionally dump every run as JSON."""
    if not RUNS:
        return
    print("\n\n## max_shifts_hours summary\n")
    print(_summary())
    if REPORT_PATH:
        with open(REPORT_PATH, "w", encoding="utf-8") as handle:
            json.dump([_plain(asdict(run)) for run in RUNS], handle, indent=1, default=str)


def _plain(item: Any) -> Any:
    """``item`` with every mapping key turned into a string, for JSON."""
    if isinstance(item, dict):
        return {str(key): _plain(value) for key, value in item.items()}
    if isinstance(item, (list, tuple)):
        return [_plain(value) for value in item]
    return item


# --- Strict maximum --------------------------------------------------------------------------


def _strict_sweep(test: unittest.TestCase, seeds: Iterable[int], size: str) -> list[Run]:
    """Every mode x hours profile, preference mixes rotating, planted and random."""
    cells: list[Instance] = []
    for seed in seeds:
        for mode_index, mode in enumerate(MODES):
            for hours_index, hours in enumerate(HOURS_PROFILES):
                prefs = PREFERENCE_MIXES[(mode_index + hours_index + seed) % len(PREFERENCE_MIXES)]
                for planted in (True, False):
                    knobs = sweep_knobs(seed, mode, hours, prefs, True, 1000.0, planted, size)
                    instance = build(seed * 100 + mode_index * 10 + hours_index, knobs)
                    if instance is not None:
                        cells.append(instance)
    outcomes = solve(cells, BUDGET if size == "small" else 20.0)
    runs = [judge("strict-sweep", instance, outcome) for instance, outcome in zip(cells, outcomes)]
    test.assertTrue(runs)
    return runs


def _below_placements(test: unittest.TestCase, seeds: Iterable[int]) -> list[Run]:
    """A strict cap below a person's own placements keeps exactly those placements."""
    cells: list[tuple[Instance, list[int]]] = []
    for seed in seeds:
        knobs = sweep_knobs(seed, "none", "mixed", "any", True, 1000.0, True, n_fixed=12, fixed_share=0.3)
        base = build(seed, knobs)
        if base is None:
            continue
        placed = loads(base, base.fixed)
        chosen = sorted(user for user, n in placed.items() if n >= 2)[:3]
        if not chosen:
            continue
        caps = {user: 1 for user in chosen}
        # Not planted any more: the witness may give these people more duties.
        cells.append((replace(with_caps(base, caps, "cap1"), witness=None), chosen))
    outcomes = solve([instance for instance, _chosen in cells])
    runs = []
    for (instance, chosen), outcome in zip(cells, outcomes):
        run = judge("cap-below-placements", instance, outcome, planted=False)
        if outcome.status == "ok":
            got = loads(instance, outcome.assignments)
            placed = loads(instance, instance.fixed)
            for user in chosen:
                if got[user] != placed[user]:
                    run.problems.append(f"user {user}: {got[user]} duties, {placed[user]} placements, cap 1")
            run.tags["users_checked"] = len(chosen)
        runs.append(run)
    test.assertTrue(runs)
    return runs


def _no_limit_equivalence(test: unittest.TestCase, seeds: Iterable[int]) -> list[Run]:
    """0, ``None`` and an unreachable cap all give the uncapped optimum."""
    groups: list[list[Instance]] = []
    for seed in seeds:
        knobs = sweep_knobs(seed, "none", HOURS_PROFILES[seed % 4], PREFERENCE_MIXES[seed % 4], False, 1000.0, True)
        base = build(seed, knobs)
        if base is None:
            continue
        ids = [employee.id for employee in base.employees]
        variants = [
            with_caps(base, {user: None for user in ids}, "none"),
            with_policy(with_caps(base, {user: 0 for user in ids}, "zero"), {MAX_SHIFTS: (True, 1000.0)}, "strict"),
            with_caps(base, {user: 0 for user in ids}, "zero-pen"),
            with_policy(with_caps(base, {user: 999 for user in ids}, "999"), {MAX_SHIFTS: (True, 1000.0)}, "strict"),
            with_caps(base, {user: (0 if user % 2 else None) for user in ids}, "half-zero"),
        ]
        groups.append(variants)
    outcomes = solve([instance for group in groups for instance in group])
    runs: list[Run] = []
    position = 0
    for group in groups:
        results = outcomes[position:position + len(group)]
        position += len(group)
        group_runs = [judge("no-limit", instance, outcome) for instance, outcome in zip(group, results)]
        runs += group_runs
        if any(o.status != "ok" or budget_hit(o) for o in results):
            continue
        costs = [first_pass_cost(instance, o.assignments) for instance, o in zip(group, results)]
        reference = costs[0]
        for instance, cost, run in zip(group, costs, group_runs):
            if abs(cost - reference) > balance_lock_slack(reference):
                run.problems.append(f"optimum {cost:.6f} differs from the uncapped {reference:.6f}")
        group_runs[0].tags["same_roster"] = sum(
            sorted(o.assignments) == sorted(results[0].assignments) for o in results
        )
    test.assertTrue(runs)
    return runs


class StrictMaximumTests(unittest.TestCase):
    """A strict monthly maximum, and what 0 / None mean."""

    def test_strict_cap_every_mode_and_hours_profile(self) -> None:
        """8 modes x 4 hours profiles (preference mixes rotating), planted and random."""
        runs = _strict_sweep(self, range(1), "small")
        self.assertEqual(problems_of(runs), [])
        self.assertGreater(sum(run.capped for run in runs if run.status == "ok"), 0)

    def test_cap_below_own_placements(self) -> None:
        """Cap 1 for people with 2+ placements: they keep exactly their placements."""
        runs = _below_placements(self, range(6))
        self.assertEqual(problems_of(runs), [])
        self.assertGreater(sum(run.tags.get("users_checked", 0) for run in runs), 0)

    def test_zero_and_none_mean_no_limit(self) -> None:
        """None, 0 (strict and penalized), 999 and a mix give the same optimum."""
        runs = _no_limit_equivalence(self, range(4))
        self.assertEqual(problems_of(runs), [])


# --- Penalized maximum ---------------------------------------------------------------------


def _penalized_sweep(
    test: unittest.TestCase,
    seeds: Iterable[int],
    modes: Iterable[str],
    weights: Iterable[float],
    roles: int | None = None,
) -> list[Run]:
    """Solver excess and first-pass cost against the independent MILP.

    One planted base per (seed, mode); each weight is a variant. The MILP
    gives the least total excess the hard rules allow (once per base) and
    the first-pass optimum for every weight; where the solver's excess is
    above the minimum, the MILP with the excess bounded by it must not find
    a cheaper roster.
    """
    weights = tuple(weights)
    bases: list[Instance] = []
    for seed in seeds:
        for mode_index, mode in enumerate(modes):
            hours = HOURS_PROFILES[(seed + mode_index) % 4]
            prefs = PREFERENCE_MIXES[(seed + 2 * mode_index) % 4]
            knobs = sweep_knobs(
                seed, mode, hours, prefs, False, 1000.0, True,
                n_employees=random.Random(f"n/{seed}/{mode}").randint(5, 8),
                n_fixed=0, demand_profile=random.Random(f"d/{seed}/{mode}").choice(["flat", "weekday", "heavy"]),
                **({"n_competences": roles} if roles else {}),
            )
            base = build(seed * 31 + mode_index, knobs)
            if base is not None and base.effective_policy.is_strict(REST):
                bases.append(base)
    variants = [
        with_policy(base, {MAX_SHIFTS: (False, weight)}, f"w{weight:g}") for base in bases for weight in weights
    ]
    outcomes = solve(variants)
    minimum = parallel_map(_exact_job, [(base, "excess", None) for base in bases])
    optimum = parallel_map(_exact_job, [(variant, "first_pass", None) for variant in variants])
    runs: list[Run] = []
    lexi_jobs: list[tuple[int, tuple[Instance, str, int]]] = []
    for index, (variant, outcome, best) in enumerate(zip(variants, outcomes, optimum)):
        least = minimum[index // len(weights)]
        weight = weights[index % len(weights)]
        run = judge("penalized-excess", variant, outcome, weight=weight)
        run.tags["exact_status"] = best.status
        run.tags["exact_seconds"] = round(best.seconds, 2)
        if least.status == "optimal":
            run.min_excess = int(round(least.objective))
        if outcome.status == "ok" and best.status == "optimal":
            cost = first_pass_cost(variant, outcome.assignments)
            exact_cost = first_pass_cost(variant, best.roster)
            run.tags["exact_excess"] = total_excess(variant, best.roster)
            run.tags["cost_gap"] = round(cost - exact_cost, 6)
            if not budget_hit(outcome) and cost > exact_cost + balance_lock_slack(max(cost, exact_cost)):
                run.problems.append(f"first pass {cost:.6f}, the exact model reaches {exact_cost:.6f}")
        if outcome.status == "ok" and run.min_excess is not None and run.excess > run.min_excess:
            run.tags["above_min"] = run.excess - run.min_excess
            if weight >= 1000:
                lexi_jobs.append((len(runs), (variant, "first_pass", run.min_excess)))
        runs.append(run)
    lexi = parallel_map(_exact_job, [job for _position, job in lexi_jobs])
    for (position, (variant, _objective, _bound)), best in zip(lexi_jobs, lexi):
        run = runs[position]
        outcome = outcomes[position]
        run.tags["lexi_status"] = best.status
        if best.status != "optimal" or budget_hit(outcome):
            continue
        cost = first_pass_cost(variant, outcome.assignments)
        bounded = first_pass_cost(variant, best.roster)
        run.tags["lexi_cost_gap"] = round(cost - bounded, 6)
        if cost > bounded + balance_lock_slack(max(cost, bounded)):
            run.problems.append(
                f"excess {run.excess} > minimum {run.min_excess}, and a minimum-excess roster is cheaper "
                f"({bounded:.6f} < {cost:.6f})"
            )
    test.assertTrue(runs)
    return runs


def _starved_symmetric(test: unittest.TestCase, sizes: Iterable[tuple[int, int, int]]) -> list[Run]:
    """Identical people, all capped at 60 % of the average: the overflow is even."""
    cells: list[tuple[Instance, int]] = []
    for n_employees, n_competences, month in sizes:
        base = symmetric_instance(n_employees, n_competences, month=month, recovery=1)
        demanded = n_competences * len(base.days)
        cap = max(1, math.floor(0.6 * math.ceil(demanded / n_employees)))
        capped = with_caps(base, {e.id: cap for e in base.employees}, f"starved{cap}")
        for weight in PENALIZED_WEIGHTS:
            cells.append(
                (with_policy(capped, {MAX_SHIFTS: (False, weight)}, f"w{weight:g}"), demanded - n_employees * cap)
            )
    outcomes = solve([instance for instance, _least in cells])
    runs = []
    for (instance, least), outcome in zip(cells, outcomes):
        run = judge("starved-symmetric", instance, outcome, planted=False, mode="starved", hours="uniform4", prefs="any")
        if outcome.status == "ok":
            per_user = excess_by_user(instance, outcome.assignments)
            run.min_excess = least
            run.tags["excess_distribution"] = dict(sorted(Counter(per_user.values()).items()))
            if run.excess != least:
                run.problems.append(f"total excess {run.excess}, the month forces exactly {least}")
            if max(per_user.values()) - min(per_user.values()) > 1:
                run.problems.append(f"overflow uneven: {sorted(per_user.values())}")
            if run.load_spread > 1:
                run.problems.append(f"load spread {run.load_spread} among identical people")
        runs.append(run)
    test.assertTrue(runs)
    return runs


def _hetero_symmetric(test: unittest.TestCase) -> list[Run]:
    """Identical people, part-timers capped low: at a high weight the excess is minimal."""
    cells = []
    for n_employees, part_cap, full_cap, month in ((6, 2, 8, 8), (8, 2, 6, 12), (5, 3, 9, 2)):
        base = symmetric_instance(n_employees, 1, month=month, recovery=1)
        caps = {e.id: (part_cap if e.id <= n_employees // 2 else full_cap) for e in base.employees}
        capped = with_caps(base, caps, f"hetero{part_cap}-{full_cap}")
        for weight in PENALIZED_WEIGHTS:
            cells.append(with_policy(capped, {MAX_SHIFTS: (False, weight)}, f"w{weight:g}"))
    outcomes = solve(cells)
    least = parallel_map(_exact_job, [(instance, "excess", None) for instance in cells])
    runs = []
    for instance, outcome, best in zip(cells, outcomes, least):
        weight = instance.effective_policy.weight(MAX_SHIFTS)
        run = judge("hetero-symmetric", instance, outcome, planted=False, mode="hetero", hours="uniform4", prefs="any")
        if outcome.status == "ok" and best.status == "optimal":
            run.min_excess = int(round(best.objective))
            run.tags["excess_by_user"] = excess_by_user(instance, outcome.assignments)
            if weight >= 1000 and run.excess != run.min_excess:
                run.problems.append(f"weight {weight:g}: excess {run.excess}, minimum {run.min_excess}")
        runs.append(run)
    test.assertTrue(runs)
    return runs


class PenalizedMaximumTests(unittest.TestCase):
    """A penalized maximum: least excess, paid only where it is cheaper overall."""

    def test_excess_against_the_exact_model(self) -> None:
        """Capping modes x weights 0.5/10/1000/100000 against the independent MILP (one role)."""
        runs = _penalized_sweep(self, range(2), CAPPING_MODES, PENALIZED_WEIGHTS, roles=1)
        self.assertEqual(problems_of(runs), [])
        self.assertGreater(sum(run.optimality_checked for run in runs), len(runs) / 2)

    def test_starved_symmetric_overflow_is_even(self) -> None:
        """Everybody capped at 60 % of the average: forced excess, spread evenly."""
        runs = _starved_symmetric(self, ((6, 1, 8), (7, 2, 12), (5, 1, 2)))
        self.assertEqual(problems_of(runs), [])

    def test_hetero_symmetric_minimal_excess(self) -> None:
        """Part-timers and full-timers: at weight >= 1000 the excess is the minimum."""
        runs = _hetero_symmetric(self)
        self.assertEqual(problems_of(runs), [])


# --- Hours fairness ------------------------------------------------------------------------


def _tiny_hours(test: unittest.TestCase, seeds: Iterable[int]) -> list[Run]:
    """Tiny instances with mixed and fractional hours against the brute force."""
    cells: list[Instance] = []
    for seed in seeds:
        rng = random.Random(f"tiny-hours/{seed}")
        knobs = replace(
            tiny_knobs(rng, planted=True),
            hours_profile=("mixed", "fractional")[seed % 2],
            max_shifts_mode=MODES[seed % len(MODES)],
            preference_mix=PREFERENCE_MIXES[seed % 4],
        )
        instance = build(seed, knobs)
        if instance is not None and not known_bug_triggers(instance) - {"penalized_rest_month_end"}:
            cells.append(instance)
    outcomes = solve(cells, 5.0)
    runs = []
    for instance, outcome in zip(cells, outcomes):
        run = judge("tiny-hours", instance, outcome)
        if outcome.status == "ok" and not budget_hit(outcome):
            best = brute_force(instance, node_limit=300_000)
            run.tags["brute_complete"] = best.complete
            if best.complete and best.feasible:
                cost = first_pass_cost(instance, outcome.assignments)
                run.tags["brute_gap"] = round(cost - best.best_cost, 6)
                if cost > best.best_cost + balance_lock_slack(best.best_cost):
                    run.problems.append(f"first pass {cost:.6f}, brute force {best.best_cost:.6f}")
                elif abs(cost - best.best_cost) <= 1e-6:
                    wish = day_wish_cost(instance, outcome.assignments)
                    if wish > best.best_wish + best.wish_slack + 1e-6:
                        run.problems.append(f"day wishes {wish:.4f}, brute force {best.best_wish:.4f}")
        runs.append(run)
    test.assertTrue(runs)
    return runs


def _hours_small(test: unittest.TestCase, seeds: Iterable[int], roles: int | None = None) -> list[Run]:
    """Small mixed / fractional hour months: first-pass optimum and the hours spread."""
    cells: list[Instance] = []
    for seed in seeds:
        hours = ("mixed", "fractional")[seed % 2]
        knobs = sweep_knobs(
            seed, ("none", "loose")[seed % 2], hours, PREFERENCE_MIXES[seed % 4], False, 1000.0, True,
            n_fixed=0, n_employees=random.Random(f"h/{seed}").randint(4, 7),
            **({"n_competences": roles} if roles else {}),
        )
        instance = build(seed, knobs)
        if instance is not None:
            cells.append(instance)
    outcomes = solve(cells)
    optimum = parallel_map(_exact_job, [(instance, "first_pass", None) for instance in cells])
    spread = parallel_map(_exact_job, [(instance, "hours_spread", None) for instance in cells])
    runs = []
    for instance, outcome, best, flat in zip(cells, outcomes, optimum, spread):
        run = judge("hours-small", instance, outcome)
        if flat.status == "optimal":
            run.tags["min_hours_spread"] = round(flat.objective, 3)
        run.tags["spread_status"] = flat.status
        run.tags["exact_status"] = best.status
        run.tags["exact_seconds"] = round(best.seconds, 2)
        if outcome.status == "ok" and best.status == "optimal":
            cost = first_pass_cost(instance, outcome.assignments)
            exact_cost = first_pass_cost(instance, best.roster)
            run.tags["cost_gap"] = round(cost - exact_cost, 6)
            run.tags["exact_hours_spread"] = round(metrics(instance, best.roster).hours_spread, 3)
            if not budget_hit(outcome) and cost > exact_cost + balance_lock_slack(max(cost, exact_cost)):
                run.problems.append(f"first pass {cost:.6f}, the exact model reaches {exact_cost:.6f}")
        runs.append(run)
    test.assertTrue(runs)
    return runs


class HoursFairnessTests(unittest.TestCase):
    """Fair hours with duties of different lengths."""

    def test_symmetric_long_duties(self) -> None:
        """Identical people, 12-hour duties: loads within one duty, hours within 12."""
        cells = [
            symmetric_instance(n, k, month=m, recovery=r, hours=12.0)
            for n, k, m, r in ((5, 1, 8, 1), (7, 2, 2, 1), (6, 1, 12, 0), (9, 3, 4, 2))
        ]
        runs = [
            judge("symmetric-12h", instance, outcome, planted=False, mode="none", hours="uniform12", prefs="any")
            for instance, outcome in zip(cells, solve(cells))
        ]
        problems = problems_of(runs)
        for run in runs:
            if run.status != "ok":
                problems.append(f"{run.label}: {run.status}")
            elif run.load_spread > 1 or run.hours_spread > 12 + 1e-6:
                problems.append(f"{run.label}: load spread {run.load_spread}, hours spread {run.hours_spread}")
        self.assertEqual(problems, [])

    def test_tiny_mixed_and_fractional_hours_brute_force(self) -> None:
        """Tiny months, mixed / fractional hours, every cap mode: brute-force optimum."""
        runs = _tiny_hours(self, range(24))
        self.assertEqual(problems_of(runs), [])
        self.assertGreater(sum("brute_gap" in run.tags for run in runs), 5)

    def test_small_mixed_and_fractional_hours_exact(self) -> None:
        """Small months, mixed / fractional hours: the exact first-pass optimum."""
        runs = _hours_small(self, range(6), roles=1)
        self.assertEqual(problems_of(runs), [])


#: A planted 4-person month with fractional duty lengths (4.5 / 6.25 / 7.5 / 12 h)
#: where the first-pass optimum keeps counts within one but not hours.
HOURS_DOC_KNOBS = Knobs(
    n_employees=4, n_competences=1, month=8, year=2026, qualification_density=1.0,
    demand_profile="sparse", special_days="random", recovery_profile="one", hours_profile="fractional",
    unavailability_rate=0.1, vacation_block_rate=0.2, preferred_rate=0.05, soft_decline_rate=0.05,
    max_shifts_mode="loose", preference_mix="mixed", policy={MAX_SHIFTS: (False, 1000.0)},
    planted=True, max_spares=6,
)


class HoursBalanceDocTests(unittest.TestCase):
    """Suspected doc mismatch: "balanced in both" counts and hours (model doc 3.2)."""

    @unittest.expectedFailure
    def test_hours_balanced_where_counts_are(self) -> None:
        """Mixed duty lengths should leave the month balanced in hours as well as counts.

        Model doc 3.2 says the hours ladder is stepped in one average duty so
        that where 4- and 12-hour duties mix "the roster comes out balanced in
        both". On this planted month (seed 3, ``HOURS_DOC_KNOBS``; three
        surcharge-minded people) the solver's roster, which equals the exact
        first-pass optimum of this file's independent MILP, has a count
        spread of 1 but an hours spread of 10.25 h, while a roster with the
        same count spread and an hours spread of 1.25 h exists. The gap
        (9 h) exceeds one average duty (8.39 h): the kind ladders outweigh the
        hours ladder. The objective does what it says; the doc's promise is
        stronger than the objective (repro: ``findings/max_shifts_hours_1.py``).
        """
        from tests.scheduling_harness.oracle import CostModel
        from tests.scheduling_harness.runner import run_solver

        instance = make_instance(3, HOURS_DOC_KNOBS)
        outcome = run_solver(instance, 20.0, observe=True)
        self.assertEqual(outcome.status, "ok")
        self.assertFalse(budget_hit(outcome))
        found = metrics(instance, outcome.assignments)
        self.assertLessEqual(found.load_spread, 1)
        best = exact_model(instance, "hours_spread", load_spread_at_most=found.load_spread)
        self.assertEqual(best.status, "optimal")
        self.assertLessEqual(found.hours_spread, best.objective + CostModel(instance).hours_step)


# --- Preference tilt -----------------------------------------------------------------------


def _kinds(instance: Instance, duties: Iterable[Duty]) -> dict[int, tuple[int, int]]:
    """``(surcharge, standard)`` duties per user."""
    found: dict[int, list[int]] = defaultdict(lambda: [0, 0])
    for user_id, competence_id, work_date in in_month(instance, duties):
        surcharge = instance.competence_map[competence_id].is_surcharge_on(work_date)
        found[user_id][0 if surcharge else 1] += 1
    return {user: (pair[0], pair[1]) for user, pair in found.items()}


def swap_violations(
    instance: Instance, duties: Iterable[Duty], pairs: Iterable[tuple[int, int]]
) -> list[str]:
    """Pairs ``(surcharge-minded, standard-minded)`` whose rosters should be exchanged.

    For two people with identical availability, qualifications, caps and
    commitments, exchanging their whole rosters keeps every hard rule and
    leaves the total and hours ladders unchanged. If the standard-minded one
    has more surcharge duties and no more standard duties, the exchange
    lowers the kind ladders by ``2 * scale * (L(s_b) - L(s_a) + L(t_a) -
    L(t_b)) > 0``: an optimal first pass cannot leave it.
    """
    kinds = _kinds(instance, duties)
    found = []
    for surcharge_minded, standard_minded in pairs:
        s_a, t_a = kinds.get(surcharge_minded, (0, 0))
        s_b, t_b = kinds.get(standard_minded, (0, 0))
        if s_b > s_a and t_b <= t_a:
            found.append(f"{surcharge_minded}:{s_a}s/{t_a}t vs {standard_minded}:{s_b}s/{t_b}t")
    return found


def twin_instance(instance: Instance) -> tuple[Instance, list[tuple[int, int]]]:
    """Every employee gets an identical twin; originals surcharge-minded, twins standard."""
    offset = 1000
    employees = []
    pairs = []
    for employee in instance.employees:
        employees.append(replace(employee, shift_preference="surcharge"))
        employees.append(
            replace(
                employee,
                id=employee.id + offset,
                email=f"twin{employee.id}@example.test",
                shift_preference="standard",
            )
        )
        pairs.append((employee.id, employee.id + offset))
    return replace(instance, employees=employees, label=f"{instance.label}-twins"), pairs


def _twins(test: unittest.TestCase, seeds: Iterable[int]) -> list[Run]:
    """Twins with identical availability: the tilt never leaves a profitable exchange."""
    cells: list[tuple[Instance, list[tuple[int, int]]]] = []
    for seed in seeds:
        knobs = sweep_knobs(
            seed, ("none", "loose", "tight", "hetero")[seed % 4], HOURS_PROFILES[seed % 4], "any",
            False, 1000.0, True, n_fixed=0, adjacent_rate=0.0, generate_from=None,
            surcharge_profile=("weekend", "random")[seed % 2], n_employees=random.Random(seed).randint(3, 6),
        )
        base = build(seed, knobs)
        if base is not None:
            cells.append(twin_instance(base))
    outcomes = solve([instance for instance, _pairs in cells])
    runs = []
    for (instance, pairs), outcome in zip(cells, outcomes):
        run = judge("twins", instance, outcome, prefs="twins")
        if outcome.status == "ok":
            kinds = _kinds(instance, outcome.assignments)
            run.tags["pairs"] = len(pairs)
            run.tags["surcharge_s"] = sum(kinds.get(a, (0, 0))[0] for a, _b in pairs)
            run.tags["surcharge_t"] = sum(kinds.get(b, (0, 0))[0] for _a, b in pairs)
            run.tags["total_gap"] = dict(Counter(
                abs(sum(kinds.get(a, (0, 0))) - sum(kinds.get(b, (0, 0)))) for a, b in pairs
            ))
            if not budget_hit(outcome):
                for found in swap_violations(instance, outcome.assignments, pairs):
                    run.problems.append(f"exchange of twin rosters is cheaper: {found}")
        runs.append(run)
    test.assertTrue(runs)
    return runs


class PreferenceTiltTests(unittest.TestCase):
    """Surcharge-minded vs standard-minded people with identical availability."""

    def test_symmetric_half_and_half(self) -> None:
        """Identical people, half of each preference: tilt holds, totals within one."""
        cells = []
        groups = []
        for n, k, month in ((6, 1, 8), (8, 1, 12), (6, 2, 2), (4, 1, 4)):
            base = symmetric_instance(n, k, month=month)
            prefs = {e.id: ("surcharge" if e.id % 2 else "standard") for e in base.employees}
            employees = [replace(e, shift_preference=prefs[e.id]) for e in base.employees]
            cells.append(replace(base, employees=employees, label=f"{base.label}-tilt"))
            groups.append(
                [(a, b) for a in prefs if prefs[a] == "surcharge" for b in prefs if prefs[b] == "standard"]
            )
        problems = []
        for instance, pairs, outcome in zip(cells, groups, solve(cells)):
            run = judge("tilt-symmetric", instance, outcome, planted=False, mode="none", hours="uniform4", prefs="half")
            problems += problems_of([run])
            if outcome.status != "ok":
                problems.append(f"{instance.label}: {outcome.status}")
                continue
            kinds = _kinds(instance, outcome.assignments)
            minded = [a for a, _b in pairs]
            others = [b for _a, b in pairs]
            surcharge_s = [kinds.get(user, (0, 0))[0] for user in set(minded)]
            surcharge_t = [kinds.get(user, (0, 0))[0] for user in set(others)]
            run.tags["surcharge_s"] = sorted(surcharge_s)
            run.tags["surcharge_t"] = sorted(surcharge_t)
            if statistics.mean(surcharge_s) <= statistics.mean(surcharge_t):
                problems.append(f"{instance.label}: no tilt {sorted(surcharge_s)} vs {sorted(surcharge_t)}")
            if run.load_spread > 1:
                problems.append(f"{instance.label}: load spread {run.load_spread}")
            if not budget_hit(outcome):
                problems += [f"{instance.label}: {found}" for found in swap_violations(instance, outcome.assignments, pairs)]
        self.assertEqual(problems, [])

    def test_twins_with_identical_availability(self) -> None:
        """Planted months where every employee has a standard-minded twin."""
        runs = _twins(self, range(8))
        self.assertEqual(problems_of(runs), [])


# --- Stress --------------------------------------------------------------------------------


@unittest.skipUnless(STRESS, "set SCHEDULING_STRESS=1 for the heavy sweep")
class MaxShiftsStressTests(unittest.TestCase):
    """The heavier sweep: more seeds, medium sizes, every weight."""

    def test_stress_strict_sweep(self) -> None:
        """Three more small seeds and one medium seed of the full strict grid."""
        runs = _strict_sweep(self, range(10, 13), "small")
        runs += _strict_sweep(self, range(20, 21), "medium")
        self.assertEqual(problems_of(runs), [])

    def test_stress_penalized_against_exact(self) -> None:
        """Four more seeds (one or two roles) of every capping mode and weight against the MILP."""
        runs = _penalized_sweep(self, range(10, 14), CAPPING_MODES, PENALIZED_WEIGHTS)
        self.assertEqual(problems_of(runs), [])

    def test_stress_below_placements_and_no_limit(self) -> None:
        """More seeds of the cap-below-placements and no-limit checks."""
        runs = _below_placements(self, range(10, 30))
        runs += _no_limit_equivalence(self, range(10, 22))
        self.assertEqual(problems_of(runs), [])

    def test_stress_hours(self) -> None:
        """More tiny brute-force and small exact hour months."""
        runs = _tiny_hours(self, range(100, 180))
        runs += _hours_small(self, range(100, 112))
        self.assertEqual(problems_of(runs), [])

    def test_stress_twins(self) -> None:
        """More twin months."""
        runs = _twins(self, range(100, 140))
        self.assertEqual(problems_of(runs), [])


if __name__ == "__main__":
    unittest.main()
