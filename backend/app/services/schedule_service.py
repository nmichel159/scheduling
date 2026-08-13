from calendar import monthrange
from datetime import date

from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.models.ambulance import Ambulance
from app.models.associations import UserAmbulance, UserCompetence
from app.models.competence import Competence
from app.models.schedule import Schedule
from app.models.unavailability import Unavailability
from app.models.user import User
from app.schemas.schedule import ScheduleCreate, ScheduleEdit, ScheduleEntry, ScheduleResponse
from app.services.database_conflict import commit_or_conflict


def month_range(month: int | None, year: int | None) -> tuple[date, date] | None:
    if month is None and year is None:
        return None
    if month is None or year is None or not 1 <= month <= 12 or not 2000 <= year <= 2100:
        raise HTTPException(status_code=422, detail="month and year must be supplied together and be valid.")
    return date(year, month, 1), date(year, month, monthrange(year, month)[1])


def _response(item: Schedule) -> ScheduleResponse:
    return ScheduleResponse(id=item.id, user_id=item.user_id, ambulance_id=item.ambulance_id, competence_id=item.competence_id, work_date=item.work_date, user_email=item.user.email if item.user else None, user_full_name=item.user.full_name if item.user else None, competence_name=item.competence.name if item.competence else None, created_at=item.created_at, updated_at=item.updated_at)


def get_manageable_user_ambulance_ids(
    db: Session,
    current_user: User,
    user_id: int,
) -> set[int] | None:
    """Return the employee's clinics visible to a manager; admins see all."""
    is_admin = any(
        item.role and item.role.is_active and item.role.level >= 3
        for item in current_user.user_roles
    )
    if is_admin:
        return None
    ambulance_ids = {
        ambulance_id
        for (ambulance_id,) in db.query(UserAmbulance.ambulance_id)
        .join(Ambulance)
        .filter(
            UserAmbulance.user_id == user_id,
            UserAmbulance.is_active.is_(True),
            Ambulance.managed_by_user_id == current_user.id,
            Ambulance.is_active.is_(True),
        )
        .all()
    }
    if not ambulance_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You may view schedules only in ambulances you manage.",
        )
    return ambulance_ids


def get_user_schedule(
    db: Session,
    user_id: int,
    month: int | None = None,
    year: int | None = None,
    ambulance_ids: set[int] | None = None,
) -> list[ScheduleResponse]:
    query = (
        db.query(Schedule)
        .options(joinedload(Schedule.user), joinedload(Schedule.competence))
        .filter(Schedule.user_id == user_id, Schedule.is_active.is_(True))
    )
    period = month_range(month, year)
    if period:
        query = query.filter(Schedule.work_date.between(*period))
    if ambulance_ids is not None:
        if not ambulance_ids:
            return []
        query = query.filter(Schedule.ambulance_id.in_(ambulance_ids))
    return [_response(row) for row in query.order_by(Schedule.work_date, Schedule.competence_id).all()]


def get_ambulance_schedule(
    db: Session,
    ambulance_id: int,
    month: int | None = None,
    year: int | None = None,
    user_ids: set[int] | None = None,
) -> list[ScheduleResponse]:
    query = (
        db.query(Schedule)
        .options(joinedload(Schedule.user), joinedload(Schedule.competence))
        .filter(Schedule.ambulance_id == ambulance_id, Schedule.is_active.is_(True))
    )
    period = month_range(month, year)
    if period:
        query = query.filter(Schedule.work_date.between(*period))
    if user_ids is not None:
        if not user_ids:
            return []
        query = query.filter(Schedule.user_id.in_(user_ids))
    return [_response(row) for row in query.order_by(Schedule.work_date, Schedule.competence_id, Schedule.user_id).all()]


def get_next_user_schedule(db: Session, user_id: int, today: date | None = None) -> ScheduleResponse | None:
    """Return the first active duty today or in the future for one user."""
    reference_date = today or date.today()
    item = (
        db.query(Schedule)
        .options(joinedload(Schedule.user), joinedload(Schedule.competence))
        .filter(
            Schedule.user_id == user_id,
            Schedule.is_active.is_(True),
            Schedule.work_date >= reference_date,
        )
        .order_by(Schedule.work_date, Schedule.competence_id, Schedule.id)
        .first()
    )
    return _response(item) if item else None


def get_user_monthly_statistics(
    db: Session, user_id: int, today: date | None = None
) -> dict[str, int]:
    """Count the authenticated user's planned duties in the current month."""
    reference_date = today or date.today()
    start, end = month_range(reference_date.month, reference_date.year)
    scheduled_shift_count = (
        db.query(Schedule)
        .filter(
            Schedule.user_id == user_id,
            Schedule.is_active.is_(True),
            Schedule.work_date.between(start, end),
        )
        .count()
    )
    return {
        "month": reference_date.month,
        "year": reference_date.year,
        "scheduled_shift_count": scheduled_shift_count,
    }


def get_user_worked_statistics(
    db: Session, user_id: int, today: date | None = None
) -> dict[str, int | date]:
    """Count distinct current-month work days up to and including today."""
    reference_date = today or date.today()
    start = date(reference_date.year, reference_date.month, 1)
    worked_day_count = (
        db.query(Schedule.work_date)
        .filter(
            Schedule.user_id == user_id,
            Schedule.is_active.is_(True),
            Schedule.work_date.between(start, reference_date),
        )
        .distinct()
        .count()
    )
    return {
        "month": reference_date.month,
        "year": reference_date.year,
        "through_date": reference_date,
        "worked_day_count": worked_day_count,
    }


def _validate_entries(
    db: Session,
    entries: list[tuple[int, ScheduleCreate]],
) -> None:
    """Validate schedule entries with a bounded set of database queries."""
    if not entries:
        return

    user_ids = {user_id for user_id, _entry in entries}
    ambulance_ids = {entry.ambulance_id for _user_id, entry in entries}
    competence_ids = {entry.competence_id for _user_id, entry in entries}
    work_dates = {entry.work_date for _user_id, entry in entries}

    active_user_ids = {
        user_id
        for (user_id,) in db.query(User.id)
        .filter(User.id.in_(user_ids), User.is_active.is_(True))
        .all()
    }
    active_memberships = {
        (user_id, ambulance_id)
        for user_id, ambulance_id in db.query(
            UserAmbulance.user_id,
            UserAmbulance.ambulance_id,
        )
        .filter(
            UserAmbulance.user_id.in_(user_ids),
            UserAmbulance.ambulance_id.in_(ambulance_ids),
            UserAmbulance.is_active.is_(True),
        )
        .all()
    }
    active_competences = {
        (competence_id, ambulance_id)
        for competence_id, ambulance_id in db.query(
            Competence.id,
            Competence.ambulance_id,
        )
        .filter(
            Competence.id.in_(competence_ids),
            Competence.ambulance_id.in_(ambulance_ids),
            Competence.is_active.is_(True),
        )
        .all()
    }
    active_qualifications = {
        (user_id, competence_id)
        for user_id, competence_id in db.query(
            UserCompetence.user_id,
            UserCompetence.competence_id,
        )
        .filter(
            UserCompetence.user_id.in_(user_ids),
            UserCompetence.competence_id.in_(competence_ids),
            UserCompetence.is_active.is_(True),
        )
        .all()
    }
    unavailable_dates = {
        (user_id, unavailable_date)
        for user_id, unavailable_date in db.query(
            Unavailability.user_id,
            Unavailability.date_absent,
        )
        .filter(
            Unavailability.user_id.in_(user_ids),
            Unavailability.date_absent.in_(work_dates),
            Unavailability.is_active.is_(True),
        )
        .all()
    }
    scheduled_ambulances: dict[tuple[int, date], set[int]] = {}
    schedule_rows = (
        db.query(Schedule.user_id, Schedule.ambulance_id, Schedule.work_date)
        .filter(
            Schedule.user_id.in_(user_ids),
            Schedule.work_date.in_(work_dates),
            Schedule.is_active.is_(True),
        )
        .all()
    )
    for user_id, ambulance_id, work_date in schedule_rows:
        scheduled_ambulances.setdefault((user_id, work_date), set()).add(
            ambulance_id
        )

    for user_id, entry in entries:
        if user_id not in active_user_ids:
            raise HTTPException(status_code=404, detail="User not found or inactive.")
        if (
            (user_id, entry.ambulance_id) not in active_memberships
            or (entry.competence_id, entry.ambulance_id) not in active_competences
            or (user_id, entry.competence_id) not in active_qualifications
        ):
            raise HTTPException(
                status_code=400,
                detail="User must be an active, qualified member of the selected ambulance.",
            )
        if (user_id, entry.work_date) in unavailable_dates:
            raise HTTPException(
                status_code=400,
                detail="User is unavailable on the selected date.",
            )
        if any(
            ambulance_id != entry.ambulance_id
            for ambulance_id in scheduled_ambulances.get(
                (user_id, entry.work_date), set()
            )
        ):
            raise HTTPException(
                status_code=409,
                detail="User already has a duty in another ambulance on the selected date.",
            )


def _validate_entry(db: Session, user_id: int, data: ScheduleCreate) -> None:
    """Validate one entry through the same bounded bulk-validation path."""
    _validate_entries(db, [(user_id, data)])


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
    commit_or_conflict(db, "Schedule entry already exists.")
    db.refresh(item)
    return _response(item)


def update_schedule(db: Session, item: Schedule, data: ScheduleEdit) -> ScheduleResponse:
    payload = data.model_dump(exclude_unset=True)
    candidate = ScheduleCreate(ambulance_id=item.ambulance_id, competence_id=payload.get("competence_id", item.competence_id), work_date=payload.get("work_date", item.work_date))
    _validate_entry(db, item.user_id, candidate)
    for field, value in payload.items(): setattr(item, field, value)
    commit_or_conflict(db, "Schedule entry already exists.")
    db.refresh(item)
    return _response(item)


def deactivate_schedule(db: Session, item: Schedule) -> None:
    item.is_active = False
    db.commit()


def save_monthly_schedule(db: Session, user_id: int, month: int, year: int, entries: list[ScheduleCreate]) -> list[ScheduleResponse]:
    start, end = month_range(month, year)
    requested = {(entry.ambulance_id, entry.competence_id, entry.work_date): entry for entry in entries}
    _validate_entries(db, [(user_id, entry) for entry in entries])
    existing = db.query(Schedule).filter(Schedule.user_id == user_id, Schedule.work_date.between(start, end)).all()
    existing_by_key = {(item.ambulance_id, item.competence_id, item.work_date): item for item in existing}
    for key, item in existing_by_key.items():
        item.is_active = key in requested
    for key, entry in requested.items():
        if key in existing_by_key:
            existing_by_key[key].is_active = True
        else:
            db.add(Schedule(user_id=user_id, is_active=True, **entry.model_dump()))
    commit_or_conflict(db, "One or more schedule entries already exist.")
    return get_user_schedule(db, user_id, month, year)


def save_ambulance_monthly_schedule(
    db: Session,
    ambulance_id: int,
    month: int,
    year: int,
    entries: list[ScheduleEntry],
) -> list[ScheduleResponse]:
    """Synchronize one ambulance's schedule for one calendar month only.

    Entries omitted from the request are deactivated only when they belong to
    the selected ambulance and month.  Schedules from another ambulance, even
    for the same employee, are deliberately left untouched.
    """
    start, end = month_range(month, year)
    requested = {(entry.user_id, entry.competence_id, entry.work_date): entry for entry in entries}

    validation_entries = [
        (
            entry.user_id,
            ScheduleCreate(
                ambulance_id=ambulance_id,
                competence_id=entry.competence_id,
                work_date=entry.work_date,
            ),
        )
        for entry in requested.values()
    ]
    _validate_entries(db, validation_entries)

    existing = (
        db.query(Schedule)
        .filter(
            Schedule.ambulance_id == ambulance_id,
            Schedule.work_date.between(start, end),
        )
        .all()
    )
    existing_by_key = {
        (item.user_id, item.competence_id, item.work_date): item for item in existing
    }

    for key, item in existing_by_key.items():
        item.is_active = key in requested
    for key, entry in requested.items():
        if key in existing_by_key:
            existing_by_key[key].is_active = True
        else:
            db.add(
                Schedule(
                    user_id=entry.user_id,
                    ambulance_id=ambulance_id,
                    competence_id=entry.competence_id,
                    work_date=entry.work_date,
                    is_active=True,
                )
            )

    commit_or_conflict(db, "One or more schedule entries already exist.")
    return get_ambulance_schedule(
        db,
        ambulance_id,
        month,
        year,
        user_ids={entry.user_id for entry in entries},
    )
