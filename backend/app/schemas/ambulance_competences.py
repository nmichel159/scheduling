"""Schemas for the ambulance employee/competence table."""

from pydantic import BaseModel, Field


class CompetenceTableItem(BaseModel):
    id: int
    name: str


class AmbulanceEmployeeCompetenceRow(BaseModel):
    user_id: int
    email: str
    full_name: str | None = None
    competences: list[CompetenceTableItem] = Field(default_factory=list)


class AmbulanceEmployeeCompetenceUpdate(BaseModel):
    user_id: int = Field(ge=1)
    competence_ids: list[int] = Field(default_factory=list, max_length=200)


class AmbulanceEmployeeCompetenceTableUpdate(BaseModel):
    employees: list[AmbulanceEmployeeCompetenceUpdate] = Field(max_length=2000)
