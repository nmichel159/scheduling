"""MILP-based monthly schedule generation for one ambulance."""

from __future__ import annotations

from calendar import monthrange
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
from app.models.schedule import Schedule
from app.models.unavailability import Unavailability
from app.models.user import User
from app.schemas.schedule import (
    GeneratedScheduleEntry,
    ScheduleGenerationResponse,
)


PREFERRED_UNAVAILABILITY_REASON = "PREFERRED"


@dataclass(frozen=True)
class SchedulingCompetence:
    """Solver input describing one required ambulance competence."""

    id: int
    name: str
    required_count: int
    weekday_required_counts: tuple[int, ...] | None = None

    def required_on(self, work_date: date) -> int:
        """Return the configured demand for a concrete calendar date."""
        if self.weekday_required_counts is None:
            return self.required_count
        return self.weekday_required_counts[work_date.weekday()]


@dataclass(frozen=True)
class SchedulingEmployee:
    """Solver input describing an employee and all hard availability limits."""

    id: int
    email: str
    full_name: str | None
    competence_ids: frozenset[int]
    unavailable_dates: frozenset[date]
    externally_scheduled_dates: frozenset[date]


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


def _candidate_ids(
    variables: dict[tuple[int, int, date], LpVariable],
    competence_id: int,
    work_date: date,
) -> set[int]:
    """Return employees with a decision variable for a role and date."""
    return {
        user_id
        for user_id, candidate_competence_id, candidate_date in variables
        if candidate_competence_id == competence_id and candidate_date == work_date
    }


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

    return ScheduleVariableIndex(
        by_competence_date=by_competence_date,
        candidate_ids_by_competence_date=candidate_ids_by_competence_date,
        by_user_date=by_user_date,
        by_user=by_user,
        candidate_dates_by_user=candidate_dates_by_user,
        candidate_ids_by_date=candidate_ids_by_date,
    )


def _is_hard_unavailability(reason: str | None) -> bool:
    """Return whether an availability record must block schedule generation.

    The current UI stores preferred days in the unavailability table as a
    transitional representation. Preferences are not optimized yet, so they
    must remain neutral rather than being treated as absences.
    """
    return reason != PREFERRED_UNAVAILABILITY_REASON


def _rest_blocked_dates(scheduled_dates: frozenset[date]) -> frozenset[date]:
    """Expand fixed duties to the duty date and both mandatory rest days."""
    return frozenset(
        blocked_date
        for scheduled_date in scheduled_dates
        for blocked_date in (
            scheduled_date - timedelta(days=1),
            scheduled_date,
            scheduled_date + timedelta(days=1),
        )
    )


def _maximum_nonconsecutive_days(candidate_dates: set[date]) -> int:
    """Return the maximum duties possible when adjacent dates are forbidden."""
    selected_count = 0
    last_selected: date | None = None
    for candidate_date in sorted(candidate_dates):
        if last_selected is None or candidate_date > last_selected + timedelta(days=1):
            selected_count += 1
            last_selected = candidate_date
    return selected_count


def _detect_capacity_issues(
    variables: dict[tuple[int, int, date], LpVariable],
    competences: list[SchedulingCompetence],
    days: list[date],
    variable_index: ScheduleVariableIndex | None = None,
) -> list[dict[str, object]]:
    """Find obvious daily and consecutive-day capacity conflicts."""
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

    for current_day, next_day in zip(days, days[1:]):
        for competence in competences:
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


def solve_monthly_schedule(
    employees: list[SchedulingEmployee],
    competences: list[SchedulingCompetence],
    month: int,
    year: int,
    adjacent_assignments: frozenset[tuple[int, int, date]] = frozenset(),
) -> list[GeneratedAssignment]:
    """Solve one monthly ambulance schedule as a binary MILP.

    The model guarantees full daily coverage, employee availability, at most
    one role per employee per day, and a complete day of rest between duties.
    The objective uses an increasing marginal cost for every additional duty,
    which balances workload as evenly as the hard constraints permit.

    Args:
        employees: Active ambulance employees with qualifications and absences.
        competences: Active roles and the required daily headcount for each.
        month: Calendar month from 1 to 12.
        year: Four-digit calendar year.
        adjacent_assignments: Assignments on the day before or after the month.

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
    if not employees:
        if all(
            competence.required_on(work_date) == 0
            for competence in competences
            for work_date in days
        ):
            return []
        raise ScheduleGenerationError(
            "The ambulance has no active employees to schedule.",
            [{"code": "no_active_employees"}],
        )
    first_day = days[0]
    last_day = days[-1]
    previous_day = first_day - timedelta(days=1)
    following_day = last_day + timedelta(days=1)
    previously_scheduled_employee_ids = {
        user_id
        for user_id, _competence_id, work_date in adjacent_assignments
        if work_date == previous_day
    }
    subsequently_scheduled_employee_ids = {
        user_id
        for user_id, _competence_id, work_date in adjacent_assignments
        if work_date == following_day
    }

    problem = LpProblem("ambulance_monthly_schedule", LpMinimize)
    variables: dict[tuple[int, int, date], LpVariable] = {}

    for employee in sorted(employees, key=lambda item: item.id):
        blocked_dates = employee.unavailable_dates | _rest_blocked_dates(
            employee.externally_scheduled_dates
        )
        for competence in sorted(competences, key=lambda item: item.id):
            if competence.id not in employee.competence_ids:
                continue
            for work_date in days:
                if competence.required_on(work_date) == 0:
                    continue
                if work_date in blocked_dates:
                    continue
                if work_date == first_day and employee.id in previously_scheduled_employee_ids:
                    continue
                if work_date == last_day and employee.id in subsequently_scheduled_employee_ids:
                    continue
                variables[(employee.id, competence.id, work_date)] = LpVariable(
                    f"assign_{employee.id}_{competence.id}_{work_date.isoformat()}",
                    cat="Binary",
                )

    variable_index = _index_schedule_variables(variables)
    capacity_issues = _detect_capacity_issues(
        variables,
        competences,
        days,
        variable_index,
    )
    if capacity_issues:
        raise ScheduleGenerationError(
            "There are not enough available qualified employees to cover the schedule.",
            capacity_issues,
        )

    for work_date in days:
        for competence in competences:
            coverage_variables = variable_index.by_competence_date.get(
                (competence.id, work_date), []
            )
            problem += (
                lpSum(coverage_variables) == competence.required_on(work_date),
                f"coverage_{competence.id}_{work_date.isoformat()}",
            )

        for employee in employees:
            daily_variables = variable_index.by_user_date.get(
                (employee.id, work_date), []
            )
            problem += (
                lpSum(daily_variables) <= 1,
                f"one_role_{employee.id}_{work_date.isoformat()}",
            )

    for employee in employees:
        for current_day, next_day in zip(days, days[1:]):
            consecutive_variables = (
                variable_index.by_user_date.get((employee.id, current_day), [])
                + variable_index.by_user_date.get((employee.id, next_day), [])
            )
            problem += (
                lpSum(consecutive_variables) <= 1,
                f"rest_{employee.id}_{current_day.isoformat()}",
            )

    marginal_workload_costs: list[LpAffineExpression] = []
    for employee in employees:
        employee_variables = variable_index.by_user.get(employee.id, [])
        candidate_dates = variable_index.candidate_dates_by_user.get(
            employee.id, set()
        )
        maximum_workload = _maximum_nonconsecutive_days(candidate_dates)
        if maximum_workload == 0:
            continue

        workload_levels = [
            LpVariable(f"workload_level_{employee.id}_{level}", cat="Binary")
            for level in range(1, maximum_workload + 1)
        ]
        problem += lpSum(employee_variables) == lpSum(workload_levels)
        for current_level, next_level in zip(workload_levels, workload_levels[1:]):
            problem += current_level >= next_level

        # Costs 1, 3, 5, ... linearize workload squared. The convex cost makes
        # every additional duty progressively less attractive for an already
        # busy employee and can later be generalized to hour-based segments.
        marginal_workload_costs.extend(
            (2 * level - 1) * workload_level
            for level, workload_level in enumerate(workload_levels, start=1)
        )

    problem += lpSum(marginal_workload_costs)
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


def generate_ambulance_monthly_schedule(
    db: Session,
    ambulance_id: int,
    month: int,
    year: int,
) -> ScheduleGenerationResponse:
    """Load one ambulance's data and return an unsaved optimized schedule draft."""
    days = _calendar_days(month, year)
    start = days[0]
    end = days[-1]
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

    externally_scheduled_dates: dict[int, set[date]] = {
        user_id: set() for user_id in user_ids
    }
    adjacent_assignments: set[tuple[int, int, date]] = set()
    if user_ids:
        external_schedule_rows = (
            db.query(Schedule.user_id, Schedule.work_date)
            .filter(
                Schedule.user_id.in_(user_ids),
                Schedule.ambulance_id != ambulance_id,
                Schedule.work_date.between(
                    start - timedelta(days=1),
                    end + timedelta(days=1),
                ),
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
                Schedule.work_date.in_([start - timedelta(days=1), end + timedelta(days=1)]),
                Schedule.is_active.is_(True),
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
        )
        for user in user_rows
    ]
    competences = [
        SchedulingCompetence(
            id=competence.id,
            name=competence.name,
            required_count=competence.required_count,
            weekday_required_counts=tuple(
                {
                    requirement.weekday: requirement.required_count
                    for requirement in competence.weekday_requirements
                }.get(weekday, competence.required_count)
                for weekday in range(7)
            ),
        )
        for competence in competence_rows
    ]
    assignments = solve_monthly_schedule(
        employees,
        competences,
        month,
        year,
        frozenset(adjacent_assignments),
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
