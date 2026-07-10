"""
Pydantic schemas for Ambulance Employee Management.

Used by ambulance managers (Role Level >= 2) to add, remove,
and list employees assigned to their ambulances.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class AmbulanceEmployeeAdd(BaseModel):
    """Schema for adding an employee to an ambulance."""

    user_id: int = Field(..., description="ID of the user to assign to the ambulance.")


class AmbulanceEmployeeResponse(BaseModel):
    """Schema for serializing an ambulance-employee assignment."""

    user_id: int
    ambulance_id: int
    created_at: Optional[datetime] = None
    is_active: Optional[bool] = None

    class Config:
        from_attributes = True


class EmployeeListResponse(BaseModel):
    """Lightweight schema for listing employees assigned to an ambulance."""

    user_id: int
    email: str
    full_name: Optional[str] = None

    class Config:
        from_attributes = True
