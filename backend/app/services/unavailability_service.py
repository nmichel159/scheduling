"""
Service layer for User Availability (Unavailability) operations.

Encapsulates business rules:
- Users may only manage their own unavailability records.
- Duplicate records (same user + date) are prevented.
- Past months are locked: records dated before the first day of the
  current month cannot be created, updated or deleted.
- A month the scheduler's window has closed is locked for the employee;
  the scheduler editing on their behalf passes ``enforce_month_lock=False``.
- A day whose limit for the reason is used up is refused to the employee in
  the same way; the scheduler's ``enforce_month_lock=False`` passes it too.
- Every record remembers when its present reason was set and by whom, so a
  day's restrictions can be read back in the order they were entered.
"""

from datetime import date, datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import tuple_
from sqlalchemy.orm import Session

from app.models.unavailability import Unavailability
from app.models.user import User
from app.schemas.unavailability import (
    MonthlyDutyWish,
    UnavailabilityCreate,
    UnavailabilityUpdate,
)
from app.services.availability_overview_service import (
    ensure_day_has_room,
    normalize_reason,
)
from app.services.availability_window_service import ensure_month_open
from app.services.database_conflict import commit_or_conflict


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


def _ensure_writable(
    db: Session, user_id: int, target: date, enforce_month_lock: bool
) -> None:
    """Both locks: the past month always, the closed month for the employee."""
    _ensure_editable_date(target)
    if enforce_month_lock:
        ensure_month_open(db, user_id, target)


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


def create_unavailability(
    db: Session,
    user_id: int,
    data: UnavailabilityCreate,
    enforce_month_lock: bool = True,
    entered_by_id: Optional[int] = None,
) -> Unavailability:
    """Create a new unavailability record for a user.

    Args:
        db: Active database session.
        user_id: The ID of the user creating the record.
        data: Validated creation payload.
        entered_by_id: Who is entering it, the user themself when omitted.

    Returns:
        The newly created :class:`Unavailability` instance.
    """
    _ensure_writable(db, user_id, data.date_absent, enforce_month_lock)
    _check_duplicate(db, user_id, data.date_absent)
    if enforce_month_lock:
        ensure_day_has_room(db, user_id, data.date_absent, data.reason)

    record = Unavailability(
        user_id=user_id,
        date_absent=data.date_absent,
        reason=data.reason,
        is_active=True,
        entered_at=datetime.now(timezone.utc),
        entered_by_user_id=entered_by_id if entered_by_id is not None else user_id,
    )
    db.add(record)
    commit_or_conflict(
        db,
        f"Unavailability record already exists for date {data.date_absent}.",
    )
    db.refresh(record)
    return record


def get_unavailabilities(
    db: Session,
    user_id: int,
    skip: int = 0,
    limit: int = 100,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    after_date: Optional[date] = None,
    after_id: Optional[int] = None,
) -> list[Unavailability]:
    """Retrieve unavailability records for a user with optional date-range filtering.

    Args:
        db: Active database session.
        user_id: The owner of the records.
        skip: Legacy number of records to skip (pagination offset).
        limit: Maximum number of records to return.
        date_from: Optional start date for range filtering (inclusive).
        date_to: Optional end date for range filtering (inclusive).
        after_date: Date component of the keyset pagination cursor.
        after_id: ID component of the keyset pagination cursor.

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

    if (after_date is None) != (after_id is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="after_date and after_id must be provided together.",
        )
    if after_date is not None and skip:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="skip cannot be combined with the cursor parameters.",
        )
    if after_date is not None and after_id is not None:
        query = query.filter(
            tuple_(
                Unavailability.date_absent,
                Unavailability.id,
            )
            > (after_date, after_id)
        )

    return (
        query.order_by(Unavailability.date_absent, Unavailability.id)
        .offset(skip if after_date is None else 0)
        .limit(limit)
        .all()
    )


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
    db: Session,
    unavailability_id: int,
    user_id: int,
    data: UnavailabilityUpdate,
    enforce_month_lock: bool = True,
    entered_by_id: Optional[int] = None,
) -> Unavailability:
    """Update an existing unavailability record with partial data.

    Args:
        db: Active database session.
        unavailability_id: The ID of the record to update.
        user_id: The expected owner of the record.
        data: Validated update payload (only set fields are applied).
        entered_by_id: Who is changing it, the user themself when omitted.

    Returns:
        The updated :class:`Unavailability` instance.

    Raises:
        HTTPException 400: If the record or target date is in a locked month.
    """
    record = get_unavailability(db, unavailability_id, user_id)
    _ensure_writable(db, user_id, record.date_absent, enforce_month_lock)

    update_data = data.model_dump(exclude_unset=True)

    # If date_absent is being changed, the target date must also be editable
    # and free of duplicates.
    if "date_absent" in update_data:
        _ensure_writable(db, user_id, update_data["date_absent"], enforce_month_lock)
        _check_duplicate(db, user_id, update_data["date_absent"], exclude_id=unavailability_id)

    target = update_data.get("date_absent", record.date_absent)
    reason = update_data.get("reason", record.reason)
    reason_changed = normalize_reason(reason) != normalize_reason(record.reason)
    moved = target != record.date_absent
    if enforce_month_lock and (reason_changed or moved):
        ensure_day_has_room(db, user_id, target, reason, exclude_id=record.id)

    for field, value in update_data.items():
        setattr(record, field, value)
    if reason_changed or moved:
        # A new reason, or the same one on another day, queues afresh.
        record.entered_at = datetime.now(timezone.utc)
        record.entered_by_user_id = entered_by_id if entered_by_id is not None else user_id

    commit_or_conflict(
        db,
        f"Unavailability record already exists for date {record.date_absent}.",
    )
    db.refresh(record)
    return record


def delete_unavailability(
    db: Session,
    unavailability_id: int,
    user_id: int,
    enforce_month_lock: bool = True,
) -> None:
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
    _ensure_writable(db, user_id, record.date_absent, enforce_month_lock)
    db.delete(record)
    db.commit()


def _duty_wish_of(user: User) -> MonthlyDutyWish:
    """Both monthly wishes of one user, as the API returns them."""
    return MonthlyDutyWish(
        max_shifts_per_month=user.max_shifts_per_month,
        max_surcharge_shifts_per_month=user.max_surcharge_shifts_per_month,
    )


def get_monthly_duty_wish(db: Session, user_id: int) -> MonthlyDutyWish:
    """Return how many duties a month the user wants at most."""
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )
    return _duty_wish_of(user)


def set_monthly_duty_wish(
    db: Session, user_id: int, data: MonthlyDutyWish
) -> MonthlyDutyWish:
    """Store the user's monthly duty wishes; ``None`` clears one.

    Only the fields the request names are written, so the calendar can save
    either wish on its own without touching the other.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )
    sent = data.model_fields_set
    if "max_shifts_per_month" in sent:
        user.max_shifts_per_month = data.max_shifts_per_month
    if "max_surcharge_shifts_per_month" in sent:
        user.max_surcharge_shifts_per_month = data.max_surcharge_shifts_per_month
    commit_or_conflict(db, "Could not save the monthly duty wish.")
    db.refresh(user)
    return _duty_wish_of(user)
