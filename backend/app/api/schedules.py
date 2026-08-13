from datetime import date
from threading import BoundedSemaphore
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, contains_eager

from app.core.config import settings
from app.core.dependencies import get_current_user, get_manager_ambulance, require_manager_role
from app.db.session import get_db
from app.models.ambulance import Ambulance
from app.models.associations import UserAmbulance
from app.models.schedule import Schedule
from app.models.user import User
from app.schemas.schedule import MonthlyScheduleSave, MonthlyScheduleStatistics, NextScheduleResponse, ScheduleCreate, ScheduleEdit, ScheduleGenerationResponse, ScheduleResponse, ScheduleUpdate, UserMonthlySchedule, WorkedScheduleStatistics
from app.services.schedule_generation_service import ScheduleGenerationError, generate_ambulance_monthly_schedule
from app.services.schedule_service import create_schedule, deactivate_schedule, get_ambulance_schedule, get_manageable_user_ambulance_ids, get_next_user_schedule, get_user_monthly_statistics, get_user_schedule, get_user_worked_statistics, save_ambulance_monthly_schedule, save_monthly_schedule, update_schedule

router = APIRouter()
ambulance_router = APIRouter()
_schedule_generation_slots = BoundedSemaphore(
    value=settings.SCHEDULE_GENERATION_MAX_CONCURRENCY
)


def _is_admin(user: User) -> bool:
    return any(item.role and item.role.is_active and item.role.level >= 3 for item in user.user_roles)


def _bounded_schedule_period(
    month: int | None,
    year: int | None,
    today: date | None = None,
) -> tuple[int | None, int | None]:
    """Default unbounded API reads to the current calendar month."""
    if month is None and year is None:
        reference_date = today or date.today()
        return reference_date.month, reference_date.year
    return month, year


def _can_manage_user(current_user: User, db: Session, user_id: int, ambulance_id: int | None = None) -> None:
    if _is_admin(current_user):
        return
    query = db.query(UserAmbulance).join(Ambulance).filter(UserAmbulance.user_id == user_id, UserAmbulance.is_active.is_(True), Ambulance.managed_by_user_id == current_user.id, Ambulance.is_active.is_(True))
    if ambulance_id is not None:
        query = query.filter(Ambulance.id == ambulance_id)
    if not query.first():
        raise HTTPException(status_code=403, detail="You may manage schedules only in ambulances you manage.")


def _can_manage_schedule_pairs(
    current_user: User,
    db: Session,
    schedule_pairs: set[tuple[int, int]],
) -> None:
    """Authorize many user/ambulance schedule pairs with one query."""
    if _is_admin(current_user) or not schedule_pairs:
        return
    user_ids = {user_id for user_id, _ambulance_id in schedule_pairs}
    ambulance_ids = {ambulance_id for _user_id, ambulance_id in schedule_pairs}
    manageable_pairs = {
        (user_id, ambulance_id)
        for user_id, ambulance_id in db.query(
            UserAmbulance.user_id,
            UserAmbulance.ambulance_id,
        )
        .join(Ambulance)
        .filter(
            UserAmbulance.user_id.in_(user_ids),
            UserAmbulance.ambulance_id.in_(ambulance_ids),
            UserAmbulance.is_active.is_(True),
            Ambulance.managed_by_user_id == current_user.id,
            Ambulance.is_active.is_(True),
        )
        .all()
    }
    if not schedule_pairs.issubset(manageable_pairs):
        raise HTTPException(
            status_code=403,
            detail="You may manage schedules only in ambulances you manage.",
        )


@router.get("/me", response_model=list[ScheduleResponse])
def get_my_schedule(month: int | None = None, year: int | None = None, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    selected_month, selected_year = _bounded_schedule_period(month, year)
    return get_user_schedule(db, current_user.id, selected_month, selected_year)


@router.get("/me/next", response_model=NextScheduleResponse)
def get_my_next_schedule(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Return the next active duty, or a null value when none is scheduled."""
    return {"next_shift": get_next_user_schedule(db, current_user.id)}


@router.get("/me/monthly-statistics", response_model=MonthlyScheduleStatistics)
def get_my_monthly_schedule_statistics(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return get_user_monthly_statistics(db, current_user.id)


@router.get("/me/worked-statistics", response_model=WorkedScheduleStatistics)
def get_my_worked_schedule_statistics(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return get_user_worked_statistics(db, current_user.id)


@router.get("/user/{user_id}", response_model=list[ScheduleResponse])
def get_user_schedule_endpoint(user_id: int, month: int | None = None, year: int | None = None, current_user: User = Depends(require_manager_role), db: Session = Depends(get_db)):
    ambulance_ids = get_manageable_user_ambulance_ids(db, current_user, user_id)
    selected_month, selected_year = _bounded_schedule_period(month, year)
    return get_user_schedule(
        db,
        user_id,
        selected_month,
        selected_year,
        ambulance_ids=ambulance_ids,
    )


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
    # The synchronization also deactivates omitted entries. A manager must
    # therefore be authorized for every existing entry that can be affected.
    existing = get_user_schedule(db, data.user_id, data.month, data.year)
    schedule_pairs = {
        (data.user_id, entry.ambulance_id)
        for entry in [*data.entries, *existing]
    }
    _can_manage_schedule_pairs(current_user, db, schedule_pairs)
    return save_monthly_schedule(db, data.user_id, data.month, data.year, data.entries)


@ambulance_router.get("/{ambulance_id}/schedule", response_model=list[UserMonthlySchedule])
def get_ambulance_schedule_endpoint(
    ambulance: Ambulance = Depends(get_manager_ambulance),
    month: int | None = None,
    year: int | None = None,
    after_id: Annotated[
        int | None,
        Query(ge=0, description="Return employees after this user ID"),
    ] = None,
    limit: Annotated[
        int,
        Query(ge=1, le=500, description="Max employees to return"),
    ] = 250,
    db: Session = Depends(get_db),
):
    displayed_month, displayed_year = (month, year) if month is not None and year is not None else (date.today().month, date.today().year)
    employees_query = (
        db.query(UserAmbulance)
        .join(User, User.id == UserAmbulance.user_id)
        .options(contains_eager(UserAmbulance.user))
        .filter(
            UserAmbulance.ambulance_id == ambulance.id,
            UserAmbulance.is_active.is_(True),
            User.is_active.is_(True),
        )
    )
    if after_id is not None:
        employees_query = employees_query.filter(UserAmbulance.user_id > after_id)
    if after_id is not None or limit is not None:
        employees_query = employees_query.order_by(UserAmbulance.user_id)
    if limit is not None:
        employees_query = employees_query.limit(limit)
    employees = employees_query.all()
    displayed_user_ids = {
        item.user_id for item in employees if item.user and item.user.is_active
    }
    entries_by_user: dict[int, list[ScheduleResponse]] = {}
    for entry in get_ambulance_schedule(
        db,
        ambulance.id,
        displayed_month,
        displayed_year,
        user_ids=(
            displayed_user_ids
            if after_id is not None or limit is not None
            else None
        ),
    ):
        entries_by_user.setdefault(entry.user_id, []).append(entry)
    return [UserMonthlySchedule(user_id=item.user_id, user_full_name=item.user.full_name if item.user else None, month=displayed_month, year=displayed_year, entries=entries_by_user.get(item.user_id, [])) for item in employees if item.user and item.user.is_active]


@ambulance_router.put("/{ambulance_id}/schedule", response_model=list[ScheduleResponse])
def update_ambulance_schedule_endpoint(data: ScheduleUpdate, ambulance: Ambulance = Depends(get_manager_ambulance), month: int | None = None, year: int | None = None, db: Session = Depends(get_db)):
    """Synchronize the selected ambulance's schedule for the selected month."""
    selected_month, selected_year = (month, year) if month is not None and year is not None else (date.today().month, date.today().year)
    for entry in data.entries:
        if entry.work_date.month != selected_month or entry.work_date.year != selected_year:
            raise HTTPException(status_code=400, detail="Entries must belong to the selected month and year.")
    return save_ambulance_monthly_schedule(db, ambulance.id, selected_month, selected_year, data.entries)


@ambulance_router.post(
    "/{ambulance_id}/schedule/generate",
    response_model=ScheduleGenerationResponse,
    summary="Generate an optimized monthly ambulance schedule draft",
)
def generate_ambulance_schedule_endpoint(
    month: int,
    year: int,
    ambulance: Ambulance = Depends(get_manager_ambulance),
    db: Session = Depends(get_db),
) -> ScheduleGenerationResponse:
    """Generate, but do not persist, a manager-reviewable MILP schedule draft."""
    if not 1 <= month <= 12 or not 2000 <= year <= 2100:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="month and year must be valid.",
        )
    if not _schedule_generation_slots.acquire(blocking=False):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Schedule generation capacity is currently in use. Try again shortly.",
            headers={"Retry-After": "5"},
        )
    try:
        try:
            return generate_ambulance_monthly_schedule(db, ambulance.id, month, year)
        except ScheduleGenerationError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=exc.as_detail(),
            ) from exc
    finally:
        _schedule_generation_slots.release()
