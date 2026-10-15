"""The rules of a roster, written once from the documentation.

Everything the generator, the oracle and the reference models agree on lives
here: how long a duty holds its holder, how long a duty worked elsewhere
holds them, when two duties collide, how many people a role needs on a day.
It is derived from ``schedule_generation_model.md`` (sections 1, 2 and 6)
and the README's "Scheduling rules per workplace", never from the solver's
own helpers.

Vocabulary used across the harness:

* A *duty* is ``(user_id, competence_id, work_date)``.
* A duty on ``e`` with rest ``r`` *holds* the days ``e .. e + r``.
* Two duties on different days *collide* when the later one starts on a day
  the earlier one still holds. Two duties on one day are a "double role",
  which is a separate rule.
* A *generated* duty is one in the output that is not a manual placement.
"""

from __future__ import annotations

from calendar import monthrange
from collections import Counter
from collections.abc import Iterable
from datetime import date, timedelta
from typing import TYPE_CHECKING

from app.services.constraint_setting_service import (
    UNAVAILABLE,
    ConstraintPolicy,
)
from app.services.schedule_generation_service import (
    GeneratedAssignment,
    SchedulingCompetence,
    SchedulingEmployee,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from tests.scheduling_harness.instances import Instance

Duty = tuple[int, int, date]

#: Rest assumed for a duty in a competence the workplace no longer has.
UNKNOWN_COMPETENCE_REST = 1

#: How far around the month duties and calendars are read.
MARGIN_DAYS = 7

#: The solver locks its first-pass value as ``reached + 1e-4 + 1e-7 * |reached|``.
#: Restated here as numbers, not imported, so that a change on the solver
#: side shows up as a failing test instead of silently moving thresholds.
LOCK_ABSOLUTE_SLACK = 1e-4
LOCK_RELATIVE_SLACK = 1e-7


def balance_lock_slack(reached: float) -> float:
    """How far above the first-pass value the solver lets its second pass go."""
    return LOCK_ABSOLUTE_SLACK + LOCK_RELATIVE_SLACK * abs(reached)


#: Unit costs of the four balance ladders, at the default balance weight.
TOTAL_UNIT = 4.0
HOURS_UNIT = 4.0
ANY_KIND_UNIT = 4.0
PREFERRED_KIND_UNIT = 3.0
DISPREFERRED_KIND_UNIT = 5.0


def month_days(month: int, year: int) -> list[date]:
    """Every date of one calendar month, in order."""
    return [date(year, month, day) for day in range(1, monthrange(year, month)[1] + 1)]


def date_range(first: date, last: date) -> list[date]:
    """Every date from ``first`` to ``last`` inclusive."""
    return [first + timedelta(days=offset) for offset in range((last - first).days + 1)]


def as_duty(item: GeneratedAssignment | Duty) -> Duty:
    """Read one solver assignment or plain tuple as a duty tuple."""
    if isinstance(item, GeneratedAssignment):
        return (item.user_id, item.competence_id, item.work_date)
    user_id, competence_id, work_date = item
    return (int(user_id), int(competence_id), work_date)


def as_duties(items: Iterable[GeneratedAssignment | Duty]) -> list[Duty]:
    """Read a whole roster as a list of duty tuples, duplicates kept."""
    return [as_duty(item) for item in items]


def policy_of(instance: Instance) -> ConstraintPolicy:
    """The policy an instance is solved under, defaults filled in."""
    return instance.policy or ConstraintPolicy.default()


def duty_rest(
    competences: dict[int, SchedulingCompetence], competence_id: int, work_date: date
) -> int:
    """Rest a duty at this workplace earns: its competence's, or one day."""
    competence = competences.get(competence_id)
    if competence is None:
        return UNKNOWN_COMPETENCE_REST
    return int(competence.recovery_days_on(work_date))


def fallback_external_rest(
    competences: Iterable[SchedulingCompetence], work_date: date
) -> int:
    """Rest assumed after a duty elsewhere whose own rest is not known."""
    return max(
        (int(competence.recovery_days_on(work_date)) for competence in competences),
        default=UNKNOWN_COMPETENCE_REST,
    )


def explicit_external_rest(employee: SchedulingEmployee) -> dict[date, int]:
    """The rest each day worked elsewhere carries by itself, where it is known.

    Two duties elsewhere on one date (two competences, or two other
    workplaces) hold the person for the longer of their two rests: rest is
    read from that workplace's calendar (model doc 2.2), and a person who
    worked both duties needs both rests. The order of the entries never
    matters. Entries for a date that is not in ``externally_scheduled_dates``
    describe no duty and are ignored, as the solver ignores them.
    """
    rests: dict[date, int] = {}
    for work_date, rest in employee.external_commitments:
        if work_date in employee.externally_scheduled_dates:
            rests[work_date] = max(int(rest), rests.get(work_date, int(rest)))
    return rests


def external_duties(
    employee: SchedulingEmployee, competences: Iterable[SchedulingCompetence]
) -> list[tuple[date, int]]:
    """An employee's days worked elsewhere, each with the rest it earns.

    One entry per date: the longest explicit rest given for that date or,
    when none is given, the longest rest this workplace would give for it
    (:func:`fallback_external_rest`).
    """
    competence_list = list(competences)
    explicit = explicit_external_rest(employee)
    return [
        (
            work_date,
            explicit[work_date]
            if work_date in explicit
            else fallback_external_rest(competence_list, work_date),
        )
        for work_date in sorted(employee.externally_scheduled_dates)
    ]


def has_duplicate_external_dates(employee: SchedulingEmployee) -> bool:
    """Whether some day worked elsewhere carries more than one explicit rest."""
    seen = Counter(
        work_date
        for work_date, _rest in employee.external_commitments
        if work_date in employee.externally_scheduled_dates
    )
    return any(count > 1 for count in seen.values())


def holds(start: date, rest: int, day: date) -> bool:
    """Whether a duty started on ``start`` with ``rest`` holds ``day``."""
    return start <= day <= start + timedelta(days=rest)


def collide(first: date, first_rest: int, second: date, second_rest: int) -> bool:
    """Whether two duties on different days break the rest of the earlier one."""
    if first == second:
        return False
    if first < second:
        return second <= first + timedelta(days=first_rest)
    return first <= second + timedelta(days=second_rest)


def touches(first: date, first_rest: int, second: date, second_rest: int) -> bool:
    """Same day, or a rest collision: whatever keeps a duty from a commitment."""
    return first == second or collide(first, first_rest, second, second_rest)


def shared_days(first: date, first_rest: int, second: date, second_rest: int) -> int:
    """Days held by both duties, which is what a penalized rest is charged."""
    start = max(first, second)
    end = min(first + timedelta(days=first_rest), second + timedelta(days=second_rest))
    return max(0, (end - start).days + 1)


def absence_rule(employee: SchedulingEmployee, work_date: date) -> str | None:
    """Which absence rule a date falls under for an employee, if any."""
    if work_date not in employee.unavailable_dates:
        return None
    return dict(employee.absence_rules).get(work_date, UNAVAILABLE)


def fixed_counts(fixed: Iterable[Duty]) -> Counter[tuple[int, date]]:
    """How many manual placements each competence has on each day."""
    return Counter((competence_id, work_date) for _user, competence_id, work_date in fixed)


def demand(
    competence: SchedulingCompetence,
    work_date: date,
    placed: Counter[tuple[int, date]],
) -> int:
    """People a role gets on a day: what it asks for, or more if placed by hand."""
    return max(int(competence.required_on(work_date)), placed[(competence.id, work_date)])


def kind_units(preference: str) -> tuple[float, float]:
    """Unit costs ``(surcharge, standard)`` of the two kind ladders."""
    if preference == "surcharge":
        return PREFERRED_KIND_UNIT, DISPREFERRED_KIND_UNIT
    if preference == "standard":
        return DISPREFERRED_KIND_UNIT, PREFERRED_KIND_UNIT
    return ANY_KIND_UNIT, ANY_KIND_UNIT


def ladder_cost(load: float, unit: float, step: float = 1.0) -> float:
    """Cost of one convex load ladder: ``unit`` times 1, 3, 5, ... per step.

    The load is measured in steps, ``q = load / step``. Whole steps cost
    ``unit * floor(q)^2``; a fractional last step costs its share of the
    next odd number.
    """
    if unit <= 0 or step <= 0 or load <= 0:
        return 0.0
    q = load / step
    whole = int(q + 1e-9)
    if abs(q - round(q)) < 1e-9:
        whole = int(round(q))
    fraction = max(0.0, q - whole)
    return unit * (whole * whole + (2 * whole + 1) * fraction)
