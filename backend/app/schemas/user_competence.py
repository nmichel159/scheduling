"""
Pydantic schemas for User Competence Assignment.

Used by ambulance managers to assign and remove competences
from employees working in their ambulances.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class UserCompetenceAssign(BaseModel):
    """Schema for assigning a competence to an employee."""

    competence_id: int = Field(..., description="ID of the competence to assign.")


class UserCompetenceResponse(BaseModel):
    """Schema for serializing a user-competence assignment."""

    user_id: int
    competence_id: int
    competence_name: Optional[str] = None
    created_at: Optional[datetime] = None
    is_active: Optional[bool] = None

    class Config:
        from_attributes = True
