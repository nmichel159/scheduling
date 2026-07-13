"""
Pydantic schemas for the User Availability (Unavailability) domain.

Implements the mandatory 4-schema lifecycle pattern:
- UnavailabilityBase: Shared fields for read/write.
- UnavailabilityCreate: Fields required for creation.
- UnavailabilityUpdate: All-optional fields for partial updates.
- UnavailabilityResponse: Serialization schema returned to the frontend.

Additionally provides schemas for the monthly week-pattern bulk fill:
- PatternDay / ApplyPatternRequest / ApplyPatternResponse.
"""

from datetime import date, datetime, time
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class UnavailabilityBase(BaseModel):
    """Shared fields between read and write operations."""

    date_absent: date = Field(..., description="The date the user is unavailable.")
    start_time: Optional[time] = Field(
        None, description="Start of the unavailability window. NULL together with end_time means all day."
    )
    end_time: Optional[time] = Field(
        None, description="End of the unavailability window. NULL together with start_time means all day."
    )
    reason: Optional[str] = Field(None, description="Optional reason for unavailability.")

    @model_validator(mode="after")
    def validate_time_window(self) -> "UnavailabilityBase":
        """Ensure the time window is either fully set and ordered, or fully empty."""
        if (self.start_time is None) != (self.end_time is None):
            raise ValueError("start_time and end_time must be provided together or both omitted.")
        if self.start_time is not None and self.start_time >= self.end_time:
            raise ValueError("start_time must be earlier than end_time.")
        return self


class UnavailabilityCreate(UnavailabilityBase):
    """Schema for creating a new unavailability record via POST."""

    pass


class UnavailabilityUpdate(BaseModel):
    """Schema for updating an unavailability record via PUT.

    All fields are optional to support partial updates. Time-window
    consistency for partial updates is validated in the service layer,
    where the existing record values are known.
    """

    date_absent: Optional[date] = Field(None, description="Updated absence date.")
    start_time: Optional[time] = Field(None, description="Updated window start.")
    end_time: Optional[time] = Field(None, description="Updated window end.")
    clear_times: bool = Field(
        False, description="Set to true to clear the time window (mark as all-day absence)."
    )
    reason: Optional[str] = Field(None, description="Updated reason for unavailability.")


class UnavailabilityResponse(UnavailabilityBase):
    """Schema for serializing an unavailability record in API responses."""

    id: int
    user_id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    is_active: Optional[bool] = None

    class Config:
        from_attributes = True


class PatternDay(BaseModel):
    """A single weekday entry of the repeating week pattern."""

    weekday: int = Field(..., ge=0, le=6, description="ISO weekday index: 0=Monday ... 6=Sunday.")
    start_time: time = Field(..., description="Window start applied to matching days.")
    end_time: time = Field(..., description="Window end applied to matching days.")

    @model_validator(mode="after")
    def validate_order(self) -> "PatternDay":
        """Ensure the pattern window is ordered."""
        if self.start_time >= self.end_time:
            raise ValueError("start_time must be earlier than end_time.")
        return self


class ApplyPatternRequest(BaseModel):
    """Request payload for applying a week pattern to a whole month."""

    year: int = Field(..., ge=2000, le=2100, description="Target year.")
    month: int = Field(..., ge=1, le=12, description="Target month (1-12).")
    overwrite: bool = Field(
        False, description="If true, existing records on matching days are updated; otherwise skipped."
    )
    pattern: list[PatternDay] = Field(..., min_length=1, description="Weekday pattern entries.")

    @model_validator(mode="after")
    def validate_unique_weekdays(self) -> "ApplyPatternRequest":
        """Reject duplicate weekday entries in the pattern."""
        weekdays = [p.weekday for p in self.pattern]
        if len(weekdays) != len(set(weekdays)):
            raise ValueError("Duplicate weekday entries in pattern.")
        return self


class ApplyPatternResponse(BaseModel):
    """Summary of a bulk pattern application."""

    created: int
    updated: int
    skipped: int
