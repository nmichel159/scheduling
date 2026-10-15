"""Judge a roster against the rules, without asking the solver.

:func:`validate` lists every hard rule a roster breaks, :func:`metrics`
measures how fair and how kind it is, :func:`first_pass_cost` and
:func:`day_wish_cost` price it the way the documentation says the two solver
passes do, and :func:`find_improving_moves` looks for a single change the
solver should have found.

Everything is re-derived from ``schedule_generation_model.md`` through
:mod:`.semantics`; none of the solver's helpers are used.
"""

from __future__ import annotations

import random
import statistics
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.services.constraint_setting_service import (
    BALANCE,
    MAX_SHIFTS,
    OVERSTAFF,
    PREFERRED,
    REST,
    SOFT_DECLINE,
    SPREAD,
)
from app.services.schedule_generation_service import GeneratedAssignment

from tests.scheduling_harness.instances import Instance
from tests.scheduling_harness.semantics import (
    HOURS_UNIT,
    TOTAL_UNIT,
    Duty,
    absence_rule,
    as_duties,
    balance_lock_slack,
    collide,
    demand,
    duty_rest,
    external_duties,
    fixed_counts,
    holds,
    kind_units,
    ladder_cost,
    shared_days,
    touches,
)

#: Every hard-rule violation code :func:`validate` can report.
VIOLATION_CODES = (
    "malformed",
    "fixed_missing",
    "history_changed",
    "coverage",
    "unqualified",
    "double_role",
    "other_workplace",
    "rest",
    "absence",
    "soft_decline",
    "max_shifts",
)

Assignments = Iterable[GeneratedAssignment | Duty]


@dataclass(frozen=True)
class Violation:
    """One broken hard rule, with what identifies the breach."""

    code: str
    detail: dict


# --- Shared context -----------------------------------------------------------------


class _Context:
    """Everything about an instance the judges need, computed once."""

    def __init__(self, instance: Instance) -> None:
        """Precompute lookups for one instance."""
        self.instance = instance
        self.policy = instance.effective_policy
        self.competences = instance.competence_map
        self.employees = instance.employee_map
        self.days = instance.day_set
        self.window = frozenset(instance.window_days)
        self.fixed = frozenset(duty for duty in instance.fixed if duty[2] in self.days)
        self.fixed_counts = fixed_counts(self.fixed)
        self.fixed_by_user: Counter[int] = Counter(duty[0] for duty in self.fixed)
        self.fixed_by_user_day: Counter[tuple[int, date]] = Counter(
            (duty[0], duty[2]) for duty in self.fixed
        )
        self.rest_strict = self.policy.is_strict(REST)
        #: Commitments outside the model, per user: (date, rest).
        self.outside: dict[int, list[tuple[date, int]]] = {}
        for user_id, competence_id, work_date in instance.adjacent:
            self.outside.setdefault(user_id, []).append(
                (work_date, duty_rest(self.competences, competence_id, work_date))
            )
        self.external_dates: dict[int, frozenset[date]] = {}
        for employee in instance.employees:
            for item in external_duties(employee, instance.competences):
                self.outside.setdefault(employee.id, []).append(item)
            self.external_dates[employee.id] = frozenset(employee.externally_scheduled_dates)
        for items in self.outside.values():
            items.sort()

    def rest(self, duty: Duty) -> int:
        """Rest one duty at this workplace earns."""
        return duty_rest(self.competences, duty[1], duty[2])

    def strict_absence(self, user_id: int, work_date: date) -> bool:
        """Whether a date is an absence the policy makes strict for the user."""
        rule = absence_rule(self.employees[user_id], work_date)
        return rule is not None and self.policy.is_strict(rule)

    def limit(self, user_id: int) -> int | None:
        """The user's strict monthly maximum, if one applies."""
        wish = self.employees[user_id].max_shifts_per_month
        if not wish or not self.policy.is_strict(MAX_SHIFTS):
            return None
        return max(int(wish), self.fixed_by_user[user_id])

    def fits(self, user_id: int, competence_id: int, work_date: date, own: Iterable[Duty]) -> bool:
        """Whether a generated duty may join the user's other duties ``own``."""
        employee = self.employees.get(user_id)
        competence = self.competences.get(competence_id)
        if employee is None or competence is None:
            return False
        if work_date not in self.window or competence.required_on(work_date) <= 0:
            return False
        if competence_id not in employee.competence_ids:
            return False
        if work_date in self.external_dates.get(user_id, frozenset()):
            return False
        if self.strict_absence(user_id, work_date):
            return False
        if self.policy.is_strict(SOFT_DECLINE) and work_date in employee.soft_declined_dates:
            return False
        rest = competence.recovery_days_on(work_date)
        count = 0
        for other in own:
            count += 1
            if other[2] == work_date:
                return False
            if self.rest_strict and collide(work_date, rest, other[2], self.rest(other)):
                return False
        if self.rest_strict:
            for other_date, other_rest in self.outside.get(user_id, ()):
                if collide(work_date, rest, other_date, other_rest):
                    return False
        limit = self.limit(user_id)
        if limit is not None and count + 1 > limit:
            return False
        return True


def _charged_rest_days(context: _Context, user_id: int, own: Iterable[Duty]) -> int:
    """Days a penalized rest charges one employee for, as the solver prices them.

    Per day of the month: the duties holding that day, minus
    ``max(1, manual placements among them)`` -- the per-day breach variable
    of model doc 2.2/6, which only exists on the month's days. Plus, for
    every generated duty, the days it shares with each duty outside the model
    (around the month or elsewhere), counted in full even past the month's
    end. Whether rests that overlap only after the month's end should be
    charged too is an open question (``known_bugs``:
    ``penalized_rest_month_end``).
    """
    own = [duty for duty in own if duty[2] in context.days]
    spans = [(duty[2], context.rest(duty), duty in context.fixed) for duty in own]
    breach_days = 0
    for day in context.instance.days:
        holding = [placed for start, rest, placed in spans if holds(start, rest, day)]
        if len(holding) > 1:
            breach_days += max(0, len(holding) - max(1, sum(holding)))
    for duty in own:
        if duty in context.fixed:
            continue
        rest = context.rest(duty)
        for other_date, other_rest in context.outside.get(user_id, ()):
            breach_days += shared_days(duty[2], rest, other_date, other_rest)
    return breach_days


# --- Hard rules -----------------------------------------------------------------------


def validate(instance: Instance, assignments: Assignments) -> list[Violation]:
    """Every hard rule the roster breaks under the instance's policy.

    Resolutions of the spec's corner cases:

    * A manual placement missing from the output is ``fixed_missing`` even in
      the history; ``history_changed`` is only a duty added there.
    * A duty on a history date is judged only by ``history_changed`` (plus
      the per-person rules), never by ``coverage``.
    * Two duties of one person on one day are ``double_role``; ``rest`` only
      looks at duties on different days, and a duty on a day worked elsewhere
      is ``other_workplace``, not ``rest``.
    * A rest collision is a breach only if at least one of the two duties is
      generated: manual placements, duties around the month and duties
      elsewhere may collide among themselves.
    """
    context = _Context(instance)
    violations: list[Violation] = []
    duties = as_duties(assignments)

    counts = Counter(duties)
    for duty, count in sorted(counts.items()):
        if count > 1:
            violations.append(Violation("malformed", {"kind": "duplicate", "duty": duty}))
    valid: set[Duty] = set()
    for duty in sorted(counts):
        user_id, competence_id, work_date = duty
        if work_date not in context.days:
            violations.append(Violation("malformed", {"kind": "outside_month", "duty": duty}))
        elif user_id not in context.employees:
            violations.append(Violation("malformed", {"kind": "unknown_user", "duty": duty}))
        elif competence_id not in context.competences:
            violations.append(Violation("malformed", {"kind": "unknown_competence", "duty": duty}))
        else:
            valid.add(duty)

    for duty in sorted(context.fixed - valid):
        violations.append(Violation("fixed_missing", {"duty": duty}))

    generated = valid - context.fixed
    for duty in sorted(generated):
        if duty[2] not in context.window:
            violations.append(Violation("history_changed", {"duty": duty}))

    coverage = Counter((duty[1], duty[2]) for duty in valid)
    generated_coverage = Counter((duty[1], duty[2]) for duty in generated)
    overstaff_strict = context.policy.is_strict(OVERSTAFF)
    for work_date in instance.window_days:
        for competence in instance.competences:
            key = (competence.id, work_date)
            staffed = coverage[key]
            needed = demand(competence, work_date, context.fixed_counts)
            detail = {
                "competence_id": competence.id,
                "work_date": work_date,
                "staffed": staffed,
                "demand": needed,
            }
            if competence.required_on(work_date) == 0:
                if generated_coverage[key] > 0:
                    violations.append(Violation("coverage", {**detail, "kind": "zero_day"}))
            elif staffed < needed or (overstaff_strict and staffed != needed):
                violations.append(Violation("coverage", detail))

    for duty in sorted(generated):
        user_id, competence_id, work_date = duty
        employee = context.employees[user_id]
        if competence_id not in employee.competence_ids:
            violations.append(Violation("unqualified", {"duty": duty}))
        if work_date in context.external_dates.get(user_id, frozenset()):
            violations.append(Violation("other_workplace", {"duty": duty}))
        if context.strict_absence(user_id, work_date):
            violations.append(
                Violation(
                    "absence",
                    {"duty": duty, "rule": absence_rule(employee, work_date)},
                )
            )
        if context.policy.is_strict(SOFT_DECLINE) and work_date in employee.soft_declined_dates:
            violations.append(Violation("soft_decline", {"duty": duty}))

    per_user_day = Counter((duty[0], duty[2]) for duty in valid)
    for (user_id, work_date), count in sorted(per_user_day.items()):
        if count > max(1, context.fixed_by_user_day[(user_id, work_date)]):
            violations.append(
                Violation(
                    "double_role",
                    {"user_id": user_id, "work_date": work_date, "duties": count},
                )
            )

    by_user: dict[int, list[Duty]] = {}
    for duty in valid:
        by_user.setdefault(duty[0], []).append(duty)

    if context.rest_strict:
        for user_id, own in sorted(by_user.items()):
            # (date, rest, kind, duty) for every duty that holds this person.
            items: list[tuple[date, int, str, Duty | None]] = [
                (duty[2], context.rest(duty), "generated" if duty in generated else "fixed", duty)
                for duty in own
            ] + [
                (work_date, rest, "outside", None)
                for work_date, rest in context.outside.get(user_id, ())
            ]
            items.sort(key=lambda item: (item[0], item[2]))
            for position, (first, first_rest, first_kind, first_duty) in enumerate(items):
                for second, second_rest, second_kind, second_duty in items[position + 1:]:
                    if second > first + timedelta(days=first_rest):
                        break
                    if second == first:
                        continue
                    if "generated" not in (first_kind, second_kind):
                        continue
                    violations.append(
                        Violation(
                            "rest",
                            {
                                "user_id": user_id,
                                "earlier": first_duty or ("outside", first),
                                "later": second_duty or ("outside", second),
                                "earlier_rest": first_rest,
                            },
                        )
                    )

    for user_id, own in sorted(by_user.items()):
        limit = context.limit(user_id)
        if limit is not None and len(own) > limit:
            violations.append(
                Violation(
                    "max_shifts",
                    {"user_id": user_id, "duties": len(own), "limit": limit},
                )
            )
    return violations


def violation_codes(violations: Iterable[Violation]) -> set[str]:
    """The distinct codes of a list of violations."""
    return {violation.code for violation in violations}


def eligible(
    instance: Instance,
    user_id: int,
    competence_id: int,
    work_date: date,
    schedule: Assignments,
) -> bool:
    """Whether ``(user_id, competence_id, work_date)`` may be added as a generated duty.

    Checks every per-person hard rule against the user's duties in
    ``schedule`` (which should not contain the duty itself): window,
    non-zero demand, qualification, other workplace, strict absences and
    "rather not", one duty a day, strict rest against all commitments, and a
    strict monthly maximum. Coverage is the caller's business.
    """
    context = _Context(instance)
    own = [duty for duty in as_duties(schedule) if duty[0] == user_id]
    return context.fits(user_id, competence_id, work_date, own)


# --- Measures ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EmployeeLoad:
    """What one employee was given."""

    total: int
    surcharge: int
    standard: int
    hours: float


@dataclass
class ScheduleMetrics:
    """How fair and how kind a roster is."""

    loads: dict[int, EmployeeLoad]
    #: Employees with at least one slot they could have been given.
    eligible_employees: frozenset[int]
    load_spread: int
    load_stdev: float
    hours_spread: float
    surcharge_spread: int
    overstaff: int
    over_max: dict[int, int]
    #: Generated duties on absences the policy penalizes, by rule.
    absence_breaches: dict[str, int]
    #: Pairs of colliding duties on different days, at least one generated.
    rest_breach_pairs: int
    #: Days a penalized rest is charged for (``_charged_rest_days``,
    #: summed over employees): the rest part of :func:`first_pass_cost`
    #: divided by the rest weight.
    rest_breach_days: int
    #: Sum over colliding pairs of the days both hold, past the month too.
    rest_overlap_pair_days: int
    soft_declined_worked: int
    preferred_honored: int
    preferred_opportunities: int
    gap_histogram: dict[int, int]
    min_gap: int | None
    #: Gaps exactly one day longer than the earlier duty's rest.
    tightest_gaps: int
    per_employee_gaps: dict[int, list[int]] = field(default_factory=dict)


def eligible_slots(instance: Instance, user_id: int) -> set[tuple[int, date]]:
    """Window slots the user could ever hold, ignoring the rest of the roster.

    Same filters as the model's variables (section 1 of the model doc):
    qualification, non-zero demand, no strict absence or "rather not", no
    duty elsewhere that day, and -- while rest is strict -- no collision
    with a manual placement, a duty around the month or a duty elsewhere.
    """
    context = _Context(instance)
    return _eligible_slots(context, user_id)


def _eligible_slots(context: _Context, user_id: int) -> set[tuple[int, date]]:
    """:func:`eligible_slots` on a prepared context."""
    fixed_own = [duty for duty in context.fixed if duty[0] == user_id]
    slots: set[tuple[int, date]] = set()
    for competence in context.instance.competences:
        for work_date in context.instance.window_days:
            if context.fits(user_id, competence.id, work_date, fixed_own):
                slots.add((competence.id, work_date))
    return slots


def metrics(instance: Instance, assignments: Assignments) -> ScheduleMetrics:
    """Measure loads, balance, penalties paid and wishes kept."""
    context = _Context(instance)
    duties = sorted(set(as_duties(assignments)))
    duties = [duty for duty in duties if duty[2] in context.days]
    generated = [duty for duty in duties if duty not in context.fixed]
    by_user: dict[int, list[Duty]] = {employee.id: [] for employee in instance.employees}
    for duty in duties:
        by_user.setdefault(duty[0], []).append(duty)

    loads: dict[int, EmployeeLoad] = {}
    for user_id, own in by_user.items():
        surcharge = sum(
            1
            for duty in own
            if duty[1] in context.competences
            and context.competences[duty[1]].is_surcharge_on(duty[2])
        )
        hours = sum(
            float(context.competences[duty[1]].shift_hours_on(duty[2]))
            for duty in own
            if duty[1] in context.competences
        )
        loads[user_id] = EmployeeLoad(len(own), surcharge, len(own) - surcharge, hours)

    eligible_ids = frozenset(
        employee.id
        for employee in instance.employees
        if context.fixed_by_user[employee.id] or _eligible_slots(context, employee.id)
    )
    considered = [loads[user_id] for user_id in eligible_ids] or [EmployeeLoad(0, 0, 0, 0.0)]
    totals = [load.total for load in considered]

    coverage = Counter((duty[1], duty[2]) for duty in duties)
    overstaff = 0
    for work_date in instance.window_days:
        for competence in instance.competences:
            needed = demand(competence, work_date, context.fixed_counts)
            overstaff += max(0, coverage[(competence.id, work_date)] - needed)

    over_max: dict[int, int] = {}
    for employee in instance.employees:
        if employee.max_shifts_per_month:
            excess = loads[employee.id].total - employee.max_shifts_per_month
            if excess > 0:
                over_max[employee.id] = excess

    absence_breaches: Counter[str] = Counter()
    soft_declined_worked = 0
    preferred_honored = 0
    for duty in generated:
        employee = context.employees.get(duty[0])
        if employee is None:
            continue
        rule = absence_rule(employee, duty[2])
        if rule is not None and not context.policy.is_strict(rule):
            absence_breaches[rule] += 1
        if duty[2] in employee.soft_declined_dates:
            soft_declined_worked += 1
    for duty in duties:
        employee = context.employees.get(duty[0])
        if employee is not None and duty[2] in employee.preferred_dates:
            preferred_honored += 1
    preferred_opportunities = 0
    for employee in instance.employees:
        slot_days = {work_date for _competence, work_date in _eligible_slots(context, employee.id)}
        fixed_days = {duty[2] for duty in context.fixed if duty[0] == employee.id}
        preferred_opportunities += len(employee.preferred_dates & (slot_days | fixed_days))

    rest_pairs = 0
    rest_days = 0
    overlap_days = 0
    generated_set = set(generated)
    for user_id, own in by_user.items():
        items = [
            (duty[2], context.rest(duty), duty in generated_set) for duty in own
        ] + [(work_date, rest, False) for work_date, rest in context.outside.get(user_id, ())]
        items.sort()
        for position, (first, first_rest, first_generated) in enumerate(items):
            for second, second_rest, second_generated in items[position + 1:]:
                if second > first + timedelta(days=first_rest):
                    break
                if second == first or not (first_generated or second_generated):
                    continue
                rest_pairs += 1
                overlap_days += shared_days(first, first_rest, second, second_rest)
        rest_days += _charged_rest_days(context, user_id, own)

    histogram: Counter[int] = Counter()
    per_employee_gaps: dict[int, list[int]] = {}
    tightest = 0
    for user_id, own in by_user.items():
        dated = sorted({(duty[2], context.rest(duty)) for duty in own})
        gaps = []
        for (earlier, earlier_rest), (later, _later_rest) in zip(dated, dated[1:]):
            if later == earlier:
                continue
            gap = (later - earlier).days
            gaps.append(gap)
            histogram[gap] += 1
            if gap == earlier_rest + 1:
                tightest += 1
        per_employee_gaps[user_id] = gaps

    return ScheduleMetrics(
        loads=loads,
        eligible_employees=eligible_ids,
        load_spread=max(totals) - min(totals),
        load_stdev=statistics.pstdev(totals) if len(totals) > 1 else 0.0,
        hours_spread=max(load.hours for load in considered) - min(load.hours for load in considered),
        surcharge_spread=max(load.surcharge for load in considered)
        - min(load.surcharge for load in considered),
        overstaff=overstaff,
        over_max=over_max,
        absence_breaches=dict(absence_breaches),
        rest_breach_pairs=rest_pairs,
        rest_breach_days=rest_days,
        rest_overlap_pair_days=overlap_days,
        soft_declined_worked=soft_declined_worked,
        preferred_honored=preferred_honored,
        preferred_opportunities=preferred_opportunities,
        gap_histogram=dict(sorted(histogram.items())),
        min_gap=min(histogram) if histogram else None,
        tightest_gaps=tightest,
        per_employee_gaps=per_employee_gaps,
    )


# --- Objective -------------------------------------------------------------------------


class CostModel:
    """The first-pass objective of the model doc, sections 3.1, 3.2 and 6.

    For a roster that keeps every hard rule this is the solver's own
    first-pass objective value, with no constant offset: manual placements
    are charged for load (they count towards every ladder) but never for
    absences or for rest against duties outside the model, exactly as the
    doc says the model only charges variables it is free to set. Two rosters
    of the same instance can therefore be compared directly.

    The per-employee part is exposed separately so a move that touches two
    employees can be priced without re-pricing everybody.
    """

    def __init__(self, instance: Instance) -> None:
        """Precompute the constants of one instance's objective."""
        self.context = _Context(instance)
        policy = self.context.policy
        self.scale = policy.weight(BALANCE) / TOTAL_UNIT
        demanded = 0
        demanded_hours = 0.0
        for competence in instance.competences:
            for work_date in instance.window_days:
                required = int(competence.required_on(work_date))
                demanded += required
                demanded_hours += required * float(competence.shift_hours_on(work_date))
        #: One "average duty" of hours: the hours ladder's step.
        self.hours_step = demanded_hours / demanded if demanded else 0.0
        self.max_shifts_weight = (
            0.0 if policy.is_strict(MAX_SHIFTS) else policy.weight(MAX_SHIFTS)
        )
        self.overstaff_weight = (
            0.0 if policy.is_strict(OVERSTAFF) else policy.weight(OVERSTAFF)
        )
        self.rest_weight = 0.0 if policy.is_strict(REST) else policy.weight(REST)

    def employee_cost(self, user_id: int, own: Iterable[Duty]) -> float:
        """Ladders, monthly-maximum excess, absences and rest of one employee."""
        context = self.context
        employee = context.employees.get(user_id)
        own = [duty for duty in own if duty[2] in context.days and duty[1] in context.competences]
        if employee is None or not own:
            return 0.0
        policy = context.policy
        total = len(own)
        surcharge = 0
        hours = 0.0
        for _user, competence_id, work_date in own:
            competence = context.competences[competence_id]
            if competence.is_surcharge_on(work_date):
                surcharge += 1
            hours += float(competence.shift_hours_on(work_date))
        surcharge_unit, standard_unit = kind_units(employee.shift_preference)
        cost = ladder_cost(total, TOTAL_UNIT * self.scale)
        cost += ladder_cost(surcharge, surcharge_unit * self.scale)
        cost += ladder_cost(total - surcharge, standard_unit * self.scale)
        if self.hours_step > 0:
            cost += ladder_cost(hours, HOURS_UNIT * self.scale, self.hours_step)

        if employee.max_shifts_per_month and self.max_shifts_weight > 0:
            cost += self.max_shifts_weight * max(0, total - employee.max_shifts_per_month)

        generated = [duty for duty in own if duty not in context.fixed]
        for duty in generated:
            rule = absence_rule(employee, duty[2])
            if rule is not None and not policy.is_strict(rule):
                cost += policy.weight(rule)

        if self.rest_weight > 0:
            cost += self.rest_weight * _charged_rest_days(context, user_id, own)
        return cost

    def overstaff_cost(self, duties: Iterable[Duty]) -> float:
        """What the roster pays for people beyond a role's demand."""
        if self.overstaff_weight <= 0:
            return 0.0
        context = self.context
        coverage = Counter((duty[1], duty[2]) for duty in duties if duty[2] in context.window)
        excess = 0
        for work_date in context.instance.window_days:
            for competence in context.instance.competences:
                needed = demand(competence, work_date, context.fixed_counts)
                excess += max(0, coverage[(competence.id, work_date)] - needed)
        return self.overstaff_weight * excess

    def total(self, assignments: Assignments) -> float:
        """The whole first-pass objective of a roster."""
        duties = sorted(set(as_duties(assignments)))
        by_user: dict[int, list[Duty]] = {}
        for duty in duties:
            by_user.setdefault(duty[0], []).append(duty)
        return sum(
            self.employee_cost(user_id, own) for user_id, own in by_user.items()
        ) + self.overstaff_cost(duties)


def first_pass_cost(instance: Instance, assignments: Assignments) -> float:
    """The first-pass ("balance") objective of a roster; see :class:`CostModel`."""
    return CostModel(instance).total(assignments)


def day_wish_weights(instance: Instance) -> tuple[float, float]:
    """Effective ``(preferred, soft_decline)`` weights of the second pass."""
    policy = instance.effective_policy
    soft = 0.0 if policy.is_strict(SOFT_DECLINE) else policy.weight(SOFT_DECLINE)
    return policy.weight(PREFERRED), soft


def day_wish_cost(instance: Instance, assignments: Assignments) -> float:
    """Day wishes of the second pass: requested days earn, reluctant days cost.

    Manual placements are counted too; they are the same in every roster of
    an instance, so they shift every roster's value by the same constant.
    """
    preferred_weight, soft_weight = day_wish_weights(instance)
    employees = instance.employee_map
    cost = 0.0
    for user_id, _competence_id, work_date in set(as_duties(assignments)):
        employee = employees.get(user_id)
        if employee is None:
            continue
        if work_date in employee.preferred_dates:
            cost -= preferred_weight
        if work_date in employee.soft_declined_dates:
            cost += soft_weight
    return cost


# --- Local search -----------------------------------------------------------------------


@dataclass(frozen=True)
class Move:
    """One change to a roster that keeps every hard rule.

    ``kind`` is ``reassign`` (one generated duty to someone else), ``swap``
    (two generated duties exchange holders) or ``drop`` (a generated duty
    above demand is removed). ``reason`` says why it was reported:

    * ``first_pass`` -- lowers :func:`first_pass_cost` by more than the
      solver's balance-lock slack (:func:`.semantics.balance_lock_slack`): a
      first pass that ran to optimality cannot leave this behind.
    * ``lock_drift`` -- lowers it by more than 1e-6 but no more than that
      slack: the solver's code lets the second pass drift this far (its
      documentation does not; ``known_bugs``: ``balance_lock_drift``).
    * ``day_wish`` -- keeps the first pass within the lock and gains at
      least :func:`wish_threshold` in day wishes: a second-pass miss.
    """

    kind: str
    removed: tuple[Duty, ...]
    added: tuple[Duty, ...]
    first_pass_delta: float
    day_wish_delta: float
    reason: str


def wish_threshold(instance: Instance) -> float | None:
    """How much a move must gain in day wishes to prove the second pass missed it.

    A move touches two employees, and each one's spread is worth at most the
    spread weight, so the second-pass objective of the moved roster is lower
    by at least ``gain - 2 * spread``. That proves a miss once it exceeds the
    second pass's own optimality tolerance, ``min(spread, 0.1 * cheapest
    wish)``. The spec's ``cheapest wish - 2 * spread`` is applied on top, and
    the larger of the two is used. ``None`` when no day wish has a weight.
    """
    preferred_weight, soft_weight = day_wish_weights(instance)
    spread = instance.effective_policy.weight(SPREAD)
    wishes = [weight for weight in (preferred_weight, soft_weight) if weight > 0]
    if not wishes:
        return None
    tolerance = min(([spread] if spread > 0 else []) + [0.1 * weight for weight in wishes])
    sound = 2 * spread + tolerance + 1e-6
    spec = min(wishes) - 2 * spread
    return max(sound, spec)


def _clashing_users(context: _Context) -> set[int]:
    """Employees whose manual placements share a day or a rest."""
    clashing: set[int] = set()
    by_user: dict[int, list[Duty]] = {}
    for duty in sorted(context.fixed):
        by_user.setdefault(duty[0], []).append(duty)
    for user_id, own in by_user.items():
        for position, first in enumerate(own):
            for second in own[position + 1:]:
                if touches(first[2], context.rest(first), second[2], context.rest(second)):
                    clashing.add(user_id)
    return clashing


def find_improving_moves(
    instance: Instance,
    assignments: Assignments,
    max_checks: int = 20000,
    seed: int = 0,
    balance_cap: float | None = None,
) -> list[Move]:
    """Single reassignments, swaps and drops the solver should have made.

    Only moves that keep :func:`validate` clean are considered; see
    :class:`Move` for the three reasons a move is reported. ``balance_cap``
    is the first-pass value the solver locked (``SolveOutcome.balance_cap``
    of an observed run); when given, a day-wish move only has to stay within
    it, instead of within 1e-6 of the roster's own first-pass cost. The
    day-wish test is skipped for employees whose manual placements clash,
    where the spread bound does not hold. ``max_checks`` bounds the candidate
    moves examined (reassignments first, then drops, then swaps in a seeded
    random order).

    Raises:
        ValueError: If the roster itself breaks a hard rule.
    """
    duties = sorted(set(as_duties(assignments)))
    broken = validate(instance, duties)
    if broken:
        raise ValueError(f"roster breaks hard rules: {sorted(violation_codes(broken))}")
    model = CostModel(instance)
    context = model.context
    threshold = wish_threshold(instance)
    clashing = _clashing_users(context)
    preferred_weight, soft_weight = day_wish_weights(instance)

    by_user: dict[int, list[Duty]] = {employee.id: [] for employee in instance.employees}
    for duty in duties:
        by_user.setdefault(duty[0], []).append(duty)
    base_cost = {user_id: model.employee_cost(user_id, own) for user_id, own in by_user.items()}
    base_total = sum(base_cost.values()) + model.overstaff_cost(duties)
    slack = balance_lock_slack(base_total)
    generated = [duty for duty in duties if duty not in context.fixed]

    def wish_of(duty: Duty) -> float:
        employee = context.employees[duty[0]]
        value = 0.0
        if duty[2] in employee.preferred_dates:
            value -= preferred_weight
        if duty[2] in employee.soft_declined_dates:
            value += soft_weight
        return value

    found: list[Move] = []

    def judge(
        kind: str, removed: tuple[Duty, ...], added: tuple[Duty, ...], extra: float = 0.0
    ) -> None:
        touched = {duty[0] for duty in removed + added}
        delta = extra
        for user_id in touched:
            own = [duty for duty in by_user[user_id] if duty not in removed] + [
                duty for duty in added if duty[0] == user_id
            ]
            delta += model.employee_cost(user_id, own) - base_cost[user_id]
        wish_delta = sum(wish_of(duty) for duty in added) - sum(wish_of(duty) for duty in removed)
        if balance_cap is not None:
            within_lock = base_total + delta <= balance_cap + 1e-6
        else:
            within_lock = delta <= 1e-6
        reason = ""
        if delta < -max(1e-6, slack):
            reason = "first_pass"
        elif delta < -1e-6:
            reason = "lock_drift"
        elif (
            within_lock
            and threshold is not None
            and not touched & clashing
            and -wish_delta >= threshold
        ):
            reason = "day_wish"
        if not reason:
            return
        moved = [duty for duty in duties if duty not in removed] + list(added)
        if validate(instance, moved):
            raise AssertionError(f"harness bug: move {kind} {removed}->{added} breaks a rule")
        found.append(Move(kind, removed, added, delta, wish_delta, reason))

    checks = 0
    user_ids = [employee.id for employee in instance.employees]
    for duty in generated:
        user_id, competence_id, work_date = duty
        for other in user_ids:
            if other == user_id:
                continue
            checks += 1
            if checks > max_checks:
                return found
            if context.fits(other, competence_id, work_date, by_user[other]):
                judge("reassign", (duty,), ((other, competence_id, work_date),))

    staffed = Counter((duty[1], duty[2]) for duty in duties)
    for duty in generated:
        competence = context.competences[duty[1]]
        if staffed[(duty[1], duty[2])] <= demand(competence, duty[2], context.fixed_counts):
            continue
        checks += 1
        if checks > max_checks:
            return found
        without = [item for item in duties if item != duty]
        extra = model.overstaff_cost(without) - model.overstaff_cost(duties)
        judge("drop", (duty,), (), extra)

    pairs = [
        (first, second)
        for position, first in enumerate(generated)
        for second in generated[position + 1:]
        if first[0] != second[0] and (first[1], first[2]) != (second[1], second[2])
    ]
    random.Random(seed).shuffle(pairs)
    for first, second in pairs:
        checks += 1
        if checks > max_checks:
            break
        new_first = (second[0], first[1], first[2])
        new_second = (first[0], second[1], second[2])
        own_second = [duty for duty in by_user[second[0]] if duty != second]
        own_first = [duty for duty in by_user[first[0]] if duty != first]
        if context.fits(new_first[0], new_first[1], new_first[2], own_second) and context.fits(
            new_second[0], new_second[1], new_second[2], own_first
        ):
            judge("swap", (first, second), (new_first, new_second))
    return found
