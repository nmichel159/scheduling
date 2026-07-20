"""
Pydantic schemas for the Competence domain (codebook CRUD).

Implements the mandatory 4-schema lifecycle pattern:
- CompetenceBase: Shared fields for read/write.
- CompetenceCreate: Fields required for creation.
- CompetenceUpdate: All-optional fields for partial updates.
- CompetenceResponse: Serialization schema returned to the frontend.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class CompetenceBase(BaseModel):
    """Shared fields between read and write operations."""

    name: str = Field(..., description="Name of the competence.")
    description: Optional[str] = Field(None, description="Optional description of the competence.")
    required_count: int = Field(1, ge=1, description="Required number of workers for this competence.")


class CompetenceCreate(CompetenceBase):
    """Schema for creating a new competence record via POST."""

    pass


class CompetenceUpdate(BaseModel):
    """Schema for updating a competence record via PUT.

    All fields are optional to support partial updates.
    """

    name: Optional[str] = Field(None, description="Updated competence name.")
    description: Optional[str] = Field(None, description="Updated competence description.")
    required_count: Optional[int] = Field(None, ge=1, description="Updated required worker count.")


class CompetenceResponse(CompetenceBase):
    """Schema for serializing a competence record in API responses."""

    id: int
    ambulance_id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    is_active: Optional[bool] = None
    count: int

    class Config:
        from_attributes = True


class AmbulanceCompetenceGroup(BaseModel):
    ambulance_id: int
    ambulance_name: str
    ambulance_description: Optional[str] = None
    competences: list[CompetenceResponse]
