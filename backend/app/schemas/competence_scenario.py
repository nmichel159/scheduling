"""
Pydantic schemas for the competence scenario domain.

A scenario is a named parameter set over the workplace's competences. The
competence list itself is shared by every scenario of the workplace; only
the per-weekday counts and recovery days differ between them.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class CompetenceScenarioBase(BaseModel):
    """Shared fields between read and write operations."""

    name: str = Field(..., min_length=1, max_length=200, description="Name of the scenario.")


class CompetenceScenarioCreate(CompetenceScenarioBase):
    """Schema for creating a scenario via POST.

    ``copy_from_scenario_id`` seeds the new scenario with another scenario's
    parameters instead of the defaults (one person per day, one recovery day).
    """

    copy_from_scenario_id: Optional[int] = Field(
        None, description="Scenario whose parameters the new one starts from."
    )


class CompetenceScenarioUpdate(BaseModel):
    """Schema for updating a scenario via PUT. All fields are optional."""

    name: Optional[str] = Field(None, min_length=1, max_length=200)
    is_selected: Optional[bool] = Field(
        None,
        description="Set to true to make this the scenario the application reads.",
    )


class CompetenceScenarioResponse(CompetenceScenarioBase):
    """Schema for serializing a scenario in API responses."""

    id: int
    ambulance_id: int
    is_selected: bool
    competence_count: int = Field(
        0, description="Number of active competences this scenario parameterizes."
    )
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    is_active: Optional[bool] = None

    class Config:
        from_attributes = True
