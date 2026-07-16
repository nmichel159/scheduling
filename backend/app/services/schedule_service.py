from calendar import monthrange
from datetime import date
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from app.models.schedule import Schedule
from app.models.user import User
from app.models.competence import Competence
from app.models.associations import UserAmbulance
from app.schemas.schedule import ScheduleResponse, ScheduleUpdate

def current_month_range() -> tuple[date, date]:
    today = date.today()
    return today.replace(day=1), today.replace(day=monthrange(today.year, today.month)[1])

def _response(item: Schedule) -> ScheduleResponse:
    return ScheduleResponse(
        id=item.id, user_id=item.user_id, ambulance_id=item.ambulance_id,
        competence_id=item.competence_id, work_date=item.work_date,
        user_email=item.user.email if item.user else None,
        user_full_name=item.user.full_name if item.user else None,
        competence_name=item.competence.name if item.competence else None,
        created_at=item.created_at, updated_at=item.updated_at,
    )

def get_user_schedule(db: Session, user_id: int) -> list[ScheduleResponse]:
    start, end = current_month_range()
    rows = db.query(Schedule).filter(
        Schedule.user_id == user_id, Schedule.work_date.between(start, end), Schedule.is_active.is_(True)
    ).order_by(Schedule.work_date, Schedule.competence_id).all()
    return [_response(row) for row in rows]

def get_ambulance_schedule(db: Session, ambulance_id: int) -> list[ScheduleResponse]:
    start, end = current_month_range()
    rows = db.query(Schedule).filter(
        Schedule.ambulance_id == ambulance_id, Schedule.work_date.between(start, end), Schedule.is_active.is_(True)
    ).order_by(Schedule.work_date, Schedule.competence_id, Schedule.user_id).all()
    return [_response(row) for row in rows]

def update_ambulance_schedule(db: Session, ambulance_id: int, data: ScheduleUpdate) -> list[ScheduleResponse]:
    start, end = current_month_range()
    if any(entry.work_date < start or entry.work_date > end for entry in data.entries):
        raise HTTPException(status_code=400, detail="Schedule entries must be in the current month.")
    user_ids = {entry.user_id for entry in data.entries}
    competence_ids = {entry.competence_id for entry in data.entries}
    valid_users = {uid for (uid,) in db.query(UserAmbulance.user_id).filter(
        UserAmbulance.ambulance_id == ambulance_id, UserAmbulance.user_id.in_(user_ids), UserAmbulance.is_active.is_(True)
    ).all()}
    valid_competences = {cid for (cid,) in db.query(Competence.id).filter(
        Competence.ambulance_id == ambulance_id, Competence.id.in_(competence_ids), Competence.is_active.is_(True)
    ).all()}
    if user_ids != valid_users or competence_ids != valid_competences:
        raise HTTPException(status_code=400, detail="Users and competences must belong to this ambulance.")
    db.query(Schedule).filter(Schedule.ambulance_id == ambulance_id, Schedule.work_date.between(start, end)).update(
        {Schedule.is_active: False}, synchronize_session=False
    )
    for entry in data.entries:
        db.add(Schedule(ambulance_id=ambulance_id, is_active=True, **entry.model_dump()))
    db.commit()
    return get_ambulance_schedule(db, ambulance_id)
