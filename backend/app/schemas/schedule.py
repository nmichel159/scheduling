from datetime import date, datetime
from pydantic import BaseModel, Field, model_validator

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


class ScheduleCreate(ScheduleEntry):
    ambulance_id: int


class ScheduleEdit(BaseModel):
    competence_id: int | None = None
    work_date: date | None = None
    is_active: bool | None = None


class MonthlyScheduleSave(BaseModel):
    user_id: int
    month: int = Field(ge=1, le=12)
    year: int = Field(ge=2000, le=2100)
    entries: list[ScheduleCreate] = Field(default_factory=list)

    @model_validator(mode="after")
    def entries_must_belong_to_month(self):
        if any(entry.work_date.month != self.month or entry.work_date.year != self.year for entry in self.entries):
            raise ValueError("Every schedule entry must belong to the supplied month and year.")
        return self


class UserMonthlySchedule(BaseModel):
    user_id: int
    user_full_name: str | None = None
    month: int
    year: int
    entries: list[ScheduleResponse]
