"""
Pydantic schemas for the User Availability (Unavailability) domain.

Implements the mandatory 4-schema lifecycle pattern:
- UnavailabilityBase: Shared fields for read/write.
- UnavailabilityCreate: Fields required for creation.
- UnavailabilityUpdate: All-optional fields for partial updates.
- UnavailabilityResponse: Serialization schema returned to the frontend.
"""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


class UnavailabilityBase(BaseModel):
    """Shared fields between read and write operations."""

    date_absent: date = Field(..., description="The date the user is unavailable.")
    reason: Optional[str] = Field(None, description="Optional reason for unavailability.")


class UnavailabilityCreate(UnavailabilityBase):
    """Schema for creating a new unavailability record via POST."""

    pass


class UnavailabilityUpdate(BaseModel):
    """Schema for updating an unavailability record via PUT.

    All fields are optional to support partial updates.
    """

    date_absent: Optional[date] = Field(None, description="Updated absence date.")
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
