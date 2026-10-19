"""FastAPI router for a workplace's custom days and the month's needs.

A custom day is a named set of staffing parameters a scheduler can place on
any date of the calendar; it outranks the weekday and the day of rest. The
month overview answers what every competence needs on every date, which is
the same reading the schedule generator makes.

All routes require the caller to manage the ambulance in the path.
"""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_manager_ambulance
from app.db.session import get_db
from app.models.ambulance import Ambulance
from app.schemas.custom_day import (
    CustomDayCreate,
    CustomDayDateWrite,
    CustomDayResponse,
    CustomDayUpdate,
    MonthNeeds,
)
from app.services.custom_day_service import (
    create_custom_day,
    delete_custom_day,
    list_custom_days,
    month_needs,
    set_custom_date,
    update_custom_day,
)
from app.services.special_day_service import validate_year

router = APIRouter()


@router.get(
    "/{ambulance_id}/custom-days",
    response_model=list[CustomDayResponse],
    summary="List a workplace's custom days",
)
def list_custom_days_endpoint(
    ambulance: Ambulance = Depends(get_manager_ambulance),
    db: Session = Depends(get_db),
) -> list[CustomDayResponse]:
    return list_custom_days(db, ambulance.id)


@router.post(
    "/{ambulance_id}/custom-days",
    response_model=CustomDayResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a custom day",
)
def create_custom_day_endpoint(
    data: CustomDayCreate,
    ambulance: Ambulance = Depends(get_manager_ambulance),
    db: Session = Depends(get_db),
) -> CustomDayResponse:
    return create_custom_day(db, ambulance.id, data)


@router.put(
    "/{ambulance_id}/custom-days/{custom_day_id}",
    response_model=CustomDayResponse,
    summary="Rename a custom day or change what it needs",
)
def update_custom_day_endpoint(
    custom_day_id: int,
    data: CustomDayUpdate,
    ambulance: Ambulance = Depends(get_manager_ambulance),
    db: Session = Depends(get_db),
) -> CustomDayResponse:
    return update_custom_day(db, ambulance.id, custom_day_id, data)


@router.delete(
    "/{ambulance_id}/custom-days/{custom_day_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a custom day; its dates return to the calendar",
)
def delete_custom_day_endpoint(
    custom_day_id: int,
    ambulance: Ambulance = Depends(get_manager_ambulance),
    db: Session = Depends(get_db),
) -> None:
    delete_custom_day(db, ambulance.id, custom_day_id)


@router.put(
    "/{ambulance_id}/custom-day-dates",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Staff a date as a custom day, or by the calendar again",
)
def set_custom_date_endpoint(
    data: CustomDayDateWrite,
    ambulance: Ambulance = Depends(get_manager_ambulance),
    db: Session = Depends(get_db),
) -> None:
    set_custom_date(db, ambulance.id, data.day, data.custom_day_id)


@router.get(
    "/{ambulance_id}/competence-needs",
    response_model=MonthNeeds,
    summary="What every competence needs on every date of a month",
)
def month_needs_endpoint(
    year: int = Query(...),
    month: int = Query(..., ge=1, le=12),
    scenario_id: int | None = Query(None),
    ambulance: Ambulance = Depends(get_manager_ambulance),
    db: Session = Depends(get_db),
) -> MonthNeeds:
    validate_year(year)
    return month_needs(db, ambulance.id, year, month, scenario_id)
