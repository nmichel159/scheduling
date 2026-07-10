"""
FastAPI router for Competence Codebook CRUD endpoints.

Allows ambulance managers (Role Level >= 2) to manage the competence
definitions (codebook) scoped to their own ambulances.
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_manager_ambulance
from app.db.session import get_db
from app.models.ambulance import Ambulance
from app.schemas.competence import (
    CompetenceCreate,
    CompetenceResponse,
    CompetenceUpdate,
)
from app.services.competence_service import (
    create_competence,
    delete_competence,
    list_competences,
    update_competence,
)

router = APIRouter()


@router.get(
    "/{ambulance_id}/competences",
    response_model=list[CompetenceResponse],
    summary="List competences for an ambulance",
)
def list_competences_endpoint(
    ambulance: Ambulance = Depends(get_manager_ambulance),
    db: Session = Depends(get_db),
) -> list[CompetenceResponse]:
    """Retrieve all active competences defined for the manager's ambulance."""
    return list_competences(db, ambulance.id)


@router.post(
    "/{ambulance_id}/competences",
    response_model=CompetenceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a competence for an ambulance",
)
def create_competence_endpoint(
    data: CompetenceCreate,
    ambulance: Ambulance = Depends(get_manager_ambulance),
    db: Session = Depends(get_db),
) -> CompetenceResponse:
    """Add a new competence definition to the manager's ambulance codebook."""
    return create_competence(db, ambulance.id, data)


@router.put(
    "/{ambulance_id}/competences/{competence_id}",
    response_model=CompetenceResponse,
    summary="Update a competence",
)
def update_competence_endpoint(
    competence_id: int,
    data: CompetenceUpdate,
    ambulance: Ambulance = Depends(get_manager_ambulance),
    db: Session = Depends(get_db),
) -> CompetenceResponse:
    """Update an existing competence in the manager's ambulance codebook."""
    return update_competence(db, competence_id, ambulance.id, data)


@router.delete(
    "/{ambulance_id}/competences/{competence_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a competence",
)
def delete_competence_endpoint(
    competence_id: int,
    ambulance: Ambulance = Depends(get_manager_ambulance),
    db: Session = Depends(get_db),
) -> None:
    """Remove a competence from the manager's ambulance codebook."""
    delete_competence(db, competence_id, ambulance.id)
