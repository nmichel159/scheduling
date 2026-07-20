from calendar import monthrange
from datetime import date

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.associations import UserAmbulance
from app.models.competence import Competence
from app.models.schedule import Schedule
from app.models.user import User
from app.schemas.schedule import ScheduleCreate, ScheduleEdit, ScheduleResponse


def month_range(month: int | None, year: int | None) -> tuple[date, date] | None:
    if month is None and year is None:
        return None
    if month is None or year is None or not 1 <= month <= 12 or not 2000 <= year <= 2100:
        raise HTTPException(status_code=422, detail="month and year must be supplied together and be valid.")
    return date(year, month, 1), date(year, month, monthrange(year, month)[1])


def _response(item: Schedule) -> ScheduleResponse:
    return ScheduleResponse(id=item.id, user_id=item.user_id, ambulance_id=item.ambulance_id, competence_id=item.competence_id, work_date=item.work_date, user_email=item.user.email if item.user else None, user_full_name=item.user.full_name if item.user else None, competence_name=item.competence.name if item.competence else None, created_at=item.created_at, updated_at=item.updated_at)


def get_user_schedule(db: Session, user_id: int, month: int | None = None, year: int | None = None) -> list[ScheduleResponse]:
    query = db.query(Schedule).filter(Schedule.user_id == user_id, Schedule.is_active.is_(True))
    period = month_range(month, year)
    if period:
        query = query.filter(Schedule.work_date.between(*period))
    return [_response(row) for row in query.order_by(Schedule.work_date, Schedule.competence_id).all()]


def get_ambulance_schedule(db: Session, ambulance_id: int, month: int | None = None, year: int | None = None) -> list[ScheduleResponse]:
    query = db.query(Schedule).filter(Schedule.ambulance_id == ambulance_id, Schedule.is_active.is_(True))
    period = month_range(month, year)
    if period:
        query = query.filter(Schedule.work_date.between(*period))
    return [_response(row) for row in query.order_by(Schedule.work_date, Schedule.competence_id, Schedule.user_id).all()]


def _validate_entry(db: Session, user_id: int, data: ScheduleCreate) -> None:
    user = db.query(User).filter(User.id == user_id, User.is_active.is_(True)).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found or inactive.")
    assigned = db.query(UserAmbulance).filter(UserAmbulance.user_id == user_id, UserAmbulance.ambulance_id == data.ambulance_id, UserAmbulance.is_active.is_(True)).first()
    competence = db.query(Competence).filter(Competence.id == data.competence_id, Competence.ambulance_id == data.ambulance_id, Competence.is_active.is_(True)).first()
    if not assigned or not competence:
        raise HTTPException(status_code=400, detail="User and competence must be active members of the selected ambulance.")


def create_schedule(db: Session, user_id: int, data: ScheduleCreate) -> ScheduleResponse:
    _validate_entry(db, user_id, data)
    existing = db.query(Schedule).filter(Schedule.user_id == user_id, Schedule.ambulance_id == data.ambulance_id, Schedule.competence_id == data.competence_id, Schedule.work_date == data.work_date).first()
    if existing and existing.is_active:
        raise HTTPException(status_code=409, detail="Schedule entry already exists.")
    if existing:
        existing.is_active = True
        item = existing
    else:
        item = Schedule(user_id=user_id, is_active=True, **data.model_dump())
        db.add(item)
    db.commit(); db.refresh(item)
    return _response(item)


def update_schedule(db: Session, item: Schedule, data: ScheduleEdit) -> ScheduleResponse:
    payload = data.model_dump(exclude_unset=True)
    candidate = ScheduleCreate(user_id=item.user_id, ambulance_id=item.ambulance_id, competence_id=payload.get("competence_id", item.competence_id), work_date=payload.get("work_date", item.work_date))
    _validate_entry(db, item.user_id, candidate)
    for field, value in payload.items(): setattr(item, field, value)
    db.commit(); db.refresh(item)
    return _response(item)


def deactivate_schedule(db: Session, item: Schedule) -> None:
    item.is_active = False
    db.commit()


def save_monthly_schedule(db: Session, user_id: int, month: int, year: int, entries: list[ScheduleCreate]) -> list[ScheduleResponse]:
    start, end = month_range(month, year)
    requested = {(entry.ambulance_id, entry.competence_id, entry.work_date): entry for entry in entries}
    for entry in entries:
        _validate_entry(db, user_id, entry)
    existing = db.query(Schedule).filter(Schedule.user_id == user_id, Schedule.work_date.between(start, end)).all()
    existing_by_key = {(item.ambulance_id, item.competence_id, item.work_date): item for item in existing}
    for key, item in existing_by_key.items():
        item.is_active = key in requested
    for key, entry in requested.items():
        if key in existing_by_key:
            existing_by_key[key].is_active = True
        else:
            db.add(Schedule(user_id=user_id, is_active=True, **entry.model_dump()))
    db.commit()
    return get_user_schedule(db, user_id, month, year)
