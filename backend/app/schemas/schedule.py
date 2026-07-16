from datetime import date, datetime
from pydantic import BaseModel

class ScheduleEntry(BaseModel):
    user_id: int
    competence_id: int
    work_date: date

class ScheduleResponse(ScheduleEntry):
    id: int
    ambulance_id: int
    user_email: str | None = None
    user_full_name: str | None = None
    competence_name: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    class Config:
        from_attributes = True

class ScheduleUpdate(BaseModel):
    entries: list[ScheduleEntry]
