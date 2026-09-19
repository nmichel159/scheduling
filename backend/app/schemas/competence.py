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

from pydantic import BaseModel, Field, field_validator

from app.models.competence import COMPETENCE_TYPES, DEFAULT_COMPETENCE_TYPE
from app.models.competence_weekday_requirement import (
    DEFAULT_RECOVERY_DAYS,
    DEFAULT_SHIFT_HOURS,
)


class CompetenceWeekdayRequirementData(BaseModel):
    """Parameters of one competence on one ISO weekday (Monday=0, Sunday=6).

    ``recovery_days`` is how many days off a duty started on this weekday
    costs its holder and ``shift_hours`` is how long that duty lasts; both
    default so that clients written against the staffing-only contract keep
    working unchanged.
    """

    weekday: int = Field(..., ge=0, le=6)
    required_count: int = Field(..., ge=0, le=1000)
    recovery_days: int = Field(
        DEFAULT_RECOVERY_DAYS,
        ge=0,
        le=6,
        description="Days off owed after a duty on this weekday.",
    )
    shift_hours: float = Field(
        DEFAULT_SHIFT_HOURS,
        ge=0,
        le=24,
        description="Hours a duty on this weekday lasts.",
    )

    class Config:
        from_attributes = True


def _validate_competence_type(value: str) -> str:
    """Reject types the application has no meaning for."""
    if value not in COMPETENCE_TYPES:
        raise ValueError(
            f"competence_type must be one of {', '.join(COMPETENCE_TYPES)}"
        )
    return value


def _validate_complete_weekday_requirements(
    requirements: list[CompetenceWeekdayRequirementData] | None,
) -> list[CompetenceWeekdayRequirementData] | None:
    """Require a complete, duplicate-free weekly definition when supplied."""
    if requirements is None:
        return None
    weekdays = [item.weekday for item in requirements]
    if len(weekdays) != 7 or set(weekdays) != set(range(7)):
        raise ValueError("weekday_requirements must contain each weekday 0 through 6 exactly once")
    return requirements


class CompetenceBase(BaseModel):
    """Shared fields between read and write operations."""

    name: str = Field(..., min_length=1, max_length=200, description="Name of the competence.")
    description: Optional[str] = Field(None, max_length=2000, description="Optional description of the competence.")
    required_count: int = Field(
        1,
        ge=0,
        le=1000,
        description="Legacy all-days worker count used when weekday requirements are absent.",
    )
    competence_type: str = Field(
        DEFAULT_COMPETENCE_TYPE,
        description="Kind of duty the competence stands for.",
    )
    weekday_requirements: Optional[list[CompetenceWeekdayRequirementData]] = Field(
        None,
        description="Optional complete Monday-to-Sunday staffing definition.",
    )

    @field_validator("competence_type")
    @classmethod
    def _known_competence_type(cls, value: str) -> str:
        return _validate_competence_type(value)

    _validate_weekdays = field_validator("weekday_requirements")(
        _validate_complete_weekday_requirements
    )


class CompetenceCreate(CompetenceBase):
    """Schema for creating a new competence record via POST."""

    pass


class CompetenceUpdate(BaseModel):
    """Schema for updating a competence record via PUT.

    All fields are optional to support partial updates.
    """

    name: Optional[str] = Field(None, min_length=1, max_length=200, description="Updated competence name.")
    description: Optional[str] = Field(None, max_length=2000, description="Updated competence description.")
    required_count: Optional[int] = Field(None, ge=0, le=1000, description="Updated legacy worker count.")
    competence_type: Optional[str] = Field(None, description="Updated competence type.")
    weekday_requirements: Optional[list[CompetenceWeekdayRequirementData]] = None

    @field_validator("competence_type")
    @classmethod
    def _known_competence_type(cls, value):
        return value if value is None else _validate_competence_type(value)

    _validate_weekdays = field_validator("weekday_requirements")(
        _validate_complete_weekday_requirements
    )


class CompetenceResponse(CompetenceBase):
    """Schema for serializing a competence record in API responses."""

    weekday_requirements: Optional[list[CompetenceWeekdayRequirementData]] = None
    id: int
    ambulance_id: int
    scenario_id: Optional[int] = Field(
        None, description="Scenario the returned weekday parameters belong to."
    )
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    is_active: Optional[bool] = None
    count: int

    @field_validator("weekday_requirements", mode="before")
    @classmethod
    def _empty_weekday_requirements_use_legacy_count(cls, requirements):
        """Serialize pre-migration rows through the legacy count contract.

        Some deployed databases can contain competences without the optional
        weekday child rows.  Returning ``None`` keeps that established state
        readable; clients already expand it to seven days from
        ``required_count``.  Non-empty definitions still pass through the
        complete-week validator inherited from :class:`CompetenceBase`.
        """
        if requirements is not None and len(requirements) == 0:
            return None
        return requirements

    class Config:
        from_attributes = True


class AmbulanceCompetenceGroup(BaseModel):
    ambulance_id: int
    ambulance_name: str
    ambulance_description: Optional[str] = None
    competences: list[CompetenceResponse]
