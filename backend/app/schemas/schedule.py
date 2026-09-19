from datetime import date, datetime
from pydantic import BaseModel, Field, model_validator

class ScheduleCreate(BaseModel):
    ambulance_id: int
    competence_id: int
    work_date: date


class ScheduleEntry(BaseModel):
    """A schedule item with its employee, used by ambulance-wide updates."""
    user_id: int
    competence_id: int
    work_date: date


class ScheduleResponse(ScheduleEntry):
    id: int
    ambulance_id: int
    user_email: str | None = None
    user_full_name: str | None = None
    competence_name: str | None = None
    is_approved: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None
    class Config:
        from_attributes = True


class GeneratedScheduleEntry(ScheduleEntry):
    """An unsaved optimized assignment returned for manager review."""

    ambulance_id: int
    user_email: str
    user_full_name: str | None = None
    competence_name: str


class ScheduleGenerationRequest(BaseModel):
    """What the solver must keep, and from which date it may fill the month.

    ``fixed_entries`` are the duties already placed in the editor; the solver
    keeps every one of them and plans around them. ``generate_from`` is the
    first date it may touch, so a month that is already partly worked can be
    regenerated from tomorrow onwards without rewriting its past.
    """

    fixed_entries: list[ScheduleEntry] = Field(default_factory=list, max_length=20000)
    generate_from: date | None = None


class ScheduleGenerationResponse(BaseModel):
    """Complete unsaved monthly schedule draft produced by the MILP solver."""

    month: int
    year: int
    assignment_count: int
    entries: list[GeneratedScheduleEntry]


class ScheduleApprovalResponse(BaseModel):
    """Approval state for one ambulance schedule package and calendar month."""

    ambulance_id: int
    month: int
    year: int
    is_approved: bool
    approved_entry_count: int


class AmbulanceScheduleStatus(BaseModel):
    """Publication state of one ambulance's schedule for one calendar month.

    `shift_count` of 0 means the month was never generated or saved.
    `is_approved` is true only when the package holds shifts and every one of
    them is published, which is the same rule the editor applies locally.
    """

    ambulance_id: int
    ambulance_name: str
    manager_full_name: str | None = None
    manager_email: str | None = None
    shift_count: int
    approved_shift_count: int
    is_approved: bool


class MonthlyScheduleOverview(BaseModel):
    """Every active ambulance and where its schedule stands in one month."""

    month: int
    year: int
    ambulances: list[AmbulanceScheduleStatus]


class NextScheduleResponse(BaseModel):
    """The authenticated user's nearest scheduled duty, if one exists."""
    next_shift: ScheduleResponse | None = None


class MonthlyScheduleStatistics(BaseModel):
    """Number of duties planned for the current calendar month."""
    month: int
    year: int
    scheduled_shift_count: int


class WorkedScheduleStatistics(BaseModel):
    """Number of distinct current-month work days whose date has already arrived."""
    month: int
    year: int
    through_date: date
    worked_day_count: int

class ScheduleUpdate(BaseModel):
    entries: list[ScheduleEntry] = Field(max_length=20000)


class ScheduleEdit(BaseModel):
    competence_id: int | None = None
    work_date: date | None = None
    is_active: bool | None = None


class MonthlyScheduleSave(BaseModel):
    user_id: int
    month: int = Field(ge=1, le=12)
    year: int = Field(ge=2000, le=2100)
    entries: list[ScheduleCreate] = Field(default_factory=list, max_length=20000)

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
