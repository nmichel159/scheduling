"""How many people are away on each day, and the limits on it.

Each workplace's scheduler sets how many of its people may be on leave, on
a business trip or otherwise unable to work on the same day. An employee
filling in a day that is already full in any of their workplaces is refused;
the scheduler entering it on their behalf is not, because the scheduler is
the one who decides.

The overview counts the active restrictions of one workplace's active
members by day and reason, and lists one day's restrictions in the order
they were entered, which is the order in which the limit was used up.
"""

from __future__ import annotations

from calendar import monthrange
from datetime import date

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.models.ambulance import Ambulance
from app.models.associations import UserAmbulance
from app.models.availability_window import AvailabilityDayLimit
from app.models.unavailability import Unavailability
from app.models.user import User
from app.services.database_conflict import commit_or_conflict

#: The reasons the employee's calendar writes (see unavailabilityService.js).
PREFERRED = "PREFERRED"
SOFT_DECLINE = "SOFT_DECLINE"
UNAVAILABLE = "UNAVAILABLE"
VACATION = "VACATION"
BUSINESS_TRIP = "BUSINESS_TRIP"

#: The absences a day can be limited on, in the order the screen shows them.
LIMITED_REASONS = (VACATION, BUSINESS_TRIP, UNAVAILABLE)
KNOWN_REASONS = (PREFERRED, SOFT_DECLINE, UNAVAILABLE, VACATION, BUSINESS_TRIP)


def normalize_reason(reason: str | None) -> str:
    """The reason as the calendar reads it: anything unknown means "cannot"."""
    value = (reason or "").strip().upper()
    return value if value in KNOWN_REASONS else UNAVAILABLE


def day_limits(db: Session, ambulance_id: int) -> dict[str, int | None]:
    """Every limited reason with its limit, ``None`` where there is none."""
    stored = {
        row.reason: row.max_per_day
        for row in db.query(AvailabilityDayLimit).filter(
            AvailabilityDayLimit.ambulance_id == ambulance_id
        )
    }
    return {reason: stored.get(reason) for reason in LIMITED_REASONS}


def save_day_limits(
    db: Session, ambulance_id: int, limits: dict[str, int | None]
) -> dict[str, int | None]:
    """Store the limits; a reason left out keeps its limit, ``None`` drops it.

    Raises:
        HTTPException 422: For a reason that cannot be limited.
    """
    unknown = set(limits) - set(LIMITED_REASONS)
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "unknown_reason",
                "message": f"These reasons cannot be limited: {sorted(unknown)}.",
            },
        )
    for reason, value in limits.items():
        row = db.get(AvailabilityDayLimit, (ambulance_id, reason))
        if value is None:
            if row is not None:
                db.delete(row)
        elif row is None:
            db.add(
                AvailabilityDayLimit(
                    ambulance_id=ambulance_id, reason=reason, max_per_day=value
                )
            )
        else:
            row.max_per_day = value
    commit_or_conflict(db, "The day limits could not be saved.")
    return day_limits(db, ambulance_id)


def _active_records(ambulance_id: int):
    """Restrictions that count: active, of an active member of the workplace."""
    return (
        Unavailability.is_active.is_(True),
        User.is_active.is_(True),
        Unavailability.user_id.in_(
            select(UserAmbulance.user_id).where(
                UserAmbulance.ambulance_id == ambulance_id,
                UserAmbulance.is_active.is_(True),
            )
        ),
    )


def _count_on(
    db: Session, ambulance_id: int, target: date, reason: str, exclude_id: int | None
) -> int:
    query = (
        db.query(Unavailability.reason)
        .join(User, User.id == Unavailability.user_id)
        .filter(Unavailability.date_absent == target, *_active_records(ambulance_id))
    )
    if exclude_id is not None:
        query = query.filter(Unavailability.id != exclude_id)
    return sum(1 for (stored,) in query if normalize_reason(stored) == reason)


def ensure_day_has_room(
    db: Session,
    user_id: int,
    target: date,
    reason: str | None,
    exclude_id: int | None = None,
) -> None:
    """Refuse a restriction that would push its day over the limit of any of
    the employee's active workplaces.

    Raises:
        HTTPException 409: With code ``day_limit_reached``.
    """
    normalized = normalize_reason(reason)
    if normalized not in LIMITED_REASONS:
        return
    limits = (
        db.query(AvailabilityDayLimit)
        .join(UserAmbulance, UserAmbulance.ambulance_id == AvailabilityDayLimit.ambulance_id)
        .join(Ambulance, Ambulance.id == AvailabilityDayLimit.ambulance_id)
        .filter(
            AvailabilityDayLimit.reason == normalized,
            UserAmbulance.user_id == user_id,
            UserAmbulance.is_active.is_(True),
            Ambulance.is_active.is_(True),
        )
        .all()
    )
    for row in limits:
        if _count_on(db, row.ambulance_id, target, normalized, exclude_id) < row.max_per_day:
            continue
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "day_limit_reached",
                "reason": normalized,
                "max_per_day": row.max_per_day,
                "message": "The limit for this day is already used up.",
            },
        )


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    if not 1 <= month <= 12 or not 2000 <= year <= 2100:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="month and year must be valid.",
        )
    return date(year, month, 1), date(year, month, monthrange(year, month)[1])


def month_overview(db: Session, ambulance_id: int, year: int, month: int) -> dict:
    """Per day of the month, how many of the workplace's people entered each
    reason."""
    first, last = _month_bounds(year, month)
    rows = (
        db.query(Unavailability.date_absent, Unavailability.reason, func.count())
        .join(User, User.id == Unavailability.user_id)
        .filter(
            Unavailability.date_absent >= first,
            Unavailability.date_absent <= last,
            *_active_records(ambulance_id),
        )
        .group_by(Unavailability.date_absent, Unavailability.reason)
        .all()
    )
    counts: dict[date, dict[str, int]] = {}
    for day, reason, count in rows:
        bucket = counts.setdefault(day, {})
        key = normalize_reason(reason)
        bucket[key] = bucket.get(key, 0) + count
    return {
        "year": year,
        "month": month,
        "limits": day_limits(db, ambulance_id),
        "days": [
            {"date": day, "counts": counts[day]} for day in sorted(counts)
        ],
    }


def day_entries(db: Session, ambulance_id: int, target: date) -> dict:
    """One day's restrictions of the workplace's people, in entry order."""
    records = (
        db.query(Unavailability)
        .join(User, User.id == Unavailability.user_id)
        .options(joinedload(Unavailability.user), joinedload(Unavailability.entered_by))
        .filter(Unavailability.date_absent == target, *_active_records(ambulance_id))
        .order_by(
            Unavailability.entered_at.is_(None),
            Unavailability.entered_at,
            Unavailability.id,
        )
        .all()
    )
    user_ids = {record.user_id for record in records}
    workplaces: dict[int, list[str]] = {}
    if user_ids:
        for user_id, name in (
            db.query(UserAmbulance.user_id, Ambulance.name)
            .join(Ambulance, Ambulance.id == UserAmbulance.ambulance_id)
            .filter(
                UserAmbulance.user_id.in_(user_ids),
                UserAmbulance.is_active.is_(True),
                Ambulance.is_active.is_(True),
            )
            .order_by(Ambulance.name)
        ):
            workplaces.setdefault(user_id, []).append(name)

    entries = []
    for record in records:
        by = record.entered_by
        entries.append(
            {
                "id": record.id,
                "user_id": record.user_id,
                "full_name": record.user.full_name,
                "email": record.user.email,
                "workplaces": workplaces.get(record.user_id, []),
                "reason": normalize_reason(record.reason),
                "entered_at": record.entered_at or record.created_at,
                "entered_by_user_id": record.entered_by_user_id,
                "entered_by_name": (by.full_name or by.email) if by else None,
            }
        )
    return {"date": target, "limits": day_limits(db, ambulance_id), "entries": entries}
