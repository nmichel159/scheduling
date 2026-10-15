"""A second opinion on feasibility and optimality.

:func:`reference_feasibility` is an independently written MILP of the hard
rules only. It deliberately differs from the solver's model in structure:
duties that can never be generated are left out up front, one duty a day is
a plain per-day bound, and rest is written as pairwise exclusions between a
duty and every duty on a day it still holds -- not as the solver's single
sliding sum. Agreement between the two therefore means something. Under a
strict rest the pairwise rows are strengthened with per-day clique cuts
(at most one generated duty of a person may hold any day), which changes
nothing about which rosters are feasible -- two duties collide exactly when
they both hold some day -- but lets CBC prove long-rest months in seconds.

:func:`brute_force` enumerates every roster of a tiny instance and returns
the cheapest one by the documented objective (:func:`.oracle.first_pass_cost`,
then :func:`.oracle.day_wish_cost`), which proves or refutes the solver's
optimality on cases small enough to search.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from datetime import date, timedelta
from itertools import count

from pulp import (
    LpMinimize,
    LpProblem,
    LpStatusInfeasible,
    LpStatusOptimal,
    LpVariable,
    PULP_CBC_CMD,
    lpSum,
)

from app.services.constraint_setting_service import BALANCE, OVERSTAFF, SPREAD

from tests.scheduling_harness.instances import Instance
from tests.scheduling_harness.oracle import (
    CostModel,
    _Context,
    day_wish_cost,
    day_wish_weights,
    validate,
)
from tests.scheduling_harness.semantics import Duty, demand

_names = count()


def _candidates(context: _Context) -> dict[Duty, bool]:
    """Every duty a roster may contain, mapped to whether it is a placement.

    A generated duty must pass every per-person rule on its own, including
    strict rest against everything that is not a decision -- placements,
    duties around the month and duties elsewhere.
    """
    instance = context.instance
    placed_days = {(duty[0], duty[2]) for duty in context.fixed}
    found: dict[Duty, bool] = {duty: True for duty in sorted(context.fixed)}
    for employee in instance.employees:
        own_fixed = sorted(duty for duty in context.fixed if duty[0] == employee.id)
        for competence in instance.competences:
            for work_date in instance.window_days:
                duty = (employee.id, competence.id, work_date)
                if duty in found or (employee.id, work_date) in placed_days:
                    continue
                if context.fits(employee.id, competence.id, work_date, own_fixed):
                    found[duty] = False
    return found


def reference_feasibility(
    instance: Instance, time_limit: float = 60, clique_cuts: bool = True
) -> tuple[str, frozenset[Duty] | None]:
    """Decide whether any roster keeps every hard rule.

    Returns ``('feasible', roster)``, ``('infeasible', None)`` or
    ``('unknown', None)`` when CBC ran out of time. Treat ``'unknown'`` as a
    failed confirmation, never as a pass. ``clique_cuts=False`` leaves the
    rest as pairwise rows only (slow on long rests; for cross-checking).
    """
    context = _Context(instance)
    candidates = _candidates(context)
    problem = LpProblem(f"reference_{next(_names)}", LpMinimize)
    pick = {
        duty: LpVariable(f"pick_{index}", cat="Binary")
        for index, duty in enumerate(sorted(candidates))
    }
    problem += lpSum([])  # feasibility only

    for duty, placed in candidates.items():
        if placed:
            problem += pick[duty] == 1

    by_slot: dict[tuple[int, date], list[Duty]] = {}
    by_person_day: dict[tuple[int, date], list[Duty]] = {}
    by_person: dict[int, list[Duty]] = {}
    for duty in candidates:
        by_slot.setdefault((duty[1], duty[2]), []).append(duty)
        by_person_day.setdefault((duty[0], duty[2]), []).append(duty)
        by_person.setdefault(duty[0], []).append(duty)

    exact = context.policy.is_strict(OVERSTAFF)
    for work_date in instance.window_days:
        for competence in instance.competences:
            needed = demand(competence, work_date, context.fixed_counts)
            slot = by_slot.get((competence.id, work_date), [])
            if not slot:
                if needed > 0:
                    return "infeasible", None
                continue
            staff = lpSum(pick[duty] for duty in slot)
            problem += (staff == needed) if exact else (staff >= needed)

    # One duty a day, or as many as were placed there by hand.
    for (user_id, work_date), duties in by_person_day.items():
        placed = context.fixed_by_user_day[(user_id, work_date)]
        if len(duties) > max(1, placed):
            problem += lpSum(pick[duty] for duty in duties) <= max(1, placed)

    # Rest, pairwise: a generated duty excludes every duty on a day it
    # holds, and every earlier duty whose rest reaches it.
    if context.rest_strict:
        for user_id, duties in by_person.items():
            by_day: dict[date, list[Duty]] = {}
            for duty in duties:
                by_day.setdefault(duty[2], []).append(duty)
            for duty in duties:
                rest = context.rest(duty)
                for offset in range(1, rest + 1):
                    for later in by_day.get(duty[2] + timedelta(days=offset), []):
                        if candidates[duty] and candidates[later]:
                            continue
                        problem += pick[duty] + pick[later] <= 1
            # Clique cuts: every generated duty holding a day excludes every
            # other one holding it.
            holding: dict[date, list[Duty]] = {}
            for duty in duties if clique_cuts else ():
                if candidates[duty]:
                    continue
                for offset in range(context.rest(duty) + 1):
                    holding.setdefault(duty[2] + timedelta(days=offset), []).append(duty)
            for day in sorted(holding):
                if len(holding[day]) > 1:
                    problem += lpSum(pick[duty] for duty in holding[day]) <= 1

    for user_id, duties in by_person.items():
        limit = context.limit(user_id)
        if limit is not None and len(duties) > limit:
            problem += lpSum(pick[duty] for duty in duties) <= limit

    problem.solve(PULP_CBC_CMD(msg=False, timeLimit=max(1, int(time_limit))))
    if problem.status == LpStatusOptimal:
        roster = frozenset(duty for duty, variable in pick.items() if (variable.varValue or 0) > 0.5)
        violations = validate(instance, roster)
        if violations:
            raise AssertionError(
                f"harness bug: reference roster breaks {[v.code for v in violations[:5]]}"
            )
        return "feasible", roster
    if problem.status == LpStatusInfeasible:
        return "infeasible", None
    return "unknown", None


@dataclass
class BruteForceResult:
    """What an exhaustive search over a tiny instance found."""

    complete: bool
    feasible: bool
    best_cost: float | None
    best_wish: float | None
    best_schedule: frozenset[Duty] | None
    nodes: int
    #: How far the solver's day-wish cost may sit above ``best_wish`` on a
    #: roster with the same first-pass cost without that being a miss: the
    #: brute force ignores the spread term, worth up to the spread weight per
    #: employee, and the second pass stops within its own tolerance.
    wish_slack: float = 0.0


def brute_force(instance: Instance, node_limit: int = 2_000_000) -> BruteForceResult:
    """Search every roster of a tiny instance, cheapest first-pass cost first.

    The roster is built slot by slot in date order; each slot takes every
    combination of people who may still join it. A branch is cut once its
    partial first-pass cost exceeds the best complete one, which is sound
    because adding a duty never lowers any first-pass term. Ties on the first
    pass are settled by the day wishes, which are not monotone and are only
    compared at the leaves.

    People beyond a role's demand are only ever tried when neither
    overstaffing nor the balance carries a weight -- otherwise an extra duty
    strictly raises the first-pass cost and can never be optimal.
    """
    context = _Context(instance)
    model = CostModel(instance)
    policy = context.policy
    allow_extra = (
        not policy.is_strict(OVERSTAFF)
        and policy.weight(OVERSTAFF) == 0
        and policy.weight(BALANCE) == 0
    )

    slots: list[tuple[int, date, int, bool]] = []
    for work_date in instance.window_days:
        for competence in instance.competences:
            required = int(competence.required_on(work_date))
            placed = context.fixed_counts[(competence.id, work_date)]
            needed = max(required, placed)
            if required > 0:
                slots.append((competence.id, work_date, needed - placed, allow_extra))

    roster: dict[int, list[Duty]] = {employee.id: [] for employee in instance.employees}
    for duty in sorted(context.fixed):
        roster.setdefault(duty[0], []).append(duty)
    costs = {user_id: model.employee_cost(user_id, own) for user_id, own in roster.items()}
    state = {
        "nodes": 0,
        "best": None,
        "wish": None,
        "schedule": None,
        "complete": True,
        "partial": sum(costs.values()),
    }

    def leaf() -> None:
        duties = [duty for own in roster.values() for duty in own]
        cost = state["partial"] + model.overstaff_cost(duties)
        wish = day_wish_cost(instance, duties)
        best = state["best"]
        if best is None or cost < best - 1e-9 or (abs(cost - best) <= 1e-9 and wish < state["wish"] - 1e-9):
            state["best"], state["wish"], state["schedule"] = cost, wish, frozenset(duties)

    def search(position: int) -> None:
        if state["nodes"] >= node_limit:
            # A node is being refused: from here on the search is partial.
            state["complete"] = False
            return
        state["nodes"] += 1
        best = state["best"]
        if best is not None and state["partial"] > best + 1e-9:
            return
        if position == len(slots):
            leaf()
            return
        competence_id, work_date, need, extra = slots[position]
        options = [
            employee.id
            for employee in instance.employees
            if context.fits(employee.id, competence_id, work_date, roster[employee.id])
        ]
        if len(options) < need:
            return
        options.sort(key=lambda user_id: len(roster[user_id]))
        sizes = range(need, len(options) + 1) if extra else (need,)
        for size in sizes:
            for chosen in itertools.combinations(options, size):
                before = {user_id: costs[user_id] for user_id in chosen}
                for user_id in chosen:
                    roster[user_id].append((user_id, competence_id, work_date))
                    costs[user_id] = model.employee_cost(user_id, roster[user_id])
                    state["partial"] += costs[user_id] - before[user_id]
                search(position + 1)
                for user_id in chosen:
                    roster[user_id].pop()
                    state["partial"] += before[user_id] - costs[user_id]
                    costs[user_id] = before[user_id]
                if not state["complete"]:
                    return

    search(0)
    schedule = state["schedule"]
    if schedule is not None:
        violations = validate(instance, schedule)
        if violations:
            raise AssertionError(
                f"harness bug: brute-force roster breaks {[v.code for v in violations[:5]]}"
            )
    spread = policy.weight(SPREAD)
    wish_weights = [weight for weight in day_wish_weights(instance) if weight > 0]
    tolerance = min(([spread] if spread > 0 else []) + [0.1 * weight for weight in wish_weights], default=0.0)
    return BruteForceResult(
        wish_slack=len(instance.employees) * spread + tolerance + 1e-6,
        complete=bool(state["complete"]),
        feasible=schedule is not None,
        best_cost=state["best"],
        best_wish=state["wish"],
        best_schedule=schedule,
        nodes=int(state["nodes"]),
    )


def brute_force_size(instance: Instance) -> int:
    """A rough count of the slots a brute-force search would have to fill."""
    return sum(
        int(competence.required_on(work_date))
        for competence in instance.competences
        for work_date in instance.window_days
    )


__all__ = [
    "BruteForceResult",
    "brute_force",
    "brute_force_size",
    "reference_feasibility",
]
