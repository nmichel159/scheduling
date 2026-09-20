"""How much duty each employee of a workplace carries in one month.

The scheduler's question is not "who works here" but "who is already
loaded" -- and, because the surcharge is what people actually argue about,
"how much of that load is paid extra". Both answers come from the same
three sources the generator reads, so the figures on the screen match the
ones the solver worked with:

* the saved schedule rows of the workplace for the month,
* the selected scenario's weekday parameters (``is_surcharge`` and
  ``shift_hours``), and
* the workplace's special-day calendar, which moves a date onto the
  day-of-rest slot whatever weekday it falls on.

A competence with no row for the special-day slot falls back to Sunday's
row, the same fallback :mod:`app.services.schedule_generation_service`
applies, and a competence with no scenario row at all falls back to the
defaults in :mod:`app.models.competence_weekday_requirement`.
"""

from calendar import monthrange
from datetime import date

from sqlalchemy.orm import Session

from app.models.competence import Competence
from app.models.competence_weekday_requirement import (
    DEFAULT_SHIFT_HOURS,
    SPECIAL_DAY_SLOT,
    CompetenceWeekdayRequirement,
    default_is_surcharge,
)
from app.models.associations import UserAmbulance
from app.models.schedule import Schedule
from app.models.unavailability import Unavailability
from app.models.user import User
from app.schemas.ambulance_employee import (
    AmbulanceMonthlyLoad,
    EmployeeDutyDay,
    EmployeeMonthlyLoad,
    EmployeeSchedulingSettings,
)
from app.services.competence_scenario_service import get_selected_scenario
from app.services.database_conflict import commit_or_conflict
from app.services.special_day_service import rest_days_between


def _slot_parameters(
    db: Session, ambulance_id: int
) -> dict[tuple[int, int], tuple[bool, float]]:
    """Map (competence_id, slot) to its surcharge flag and duty length."""
    scenario = get_selected_scenario(db, ambulance_id)
    if scenario is None:
        return {}
    rows = (
        db.query(CompetenceWeekdayRequirement)
        .join(
            Competence,
            Competence.id == CompetenceWeekdayRequirement.competence_id,
        )
        .filter(
            CompetenceWeekdayRequirement.scenario_id == scenario.id,
            Competence.ambulance_id == ambulance_id,
        )
        .all()
    )
    return {
        (row.competence_id, row.weekday): (
            bool(row.is_surcharge),
            float(row.shift_hours),
        )
        for row in rows
    }


def _parameters_for(
    parameters: dict[tuple[int, int], tuple[bool, float]],
    competence_id: int,
    slot: int,
) -> tuple[bool, float]:
    """Surcharge flag and duty length of one competence on one slot."""
    found = parameters.get((competence_id, slot))
    if found is None and slot == SPECIAL_DAY_SLOT:
        # A day of rest with no slot of its own is paid like a Sunday,
        # which is how it was paid before the slot existed.
        found = parameters.get((competence_id, 6))
    if found is None:
        return default_is_surcharge(slot), DEFAULT_SHIFT_HOURS
    return found


#: The two reasons that are wishes rather than absences, spelled the same
#: way :mod:`app.services.schedule_generation_service` reads them. They are
#: repeated here rather than imported: that module pulls in the solver, and
#: this one is asked for on every load of the employees screen.
PREFERRED_REASON = "PREFERRED"
SOFT_DECLINE_REASON = "SOFT_DECLINE"


def _availability_counts(
    db: Session, user_ids: list[int], first: date, last: date
) -> dict[int, dict[str, int]]:
    """Count how each employee filled their availability calendar.

    The table stores a free-text ``reason``, and the application writes
    sentinels into it; the two the generator treats as wishes are counted
    apart, and everything else -- including the null reason older records
    were written with -- is an absence that blocks the day.
    """
    counts = {
        user_id: {"marked": 0, "preferred": 0, "declined": 0, "blocked": 0}
        for user_id in user_ids
    }
    if not user_ids:
        return counts

    rows = (
        db.query(Unavailability.user_id, Unavailability.reason)
        .filter(
            Unavailability.user_id.in_(user_ids),
            Unavailability.is_active.is_(True),
            Unavailability.date_absent >= first,
            Unavailability.date_absent <= last,
        )
        .all()
    )
    for user_id, reason in rows:
        bucket = counts.get(user_id)
        if bucket is None:
            continue
        bucket["marked"] += 1
        if reason == PREFERRED_REASON:
            bucket["preferred"] += 1
        elif reason == SOFT_DECLINE_REASON:
            bucket["declined"] += 1
        else:
            bucket["blocked"] += 1
    return counts


def get_monthly_employee_load(
    db: Session, ambulance_id: int, month: int, year: int
) -> AmbulanceMonthlyLoad:
    """Report every employee of a workplace and their load in one month.

    Employees with no duty in the month are reported with zeroes rather
    than left out: "nothing yet" is exactly what the scheduler is looking
    for on this screen.
    """
    first = date(year, month, 1)
    last = date(year, month, monthrange(year, month)[1])

    employees = (
        db.query(User)
        .join(UserAmbulance, UserAmbulance.user_id == User.id)
        .filter(
            UserAmbulance.ambulance_id == ambulance_id,
            UserAmbulance.is_active.is_(True),
            User.is_active.is_(True),
        )
        .order_by(User.full_name, User.email)
        .all()
    )
    totals: dict[int, dict[str, float]] = {
        employee.id: {"shifts": 0, "surcharge": 0, "hours": 0.0}
        for employee in employees
    }
    days: dict[int, list[EmployeeDutyDay]] = {
        employee.id: [] for employee in employees
    }

    parameters = _slot_parameters(db, ambulance_id)
    rest_days = rest_days_between(db, ambulance_id, first, last)

    availability = _availability_counts(db, list(totals), first, last)

    competence_names = dict(
        db.query(Competence.id, Competence.name)
        .filter(Competence.ambulance_id == ambulance_id)
        .all()
    )

    shifts = (
        db.query(Schedule)
        .filter(
            Schedule.ambulance_id == ambulance_id,
            Schedule.is_active.is_(True),
            Schedule.work_date >= first,
            Schedule.work_date <= last,
        )
        .order_by(Schedule.work_date)
        .all()
    )
    for shift in shifts:
        bucket = totals.get(shift.user_id)
        if bucket is None:
            # Someone who worked the month but has since left the
            # workplace; the roster is what this screen is about.
            continue
        slot = (
            SPECIAL_DAY_SLOT
            if shift.work_date in rest_days
            else shift.work_date.weekday()
        )
        is_surcharge, hours = _parameters_for(parameters, shift.competence_id, slot)
        bucket["shifts"] += 1
        bucket["hours"] += hours
        if is_surcharge:
            bucket["surcharge"] += 1
        days[shift.user_id].append(
            EmployeeDutyDay(
                work_date=shift.work_date,
                competence_id=shift.competence_id,
                competence_name=competence_names.get(shift.competence_id),
                is_surcharge=is_surcharge,
                hours=hours,
            )
        )

    return AmbulanceMonthlyLoad(
        ambulance_id=ambulance_id,
        month=month,
        year=year,
        employees=[
            EmployeeMonthlyLoad(
                user_id=employee.id,
                email=employee.email,
                full_name=employee.full_name,
                shift_count=int(totals[employee.id]["shifts"]),
                surcharge_shift_count=int(totals[employee.id]["surcharge"]),
                total_hours=round(totals[employee.id]["hours"], 2),
                max_shifts_per_month=employee.max_shifts_per_month,
                shift_preference=employee.shift_preference or "any",
                days=days[employee.id],
                marked_days=availability[employee.id]["marked"],
                preferred_days=availability[employee.id]["preferred"],
                declined_days=availability[employee.id]["declined"],
                blocked_days=availability[employee.id]["blocked"],
            )
            for employee in employees
        ],
    )


def get_scheduling_settings(db: Session, user: User) -> EmployeeSchedulingSettings:
    """Read the duty wish and duty-kind preference of one employee."""
    return EmployeeSchedulingSettings(
        max_shifts_per_month=user.max_shifts_per_month,
        shift_preference=user.shift_preference or "any",
    )


def set_scheduling_settings(
    db: Session, user: User, data: EmployeeSchedulingSettings
) -> EmployeeSchedulingSettings:
    """Store both preferences of one employee; a null wish clears it."""
    user.max_shifts_per_month = data.max_shifts_per_month
    user.shift_preference = data.shift_preference
    commit_or_conflict(db, "Could not save the employee settings.")
    db.refresh(user)
    return get_scheduling_settings(db, user)
