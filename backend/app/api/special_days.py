"""FastAPI router for the special-day (day of rest) calendar of a workplace.

The public-holiday calendar itself comes from the ``holidays`` library and
is the same for every workplace, so it needs no storage and no editing; what
these endpoints write are one workplace's exceptions to it.

Reading and writing are not the same permission here. Which dates a clinic
treats as days of rest is an administrator's decision: it follows from the
law and from how the hospital runs, not from this month's schedule. A
scheduler has to see the year -- it decides which column of a competence
staffs a date -- but may not change it, so the reads are scoped to a
workplace the caller manages (``get_manager_ambulance``) while every write
requires level 3 (``get_admin_ambulance``).
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_admin_ambulance, get_manager_ambulance
from app.db.session import get_db
from app.models.ambulance import Ambulance
from app.schemas.special_day import (
    SpecialDayCopy,
    SpecialDayEntry,
    SpecialDayWrite,
    SpecialDayYear,
)
from app.services.special_day_service import (
    clear_special_day,
    copy_special_days,
    set_special_day,
    validate_year,
    year_entries,
)

router = APIRouter()


def _year_response(db: Session, ambulance_id: int, year: int) -> SpecialDayYear:
    return SpecialDayYear(
        ambulance_id=ambulance_id,
        year=year,
        entries=[SpecialDayEntry(**entry) for entry in year_entries(db, ambulance_id, year)],
    )


@router.get(
    "/{ambulance_id}/special-days",
    response_model=SpecialDayYear,
    summary="One workplace's days of rest for a year",
)
def list_special_days_endpoint(
    year: int = Query(..., description="Calendar year to compute."),
    ambulance: Ambulance = Depends(get_manager_ambulance),
    db: Session = Depends(get_db),
) -> SpecialDayYear:
    """List the year as this workplace sees it: library plus its overrides."""
    validate_year(year)
    return _year_response(db, ambulance.id, year)


@router.put(
    "/{ambulance_id}/special-days",
    response_model=SpecialDayYear,
    summary="Mark a date as a day of rest, or as worked",
)
def set_special_day_endpoint(
    data: SpecialDayWrite,
    ambulance: Ambulance = Depends(get_admin_ambulance),
    db: Session = Depends(get_db),
) -> SpecialDayYear:
    """Override the library for one date.

    Setting a date to what the library already says removes the override
    rather than storing it, so the screen never shows an inherited day as a
    local decision. The whole year comes back, because that is the list the
    screen is showing and one write can also erase a row.
    """
    validate_year(data.day.year)
    set_special_day(db, ambulance.id, data.day, data.is_rest_day, data.name)
    return _year_response(db, ambulance.id, data.day.year)


@router.delete(
    "/{ambulance_id}/special-days/{day}",
    response_model=SpecialDayYear,
    summary="Hand one date back to the library",
)
def clear_special_day_endpoint(
    day: date,
    ambulance: Ambulance = Depends(get_admin_ambulance),
    db: Session = Depends(get_db),
) -> SpecialDayYear:
    """Drop this workplace's override for a date, whichever way it pointed."""
    validate_year(day.year)
    clear_special_day(db, ambulance.id, day)
    return _year_response(db, ambulance.id, day.year)


@router.post(
    "/{ambulance_id}/special-days/copy",
    response_model=SpecialDayYear,
    status_code=status.HTTP_200_OK,
    summary="Copy another workplace's overrides for a year",
)
def copy_special_days_endpoint(
    data: SpecialDayCopy,
    ambulance: Ambulance = Depends(get_admin_ambulance),
    db: Session = Depends(get_db),
) -> SpecialDayYear:
    """Replace this workplace's year with another workplace's.

    Only an administrator gets here, and an administrator reaches every
    workplace, so the source needs no ownership check of its own -- only to
    exist, to be active, and not to be the target.
    """
    validate_year(data.year)
    if data.source_ambulance_id == ambulance.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The source workplace must differ from the target.",
        )
    source = (
        db.query(Ambulance)
        .filter(
            Ambulance.id == data.source_ambulance_id,
            Ambulance.is_active.is_(True),
        )
        .first()
    )
    if source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ambulance with id {data.source_ambulance_id} not found or inactive.",
        )
    copy_special_days(db, source.id, ambulance.id, data.year)
    return _year_response(db, ambulance.id, data.year)
