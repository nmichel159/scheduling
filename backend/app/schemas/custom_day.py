"""Pydantic schemas for custom days and the month's staffing overview."""

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.models.competence_weekday_requirement import (
    DEFAULT_RECOVERY_DAYS,
    DEFAULT_SHIFT_HOURS,
)


class CustomDayRequirementData(BaseModel):
    """What one competence needs on a custom day."""

    competence_id: int
    required_count: int = Field(0, ge=0, le=1000)
    recovery_days: int = Field(DEFAULT_RECOVERY_DAYS, ge=0, le=6)
    shift_hours: float = Field(DEFAULT_SHIFT_HOURS, ge=0, le=24)
    is_surcharge: bool = False


class CustomDayCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    requirements: Optional[list[CustomDayRequirementData]] = None


class CustomDayUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=80)
    requirements: Optional[list[CustomDayRequirementData]] = None


class CustomDayResponse(BaseModel):
    """A custom day with an answer for every active competence."""

    id: int
    ambulance_id: int
    name: str
    requirements: list[CustomDayRequirementData]
    date_count: int = 0


class CustomDayDateWrite(BaseModel):
    """Staff ``day`` as ``custom_day_id``, or by the calendar when null."""

    day: date
    custom_day_id: Optional[int] = None


class DayNeed(BaseModel):
    """What one competence needs on one date."""

    competence_id: int
    required_count: int
    shift_hours: float
    recovery_days: int
    is_surcharge: bool


class MonthDay(BaseModel):
    """One date of the month and what it is staffed as.

    ``kind`` is ``weekday`` for an ordinary date, ``rest`` for a day of rest
    staffed from the special-day slot and ``custom`` for a date placed on a
    custom day, which outranks the other two.
    """

    day: date
    kind: Literal["weekday", "rest", "custom"]
    is_rest_day: bool
    custom_day_id: Optional[int] = None
    needs: list[DayNeed]


class MonthNeeds(BaseModel):
    ambulance_id: int
    scenario_id: int
    year: int
    month: int
    days: list[MonthDay]
