"""FastAPI router for when employees may fill in their restrictions.

Reading whether a month is closed is for everybody, because the employee's
calendar needs it; the days, the switch, the day limits and the overview of
who entered what belong to the scheduler.
"""

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, require_manager_role
from app.db.session import get_db
from app.models.user import User
from app.schemas.availability_window import (
    AvailabilityDayDetail,
    AvailabilityDayLimits,
    AvailabilityDayLimitsUpdate,
    AvailabilityMonthOverview,
    AvailabilityMonthLock,
    AvailabilityMonthStatus,
    AvailabilityWindow,
    AvailabilityWindowDays,
)
from app.services.availability_overview_service import (
    day_entries,
    day_limits,
    month_overview,
    save_day_limits,
)
from app.services.availability_window_service import (
    month_status,
    save_window_days,
    set_month_lock,
    upcoming_month,
    window_days,
)

router = APIRouter()


def _window(db: Session) -> AvailabilityWindow:
    reminder_day, lock_day = window_days(db)
    year, month = upcoming_month()
    return AvailabilityWindow(
        reminder_day=reminder_day,
        lock_day=lock_day,
        upcoming=AvailabilityMonthStatus(**month_status(db, year, month)),
    )


@router.get(
    "/window",
    response_model=AvailabilityWindow,
    summary="The reminder and lock days with the month being filled in",
)
def get_window_endpoint(
    _manager: User = Depends(require_manager_role),
    db: Session = Depends(get_db),
) -> AvailabilityWindow:
    return _window(db)


@router.put(
    "/window",
    response_model=AvailabilityWindow,
    summary="Set the reminder and lock days",
)
def set_window_endpoint(
    data: AvailabilityWindowDays,
    _manager: User = Depends(require_manager_role),
    db: Session = Depends(get_db),
) -> AvailabilityWindow:
    save_window_days(db, data.reminder_day, data.lock_day)
    return _window(db)


@router.get(
    "/months/{year}/{month}",
    response_model=AvailabilityMonthStatus,
    summary="Whether one month is closed to the employees",
)
def get_month_status_endpoint(
    year: int,
    month: int,
    _current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AvailabilityMonthStatus:
    return AvailabilityMonthStatus(**month_status(db, year, month))


@router.put(
    "/months/{year}/{month}/lock",
    response_model=AvailabilityMonthStatus,
    summary="Close or open one month by hand",
)
def set_month_lock_endpoint(
    year: int,
    month: int,
    data: AvailabilityMonthLock,
    _manager: User = Depends(require_manager_role),
    db: Session = Depends(get_db),
) -> AvailabilityMonthStatus:
    return AvailabilityMonthStatus(**set_month_lock(db, year, month, data.locked))


@router.get(
    "/day-limits",
    response_model=AvailabilityDayLimits,
    summary="How many people may be away on one day, per reason",
)
def get_day_limits_endpoint(
    _manager: User = Depends(require_manager_role),
    db: Session = Depends(get_db),
) -> AvailabilityDayLimits:
    return AvailabilityDayLimits(limits=day_limits(db))


@router.put(
    "/day-limits",
    response_model=AvailabilityDayLimits,
    summary="Set the per-day limits",
)
def set_day_limits_endpoint(
    data: AvailabilityDayLimitsUpdate,
    _manager: User = Depends(require_manager_role),
    db: Session = Depends(get_db),
) -> AvailabilityDayLimits:
    return AvailabilityDayLimits(limits=save_day_limits(db, dict(data.limits)))


@router.get(
    "/overview/{year}/{month}",
    response_model=AvailabilityMonthOverview,
    summary="How many people entered each reason on each day of a month",
)
def get_month_overview_endpoint(
    year: int,
    month: int,
    _manager: User = Depends(require_manager_role),
    db: Session = Depends(get_db),
) -> AvailabilityMonthOverview:
    return AvailabilityMonthOverview(**month_overview(db, year, month))


@router.get(
    "/days/{target}",
    response_model=AvailabilityDayDetail,
    summary="Who entered what on one day, in the order it was entered",
)
def get_day_detail_endpoint(
    target: date,
    _manager: User = Depends(require_manager_role),
    db: Session = Depends(get_db),
) -> AvailabilityDayDetail:
    return AvailabilityDayDetail(**day_entries(db, target))
