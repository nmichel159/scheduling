"""When employees may fill in their restrictions for a month.

A month is filled in during the month before it. On the *reminder day* of
that month the server mails the workplace's employees to do it; from the
*lock day* on, the month is closed and only the scheduler can change it.
Every workplace has its own: both days belong to its scheduler, and so does
the last word -- a month can be closed early or opened again by hand, and a
hand-set state wins over the lock day until it is pressed again. An
employee of several workplaces is closed out as soon as any of them closes.

A month that has already passed stays closed whatever was pressed -- that
rule is older than this module and the scheduler's switch is about the
months still being planned.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
import logging
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.ambulance import Ambulance
from app.models.associations import UserAmbulance
from app.models.availability_window import AvailabilityPeriod, AvailabilitySettings
from app.models.user import User
from app.services.database_conflict import commit_or_conflict
from app.services.email_service import (
    EmailError,
    EmailNotConfiguredError,
    build_message,
    is_valid_email,
    send_message,
)


logger = logging.getLogger(__name__)

DEFAULT_REMINDER_DAY = 14
DEFAULT_LOCK_DAY = 15
#: Every month has this many days, so a lock day up to it always exists.
LAST_ALLOWED_DAY = 28

MONTH_NAMES_GENITIVE = [
    "január",
    "február",
    "marec",
    "apríl",
    "máj",
    "jún",
    "júl",
    "august",
    "september",
    "október",
    "november",
    "december",
]


def local_now() -> datetime:
    """The time on the clinic's clock, which the days of the month follow."""
    return datetime.now(ZoneInfo(settings.AUTOMATIC_SCHEDULE_GENERATION_TIMEZONE))


def local_today() -> date:
    return local_now().date()


def _previous_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def _next_month(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def window_days(db: Session, ambulance_id: int | None) -> tuple[int, int]:
    """The workplace's reminder and lock day, the defaults until one is saved.

    ``None`` is nobody's workplace: the defaults.
    """
    row = (
        db.query(AvailabilitySettings)
        .filter(AvailabilitySettings.ambulance_id == ambulance_id)
        .first()
        if ambulance_id is not None
        else None
    )
    if row is None:
        return DEFAULT_REMINDER_DAY, DEFAULT_LOCK_DAY
    return row.reminder_day, row.lock_day


def save_window_days(
    db: Session, ambulance_id: int, reminder_day: int, lock_day: int
) -> tuple[int, int]:
    """Store the scheduler's two days for their workplace.

    Raises:
        HTTPException 422: If the reminder does not come before the lock or
            either day is outside 1..28.
    """
    if not 1 <= reminder_day < lock_day <= LAST_ALLOWED_DAY:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "invalid_days",
                "message": "The reminder must come before the lock, both within 1..28.",
            },
        )
    row = (
        db.query(AvailabilitySettings)
        .filter(AvailabilitySettings.ambulance_id == ambulance_id)
        .first()
    )
    if row is None:
        row = AvailabilitySettings(ambulance_id=ambulance_id)
        db.add(row)
    row.reminder_day = reminder_day
    row.lock_day = lock_day
    commit_or_conflict(db, "The availability window could not be saved.")
    return reminder_day, lock_day


def _period(
    db: Session, ambulance_id: int | None, year: int, month: int
) -> AvailabilityPeriod | None:
    if ambulance_id is None:
        return None
    return (
        db.query(AvailabilityPeriod)
        .filter(
            AvailabilityPeriod.ambulance_id == ambulance_id,
            AvailabilityPeriod.year == year,
            AvailabilityPeriod.month == month,
        )
        .first()
    )


def _ensure_period(db: Session, ambulance_id: int, year: int, month: int) -> AvailabilityPeriod:
    """The month's row, created if this is the first thing done about it."""
    row = _period(db, ambulance_id, year, month)
    if row is not None:
        return row
    db.add(AvailabilityPeriod(ambulance_id=ambulance_id, year=year, month=month))
    try:
        db.commit()
    except IntegrityError:
        # Another process created it in the meantime; that row is as good.
        db.rollback()
    return _period(db, ambulance_id, year, month)


def period_dates(
    db: Session, ambulance_id: int | None, year: int, month: int
) -> tuple[date, date]:
    """The reminder date and the lock date of one workplace's month."""
    reminder_day, lock_day = window_days(db, ambulance_id)
    prev_year, prev_month = _previous_month(year, month)
    return date(prev_year, prev_month, reminder_day), date(prev_year, prev_month, lock_day)


def month_status(
    db: Session,
    ambulance_id: int | None,
    year: int,
    month: int,
    today: date | None = None,
) -> dict:
    """Whether one workplace's month is closed, and why."""
    today = today or local_today()
    reminder_date, lock_date = period_dates(db, ambulance_id, year, month)
    row = _period(db, ambulance_id, year, month)
    manual = row.is_locked if row is not None else None
    is_past = date(year, month, 1) < today.replace(day=1)
    if is_past:
        locked = True
    elif manual is not None:
        locked = manual
    else:
        locked = today >= lock_date
    return {
        "year": year,
        "month": month,
        "locked": locked,
        "manual": manual,
        "is_past": is_past,
        "reminder_date": reminder_date,
        "lock_date": lock_date,
        "reminder_sent_at": row.reminder_sent_at if row else None,
        "reminder_status": row.reminder_status if row else None,
        "reminder_recipients": row.reminder_recipients if row else None,
    }


def _workplaces_of(db: Session, user_id: int) -> list[int]:
    """The active workplaces the employee is an active member of."""
    return [
        ambulance_id
        for (ambulance_id,) in db.query(UserAmbulance.ambulance_id)
        .join(Ambulance, Ambulance.id == UserAmbulance.ambulance_id)
        .filter(
            UserAmbulance.user_id == user_id,
            UserAmbulance.is_active.is_(True),
            Ambulance.is_active.is_(True),
        )
        .order_by(UserAmbulance.ambulance_id)
    ]


def employee_month_status(
    db: Session, user_id: int, year: int, month: int, today: date | None = None
) -> dict:
    """Whether one month is closed to an employee.

    It is closed as soon as any of their workplaces closed it: that
    workplace's scheduler is planning it already. Shown is the closing
    workplace's status, or the one closing first while all are open.
    """
    statuses = [
        month_status(db, ambulance_id, year, month, today)
        for ambulance_id in _workplaces_of(db, user_id)
    ] or [month_status(db, None, year, month, today)]
    closed = [entry for entry in statuses if entry["locked"]]
    return min(closed or statuses, key=lambda entry: entry["lock_date"])


def ensure_month_open(db: Session, user_id: int, target: date) -> None:
    """Refuse an employee's change to a month one of their workplaces closed.

    Raises:
        HTTPException 400: With code ``month_locked``.
    """
    if employee_month_status(db, user_id, target.year, target.month)["locked"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "month_locked",
                "message": "Restrictions for this month are closed.",
            },
        )


def set_month_lock(
    db: Session, ambulance_id: int, year: int, month: int, locked: bool
) -> dict:
    """Close or open one workplace's month by hand.

    Raises:
        HTTPException 422: For a month that has already passed.
    """
    if not 1 <= month <= 12 or not 2000 <= year <= 2100:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="month and year must be valid.",
        )
    if date(year, month, 1) < local_today().replace(day=1):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "past_month", "message": "A past month stays closed."},
        )
    row = _ensure_period(db, ambulance_id, year, month)
    row.is_locked = locked
    commit_or_conflict(db, "The month could not be closed or opened.")
    return month_status(db, ambulance_id, year, month)


def upcoming_month(today: date | None = None) -> tuple[int, int]:
    """The month being filled in now: always the next calendar month."""
    today = today or local_today()
    return _next_month(today.year, today.month)


# --------------------------------------------------------------------------
# The reminder
# --------------------------------------------------------------------------


def period_label(month: int, year: int) -> str:
    return f"{MONTH_NAMES_GENITIVE[month - 1]} {year}"


def fill_deadline(lock_date: date) -> date:
    """The last day an employee can still fill in: the day before the lock."""
    return lock_date - timedelta(days=1)


def reminder_message(db: Session, ambulance_id: int | None, year: int, month: int) -> dict:
    """Subject and body of the reminder for one workplace's month."""
    _reminder_date, lock_date = period_dates(db, ambulance_id, year, month)
    deadline = fill_deadline(lock_date)
    period = period_label(month, year)
    due = f"{deadline.day}. {deadline.month}. {deadline.year}"
    return {
        "subject": f"Vyplnenie obmedzení na {period} – do {due}",
        "body": (
            "Dobrý deň,\n\n"
            f"prosím, vyplňte si obmedzenia, dovolenky a želania na {period} "
            f"najneskôr do {due}.\n\n"
            f"Od {lock_date.day}. {lock_date.month}. sa obmedzenia na tento "
            "mesiac uzatvoria a ďalšie zmeny bude môcť urobiť už len "
            "rozvrhár.\n\n"
            f"{settings.APP_URL}\n\n"
            "Ďakujem."
        ),
    }


def reminder_addresses(db: Session, ambulance_id: int) -> list[str]:
    """Every active employee of the workplace, once each."""
    rows = (
        db.query(User.email)
        .join(UserAmbulance, UserAmbulance.user_id == User.id)
        .filter(
            UserAmbulance.ambulance_id == ambulance_id,
            User.is_active.is_(True),
            UserAmbulance.is_active.is_(True),
        )
        .distinct()
        .order_by(User.email)
        .all()
    )
    return [email for (email,) in rows if is_valid_email(email or "")]


def _claim_reminder(
    db: Session, ambulance_id: int, year: int, month: int
) -> AvailabilityPeriod | None:
    """Mark the month's reminder as taken, or ``None`` if it already was.

    The conditional update is the claim: of two server processes polling at
    once, only one sees its row change.
    """
    _ensure_period(db, ambulance_id, year, month)
    claimed = db.execute(
        update(AvailabilityPeriod)
        .where(
            AvailabilityPeriod.ambulance_id == ambulance_id,
            AvailabilityPeriod.year == year,
            AvailabilityPeriod.month == month,
            AvailabilityPeriod.reminder_sent_at.is_(None),
        )
        .values(reminder_sent_at=datetime.now(timezone.utc))
    ).rowcount
    db.commit()
    if not claimed:
        return None
    return _period(db, ambulance_id, year, month)


def _send_workplace_reminder(
    db: Session, ambulance_id: int, now: datetime
) -> str | None:
    """Send one workplace's reminder for next month if its day has come."""
    today = now.date()
    year, month = upcoming_month(today)
    current = month_status(db, ambulance_id, year, month, today)
    if today < current["reminder_date"] or now.hour < settings.AVAILABILITY_REMINDER_HOUR:
        return None
    if current["reminder_sent_at"] is not None:
        return None

    row = _claim_reminder(db, ambulance_id, year, month)
    if row is None:
        return None

    addresses = reminder_addresses(db, ambulance_id)
    if current["locked"] or not addresses:
        outcome = "skipped"
    else:
        message = reminder_message(db, ambulance_id, year, month)
        outcome = "sent"
        try:
            for address in addresses:
                result = send_message(
                    build_message(
                        subject=message["subject"],
                        recipients=[address],
                        text_body=message["body"] + "\n",
                    )
                )
                if result == "dry-run":
                    outcome = "dry-run"
        except EmailNotConfiguredError:
            outcome = "not-configured"
            logger.warning("Availability reminder not sent: mail is not configured.")
        except EmailError as exc:
            outcome = "failed"
            logger.warning("Availability reminder failed: %s", exc)

    row.reminder_status = outcome
    row.reminder_recipients = len(addresses)
    db.commit()
    return outcome


def send_due_reminder(db: Session, now: datetime | None = None) -> dict[int, str]:
    """Send next month's reminder of every workplace whose day has come.

    At most once a month per workplace. Each employee gets their own
    message, so nobody sees the others' addresses. A month already closed
    is not announced: there is nothing left to fill in.

    Returns:
        Workplace id -> the recorded status, for the workplaces sent now.
    """
    now = now or local_now()
    ambulance_ids = [
        ambulance_id
        for (ambulance_id,) in db.query(Ambulance.id)
        .filter(Ambulance.is_active.is_(True))
        .order_by(Ambulance.id)
    ]
    outcomes = {}
    for ambulance_id in ambulance_ids:
        outcome = _send_workplace_reminder(db, ambulance_id, now)
        if outcome is not None:
            outcomes[ambulance_id] = outcome
    return outcomes


def check_and_send_reminder() -> dict[int, str]:
    """The server clock's entry point: one session per check."""
    with SessionLocal() as db:
        return send_due_reminder(db)


async def availability_reminder_loop(
    stop_event: asyncio.Event, poll_seconds: float | None = None
) -> None:
    """Poll the clock beside the generation clock and stop with FastAPI."""
    interval = poll_seconds or settings.AUTOMATIC_SCHEDULE_GENERATION_POLL_SECONDS
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
            continue
        except asyncio.TimeoutError:
            pass
        try:
            await asyncio.to_thread(check_and_send_reminder)
        except Exception:  # pragma: no cover - keeps the server loop alive
            logger.exception("Availability reminder check failed")
