"""
FastAPI router for User Availability (Unavailability) endpoints.

Provides full CRUD operations over unavailability records.
All endpoints require an authenticated HttpOnly cookie session and enforce ownership —
a user may only manage their own records.
"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.unavailability import (
    MonthlyDutyWish,
    UnavailabilityCreate,
    UnavailabilityResponse,
    UnavailabilityUpdate,
)
from app.services.unavailability_service import (
    create_unavailability,
    delete_unavailability,
    get_monthly_duty_wish,
    get_unavailabilities,
    get_unavailability,
    set_monthly_duty_wish,
    update_unavailability,
)

router = APIRouter()


@router.post(
    "/",
    response_model=UnavailabilityResponse,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
@router.post(
    "",
    response_model=UnavailabilityResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an unavailability record",
)
def create_unavailability_endpoint(
    data: UnavailabilityCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UnavailabilityResponse:
    """Create a new unavailability record for the authenticated user."""
    return create_unavailability(db, current_user.id, data)


@router.get(
    "/",
    response_model=list[UnavailabilityResponse],
    include_in_schema=False,
)
@router.get(
    "",
    response_model=list[UnavailabilityResponse],
    summary="List unavailability records",
)
def list_unavailabilities_endpoint(
    skip: int = Query(0, ge=0, deprecated=True, description="Legacy pagination offset"),
    limit: int = Query(100, ge=1, le=500, description="Max records to return"),
    date_from: Optional[date] = Query(None, description="Start date filter (inclusive)"),
    date_to: Optional[date] = Query(None, description="End date filter (inclusive)"),
    after_date: Optional[date] = Query(None, description="Cursor date from the previous page"),
    after_id: Optional[int] = Query(None, ge=0, description="Cursor ID from the previous page"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[UnavailabilityResponse]:
    """Retrieve the authenticated user's unavailability records.

    Supports keyset pagination via ``after_date``, ``after_id`` and ``limit``.
    The legacy ``skip`` parameter remains available for older clients.
    """
    return get_unavailabilities(
        db,
        current_user.id,
        skip,
        limit,
        date_from,
        date_to,
        after_date,
        after_id,
    )


# Declared before the ``/{unavailability_id}`` routes so the literal path is
# matched first instead of being parsed as a record ID.
@router.get(
    "/monthly-wish",
    response_model=MonthlyDutyWish,
    summary="Get the monthly duty wish",
)
def get_monthly_duty_wish_endpoint(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MonthlyDutyWish:
    """Return how many duties a month the authenticated user wants at most."""
    return get_monthly_duty_wish(db, current_user.id)


@router.put(
    "/monthly-wish",
    response_model=MonthlyDutyWish,
    summary="Set the monthly duty wish",
)
def set_monthly_duty_wish_endpoint(
    data: MonthlyDutyWish,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MonthlyDutyWish:
    """Store the authenticated user's monthly duty wish (null clears it)."""
    return set_monthly_duty_wish(db, current_user.id, data)


@router.get(
    "/{unavailability_id}",
    response_model=UnavailabilityResponse,
    summary="Get a single unavailability record",
)
def get_unavailability_endpoint(
    unavailability_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UnavailabilityResponse:
    """Retrieve a single unavailability record by ID (ownership enforced)."""
    return get_unavailability(db, unavailability_id, current_user.id)


@router.put(
    "/{unavailability_id}",
    response_model=UnavailabilityResponse,
    summary="Update an unavailability record",
)
def update_unavailability_endpoint(
    unavailability_id: int,
    data: UnavailabilityUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UnavailabilityResponse:
    """Update an existing unavailability record (partial updates supported)."""
    return update_unavailability(db, unavailability_id, current_user.id, data)


@router.delete(
    "/{unavailability_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an unavailability record",
)
def delete_unavailability_endpoint(
    unavailability_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Delete an unavailability record (ownership enforced)."""
    delete_unavailability(db, unavailability_id, current_user.id)
