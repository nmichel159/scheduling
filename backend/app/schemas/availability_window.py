"""Shapes of the restriction window, the day limits and the month overview."""

from datetime import date, datetime
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, Field


class AvailabilityMonthStatus(BaseModel):
    """Whether one month is closed to the employees, and why."""

    year: int
    month: int
    locked: bool
    #: What the scheduler pressed by hand, ``None`` when the lock day decides.
    manual: Optional[bool] = None
    is_past: bool
    reminder_date: date
    lock_date: date
    reminder_sent_at: Optional[datetime] = None
    reminder_status: Optional[str] = None
    reminder_recipients: Optional[int] = None


class AvailabilityWindowDays(BaseModel):
    """The days of the previous month the reminder goes and the month closes."""

    reminder_day: int = Field(..., ge=1, le=27)
    lock_day: int = Field(..., ge=2, le=28)


class AvailabilityWindow(AvailabilityWindowDays):
    """The scheduler's settings with the month being filled in now."""

    upcoming: AvailabilityMonthStatus


class AvailabilityMonthLock(BaseModel):
    locked: bool


LimitedReason = Literal["VACATION", "BUSINESS_TRIP", "UNAVAILABLE"]


class AvailabilityDayLimits(BaseModel):
    """How many people may have each absence on one day; ``None`` is no limit."""

    limits: dict[LimitedReason, Optional[int]]


class AvailabilityDayLimitsUpdate(BaseModel):
    """Limits to store; a reason left out keeps its limit, ``None`` drops it."""

    limits: dict[LimitedReason, Optional[Annotated[int, Field(ge=0, le=1000)]]] = Field(
        default_factory=dict
    )


class AvailabilityDayCount(BaseModel):
    date: date
    #: Reason -> how many people entered it on this day.
    counts: dict[str, int]


class AvailabilityMonthOverview(AvailabilityDayLimits):
    year: int
    month: int
    #: Only the days somebody entered something on.
    days: list[AvailabilityDayCount]


class AvailabilityDayEntry(BaseModel):
    id: int
    user_id: int
    full_name: Optional[str] = None
    email: str
    workplaces: list[str]
    reason: str
    entered_at: Optional[datetime] = None
    entered_by_user_id: Optional[int] = None
    entered_by_name: Optional[str] = None


class AvailabilityDayDetail(AvailabilityDayLimits):
    date: date
    #: In the order they were entered.
    entries: list[AvailabilityDayEntry]
