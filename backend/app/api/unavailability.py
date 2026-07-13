"""
FastAPI router for User Availability (Unavailability) endpoints.

Provides full CRUD operations over unavailability records.
All endpoints require the ``X-User-Id`` header and enforce ownership —
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
    UnavailabilityCreate,
    UnavailabilityResponse,
    UnavailabilityUpdate,
)
from app.services.unavailability_service import (
    create_unavailability,
    delete_unavailability,
    get_unavailabilities,
    get_unavailability,
    update_unavailability,
)

router = APIRouter()


@router.post(
    "/",
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
    summary="List unavailability records",
)
def list_unavailabilities_endpoint(
    skip: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(100, ge=1, le=500, description="Max records to return"),
    date_from: Optional[date] = Query(None, description="Start date filter (inclusive)"),
    date_to: Optional[date] = Query(None, description="End date filter (inclusive)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[UnavailabilityResponse]:
    """Retrieve the authenticated user's unavailability records.

    Supports pagination via ``skip`` and ``limit``, and optional
    date-range filtering via ``date_from`` and ``date_to``.
    """
    return get_unavailabilities(db, current_user.id, skip, limit, date_from, date_to)


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
