"""
Service layer for User Availability (Unavailability) operations.

Encapsulates business rules:
- Users may only manage their own unavailability records.
- Duplicate records (same user + date) are prevented.
- Date validation is enforced.
- Past months are locked: records dated before the first day of the
  current month cannot be created, updated or deleted.
- A repeating week pattern can be applied to a whole month in a single
  transactional bulk operation.
"""

import calendar
from datetime import date
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.unavailability import Unavailability
from app.schemas.unavailability import (
    ApplyPatternRequest,
    ApplyPatternResponse,
    UnavailabilityCreate,
    UnavailabilityUpdate,
)


def _first_day_of_current_month() -> date:
    """Return the first day of the current month (edit-lock boundary)."""
    today = date.today()
    return today.replace(day=1)


def _ensure_editable_date(target: date) -> None:
    """Raise 400 if the date falls into an already closed (past) month.

    Args:
        target: The date being created, moved to, or deleted.

    Raises:
        HTTPException 400: If the date belongs to a month before the current one.
    """
    if target < _first_day_of_current_month():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Records in past months are read-only and cannot be modified.",
        )


def _check_duplicate(db: Session, user_id: int, date_absent: date, exclude_id: Optional[int] = None) -> None:
    """Raise 409 if a record already exists for the given user and date.

    Args:
        db: Active database session.
        user_id: Owner of the unavailability record.
        date_absent: The absence date to check.
        exclude_id: Optional record ID to exclude (used during updates).

    Raises:
        HTTPException 409: If a duplicate record is detected.
    """
    query = db.query(Unavailability).filter(
        Unavailability.user_id == user_id,
        Unavailability.date_absent == date_absent,
        Unavailability.is_active == True,
    )
    if exclude_id is not None:
        query = query.filter(Unavailability.id != exclude_id)
    if query.first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Unavailability record already exists for date {date_absent}.",
        )


def create_unavailability(db: Session, user_id: int, data: UnavailabilityCreate) -> Unavailability:
    """Create a new unavailability record for a user.

    Args:
        db: Active database session.
        user_id: The ID of the user creating the record.
        data: Validated creation payload.

    Returns:
        The newly created :class:`Unavailability` instance.
    """
    _ensure_editable_date(data.date_absent)
    _check_duplicate(db, user_id, data.date_absent)

    record = Unavailability(
        user_id=user_id,
        date_absent=data.date_absent,
        start_time=data.start_time,
        end_time=data.end_time,
        reason=data.reason,
        is_active=True,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def get_unavailabilities(
    db: Session,
    user_id: int,
    skip: int = 0,
    limit: int = 100,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
) -> list[Unavailability]:
    """Retrieve unavailability records for a user with optional date-range filtering.

    Args:
        db: Active database session.
        user_id: The owner of the records.
        skip: Number of records to skip (pagination offset).
        limit: Maximum number of records to return.
        date_from: Optional start date for range filtering (inclusive).
        date_to: Optional end date for range filtering (inclusive).

    Returns:
        A list of matching :class:`Unavailability` records.
    """
    query = db.query(Unavailability).filter(
        Unavailability.user_id == user_id,
        Unavailability.is_active == True,
    )
    if date_from is not None:
        query = query.filter(Unavailability.date_absent >= date_from)
    if date_to is not None:
        query = query.filter(Unavailability.date_absent <= date_to)

    return query.order_by(Unavailability.date_absent).offset(skip).limit(limit).all()


def get_unavailability(db: Session, unavailability_id: int, user_id: int) -> Unavailability:
    """Retrieve a single unavailability record, enforcing ownership.

    Args:
        db: Active database session.
        unavailability_id: The ID of the record to retrieve.
        user_id: The expected owner of the record.

    Returns:
        The :class:`Unavailability` instance.

    Raises:
        HTTPException 404: If the record does not exist or belongs to another user.
    """
    record = (
        db.query(Unavailability)
        .filter(
            Unavailability.id == unavailability_id,
            Unavailability.user_id == user_id,
            Unavailability.is_active == True,
        )
        .first()
    )
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unavailability record with id {unavailability_id} not found.",
        )
    return record


def update_unavailability(
    db: Session, unavailability_id: int, user_id: int, data: UnavailabilityUpdate
) -> Unavailability:
    """Update an existing unavailability record with partial data.

    Time-window consistency is validated against the resulting state
    (payload merged over the existing record).

    Args:
        db: Active database session.
        unavailability_id: The ID of the record to update.
        user_id: The expected owner of the record.
        data: Validated update payload (only set fields are applied).

    Returns:
        The updated :class:`Unavailability` instance.

    Raises:
        HTTPException 400: If the record or target date is in a locked month,
            or the resulting time window is invalid.
    """
    record = get_unavailability(db, unavailability_id, user_id)
    _ensure_editable_date(record.date_absent)

    update_data = data.model_dump(exclude_unset=True)
    update_data.pop("clear_times", None)

    # If date_absent is being changed, the target date must also be editable
    # and free of duplicates.
    if "date_absent" in update_data:
        _ensure_editable_date(update_data["date_absent"])
        _check_duplicate(db, user_id, update_data["date_absent"], exclude_id=unavailability_id)

    if data.clear_times:
        update_data["start_time"] = None
        update_data["end_time"] = None

    # Validate the resulting time window (merged state).
    new_start = update_data.get("start_time", record.start_time)
    new_end = update_data.get("end_time", record.end_time)
    if (new_start is None) != (new_end is None):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_time and end_time must be provided together or both cleared.",
        )
    if new_start is not None and new_start >= new_end:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_time must be earlier than end_time.",
        )

    for field, value in update_data.items():
        setattr(record, field, value)

    db.commit()
    db.refresh(record)
    return record


def delete_unavailability(db: Session, unavailability_id: int, user_id: int) -> None:
    """Delete an unavailability record, enforcing ownership and month lock.

    Args:
        db: Active database session.
        unavailability_id: The ID of the record to delete.
        user_id: The expected owner of the record.

    Raises:
        HTTPException 404: If the record does not exist or belongs to another user.
        HTTPException 400: If the record belongs to a locked (past) month.
    """
    record = get_unavailability(db, unavailability_id, user_id)
    _ensure_editable_date(record.date_absent)
    db.delete(record)
    db.commit()


def apply_pattern(db: Session, user_id: int, data: ApplyPatternRequest) -> ApplyPatternResponse:
    """Apply a repeating week pattern to every matching day of a month.

    Runs as a single transaction: either all days are written or none.
    Existing records are skipped unless ``overwrite`` is set, in which
    case their time window is replaced (reason is preserved).

    Args:
        db: Active database session.
        user_id: The user the pattern is applied for.
        data: Validated pattern payload (year, month, weekday windows).

    Returns:
        An :class:`ApplyPatternResponse` summary with created/updated/skipped counts.

    Raises:
        HTTPException 400: If the target month lies in the past.
    """
    first_day = date(data.year, data.month, 1)
    _ensure_editable_date(first_day)

    days_in_month = calendar.monthrange(data.year, data.month)[1]
    pattern_by_weekday = {p.weekday: p for p in data.pattern}

    existing = {
        record.date_absent: record
        for record in db.query(Unavailability).filter(
            Unavailability.user_id == user_id,
            Unavailability.date_absent >= first_day,
            Unavailability.date_absent <= date(data.year, data.month, days_in_month),
            Unavailability.is_active == True,
        )
    }

    created = updated = skipped = 0
    try:
        for day in range(1, days_in_month + 1):
            current = date(data.year, data.month, day)
            entry = pattern_by_weekday.get(current.weekday())
            if entry is None:
                continue

            record = existing.get(current)
            if record is not None:
                if not data.overwrite:
                    skipped += 1
                    continue
                record.start_time = entry.start_time
                record.end_time = entry.end_time
                updated += 1
            else:
                db.add(
                    Unavailability(
                        user_id=user_id,
                        date_absent=current,
                        start_time=entry.start_time,
                        end_time=entry.end_time,
                        is_active=True,
                    )
                )
                created += 1
        db.commit()
    except Exception:
        db.rollback()
        raise

    return ApplyPatternResponse(created=created, updated=updated, skipped=skipped)
