"""Schemas for the ambulance employee/competence table."""

from pydantic import BaseModel


class CompetenceTableItem(BaseModel):
    id: int
    name: str


class AmbulanceEmployeeCompetenceRow(BaseModel):
    user_id: int
    email: str
    full_name: str | None = None
    competences: list[CompetenceTableItem] = []


class AmbulanceEmployeeCompetenceUpdate(BaseModel):
    user_id: int
    competence_ids: list[int] = []


class AmbulanceEmployeeCompetenceTableUpdate(BaseModel):
    employees: list[AmbulanceEmployeeCompetenceUpdate]
