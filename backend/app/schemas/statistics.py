"""Read-only hospital-wide reporting payloads (role level >= 4).

These schemas describe aggregates, not resources, so the usual
Create/Update/Response quartet does not apply: nothing here is ever written
back, and every model is a response shape only.

On duty length: a schedule row records who works which competence on which
date, and nothing in the data model says how long that duty lasts, so these
reports count duties and days rather than hours. Competences whose *name*
carries a time range ("15:00-19:00") do not make that machine-readable. Real
hour totals need a duration field on Competence first.
"""

from pydantic import BaseModel


class WorkplaceYearStatistics(BaseModel):
    """One ambulance's load over a calendar year."""

    ambulance_id: int
    ambulance_name: str
    # Every duty dated in the year, whether it has already happened or not.
    shift_count: int
    # The subset dated today or earlier -- what was actually worked so far.
    worked_shift_count: int
    # Distinct people who hold at least one duty here this year.
    employee_count: int


class MonthShiftCount(BaseModel):
    """Duties dated in one month of the reported year."""

    month: int
    shift_count: int
    worked_shift_count: int


class EmployeeYearStatistics(BaseModel):
    """One employee's duty load over a calendar year."""

    user_id: int
    full_name: str | None = None
    email: str
    shift_count: int
    worked_shift_count: int
    ambulance_count: int


class YearlyStatistics(BaseModel):
    """Hospital-wide report for one calendar year."""

    year: int
    # The day the "worked so far" figures are counted through. Equal to the
    # last day of the year once the year is over, so a closed year reports a
    # stable number.
    through_date: str
    total_shift_count: int
    worked_shift_count: int
    # Active ambulances, and how many of them have at least one duty planned.
    workplace_count: int
    staffed_workplace_count: int
    # Reported although no tile shows it on its own: it is the denominator of
    # the duties-per-person average.
    employee_count: int
    # Always twelve entries, months without duties included, so the caller can
    # chart the year without filling gaps itself.
    by_month: list[MonthShiftCount]
    workplaces: list[WorkplaceYearStatistics]
    # Busiest employees first, already capped by the service.
    employees: list[EmployeeYearStatistics]
