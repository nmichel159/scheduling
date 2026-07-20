from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_manager_ambulance, require_manager_role
from app.db.session import get_db
from app.models.ambulance import Ambulance
from app.models.associations import UserAmbulance
from app.models.schedule import Schedule
from app.models.user import User
from app.schemas.schedule import MonthlyScheduleSave, ScheduleCreate, ScheduleEdit, ScheduleResponse, ScheduleUpdate, UserMonthlySchedule
from app.services.schedule_service import create_schedule, deactivate_schedule, get_ambulance_schedule, get_user_schedule, save_monthly_schedule, update_schedule

router = APIRouter()
ambulance_router = APIRouter()


def _is_admin(user: User) -> bool:
    return any(item.role and item.role.is_active and item.role.level >= 3 for item in user.user_roles)


def _can_manage_user(current_user: User, db: Session, user_id: int, ambulance_id: int | None = None) -> None:
    if _is_admin(current_user):
        return
    query = db.query(UserAmbulance).join(Ambulance).filter(UserAmbulance.user_id == user_id, UserAmbulance.is_active.is_(True), Ambulance.managed_by_user_id == current_user.id, Ambulance.is_active.is_(True))
    if ambulance_id is not None:
        query = query.filter(Ambulance.id == ambulance_id)
    if not query.first():
        raise HTTPException(status_code=403, detail="You may manage schedules only in ambulances you manage.")


@router.get("/me", response_model=list[ScheduleResponse])
def get_my_schedule(month: int | None = None, year: int | None = None, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return get_user_schedule(db, current_user.id, month, year)


@router.get("/user/{user_id}", response_model=list[ScheduleResponse])
def get_user_schedule_endpoint(user_id: int, month: int | None = None, year: int | None = None, current_user: User = Depends(require_manager_role), db: Session = Depends(get_db)):
    _can_manage_user(current_user, db, user_id)
    return get_user_schedule(db, user_id, month, year)


@router.post("", response_model=ScheduleResponse, status_code=status.HTTP_201_CREATED)
def create_schedule_endpoint(user_id: int, data: ScheduleCreate, current_user: User = Depends(require_manager_role), db: Session = Depends(get_db)):
    _can_manage_user(current_user, db, user_id, data.ambulance_id)
    return create_schedule(db, user_id, data)


@router.put("/entries/{schedule_id}", response_model=ScheduleResponse)
def update_schedule_endpoint(schedule_id: int, data: ScheduleEdit, current_user: User = Depends(require_manager_role), db: Session = Depends(get_db)):
    item = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Schedule entry not found.")
    _can_manage_user(current_user, db, item.user_id, item.ambulance_id)
    return update_schedule(db, item, data)


@router.delete("/entries/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_schedule_endpoint(schedule_id: int, current_user: User = Depends(require_manager_role), db: Session = Depends(get_db)):
    item = db.query(Schedule).filter(Schedule.id == schedule_id, Schedule.is_active.is_(True)).first()
    if not item:
        raise HTTPException(status_code=404, detail="Active schedule entry not found.")
    _can_manage_user(current_user, db, item.user_id, item.ambulance_id)
    deactivate_schedule(db, item)


@router.put("/monthly", response_model=list[ScheduleResponse])
def save_monthly_schedule_endpoint(data: MonthlyScheduleSave, current_user: User = Depends(require_manager_role), db: Session = Depends(get_db)):
    for entry in data.entries:
        _can_manage_user(current_user, db, data.user_id, entry.ambulance_id)
    # The synchronization also deactivates omitted entries. A manager must
    # therefore be authorized for every existing entry that can be affected.
    existing = get_user_schedule(db, data.user_id, data.month, data.year)
    for entry in existing:
        _can_manage_user(current_user, db, data.user_id, entry.ambulance_id)
    return save_monthly_schedule(db, data.user_id, data.month, data.year, data.entries)


@ambulance_router.get("/{ambulance_id}/schedule", response_model=list[UserMonthlySchedule])
def get_ambulance_schedule_endpoint(ambulance: Ambulance = Depends(get_manager_ambulance), month: int | None = None, year: int | None = None, db: Session = Depends(get_db)):
    displayed_month, displayed_year = (month, year) if month is not None and year is not None else (date.today().month, date.today().year)
    employees = db.query(UserAmbulance).filter(UserAmbulance.ambulance_id == ambulance.id, UserAmbulance.is_active.is_(True)).all()
    return [UserMonthlySchedule(user_id=item.user_id, user_full_name=item.user.full_name if item.user else None, month=displayed_month, year=displayed_year, entries=get_user_schedule(db, item.user_id, displayed_month, displayed_year)) for item in employees if item.user and item.user.is_active]


@ambulance_router.put("/{ambulance_id}/schedule", response_model=list[ScheduleResponse])
def update_ambulance_schedule_endpoint(data: ScheduleUpdate, ambulance: Ambulance = Depends(get_manager_ambulance), month: int | None = None, year: int | None = None, db: Session = Depends(get_db)):
    """Legacy bulk endpoint scoped to an ambulance; retained for frontend compatibility."""
    for entry in data.entries:
        if entry.work_date.month != (month or date.today().month) or entry.work_date.year != (year or date.today().year):
            raise HTTPException(status_code=400, detail="Entries must belong to the selected month and year.")
    grouped: dict[int, list[ScheduleCreate]] = {}
    for entry in data.entries:
        grouped.setdefault(entry.user_id, []).append(ScheduleCreate(ambulance_id=ambulance.id, competence_id=entry.competence_id, work_date=entry.work_date))
    result = []
    for user_id, entries in grouped.items():
        result.extend(save_monthly_schedule(db, user_id, month or date.today().month, year or date.today().year, entries))
    return result
