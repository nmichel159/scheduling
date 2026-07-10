"""
FastAPI router for User Competence Assignment endpoints.

Allows ambulance managers (Role Level >= 2) to assign and remove
competences from employees working in their ambulances.
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_manager_ambulance
from app.db.session import get_db
from app.models.ambulance import Ambulance
from app.schemas.user_competence import (
    UserCompetenceAssign,
    UserCompetenceResponse,
)
from app.services.user_competence_service import (
    assign_competence,
    list_user_competences,
    remove_competence,
)

router = APIRouter()


@router.get(
    "/{ambulance_id}/employees/{user_id}/competences",
    response_model=list[UserCompetenceResponse],
    summary="List competences assigned to an employee in an ambulance",
)
def list_user_competences_endpoint(
    user_id: int,
    ambulance: Ambulance = Depends(get_manager_ambulance),
    db: Session = Depends(get_db),
) -> list[UserCompetenceResponse]:
    """Retrieve all competences assigned to an employee, scoped to the ambulance."""
    return list_user_competences(db, ambulance.id, user_id)


@router.post(
    "/{ambulance_id}/employees/{user_id}/competences",
    response_model=UserCompetenceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Assign a competence to an employee",
)
def assign_competence_endpoint(
    user_id: int,
    data: UserCompetenceAssign,
    ambulance: Ambulance = Depends(get_manager_ambulance),
    db: Session = Depends(get_db),
) -> UserCompetenceResponse:
    """Assign a competence to an employee in the manager's ambulance."""
    return assign_competence(db, ambulance.id, user_id, data.competence_id)


@router.delete(
    "/{ambulance_id}/employees/{user_id}/competences/{competence_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a competence from an employee",
)
def remove_competence_endpoint(
    user_id: int,
    competence_id: int,
    ambulance: Ambulance = Depends(get_manager_ambulance),
    db: Session = Depends(get_db),
) -> None:
    """Remove a competence assignment from an employee in the manager's ambulance."""
    remove_competence(db, ambulance.id, user_id, competence_id)
