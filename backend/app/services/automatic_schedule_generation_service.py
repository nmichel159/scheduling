"""Server-side monthly generation of unapproved ambulance schedules."""

from __future__ import annotations

import asyncio
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, timezone
import logging
from typing import Callable
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.ambulance import Ambulance
from app.models.associations import UserAmbulance
from app.models.automatic_schedule_generation_run import (
    AutomaticScheduleGenerationRun,
)
from app.models.competence import Competence
from app.services.schedule_generation_service import (
    ScheduleGenerationError,
    generate_ambulance_monthly_schedule,
)
from app.services.schedule_service import save_ambulance_monthly_schedule


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AutomaticGenerationResult:
    """Summary of one claimed automatic monthly generation attempt."""

    target_year: int
    target_month: int
    ordered_ambulance_ids: tuple[int, ...]
    successful_ambulance_ids: tuple[int, ...]
    failed_ambulance_ids: tuple[int, ...]


def next_calendar_month(year: int, month: int) -> tuple[int, int]:
    """Return the year and month immediately following the supplied period."""
    return (year + 1, 1) if month == 12 else (year, month + 1)


def due_target_period(now: datetime) -> tuple[int, int] | None:
    """Return next month once the configured local monthly deadline is due."""
    local_now = now.astimezone(
        ZoneInfo(settings.AUTOMATIC_SCHEDULE_GENERATION_TIMEZONE)
    )
    deadline = local_now.replace(
        day=settings.AUTOMATIC_SCHEDULE_GENERATION_DAY,
        hour=settings.AUTOMATIC_SCHEDULE_GENERATION_HOUR,
        minute=0,
        second=0,
        microsecond=0,
    )
    if local_now < deadline:
        return None
    return next_calendar_month(local_now.year, local_now.month)


def _monthly_demand(ambulance: Ambulance, year: int, month: int) -> int:
    """Measure workplace size by the target month's required duty slots."""
    days = [
        date(year, month, day)
        for day in range(1, monthrange(year, month)[1] + 1)
    ]
    demand = 0
    for competence in ambulance.competences:
        if not competence.is_active:
            continue
        weekday_counts = {
            item.weekday: item.required_count
            for item in competence.weekday_requirements
        }
        demand += sum(
            weekday_counts.get(work_date.weekday(), competence.required_count)
            for work_date in days
        )
    return demand


def _active_employee_count(ambulance: Ambulance) -> int:
    """Count active memberships whose related user is also active."""
    return sum(
        1
        for assignment in ambulance.user_ambulances
        if assignment.is_active
        and assignment.user is not None
        and assignment.user.is_active
    )


def ordered_ambulances(
    db: Session,
    year: int,
    month: int,
) -> list[Ambulance]:
    """Load active workplaces in non-urgent, size-descending order."""
    ambulances = (
        db.query(Ambulance)
        .options(
            selectinload(Ambulance.competences).selectinload(
                Competence.weekday_requirements
            ),
            selectinload(Ambulance.user_ambulances).selectinload(
                UserAmbulance.user
            ),
        )
        .filter(Ambulance.is_active.is_(True))
        .all()
    )
    return sorted(
        ambulances,
        key=lambda ambulance: (
            bool(ambulance.isurgent),
            -_monthly_demand(ambulance, year, month),
            -_active_employee_count(ambulance),
            ambulance.id,
        ),
    )


def _claim_period(
    db: Session,
    target_year: int,
    target_month: int,
) -> AutomaticScheduleGenerationRun | None:
    """Atomically claim a target month so multiple server processes cannot repeat it."""
    run = AutomaticScheduleGenerationRun(
        target_year=target_year,
        target_month=target_month,
        status="RUNNING",
    )
    db.add(run)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return None
    db.refresh(run)
    return run


def run_automatic_generation(
    db: Session,
    target_year: int,
    target_month: int,
) -> AutomaticGenerationResult | None:
    """Claim, generate, and save every ambulance sequentially as a draft."""
    run = _claim_period(db, target_year, target_month)
    if run is None:
        return None

    ambulances = ordered_ambulances(db, target_year, target_month)
    ordered_ids = tuple(ambulance.id for ambulance in ambulances)
    successful_ids: list[int] = []
    failures: list[dict[str, object]] = []

    for ambulance in ambulances:
        try:
            generated = generate_ambulance_monthly_schedule(
                db,
                ambulance.id,
                target_month,
                target_year,
            )
            save_ambulance_monthly_schedule(
                db,
                ambulance.id,
                target_month,
                target_year,
                generated.entries,
            )
            successful_ids.append(ambulance.id)
        except ScheduleGenerationError as exc:
            db.rollback()
            failures.append(
                {
                    "ambulance_id": ambulance.id,
                    "error": exc.message,
                    "issues": exc.issues,
                }
            )
            logger.warning(
                "Automatic schedule generation was infeasible for ambulance %s: %s",
                ambulance.id,
                exc.message,
            )
        except HTTPException as exc:
            db.rollback()
            failures.append(
                {
                    "ambulance_id": ambulance.id,
                    "error": str(exc.detail),
                }
            )
            logger.warning(
                "Automatic schedule save failed validation for ambulance %s: %s",
                ambulance.id,
                exc.detail,
            )
        except Exception as exc:  # pragma: no cover - defensive service isolation
            db.rollback()
            failures.append(
                {
                    "ambulance_id": ambulance.id,
                    "error": type(exc).__name__,
                }
            )
            logger.exception(
                "Unexpected automatic schedule failure for ambulance %s",
                ambulance.id,
            )

    if failures and successful_ids:
        run.status = "PARTIAL"
    elif failures:
        run.status = "FAILED"
    else:
        run.status = "COMPLETED"
    run.summary = {
        "ordered_ambulance_ids": list(ordered_ids),
        "successful_ambulance_ids": successful_ids,
        "failures": failures,
    }
    run.completed_at = datetime.now(timezone.utc)
    db.commit()

    return AutomaticGenerationResult(
        target_year=target_year,
        target_month=target_month,
        ordered_ambulance_ids=ordered_ids,
        successful_ambulance_ids=tuple(successful_ids),
        failed_ambulance_ids=tuple(
            int(item["ambulance_id"]) for item in failures
        ),
    )


def check_and_run_automatic_generation(
    now: datetime | None = None,
) -> AutomaticGenerationResult | None:
    """Check local time and run the due target month at most once."""
    reference_time = now or datetime.now(
        ZoneInfo(settings.AUTOMATIC_SCHEDULE_GENERATION_TIMEZONE)
    )
    target_period = due_target_period(reference_time)
    if target_period is None:
        return None
    target_year, target_month = target_period
    with SessionLocal() as db:
        return run_automatic_generation(db, target_year, target_month)


async def automatic_schedule_generation_loop(
    stop_event: asyncio.Event,
    check: Callable[[], AutomaticGenerationResult | None] = (
        check_and_run_automatic_generation
    ),
    poll_seconds: float | None = None,
) -> None:
    """Poll time without blocking API requests and stop cleanly with FastAPI."""
    interval = poll_seconds or settings.AUTOMATIC_SCHEDULE_GENERATION_POLL_SECONDS
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
            continue
        except asyncio.TimeoutError:
            pass
        try:
            await asyncio.to_thread(check)
        except Exception:  # pragma: no cover - keeps the server loop alive
            logger.exception("Automatic schedule time check failed")
