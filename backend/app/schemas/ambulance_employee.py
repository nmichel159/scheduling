"""
Pydantic schemas for Ambulance Employee Management.

Used by ambulance managers (Role Level >= 2) to add, remove,
and list employees assigned to their ambulances.
"""

from datetime import date, datetime
from typing import Literal, Optional

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


class AmbulanceListResponse(BaseModel):
    """Lightweight schema for listing ambulances related to a user."""

    id: int
    name: str
    description: Optional[str] = None
    managed_by_user_id: Optional[int] = None
    isurgent: bool = False

    class Config:
        from_attributes = True


#: The three answers an employee can give to "which duties suit you".
#: ``any`` is the default: no opinion, which is not the same as either
#: of the other two.
SHIFT_PREFERENCES = ("surcharge", "standard", "any")


class EmployeeSchedulingSettings(BaseModel):
    """What the scheduler may set on one employee.

    Both fields are the employee's own preferences rather than properties
    of a workplace; the manager edits them here because the scheduler is
    usually the one who hears them.
    """

    max_shifts_per_month: Optional[int] = Field(
        None,
        ge=0,
        le=31,
        description="Preferred maximum number of duties per month; null means no opinion.",
    )
    shift_preference: Literal["surcharge", "standard", "any"] = Field(
        "any",
        description="Which kind of duty the employee would rather be given.",
    )


class EmployeeDutyDay(BaseModel):
    """One duty of one employee, with what it is worth."""

    work_date: date
    competence_id: int
    competence_name: Optional[str] = None
    is_surcharge: bool = False
    hours: float = 0.0


class EmployeeMonthlyLoad(BaseModel):
    """One employee's duties in one month of one workplace.

    ``surcharge_shift_count`` counts the duties whose weekday slot is paid
    with a surcharge in the workplace's selected scenario; a day of rest is
    read from the special-day slot rather than from its calendar weekday,
    the same way the generator staffs it.
    """

    user_id: int
    email: str
    full_name: Optional[str] = None
    shift_count: int
    surcharge_shift_count: int
    total_hours: float
    max_shifts_per_month: Optional[int] = None
    shift_preference: str = "any"
    days: list[EmployeeDutyDay] = Field(default_factory=list)

    # How the employee filled their availability calendar for this month.
    # ``marked_days`` counts every day they had an opinion about; the three
    # figures under it split those days by what the opinion was, and add up
    # to it. A month left untouched reports zeroes, which is what the
    # scheduler needs to see before chasing anyone by e-mail.
    marked_days: int = 0
    preferred_days: int = 0
    declined_days: int = 0
    blocked_days: int = 0


class AmbulanceMonthlyLoad(BaseModel):
    """Every employee of a workplace and their load in one month."""

    ambulance_id: int
    month: int
    year: int
    employees: list[EmployeeMonthlyLoad]
