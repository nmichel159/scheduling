"""Realistic multi-step situations: fill-in, regeneration and month chaining.

* :func:`repair` completes a partial roster greedily -- the harness's own
  "dogenerovanie" -- and is used to plant witnesses for changed instances.
* :func:`regenerate` turns a solved month into the instance a manager faces
  mid-month: everything before ``generate_from`` frozen as manual placements,
  one change applied (a new absence, a vacation, a lower maximum, someone
  leaving, more demand), and, where :func:`repair` finds one, a witness, so
  a solver that calls the changed month infeasible can be proved wrong.
* :func:`chain_next_month` / :func:`chain_months` feed the last week of one
  solved month into the next one as duties around the month, across year
  ends and leap Februaries.
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import replace
from datetime import date, timedelta
from typing import Callable, Iterable

from app.services.constraint_setting_service import ConstraintPolicy

from tests.scheduling_harness.instances import (
    ABSENCE_RULES,
    Instance,
    Knobs,
    _slot_counts,
    _with_counts,
    knobs_of,
    make_instance,
    next_month_knobs,
)
from tests.scheduling_harness.oracle import _Context, validate
from tests.scheduling_harness.semantics import MARGIN_DAYS, Duty, as_duties, demand

#: Accepted values of ``regenerate(change=...)``.
CHANGES = ("none", "absence", "vacation_block", "lower_max", "leave", "demand_up")


def repair(
    instance: Instance,
    start: Iterable[Duty] = (),
    seed: int = 0,
    attempts: int = 30,
) -> frozenset[Duty] | None:
    """A roster keeping every hard rule, built from ``start`` where possible.

    Keeps the instance's manual placements, then as many of ``start``'s
    window duties as still fit (in a shuffled order after the first
    attempt), then staffs every remaining gap with the least loaded person
    who may take it. Returns ``None`` when no attempt succeeds -- which says
    nothing about feasibility; ask :func:`.reference.reference_feasibility`.
    """
    context = _Context(instance)
    window = set(instance.window_days)
    proposed = sorted(
        duty
        for duty in set(as_duties(start))
        if duty[2] in window and duty not in context.fixed
    )
    for attempt in range(attempts):
        rng = random.Random(seed * 7919 + attempt)
        own: dict[int, list[Duty]] = {employee.id: [] for employee in instance.employees}
        for duty in sorted(context.fixed):
            own.setdefault(duty[0], []).append(duty)
        coverage: Counter[tuple[int, date]] = Counter(
            (duty[1], duty[2]) for duty in context.fixed
        )
        order = list(proposed)
        if attempt:
            rng.shuffle(order)
            order = order[: int(len(order) * rng.uniform(0.5, 1.0))]
        for user_id, competence_id, work_date in order:
            competence = context.competences.get(competence_id)
            if competence is None or user_id not in context.employees:
                continue
            if coverage[(competence_id, work_date)] >= demand(
                competence, work_date, context.fixed_counts
            ):
                continue
            if context.fits(user_id, competence_id, work_date, own[user_id]):
                own[user_id].append((user_id, competence_id, work_date))
                coverage[(competence_id, work_date)] += 1
        failed = False
        for work_date in instance.window_days:
            competences = list(instance.competences)
            rng.shuffle(competences)
            for competence in competences:
                if competence.required_on(work_date) <= 0:
                    continue
                need = demand(competence, work_date, context.fixed_counts) - coverage[
                    (competence.id, work_date)
                ]
                while need > 0:
                    options = [
                        employee.id
                        for employee in instance.employees
                        if context.fits(employee.id, competence.id, work_date, own[employee.id])
                    ]
                    if not options:
                        failed = True
                        break
                    options.sort(key=lambda user_id: len(own[user_id]) + rng.random())
                    chosen = options[0]
                    own[chosen].append((chosen, competence.id, work_date))
                    coverage[(competence.id, work_date)] += 1
                    need -= 1
                if failed:
                    break
            if failed:
                break
        if failed:
            continue
        roster = frozenset(duty for duties in own.values() for duty in duties)
        if not validate(instance, roster):
            return roster
    return None


def _strict_absence_rule(policy: ConstraintPolicy) -> str:
    """The first absence rule the policy makes strict, else plain "cannot"."""
    return next((rule for rule in ABSENCE_RULES if policy.is_strict(rule)), ABSENCE_RULES[0])


def regenerate(
    instance: Instance,
    roster: Iterable[Duty],
    generate_from: date,
    change: str = "none",
    seed: int = 0,
    plant: bool = True,
) -> Instance:
    """The instance for re-generating a solved month from ``generate_from`` on.

    Every duty of ``roster`` before ``generate_from`` becomes a manual
    placement (the history the solver must keep), as do the instance's own
    placements in the window. Then one ``change`` (see :data:`CHANGES`) is
    applied to someone holding a generated duty on or after
    ``generate_from``. With ``plant=True`` :func:`repair` is asked for a
    witness that starts from ``roster``; ``witness`` is ``None`` when it
    finds none (the changed month may or may not be feasible).

    Raises:
        ValueError: For an unknown change or a ``generate_from`` outside the
            month.
    """
    if change not in CHANGES:
        raise ValueError(f"unknown change {change!r}")
    if generate_from not in instance.day_set:
        raise ValueError("generate_from must be a date of the month")
    rng = random.Random(seed)
    duties = sorted(set(as_duties(roster)))
    history = {duty for duty in duties if duty[2] < generate_from}
    window_fixed = {duty for duty in instance.fixed if duty[2] >= generate_from}
    fixed = frozenset(history | window_fixed)
    movable = [duty for duty in duties if duty[2] >= generate_from and duty not in fixed]
    employees = list(instance.employees)
    competences = list(instance.competences)
    policy = instance.effective_policy
    target = rng.choice(movable) if movable else None

    def update(user_id: int, **changes: object) -> None:
        for position, employee in enumerate(employees):
            if employee.id == user_id:
                employees[position] = replace(employee, **changes)

    def add_absences(user_id: int, days: Iterable[date], rule: str) -> None:
        employee = next(item for item in employees if item.id == user_id)
        days = set(days) & instance.day_set
        update(
            user_id,
            unavailable_dates=employee.unavailable_dates | days,
            absence_rules=tuple(
                sorted(
                    [item for item in employee.absence_rules if item[0] not in days]
                    + [(day, rule) for day in days]
                )
            ),
            preferred_dates=employee.preferred_dates - days,
            soft_declined_dates=employee.soft_declined_dates - days,
        )

    if target is not None and change == "absence":
        add_absences(target[0], [target[2]], _strict_absence_rule(policy))
    elif target is not None and change == "vacation_block":
        length = rng.randint(3, 7)
        add_absences(
            target[0],
            [target[2] + timedelta(days=offset) for offset in range(length)],
            "vacation",
        )
    elif movable and change in ("lower_max", "leave"):
        loads = Counter(duty[0] for duty in movable)
        user_id = max(sorted(loads), key=lambda item: loads[item])
        if change == "lower_max":
            total = sum(1 for duty in duties if duty[0] == user_id)
            update(user_id, max_shifts_per_month=max(1, total - 2))
        else:
            add_absences(
                user_id,
                [day for day in instance.days if day >= generate_from],
                ABSENCE_RULES[0],
            )
    elif target is not None and change == "demand_up":
        competence = next(item for item in competences if item.id == target[1])
        counts = _slot_counts(competence)
        slot = 7 if target[2] in competence.special_dates else target[2].weekday()
        counts[slot] += 1
        competences = [
            _with_counts(item, counts) if item.id == competence.id else item
            for item in competences
        ]

    changed = replace(
        instance,
        employees=employees,
        competences=competences,
        fixed=fixed,
        generate_from=generate_from,
        witness=None,
        label=f"{instance.label}+regen-{change}@{generate_from.isoformat()}",
        knobs={**instance.knobs, "regenerated": change},
    )
    for name in ("days", "day_set", "window_days", "history_days", "employee_map", "competence_map", "special_dates"):
        changed.__dict__.pop(name, None)
    if plant:
        changed.witness = repair(changed, duties, seed=seed)
    return changed


def carried_week(instance: Instance, roster: Iterable[Duty]) -> frozenset[Duty]:
    """The duties of a month's last week, as the next month sees them."""
    last = instance.days[-1]
    return frozenset(
        duty
        for duty in as_duties(roster)
        if last - timedelta(days=MARGIN_DAYS - 1) <= duty[2] <= last
    )


def chain_next_month(
    instance: Instance,
    roster: Iterable[Duty],
    seed: int | None = None,
    knobs: Knobs | None = None,
) -> Instance:
    """The next month of the same workplace, starting from a solved month.

    Same seed (unless given) and knobs one month on, so the roles and who
    holds them are the same; the last week of ``roster`` becomes the next
    month's duties before the month, which a planted witness respects. Only
    the month before is carried: the next month's own duties after it are
    drawn as usual (set ``adjacent_rate=0`` for none).
    """
    base = knobs or next_month_knobs(knobs_of(instance))
    return make_instance(
        int(instance.knobs.get("seed", 0)) if seed is None else seed,
        base,
        carry_in=carried_week(instance, roster),
    )


def chain_months(
    seed: int,
    knobs: Knobs,
    n_months: int,
    solve: Callable[[Instance], list[Duty] | None],
) -> list[tuple[Instance, list[Duty] | None]]:
    """Solve ``n_months`` consecutive months, each fed by the one before.

    ``solve`` returns a roster or ``None``; the chain stops at the first
    ``None``. Returns every ``(instance, roster)`` reached.
    """
    chain: list[tuple[Instance, list[Duty] | None]] = []
    carry: frozenset[Duty] = frozenset()
    for _ in range(n_months):
        instance = make_instance(seed, knobs, carry_in=carry)
        roster = solve(instance)
        chain.append((instance, roster))
        if roster is None:
            break
        carry = carried_week(instance, roster)
        knobs = next_month_knobs(knobs)
    return chain
