"""MILP-based monthly schedule generation for one ambulance.

The model answers two questions with the same code: plan a whole month, or
plan the rest of a month that is already partly worked. The second is the
first with ``generate_from`` set and the duties already placed handed in as
``fixed_assignments``.

What the objective is made of, from the strongest term to the weakest:

1. Hard constraints -- coverage, availability, one duty a day, the recovery
   the workplace configured for each duty, and every manually placed duty.
2. The monthly wish. A duty past what an employee said they want costs
   :data:`OVER_WISH_DUTY_COST`, far above any balance step, so it happens
   only when the month cannot be staffed otherwise.
3. The balance. Three convex load ladders per employee -- all duties,
   surcharged duties and ordinary ones -- so that neither the total nor
   either kind piles up on one person. The employee's own
   ``shift_preference`` tilts the two kind ladders, which is how "I would
   rather have the surcharged days" is honored without anyone being handed
   all of them.
4. The day wishes. Requested days are rewarded, reluctant days penalized,
   each from a fixed budget that cannot add up to a single balance step.
5. The spread. A duty crowded into the same week as others costs a little,
   from the smallest budget of all, so it only orders schedules that are
   already equally good by every rule above.
"""

from __future__ import annotations

from bisect import bisect_left
from calendar import monthrange
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, timedelta

from pulp import (
    LpAffineExpression,
    LpMinimize,
    LpProblem,
    LpStatus,
    LpVariable,
    PULP_CBC_CMD,
    lpSum,
    value,
)
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.models.associations import UserAmbulance, UserCompetence
from app.models.competence import Competence
from app.models.competence_weekday_requirement import (
    DEFAULT_RECOVERY_DAYS,
    SPECIAL_DAY_SLOT,
    CompetenceWeekdayRequirement,
    default_is_surcharge,
)
from app.services.competence_scenario_service import get_selected_scenario
from app.services.special_day_service import rest_days_between
from app.models.schedule import Schedule
from app.models.unavailability import Unavailability
from app.models.user import User
from app.schemas.schedule import (
    GeneratedScheduleEntry,
    ScheduleGenerationResponse,
)


PREFERRED_UNAVAILABILITY_REASON = "PREFERRED"

#: Marked by an employee who would rather not work a day but still can.
#: Unlike every other reason, it does not block an assignment.
SOFT_DECLINE_UNAVAILABILITY_REASON = "SOFT_DECLINE"

#: The duty-kind wishes an employee can express, as stored on the user.
SURCHARGE_PREFERENCE = "surcharge"
STANDARD_PREFERENCE = "standard"
ANY_PREFERENCE = "any"

# --- Balance --------------------------------------------------------------
# Every ladder charges 1, 3, 5, ... times its unit cost for an employee's
# first, second, third duty. Summing consecutive odd numbers is the load
# squared, so an extra duty is dearer the busier the employee already is and
# the cheapest roster is the evenly shared one.
#
# Because every unit cost is a whole number, so is every difference between
# two rosters' balance cost: the cheapest possible worsening of the balance
# is exactly 1. That is the room the wish terms below have to share.
BALANCE_UNIT_COST = 4

#: What a duty of the kind an employee asked for costs them, and what the
#: other kind costs. The gap is what makes a surcharge-minded employee end
#: up with more surcharged duties and fewer ordinary ones while their total
#: load stays level with everyone else's.
PREFERRED_KIND_UNIT_COST = 3
DISPREFERRED_KIND_UNIT_COST = 5

# What one duty above an employee's monthly wish costs. The wish is a wish,
# not a cap: exceeding it stays feasible, but at a price far above any
# balance step, so the solver only does it when the month cannot be staffed
# otherwise.
OVER_WISH_DUTY_COST = 1000.0

# --- Day wishes -----------------------------------------------------------
# Each budget is shared by every day it covers, so the whole term stays below
# the cheapest balance step no matter how large the month is. Wishes
# therefore order schedules that are already equally balanced and can never
# buy an honored request with a less balanced roster.
PREFERENCE_REWARD_BUDGET = 0.4
SOFT_DECLINE_PENALTY_BUDGET = 0.4

# --- Spread ---------------------------------------------------------------
#: How long a stretch the spread rule looks at. A week that holds as many
#: duties as it physically can -- one duty for every rest period that fits
#: inside it -- is what "crowded" means here, which is a question that keeps
#: its meaning whether the employee works four duties a month or fifteen.
SPREAD_WINDOW_DAYS = 7
#: The smallest budget in the model, shared by every crowded window, so the
#: spread is the last thing to decide between two otherwise equal schedules.
SPREAD_PENALTY_BUDGET = 0.15

# 0.4 + 0.4 + 0.15 < 1: all three wish terms together cannot pay for a single
# step of imbalance.


@dataclass(frozen=True)
class SchedulingCompetence:
    """Solver input describing one required ambulance competence.

    Everything the workplace configures per weekday is carried as an
    eight-slot answer: Monday to Sunday, plus the day of rest. A date the
    workplace calls a day of rest is answered from that last slot whatever
    weekday it happens to fall on, and a slot left unset falls back to the
    weekday underneath it, which is how the workplace behaved before the
    distinction existed.
    """

    id: int
    name: str
    required_count: int
    weekday_required_counts: tuple[int, ...] | None = None
    #: Demand on a day of rest -- a public holiday from the special-day
    #: library, or one the workplace declared itself. ``None`` means the
    #: workplace draws no distinction and such a date is staffed by its
    #: calendar weekday like any other.
    special_day_required_count: int | None = None
    #: The dates the above applies to, for the month being solved.
    special_dates: frozenset[date] = frozenset()
    #: Whether a duty on each weekday is paid with a surcharge. ``None``
    #: means the weekend rule the competence editor starts from.
    weekday_is_surcharge: tuple[bool, ...] | None = None
    special_day_is_surcharge: bool | None = None
    #: Days off a duty on each weekday costs its holder before they may be
    #: given another duty. ``None`` means one day, the editor's default.
    weekday_recovery_days: tuple[int, ...] | None = None
    special_day_recovery_days: int | None = None

    def _slot(self, work_date: date) -> int:
        """Which of the eight day slots answers for a concrete date."""
        if work_date in self.special_dates:
            return SPECIAL_DAY_SLOT
        return work_date.weekday()

    def required_on(self, work_date: date) -> int:
        """Return the configured demand for a concrete calendar date."""
        if (
            self.special_day_required_count is not None
            and work_date in self.special_dates
        ):
            return self.special_day_required_count
        if self.weekday_required_counts is None:
            return self.required_count
        return self.weekday_required_counts[work_date.weekday()]

    def is_surcharge_on(self, work_date: date) -> bool:
        """Whether a duty on this date is paid with a surcharge."""
        slot = self._slot(work_date)
        if slot == SPECIAL_DAY_SLOT and self.special_day_is_surcharge is not None:
            return self.special_day_is_surcharge
        if self.weekday_is_surcharge is None:
            return default_is_surcharge(slot)
        return self.weekday_is_surcharge[work_date.weekday()]

    def recovery_days_on(self, work_date: date) -> int:
        """Days off a duty on this date costs before the next one may fall."""
        slot = self._slot(work_date)
        if slot == SPECIAL_DAY_SLOT and self.special_day_recovery_days is not None:
            return self.special_day_recovery_days
        if self.weekday_recovery_days is None:
            return DEFAULT_RECOVERY_DAYS
        return self.weekday_recovery_days[work_date.weekday()]


@dataclass(frozen=True)
class SchedulingEmployee:
    """Solver input describing an employee and all hard availability limits."""

    id: int
    email: str
    full_name: str | None
    competence_ids: frozenset[int]
    unavailable_dates: frozenset[date]
    externally_scheduled_dates: frozenset[date]
    preferred_dates: frozenset[date] = frozenset()
    #: Days the employee would rather not work, but can if needed.
    soft_declined_dates: frozenset[date] = frozenset()
    #: The most duties a month the employee wants; None means no opinion.
    max_shifts_per_month: int | None = None
    #: Which kind of duty the employee would rather be given. It tilts the
    #: balance rather than filtering anything out.
    shift_preference: str = ANY_PREFERENCE


@dataclass(frozen=True)
class GeneratedAssignment:
    """A single solver assignment before API response serialization."""

    user_id: int
    competence_id: int
    work_date: date


@dataclass
class ScheduleVariableIndex:
    """Precomputed views of decision variables used by model constraints."""

    by_competence_date: dict[tuple[int, date], list[LpVariable]]
    candidate_ids_by_competence_date: dict[tuple[int, date], set[int]]
    by_user_date: dict[tuple[int, date], list[LpVariable]]
    by_user: dict[int, list[LpVariable]]
    candidate_dates_by_user: dict[int, set[date]]
    candidate_ids_by_date: dict[date, set[int]]
    competence_ids_by_user_date: dict[tuple[int, date], set[int]]


class ScheduleGenerationError(Exception):
    """Raised when no schedule can satisfy all hard constraints."""

    def __init__(self, message: str, issues: list[dict[str, object]]) -> None:
        """Store a user-facing summary and structured infeasibility details."""
        super().__init__(message)
        self.message = message
        self.issues = issues

    def as_detail(self) -> dict[str, object]:
        """Return the structured FastAPI error detail payload."""
        return {"message": self.message, "issues": self.issues}


def _calendar_days(month: int, year: int) -> list[date]:
    """Return every date in the selected calendar month."""
    return [date(year, month, day) for day in range(1, monthrange(year, month)[1] + 1)]


def _index_schedule_variables(
    variables: dict[tuple[int, int, date], LpVariable],
) -> ScheduleVariableIndex:
    """Build all constraint lookup maps in one linear pass."""
    by_competence_date: dict[tuple[int, date], list[LpVariable]] = {}
    candidate_ids_by_competence_date: dict[tuple[int, date], set[int]] = {}
    by_user_date: dict[tuple[int, date], list[LpVariable]] = {}
    by_user: dict[int, list[LpVariable]] = {}
    candidate_dates_by_user: dict[int, set[date]] = {}
    candidate_ids_by_date: dict[date, set[int]] = {}
    competence_ids_by_user_date: dict[tuple[int, date], set[int]] = {}

    for (user_id, competence_id, work_date), variable in variables.items():
        competence_date = (competence_id, work_date)
        user_date = (user_id, work_date)
        by_competence_date.setdefault(competence_date, []).append(variable)
        candidate_ids_by_competence_date.setdefault(
            competence_date, set()
        ).add(user_id)
        by_user_date.setdefault(user_date, []).append(variable)
        by_user.setdefault(user_id, []).append(variable)
        candidate_dates_by_user.setdefault(user_id, set()).add(work_date)
        candidate_ids_by_date.setdefault(work_date, set()).add(user_id)
        competence_ids_by_user_date.setdefault(user_date, set()).add(competence_id)

    return ScheduleVariableIndex(
        by_competence_date=by_competence_date,
        candidate_ids_by_competence_date=candidate_ids_by_competence_date,
        by_user_date=by_user_date,
        by_user=by_user,
        candidate_dates_by_user=candidate_dates_by_user,
        candidate_ids_by_date=candidate_ids_by_date,
        competence_ids_by_user_date=competence_ids_by_user_date,
    )


def _is_hard_unavailability(reason: str | None) -> bool:
    """Return whether an availability record must block schedule generation.

    The UI stores preferred days in the unavailability table as a transitional
    representation. A preferred day is the opposite of an absence: it never
    blocks an assignment, and it is rewarded by the objective instead. A
    reluctant day ("I would rather not") sits between the two: it is a wish
    the objective pays for, not an absence.
    """
    return reason not in (
        PREFERRED_UNAVAILABILITY_REASON,
        SOFT_DECLINE_UNAVAILABILITY_REASON,
    )


def _maximum_spaced_days(
    candidate_dates: Iterable[date],
    recovery_of: Callable[[date], int],
) -> int:
    """Return the most duties possible once every duty claims its rest.

    A duty on a date blocks the next ``recovery_of(date)`` days, and the two
    duties bounding the answer need not be the earliest ones -- an early date
    demanding a long rest can be worth skipping. The exact answer therefore
    comes from a backward pass over the dates rather than from taking each
    one as it comes.
    """
    ordered = sorted(candidate_dates)
    best_from = [0] * (len(ordered) + 1)
    for position in range(len(ordered) - 1, -1, -1):
        earliest_next = ordered[position] + timedelta(
            days=recovery_of(ordered[position]) + 1
        )
        resume = bisect_left(ordered, earliest_next, position + 1)
        best_from[position] = max(best_from[position + 1], 1 + best_from[resume])
    return best_from[0]


def _kind_unit_cost(preference: str, is_surcharge: bool) -> int:
    """What one more duty of a kind costs an employee at the margin."""
    if preference == SURCHARGE_PREFERENCE:
        return PREFERRED_KIND_UNIT_COST if is_surcharge else DISPREFERRED_KIND_UNIT_COST
    if preference == STANDARD_PREFERENCE:
        return DISPREFERRED_KIND_UNIT_COST if is_surcharge else PREFERRED_KIND_UNIT_COST
    return BALANCE_UNIT_COST


def _load_ladder(
    problem: LpProblem,
    name: str,
    assigned: list[LpVariable],
    maximum: int,
    unit_cost: int,
) -> list[LpAffineExpression]:
    """Charge an ever-growing price for each further duty of one load.

    The level variables are continuous on purpose. The prices rise with the
    level, so the cheapest way to account for a load is always to fill the
    lowest levels first, and no integrality has to be imposed to get there.
    """
    if maximum <= 0 or not assigned:
        return []
    levels = [
        LpVariable(f"level_{name}_{step}", lowBound=0, upBound=1)
        for step in range(1, maximum + 1)
    ]
    problem += (lpSum(levels) == lpSum(assigned), f"load_{name}")
    return [
        (unit_cost * (2 * step - 1)) * level
        for step, level in enumerate(levels, start=1)
    ]


def _detect_capacity_issues(
    variables: dict[tuple[int, int, date], LpVariable],
    competences: list[SchedulingCompetence],
    days: list[date],
    variable_index: ScheduleVariableIndex | None = None,
) -> list[dict[str, object]]:
    """Find obvious daily and rest-day capacity conflicts."""
    index = variable_index or _index_schedule_variables(variables)
    issues: list[dict[str, object]] = []
    for work_date in days:
        daily_required = sum(competence.required_on(work_date) for competence in competences)
        daily_candidates = index.candidate_ids_by_date.get(work_date, set())
        if len(daily_candidates) < daily_required:
            issues.append(
                {
                    "code": "insufficient_daily_capacity",
                    "work_date": work_date.isoformat(),
                    "required_count": daily_required,
                    "available_count": len(daily_candidates),
                }
            )

        for competence in competences:
            required_count = competence.required_on(work_date)
            candidates = index.candidate_ids_by_competence_date.get(
                (competence.id, work_date), set()
            )
            if len(candidates) < required_count:
                issues.append(
                    {
                        "code": "insufficient_qualified_staff",
                        "work_date": work_date.isoformat(),
                        "competence_id": competence.id,
                        "competence_name": competence.name,
                        "required_count": required_count,
                        "available_count": len(candidates),
                    }
                )

    if issues:
        return issues

    # Two neighbouring days can only be checked together when a duty on the
    # first one actually costs a day of rest. A workplace that configured no
    # recovery at all lets the same people work both days, and there is
    # nothing to report.
    for current_day, next_day in zip(days, days[1:]):
        for competence in competences:
            if competence.recovery_days_on(current_day) < 1:
                continue
            current_candidates = index.candidate_ids_by_competence_date.get(
                (competence.id, current_day), set()
            )
            next_candidates = index.candidate_ids_by_competence_date.get(
                (competence.id, next_day), set()
            )
            combined_count = len(current_candidates | next_candidates)
            required_across_days = competence.required_on(
                current_day
            ) + competence.required_on(next_day)
            if combined_count < required_across_days:
                issues.append(
                    {
                        "code": "insufficient_consecutive_day_rotation",
                        "work_date": current_day.isoformat(),
                        "next_work_date": next_day.isoformat(),
                        "competence_id": competence.id,
                        "competence_name": competence.name,
                        "required_count": required_across_days,
                        "available_count": combined_count,
                    }
                )

        if any(
            competence.recovery_days_on(current_day) < 1 for competence in competences
        ):
            continue
        combined_candidates = index.candidate_ids_by_date.get(
            current_day, set()
        ) | index.candidate_ids_by_date.get(next_day, set())
        required_across_days = sum(
            competence.required_on(current_day) + competence.required_on(next_day)
            for competence in competences
        )
        if len(combined_candidates) < required_across_days:
            issues.append(
                {
                    "code": "insufficient_consecutive_day_capacity",
                    "work_date": current_day.isoformat(),
                    "next_work_date": next_day.isoformat(),
                    "required_count": required_across_days,
                    "available_count": len(combined_candidates),
                }
            )

    return issues


def _detect_fixed_assignment_conflicts(
    fixed_assignments: frozenset[tuple[int, int, date]],
    employees: list[SchedulingEmployee],
    competences: list[SchedulingCompetence],
) -> list[dict[str, object]]:
    """Find manually placed duties the solver could never keep.

    A manual placement is an instruction, not a wish, so anything the solver
    would have to break to honor it is reported before the solve rather than
    coming back as an unexplained infeasibility.
    """
    issues: list[dict[str, object]] = []
    employee_ids = {employee.id for employee in employees}
    competences_by_id = {competence.id: competence for competence in competences}
    placements_by_user: dict[int, list[tuple[date, int]]] = {}
    counts_by_competence_date: dict[tuple[int, date], int] = {}

    for user_id, competence_id, work_date in sorted(fixed_assignments):
        if user_id not in employee_ids or competence_id not in competences_by_id:
            issues.append(
                {
                    "code": "fixed_assignment_unknown",
                    "work_date": work_date.isoformat(),
                    "user_id": user_id,
                    "competence_id": competence_id,
                }
            )
            continue
        placements_by_user.setdefault(user_id, []).append((work_date, competence_id))
        counts_by_competence_date[(competence_id, work_date)] = (
            counts_by_competence_date.get((competence_id, work_date), 0) + 1
        )

    for (competence_id, work_date), count in sorted(counts_by_competence_date.items()):
        competence = competences_by_id[competence_id]
        required_count = competence.required_on(work_date)
        if count > required_count:
            issues.append(
                {
                    "code": "fixed_assignment_over_requirement",
                    "work_date": work_date.isoformat(),
                    "competence_id": competence_id,
                    "competence_name": competence.name,
                    "required_count": required_count,
                    "fixed_count": count,
                }
            )

    for user_id, placements in sorted(placements_by_user.items()):
        ordered = sorted(placements)
        for (current_date, current_competence), (next_date, _) in zip(
            ordered, ordered[1:]
        ):
            recovery = competences_by_id[current_competence].recovery_days_on(
                current_date
            )
            if next_date <= current_date + timedelta(days=recovery):
                issues.append(
                    {
                        "code": "fixed_assignment_rest_conflict",
                        "work_date": current_date.isoformat(),
                        "next_work_date": next_date.isoformat(),
                        "user_id": user_id,
                    }
                )

    return issues


def solve_monthly_schedule(
    employees: list[SchedulingEmployee],
    competences: list[SchedulingCompetence],
    month: int,
    year: int,
    adjacent_assignments: frozenset[tuple[int, int, date]] = frozenset(),
    fixed_assignments: frozenset[tuple[int, int, date]] = frozenset(),
    generate_from: date | None = None,
) -> list[GeneratedAssignment]:
    """Solve one monthly ambulance schedule as a binary MILP.

    The model guarantees full daily coverage, employee availability, at most
    one role per employee per day, and the rest each duty earns under the
    workplace's own recovery settings. What the objective weighs, and in what
    order, is described at the top of this module.

    Args:
        employees: Active ambulance employees with qualifications and absences.
        competences: Active roles and the required daily headcount for each.
        month: Calendar month from 1 to 12.
        year: Four-digit calendar year.
        adjacent_assignments: Assignments on the days around the month.
        fixed_assignments: Assignments the solver must keep exactly as given.
            They cover their own demand, occupy their employee's rest days and
            count towards the workload balance like any generated duty.
        generate_from: First date the solver may fill. Earlier dates keep only
            their fixed assignments and are exempt from the coverage rule, so a
            month already half worked can be regenerated from tomorrow on.

    Returns:
        A deterministic, sorted list of generated assignments.

    Raises:
        ScheduleGenerationError: If the hard constraints are infeasible.
        ValueError: If month or year is outside the supported range.
    """
    if not 1 <= month <= 12 or not 2000 <= year <= 2100:
        raise ValueError("month and year must be valid")
    if not competences:
        raise ScheduleGenerationError(
            "The ambulance has no active competences to schedule.",
            [{"code": "no_active_competences"}],
        )
    if any(
        competence.weekday_required_counts is not None
        and len(competence.weekday_required_counts) != 7
        for competence in competences
    ):
        raise ValueError("weekday_required_counts must contain exactly seven values")

    days = _calendar_days(month, year)
    if generate_from is not None and (
        generate_from.month != month or generate_from.year != year
    ):
        raise ValueError("generate_from must belong to the solved month")
    # Dates the solver may still fill. Everything before them is history: it
    # keeps whatever is fixed there and is exempt from the coverage rule.
    window_days = [
        work_date
        for work_date in days
        if generate_from is None or work_date >= generate_from
    ]
    competences_by_id = {competence.id: competence for competence in competences}
    fixed_assignments = frozenset(
        assignment
        for assignment in fixed_assignments
        if assignment[2] in set(days)
    )
    fixed_issues = _detect_fixed_assignment_conflicts(
        fixed_assignments,
        employees,
        competences,
    )
    if fixed_issues:
        raise ScheduleGenerationError(
            "The manually placed duties cannot all be kept.",
            fixed_issues,
        )
    if not employees:
        if all(
            competence.required_on(work_date) == 0
            for competence in competences
            for work_date in window_days
        ):
            return []
        raise ScheduleGenerationError(
            "The ambulance has no active employees to schedule.",
            [{"code": "no_active_employees"}],
        )

    def duty_recovery(competence_id: int, work_date: date) -> int:
        """Rest earned by one duty, for a competence that may be another's."""
        competence = competences_by_id.get(competence_id)
        if competence is None:
            return DEFAULT_RECOVERY_DAYS
        return competence.recovery_days_on(work_date)

    def foreign_recovery(work_date: date) -> int:
        """Rest assumed after a duty worked at another workplace.

        What that workplace asks for is not ours to read, so the duty is
        credited with the longest rest this one would have given for the
        same date.
        """
        return max(
            (competence.recovery_days_on(work_date) for competence in competences),
            default=DEFAULT_RECOVERY_DAYS,
        )

    # Every duty an employee already owes somebody, with the rest it earns:
    # duties placed by hand, duties just outside the month, and duties worked
    # at another workplace.
    commitments: dict[int, list[tuple[date, int]]] = {}
    for user_id, competence_id, work_date in fixed_assignments:
        commitments.setdefault(user_id, []).append(
            (work_date, duty_recovery(competence_id, work_date))
        )
    for user_id, competence_id, work_date in adjacent_assignments:
        commitments.setdefault(user_id, []).append(
            (work_date, duty_recovery(competence_id, work_date))
        )
    for employee in employees:
        for work_date in employee.externally_scheduled_dates:
            commitments.setdefault(employee.id, []).append(
                (work_date, foreign_recovery(work_date))
            )

    problem = LpProblem("ambulance_monthly_schedule", LpMinimize)
    variables: dict[tuple[int, int, date], LpVariable] = {}

    for employee in sorted(employees, key=lambda item: item.id):
        owed = commitments.get(employee.id, [])
        for competence in sorted(competences, key=lambda item: item.id):
            if competence.id not in employee.competence_ids:
                continue
            for work_date in window_days:
                if competence.required_on(work_date) == 0:
                    continue
                if work_date in employee.unavailable_dates:
                    continue
                recovery = competence.recovery_days_on(work_date)
                if any(
                    # The duty already owed falls on this very day, still
                    # holds it in rest, or starts before this duty's own rest
                    # has run out.
                    owed_date == work_date
                    or owed_date < work_date <= owed_date + timedelta(days=owed_rest)
                    or work_date < owed_date <= work_date + timedelta(days=recovery)
                    for owed_date, owed_rest in owed
                ):
                    continue
                variables[(employee.id, competence.id, work_date)] = LpVariable(
                    f"assign_{employee.id}_{competence.id}_{work_date.isoformat()}",
                    cat="Binary",
                )

    # A manual placement overrides every soft filter above: the manager has
    # already decided, so it gets a variable even on a day the employee did
    # not ask for and even outside the generation window.
    for user_id, competence_id, work_date in sorted(fixed_assignments):
        key = (user_id, competence_id, work_date)
        if key not in variables:
            variables[key] = LpVariable(
                f"assign_{user_id}_{competence_id}_{work_date.isoformat()}",
                cat="Binary",
            )

    variable_index = _index_schedule_variables(variables)
    preferred_dates_by_employee = {
        employee.id: employee.preferred_dates
        for employee in employees
        if employee.preferred_dates
    }
    soft_declined_dates_by_employee = {
        employee.id: employee.soft_declined_dates
        for employee in employees
        if employee.soft_declined_dates
    }
    capacity_issues = _detect_capacity_issues(
        variables,
        competences,
        window_days,
        variable_index,
    )
    if capacity_issues:
        raise ScheduleGenerationError(
            "There are not enough available qualified employees to cover the schedule.",
            capacity_issues,
        )

    for user_id, competence_id, work_date in sorted(fixed_assignments):
        problem += (
            variables[(user_id, competence_id, work_date)] == 1,
            f"fixed_{user_id}_{competence_id}_{work_date.isoformat()}",
        )

    for work_date in window_days:
        for competence in competences:
            coverage_variables = variable_index.by_competence_date.get(
                (competence.id, work_date), []
            )
            problem += (
                lpSum(coverage_variables) == competence.required_on(work_date),
                f"coverage_{competence.id}_{work_date.isoformat()}",
            )

    # One rule covers both "one duty a day" and "a duty earns its rest": on
    # any given day an employee may start a duty, or still be recovering from
    # one earlier duty, but not both. Every duty inside the sum already
    # excludes every other one, so they can share a single constraint.
    for employee in employees:
        for work_date in days:
            recovering = [
                variables[(employee.id, competence_id, earlier_date)]
                for earlier_date in variable_index.candidate_dates_by_user.get(
                    employee.id, set()
                )
                if earlier_date < work_date
                for competence_id in variable_index.competence_ids_by_user_date.get(
                    (employee.id, earlier_date), set()
                )
                if work_date
                <= earlier_date
                + timedelta(days=duty_recovery(competence_id, earlier_date))
            ]
            working = variable_index.by_user_date.get((employee.id, work_date), [])
            if len(recovering) + len(working) < 2:
                continue
            problem += (
                lpSum(recovering) + lpSum(working) <= 1,
                f"rest_{employee.id}_{work_date.isoformat()}",
            )

    objective_terms: list[LpAffineExpression] = []
    crowded_windows: list[LpVariable] = []
    variables_by_user: dict[int, list[tuple[int, date, LpVariable]]] = {}
    for (user_id, competence_id, work_date), variable in variables.items():
        variables_by_user.setdefault(user_id, []).append(
            (competence_id, work_date, variable)
        )

    for employee in employees:
        employee_variables = variable_index.by_user.get(employee.id, [])
        if not employee_variables:
            continue
        candidate_dates = variable_index.candidate_dates_by_user.get(employee.id, set())

        def shortest_recovery(work_date: date, employee_id: int = employee.id) -> int:
            """The least rest any duty open to this employee that day earns."""
            return min(
                duty_recovery(competence_id, work_date)
                for competence_id in variable_index.competence_ids_by_user_date[
                    (employee_id, work_date)
                ]
            )

        surcharge_variables: list[LpVariable] = []
        standard_variables: list[LpVariable] = []
        surcharge_dates: set[date] = set()
        standard_dates: set[date] = set()
        for competence_id, work_date, variable in variables_by_user[employee.id]:
            if competences_by_id[competence_id].is_surcharge_on(work_date):
                surcharge_variables.append(variable)
                surcharge_dates.add(work_date)
            else:
                standard_variables.append(variable)
                standard_dates.add(work_date)

        objective_terms.extend(
            _load_ladder(
                problem,
                f"total_{employee.id}",
                employee_variables,
                _maximum_spaced_days(candidate_dates, shortest_recovery),
                BALANCE_UNIT_COST,
            )
        )
        objective_terms.extend(
            _load_ladder(
                problem,
                f"surcharge_{employee.id}",
                surcharge_variables,
                _maximum_spaced_days(surcharge_dates, shortest_recovery),
                _kind_unit_cost(employee.shift_preference, True),
            )
        )
        objective_terms.extend(
            _load_ladder(
                problem,
                f"standard_{employee.id}",
                standard_variables,
                _maximum_spaced_days(standard_dates, shortest_recovery),
                _kind_unit_cost(employee.shift_preference, False),
            )
        )

        # The spread. A stretch of SPREAD_WINDOW_DAYS days is crowded when it
        # holds every duty it physically can, which is one duty per rest
        # period that fits inside it. The flags share the smallest budget in
        # the model, so duties sitting further apart decide only between
        # rosters that are already equal by every other rule.
        for start_index, window_start in enumerate(days):
            window_dates = [
                days[start_index + offset]
                for offset in range(SPREAD_WINDOW_DAYS)
                if start_index + offset < len(days)
                and (employee.id, days[start_index + offset]) in variable_index.by_user_date
            ]
            capacity = _maximum_spaced_days(window_dates, shortest_recovery)
            if capacity < 2:
                continue
            window_variables = [
                variable
                for window_date in window_dates
                for variable in variable_index.by_user_date[(employee.id, window_date)]
            ]
            crowded = LpVariable(
                f"crowded_{employee.id}_{window_start.isoformat()}",
                lowBound=0,
                upBound=1,
            )
            problem += (
                lpSum(window_variables) - (capacity - 1) <= crowded,
                f"spread_{employee.id}_{window_start.isoformat()}",
            )
            crowded_windows.append(crowded)

        if employee.max_shifts_per_month is not None:
            over_wish = LpVariable(f"over_wish_{employee.id}", lowBound=0)
            problem += (
                over_wish
                >= lpSum(employee_variables) - employee.max_shifts_per_month,
                f"wish_{employee.id}",
            )
            objective_terms.append(OVER_WISH_DUTY_COST * over_wish)

    objective = lpSum(objective_terms)

    preferred_variables = [
        variable
        for (user_id, _competence_id, work_date), variable in variables.items()
        if work_date in preferred_dates_by_employee.get(user_id, frozenset())
    ]
    if preferred_variables:
        # Spreading one fixed budget over every request keeps the reward below
        # the cheapest balance step no matter how large the month is, so the
        # solver maximizes honored requests strictly inside the set of optimally
        # balanced schedules.
        preference_reward = PREFERENCE_REWARD_BUDGET / (len(preferred_variables) + 1)
        objective -= preference_reward * lpSum(preferred_variables)

    soft_declined_variables = [
        variable
        for (user_id, _competence_id, work_date), variable in variables.items()
        if work_date in soft_declined_dates_by_employee.get(user_id, frozenset())
    ]
    if soft_declined_variables:
        decline_penalty = SOFT_DECLINE_PENALTY_BUDGET / (
            len(soft_declined_variables) + 1
        )
        objective += decline_penalty * lpSum(soft_declined_variables)

    if crowded_windows:
        spread_penalty = SPREAD_PENALTY_BUDGET / (len(crowded_windows) + 1)
        objective += spread_penalty * lpSum(crowded_windows)

    problem += objective
    problem.solve(
        PULP_CBC_CMD(
            msg=False,
            timeLimit=settings.SCHEDULE_SOLVER_TIME_LIMIT_SECONDS,
        )
    )

    solver_status = LpStatus[problem.status]
    if solver_status == "Not Solved":
        raise ScheduleGenerationError(
            "Schedule generation exceeded the configured time limit.",
            [
                {
                    "code": "solver_timeout",
                    "time_limit_seconds": settings.SCHEDULE_SOLVER_TIME_LIMIT_SECONDS,
                }
            ],
        )
    if solver_status != "Optimal":
        raise ScheduleGenerationError(
            "No feasible schedule satisfies all coverage, availability, and rotation constraints.",
            [{"code": "constraint_conflict"}],
        )

    assignments = [
        GeneratedAssignment(user_id=user_id, competence_id=competence_id, work_date=work_date)
        for (user_id, competence_id, work_date), variable in variables.items()
        if value(variable) is not None and value(variable) > 0.5
    ]
    return sorted(
        assignments,
        key=lambda item: (item.work_date, item.competence_id, item.user_id),
    )


#: How far past the month's edges the calendars have to reach. A duty may
#: earn up to six days of rest, so nothing closer than a week to either edge
#: can be read correctly without looking outside the month.
REST_CALENDAR_MARGIN_DAYS = 7


def _slot_value(
    slots: dict[int, CompetenceWeekdayRequirement],
    slot: int,
    attribute: str,
    fallback: object,
) -> object:
    """One parameter of one day slot, with the workplace's own fallbacks.

    A day of rest with no row of its own is answered like a Sunday, which is
    how such a date was staffed and paid before the slot existed; a
    competence with no row at all falls back to what the competence editor
    starts a new one from.
    """
    row = slots.get(slot)
    if row is None and slot == SPECIAL_DAY_SLOT:
        row = slots.get(6)
    if row is None:
        return fallback
    return getattr(row, attribute)


def generate_ambulance_monthly_schedule(
    db: Session,
    ambulance_id: int,
    month: int,
    year: int,
    fixed_entries: list[tuple[int, int, date]] | None = None,
    generate_from: date | None = None,
) -> ScheduleGenerationResponse:
    """Load one ambulance's data and return an unsaved optimized schedule draft.

    ``fixed_entries`` are duties the manager placed by hand and wants kept;
    ``generate_from`` restricts the solver to that date onwards, which is how a
    month that is already partly worked gets regenerated without rewriting its
    past.
    """
    days = _calendar_days(month, year)
    start = days[0]
    end = days[-1]
    margin = timedelta(days=REST_CALENDAR_MARGIN_DAYS)
    user_rows = (
        db.query(User)
        .join(UserAmbulance, UserAmbulance.user_id == User.id)
        .filter(
            UserAmbulance.ambulance_id == ambulance_id,
            UserAmbulance.is_active.is_(True),
            User.is_active.is_(True),
        )
        .order_by(User.id)
        .all()
    )
    competence_rows = (
        db.query(Competence)
        .options(selectinload(Competence.weekday_requirements))
        .filter(
            Competence.ambulance_id == ambulance_id,
            Competence.is_active.is_(True),
        )
        .order_by(Competence.id)
        .all()
    )
    # A workplace's competences carry one set of weekday parameters per
    # scenario. The solver reads the selected one; a workplace that has no
    # scenario yet falls back to the competence's legacy all-days count.
    selected_scenario = get_selected_scenario(db, ambulance_id)
    selected_scenario_id = selected_scenario.id if selected_scenario else None

    def scenario_slots(competence: Competence) -> dict[int, CompetenceWeekdayRequirement]:
        """This competence's parameter row per day slot in the scenario."""
        return {
            requirement.weekday: requirement
            for requirement in competence.weekday_requirements
            if requirement.scenario_id == selected_scenario_id
        }

    # Which of the month's dates are days of rest is the workplace's own
    # answer: the Slovak public-holiday library, corrected by whatever this
    # workplace added or took away. The range reaches past the month so a
    # duty just outside it is read from the right slot too.
    special_dates = frozenset(
        rest_days_between(db, ambulance_id, start - margin, end + margin)
    )
    user_ids = [user.id for user in user_rows]
    competence_ids = [competence.id for competence in competence_rows]

    qualifications: dict[int, set[int]] = {user_id: set() for user_id in user_ids}
    if user_ids and competence_ids:
        qualification_rows = (
            db.query(UserCompetence.user_id, UserCompetence.competence_id)
            .filter(
                UserCompetence.user_id.in_(user_ids),
                UserCompetence.competence_id.in_(competence_ids),
                UserCompetence.is_active.is_(True),
            )
            .all()
        )
        for user_id, competence_id in qualification_rows:
            qualifications[user_id].add(competence_id)

    unavailable_dates: dict[int, set[date]] = {user_id: set() for user_id in user_ids}
    preferred_dates: dict[int, set[date]] = {user_id: set() for user_id in user_ids}
    soft_declined_dates: dict[int, set[date]] = {user_id: set() for user_id in user_ids}
    if user_ids:
        unavailability_rows = (
            db.query(
                Unavailability.user_id,
                Unavailability.date_absent,
                Unavailability.reason,
            )
            .filter(
                Unavailability.user_id.in_(user_ids),
                Unavailability.date_absent.between(start, end),
                Unavailability.is_active.is_(True),
            )
            .all()
        )
        for user_id, unavailable_date, reason in unavailability_rows:
            if _is_hard_unavailability(reason):
                unavailable_dates[user_id].add(unavailable_date)
            elif reason == SOFT_DECLINE_UNAVAILABILITY_REASON:
                soft_declined_dates[user_id].add(unavailable_date)
            else:
                preferred_dates[user_id].add(unavailable_date)

    externally_scheduled_dates: dict[int, set[date]] = {
        user_id: set() for user_id in user_ids
    }
    adjacent_assignments: set[tuple[int, int, date]] = set()
    if user_ids:
        # A long recovery reaches further than one day, so duties on either
        # side of the month are read as far out as any of them can reach.
        external_schedule_rows = (
            db.query(Schedule.user_id, Schedule.work_date)
            .filter(
                Schedule.user_id.in_(user_ids),
                Schedule.ambulance_id != ambulance_id,
                Schedule.work_date.between(start - margin, end + margin),
                Schedule.is_active.is_(True),
            )
            .all()
        )
        for user_id, work_date in external_schedule_rows:
            externally_scheduled_dates[user_id].add(work_date)

        boundary_rows = (
            db.query(Schedule.user_id, Schedule.competence_id, Schedule.work_date)
            .filter(
                Schedule.user_id.in_(user_ids),
                Schedule.ambulance_id == ambulance_id,
                Schedule.is_active.is_(True),
                Schedule.work_date.between(start - margin, end + margin),
                ~Schedule.work_date.between(start, end),
            )
            .all()
        )
        adjacent_assignments.update(
            (user_id, competence_id, work_date)
            for user_id, competence_id, work_date in boundary_rows
        )

    employees = [
        SchedulingEmployee(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            competence_ids=frozenset(qualifications[user.id]),
            unavailable_dates=frozenset(unavailable_dates[user.id]),
            externally_scheduled_dates=frozenset(externally_scheduled_dates[user.id]),
            preferred_dates=frozenset(preferred_dates[user.id]),
            soft_declined_dates=frozenset(soft_declined_dates[user.id]),
            max_shifts_per_month=user.max_shifts_per_month,
            shift_preference=user.shift_preference or ANY_PREFERENCE,
        )
        for user in user_rows
    ]

    competences = []
    for competence in competence_rows:
        slots = scenario_slots(competence)
        competences.append(
            SchedulingCompetence(
                id=competence.id,
                name=competence.name,
                required_count=competence.required_count,
                weekday_required_counts=tuple(
                    _slot_value(
                        slots, weekday, "required_count", competence.required_count
                    )
                    for weekday in range(7)
                ),
                special_day_required_count=_slot_value(
                    slots,
                    SPECIAL_DAY_SLOT,
                    "required_count",
                    competence.required_count,
                ),
                special_dates=special_dates,
                weekday_is_surcharge=tuple(
                    _slot_value(
                        slots, weekday, "is_surcharge", default_is_surcharge(weekday)
                    )
                    for weekday in range(7)
                ),
                special_day_is_surcharge=_slot_value(
                    slots,
                    SPECIAL_DAY_SLOT,
                    "is_surcharge",
                    default_is_surcharge(SPECIAL_DAY_SLOT),
                ),
                weekday_recovery_days=tuple(
                    _slot_value(slots, weekday, "recovery_days", DEFAULT_RECOVERY_DAYS)
                    for weekday in range(7)
                ),
                special_day_recovery_days=_slot_value(
                    slots,
                    SPECIAL_DAY_SLOT,
                    "recovery_days",
                    DEFAULT_RECOVERY_DAYS,
                ),
            )
        )

    assignments = solve_monthly_schedule(
        employees,
        competences,
        month,
        year,
        frozenset(adjacent_assignments),
        frozenset(fixed_entries or ()),
        generate_from,
    )
    users_by_id = {user.id: user for user in user_rows}
    competences_by_id = {competence.id: competence for competence in competence_rows}
    entries = [
        GeneratedScheduleEntry(
            user_id=assignment.user_id,
            ambulance_id=ambulance_id,
            competence_id=assignment.competence_id,
            work_date=assignment.work_date,
            user_email=users_by_id[assignment.user_id].email,
            user_full_name=users_by_id[assignment.user_id].full_name,
            competence_name=competences_by_id[assignment.competence_id].name,
        )
        for assignment in assignments
    ]
    return ScheduleGenerationResponse(
        month=month,
        year=year,
        assignment_count=len(entries),
        entries=entries,
    )
