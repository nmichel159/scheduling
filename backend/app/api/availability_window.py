"""FastAPI router for when employees may fill in their restrictions.

Reading whether a month is closed is for everybody, because the employee's
calendar needs it; it is closed as soon as any of the employee's workplaces
closed it. Everything else belongs to one workplace -- the reminder and lock
days, the month's switch, the day limits and the overview of who entered
what -- so it sits under ``/ambulances/{id}`` for the scheduler who manages
it.
"""

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_manager_ambulance
from app.db.session import get_db
from app.models.ambulance import Ambulance
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
    employee_month_status,
    month_status,
    save_window_days,
    set_month_lock,
    upcoming_month,
    window_days,
)

router = APIRouter()


@router.get(
    "/months/{year}/{month}",
    response_model=AvailabilityMonthStatus,
    summary="Whether one month is closed to the calling employee",
)
def get_month_status_endpoint(
    year: int,
    month: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AvailabilityMonthStatus:
    return AvailabilityMonthStatus(
        **employee_month_status(db, current_user.id, year, month)
    )


# --------------------------------------------------------------------------
# One workplace: its window, day limits and the overview of what its people
# entered
# --------------------------------------------------------------------------

ambulance_router = APIRouter()


def _window(db: Session, ambulance_id: int) -> AvailabilityWindow:
    reminder_day, lock_day = window_days(db, ambulance_id)
    year, month = upcoming_month()
    return AvailabilityWindow(
        reminder_day=reminder_day,
        lock_day=lock_day,
        upcoming=AvailabilityMonthStatus(**month_status(db, ambulance_id, year, month)),
    )


@ambulance_router.get(
    "/{ambulance_id}/availability/window",
    response_model=AvailabilityWindow,
    summary="The workplace's reminder and lock days with the month being filled in",
)
def get_window_endpoint(
    ambulance: Ambulance = Depends(get_manager_ambulance),
    db: Session = Depends(get_db),
) -> AvailabilityWindow:
    return _window(db, ambulance.id)


@ambulance_router.put(
    "/{ambulance_id}/availability/window",
    response_model=AvailabilityWindow,
    summary="Set the workplace's reminder and lock days",
)
def set_window_endpoint(
    data: AvailabilityWindowDays,
    ambulance: Ambulance = Depends(get_manager_ambulance),
    db: Session = Depends(get_db),
) -> AvailabilityWindow:
    save_window_days(db, ambulance.id, data.reminder_day, data.lock_day)
    return _window(db, ambulance.id)


@ambulance_router.get(
    "/{ambulance_id}/availability/months/{year}/{month}",
    response_model=AvailabilityMonthStatus,
    summary="Whether one month is closed in the workplace",
)
def get_workplace_month_status_endpoint(
    year: int,
    month: int,
    ambulance: Ambulance = Depends(get_manager_ambulance),
    db: Session = Depends(get_db),
) -> AvailabilityMonthStatus:
    return AvailabilityMonthStatus(**month_status(db, ambulance.id, year, month))


@ambulance_router.put(
    "/{ambulance_id}/availability/months/{year}/{month}/lock",
    response_model=AvailabilityMonthStatus,
    summary="Close or open one month of the workplace by hand",
)
def set_month_lock_endpoint(
    year: int,
    month: int,
    data: AvailabilityMonthLock,
    ambulance: Ambulance = Depends(get_manager_ambulance),
    db: Session = Depends(get_db),
) -> AvailabilityMonthStatus:
    return AvailabilityMonthStatus(
        **set_month_lock(db, ambulance.id, year, month, data.locked)
    )


@ambulance_router.get(
    "/{ambulance_id}/availability/day-limits",
    response_model=AvailabilityDayLimits,
    summary="How many of the workplace's people may be away on one day, per reason",
)
def get_day_limits_endpoint(
    ambulance: Ambulance = Depends(get_manager_ambulance),
    db: Session = Depends(get_db),
) -> AvailabilityDayLimits:
    return AvailabilityDayLimits(limits=day_limits(db, ambulance.id))


@ambulance_router.put(
    "/{ambulance_id}/availability/day-limits",
    response_model=AvailabilityDayLimits,
    summary="Set the workplace's per-day limits",
)
def set_day_limits_endpoint(
    data: AvailabilityDayLimitsUpdate,
    ambulance: Ambulance = Depends(get_manager_ambulance),
    db: Session = Depends(get_db),
) -> AvailabilityDayLimits:
    return AvailabilityDayLimits(
        limits=save_day_limits(db, ambulance.id, dict(data.limits))
    )


@ambulance_router.get(
    "/{ambulance_id}/availability/overview/{year}/{month}",
    response_model=AvailabilityMonthOverview,
    summary="How many of the workplace's people entered each reason on each day",
)
def get_month_overview_endpoint(
    year: int,
    month: int,
    ambulance: Ambulance = Depends(get_manager_ambulance),
    db: Session = Depends(get_db),
) -> AvailabilityMonthOverview:
    return AvailabilityMonthOverview(**month_overview(db, ambulance.id, year, month))


@ambulance_router.get(
    "/{ambulance_id}/availability/days/{target}",
    response_model=AvailabilityDayDetail,
    summary="Who of the workplace entered what on one day, in entry order",
)
def get_day_detail_endpoint(
    target: date,
    ambulance: Ambulance = Depends(get_manager_ambulance),
    db: Session = Depends(get_db),
) -> AvailabilityDayDetail:
    return AvailabilityDayDetail(**day_entries(db, ambulance.id, target))
