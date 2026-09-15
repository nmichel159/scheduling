"""Hospital-wide reporting aggregates (role level >= 4).

Everything here is read-only and expressed as grouped SQL: the reports must
not grow more expensive as the schedules do, so no endpoint in this module
loads individual schedule rows into Python.
"""

from datetime import date, timedelta

from sqlalchemy import case, extract, func
from sqlalchemy.orm import Session

from app.models.ambulance import Ambulance
from app.models.schedule import Schedule
from app.models.user import User
from app.schemas.statistics import (
    EmployeeYearStatistics,
    MonthShiftCount,
    WorkplaceYearStatistics,
    YearlyStatistics,
)

MONTHS_IN_YEAR = 12

#: How many employees the yearly report ranks by duty count.
TOP_EMPLOYEE_LIMIT = 15


def year_range(year: int) -> tuple[date, date]:
    """First and last calendar day of `year`."""
    return date(year, 1, 1), date(year, 12, 31)


def _through_date(year: int, today: date) -> date:
    """The day the "worked so far" figures are counted through.

    Clamped to the reported year so a finished year always reports its own
    last day -- a closed year's totals never drift -- and a year that has not
    started yet reports the day before it began, which no duty in the year can
    fall on or before. That keeps one comparison valid for all three cases
    instead of special-casing the query.
    """
    start, end = year_range(year)
    if today < start:
        return start - timedelta(days=1)
    return min(today, end)


def _worked_count(through: date):
    """SQL expression counting only duties dated on or before `through`.

    count() ignores NULLs, so an else-less CASE counts exactly the matching
    rows and no second query is needed for the "so far" half of each total.
    """
    return func.count(case((Schedule.work_date <= through, 1)))


def get_yearly_statistics(
    db: Session,
    year: int,
    today: date | None = None,
) -> YearlyStatistics:
    """Report one calendar year across every active ambulance.

    Counts duties, staffed days and people -- not hours. A schedule row has a
    date but no duration, so hours are not derivable from the data model; see
    the note in app/schemas/statistics.py.

    Args:
        db: Active database session.
        year: Calendar year to report.
        today: Reference day for the "worked so far" figures; defaults to the
            current date. Injectable so tests are not time-dependent.

    Returns:
        Hospital totals, a twelve-entry monthly series, one row per active
        ambulance ordered by name, and the busiest employees.
    """
    reference_day = today or date.today()
    start, end = year_range(year)
    through = _through_date(year, reference_day)
    in_year = (
        Schedule.work_date.between(start, end),
        Schedule.is_active.is_(True),
    )
    worked = _worked_count(through)

    per_ambulance = {
        row[0]: row
        for row in db.query(
            Schedule.ambulance_id,
            func.count(Schedule.id),
            worked,
            func.count(case((Schedule.is_approved.is_(True), 1))),
            func.count(func.distinct(Schedule.work_date)),
            func.count(func.distinct(Schedule.user_id)),
        )
        .filter(*in_year)
        .group_by(Schedule.ambulance_id)
        .all()
    }

    ambulances = (
        db.query(Ambulance)
        .filter(Ambulance.is_active.is_(True))
        .order_by(Ambulance.name)
        .all()
    )
    workplaces = []
    for ambulance in ambulances:
        row = per_ambulance.get(ambulance.id)
        workplaces.append(
            WorkplaceYearStatistics(
                ambulance_id=ambulance.id,
                ambulance_name=ambulance.name,
                shift_count=row[1] if row else 0,
                worked_shift_count=row[2] if row else 0,
                approved_shift_count=row[3] if row else 0,
                covered_day_count=row[4] if row else 0,
                employee_count=row[5] if row else 0,
            )
        )

    counts_by_month = {
        int(month): (shift_count, worked_count)
        for month, shift_count, worked_count in db.query(
            extract("month", Schedule.work_date),
            func.count(Schedule.id),
            worked,
        )
        .filter(*in_year)
        .group_by(extract("month", Schedule.work_date))
        .all()
    }
    by_month = [
        MonthShiftCount(
            month=month,
            shift_count=counts_by_month.get(month, (0, 0))[0],
            worked_shift_count=counts_by_month.get(month, (0, 0))[1],
        )
        for month in range(1, MONTHS_IN_YEAR + 1)
    ]

    employees = [
        EmployeeYearStatistics(
            user_id=user_id,
            full_name=full_name,
            email=email,
            shift_count=shift_count,
            worked_shift_count=worked_count,
            ambulance_count=ambulance_count,
        )
        for user_id, full_name, email, shift_count, worked_count, ambulance_count in (
            db.query(
                User.id,
                User.full_name,
                User.email,
                func.count(Schedule.id).label("shift_count"),
                worked,
                func.count(func.distinct(Schedule.ambulance_id)),
            )
            .join(Schedule, Schedule.user_id == User.id)
            .filter(*in_year, User.is_active.is_(True))
            .group_by(User.id, User.full_name, User.email)
            # Name breaks ties so the ranking is stable between calls rather
            # than left to the database's row order.
            .order_by(func.count(Schedule.id).desc(), User.full_name)
            .limit(TOP_EMPLOYEE_LIMIT)
            .all()
        )
    ]

    totals = db.query(
        func.count(Schedule.id),
        worked,
        func.count(case((Schedule.is_approved.is_(True), 1))),
        func.count(func.distinct(Schedule.user_id)),
    ).filter(*in_year).one()

    return YearlyStatistics(
        year=year,
        through_date=through.isoformat(),
        total_shift_count=totals[0],
        worked_shift_count=totals[1],
        approved_shift_count=totals[2],
        workplace_count=len(ambulances),
        staffed_workplace_count=sum(1 for item in workplaces if item.shift_count > 0),
        employee_count=totals[3],
        by_month=by_month,
        workplaces=workplaces,
        employees=employees,
    )
