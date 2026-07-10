"""
Service layer for Competence Codebook CRUD.

Business rules:
- Competences belong to a specific ambulance (scoped by ambulance_id).
- Only the ambulance manager may create, update, or delete competences
  (ownership is enforced at the dependency level).
"""

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.competence import Competence
from app.schemas.competence import CompetenceCreate, CompetenceUpdate


def list_competences(db: Session, ambulance_id: int) -> list[Competence]:
    """List all active competences belonging to an ambulance.

    Args:
        db: Active database session.
        ambulance_id: The ambulance whose competences to list.

    Returns:
        A list of :class:`Competence` instances.
    """
    return (
        db.query(Competence)
        .filter(
            Competence.ambulance_id == ambulance_id,
            Competence.is_active == True,
        )
        .order_by(Competence.name)
        .all()
    )


def get_competence(db: Session, competence_id: int, ambulance_id: int) -> Competence:
    """Retrieve a single competence by ID, scoped to an ambulance.

    Args:
        db: Active database session.
        competence_id: The competence to retrieve.
        ambulance_id: The ambulance scope.

    Returns:
        The :class:`Competence` instance.

    Raises:
        HTTPException 404: If the competence does not exist or does not belong
            to the given ambulance.
    """
    competence = (
        db.query(Competence)
        .filter(
            Competence.id == competence_id,
            Competence.ambulance_id == ambulance_id,
            Competence.is_active == True,
        )
        .first()
    )
    if not competence:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Competence with id {competence_id} not found in ambulance {ambulance_id}.",
        )
    return competence


def create_competence(db: Session, ambulance_id: int, data: CompetenceCreate) -> Competence:
    """Create a new competence for an ambulance.

    Args:
        db: Active database session.
        ambulance_id: The ambulance to assign the competence to.
        data: Validated creation payload.

    Returns:
        The newly created :class:`Competence` instance.
    """
    competence = Competence(
        name=data.name,
        description=data.description,
        ambulance_id=ambulance_id,
        is_active=True,
    )
    db.add(competence)
    db.commit()
    db.refresh(competence)
    return competence


def update_competence(
    db: Session, competence_id: int, ambulance_id: int, data: CompetenceUpdate
) -> Competence:
    """Update an existing competence with partial data.

    Args:
        db: Active database session.
        competence_id: The competence to update.
        ambulance_id: The ambulance scope.
        data: Validated update payload (only set fields are applied).

    Returns:
        The updated :class:`Competence` instance.
    """
    competence = get_competence(db, competence_id, ambulance_id)

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(competence, field, value)

    db.commit()
    db.refresh(competence)
    return competence


def delete_competence(db: Session, competence_id: int, ambulance_id: int) -> None:
    """Delete a competence from an ambulance.

    Args:
        db: Active database session.
        competence_id: The competence to delete.
        ambulance_id: The ambulance scope.

    Raises:
        HTTPException 404: If the competence does not exist in the ambulance.
    """
    competence = get_competence(db, competence_id, ambulance_id)
    db.delete(competence)
    db.commit()
