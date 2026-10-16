"""Shapes of the restriction window: its two days and one month's state."""

from datetime import date, datetime
from typing import Optional

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
