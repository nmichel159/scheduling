"""
Service layer for User Availability (Unavailability) operations.

Encapsulates business rules:
- Users may only manage their own unavailability records.
- Duplicate records (same user + date) are prevented.
- Date validation is enforced.
"""

from datetime import date
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.unavailability import Unavailability
from app.schemas.unavailability import UnavailabilityCreate, UnavailabilityUpdate


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
    _check_duplicate(db, user_id, data.date_absent)

    record = Unavailability(
        user_id=user_id,
        date_absent=data.date_absent,
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

    Args:
        db: Active database session.
        unavailability_id: The ID of the record to update.
        user_id: The expected owner of the record.
        data: Validated update payload (only set fields are applied).

    Returns:
        The updated :class:`Unavailability` instance.
    """
    record = get_unavailability(db, unavailability_id, user_id)

    update_data = data.model_dump(exclude_unset=True)

    # If date_absent is being changed, check for duplicates
    if "date_absent" in update_data:
        _check_duplicate(db, user_id, update_data["date_absent"], exclude_id=unavailability_id)

    for field, value in update_data.items():
        setattr(record, field, value)

    db.commit()
    db.refresh(record)
    return record


def delete_unavailability(db: Session, unavailability_id: int, user_id: int) -> None:
    """Delete an unavailability record, enforcing ownership.

    Args:
        db: Active database session.
        unavailability_id: The ID of the record to delete.
        user_id: The expected owner of the record.

    Raises:
        HTTPException 404: If the record does not exist or belongs to another user.
    """
    record = get_unavailability(db, unavailability_id, user_id)
    db.delete(record)
    db.commit()
