"""What the planner checks a month against, besides the duties on it.

The workplace planner holds every duty of the month, every employee and
every competence of the workplace; from those alone it sees who serves
without the qualification, who holds two roles in a day and which duties
break the rest this workplace configured. What it cannot see is read here,
the same way :mod:`app.services.schedule_generation_service` reads it for
the solver:

* the days each employee marked as an absence or as "rather not",
* the duties they serve at other workplaces around the month, and the ones
  at this workplace just outside it, each with the rest it earns, and
* how many duties a month they asked for.
"""

from calendar import monthrange
from datetime import date, timedelta

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.ambulance import Ambulance
from app.models.associations import UserAmbulance
from app.models.competence import Competence
from app.models.schedule import Schedule
from app.models.unavailability import Unavailability
from app.models.user import User
from app.schemas.schedule import (
    EmployeeScheduleContext,
    ScheduleContextDuty,
    ScheduleContextMark,
    ScheduleContextResponse,
)
from app.services.schedule_generation_service import (
    PREFERRED_UNAVAILABILITY_REASON,
    REST_CALENDAR_MARGIN_DAYS,
    foreign_recovery_reader,
)

#: What a mark with no reason means. Older records were written without
#: one, and they were absences.
DEFAULT_ABSENCE_REASON = "UNAVAILABLE"


def get_schedule_context(
    db: Session, ambulance_id: int, month: int, year: int
) -> ScheduleContextResponse:
    """Report, per active employee, what the month's duties must respect."""
    first = date(year, month, 1)
    last = date(year, month, monthrange(year, month)[1])
    margin = timedelta(days=REST_CALENDAR_MARGIN_DAYS)

    employees = (
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
    user_ids = [employee.id for employee in employees]
    marks: dict[int, list[ScheduleContextMark]] = {user_id: [] for user_id in user_ids}
    duties: dict[int, list[ScheduleContextDuty]] = {user_id: [] for user_id in user_ids}

    if user_ids:
        mark_rows = (
            db.query(
                Unavailability.user_id,
                Unavailability.date_absent,
                Unavailability.reason,
            )
            .filter(
                Unavailability.user_id.in_(user_ids),
                Unavailability.date_absent.between(first, last),
                Unavailability.is_active.is_(True),
            )
            .order_by(Unavailability.date_absent)
            .all()
        )
        for user_id, marked_date, reason in mark_rows:
            normalized = (reason or "").strip().upper() or DEFAULT_ABSENCE_REASON
            if normalized == PREFERRED_UNAVAILABILITY_REASON:
                continue
            marks[user_id].append(
                ScheduleContextMark(work_date=marked_date, reason=normalized)
            )

        # A long rest reaches up to a week, so duties that far either side of
        # the month still matter. At this workplace only the ones outside the
        # month are read: the planner already holds the month itself, and
        # holds it as edited rather than as saved.
        duty_rows = (
            db.query(
                Schedule.user_id,
                Schedule.ambulance_id,
                Schedule.competence_id,
                Schedule.work_date,
                Ambulance.name,
                Competence.name,
            )
            .join(Ambulance, Ambulance.id == Schedule.ambulance_id)
            .join(Competence, Competence.id == Schedule.competence_id)
            .filter(
                Schedule.user_id.in_(user_ids),
                Schedule.is_active.is_(True),
                Schedule.work_date.between(first - margin, last + margin),
                or_(
                    Schedule.ambulance_id != ambulance_id,
                    ~Schedule.work_date.between(first, last),
                ),
            )
            .order_by(Schedule.work_date, Schedule.ambulance_id)
            .all()
        )
        recovery_days = foreign_recovery_reader(
            db,
            {row[1] for row in duty_rows},
            first - margin,
            last + margin,
        )
        for (
            user_id,
            duty_ambulance_id,
            competence_id,
            work_date,
            ambulance_name,
            competence_name,
        ) in duty_rows:
            duties[user_id].append(
                ScheduleContextDuty(
                    work_date=work_date,
                    ambulance_id=duty_ambulance_id,
                    ambulance_name=ambulance_name,
                    competence_id=competence_id,
                    competence_name=competence_name,
                    recovery_days=recovery_days(
                        duty_ambulance_id, competence_id, work_date
                    ),
                )
            )

    return ScheduleContextResponse(
        ambulance_id=ambulance_id,
        month=month,
        year=year,
        employees=[
            EmployeeScheduleContext(
                user_id=employee.id,
                max_shifts_per_month=employee.max_shifts_per_month,
                marks=marks[employee.id],
                duties=duties[employee.id],
            )
            for employee in employees
        ],
    )
