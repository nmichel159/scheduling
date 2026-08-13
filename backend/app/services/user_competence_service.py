"""
Service layer for User Competence Assignment.

Business rules enforced:
- The employee must be assigned to the ambulance.
- The competence must belong to the ambulance.
- Duplicate assignments are prevented.
- Manager ownership is enforced at the dependency level.
"""

from fastapi import HTTPException, status
from sqlalchemy.orm import Session, contains_eager

from app.models.associations import UserAmbulance, UserCompetence
from app.models.competence import Competence
from app.models.user import User
from app.schemas.user import UserListResponse
from app.schemas.user_competence import UserCompetenceResponse


def _validate_employee_in_ambulance(db: Session, ambulance_id: int, user_id: int) -> None:
    """Verify that the employee is assigned to the ambulance.

    Args:
        db: Active database session.
        ambulance_id: The ambulance to check.
        user_id: The employee to check.

    Raises:
        HTTPException 404: If the user does not exist or is inactive.
        HTTPException 400: If the employee is not assigned to the ambulance.
    """
    user_and_assignment = (
        db.query(
            User.id.label("user_id"),
            UserAmbulance.ambulance_id.label("assigned_ambulance_id"),
        )
        .outerjoin(
            UserAmbulance,
            (UserAmbulance.user_id == User.id)
            & (UserAmbulance.ambulance_id == ambulance_id)
            & (UserAmbulance.is_active.is_(True)),
        )
        .filter(User.id == user_id, User.is_active.is_(True))
        .first()
    )
    if not user_and_assignment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with id {user_id} not found or inactive.",
        )
    if user_and_assignment.assigned_ambulance_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"User {user_id} is not assigned to ambulance {ambulance_id}.",
        )


def _validate_competence_in_ambulance(db: Session, ambulance_id: int, competence_id: int) -> Competence:
    """Verify that the competence belongs to the ambulance.

    Args:
        db: Active database session.
        ambulance_id: The ambulance to check.
        competence_id: The competence to check.

    Returns:
        The :class:`Competence` instance.

    Raises:
        HTTPException 404: If the competence does not exist or does not belong
            to the ambulance.
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
            detail=f"Competence {competence_id} not found in ambulance {ambulance_id}.",
        )
    return competence


def list_user_competences(
    db: Session, ambulance_id: int, user_id: int
) -> list[UserCompetenceResponse]:
    """List competences assigned to an employee, scoped to an ambulance.

    Args:
        db: Active database session.
        ambulance_id: The ambulance scope.
        user_id: The employee whose competences to list.

    Returns:
        A list of :class:`UserCompetenceResponse` with competence names resolved.
    """
    _validate_employee_in_ambulance(db, ambulance_id, user_id)

    # Get all user_competences where the competence belongs to this ambulance
    assignments = (
        db.query(UserCompetence)
        .join(Competence, UserCompetence.competence_id == Competence.id)
        .options(contains_eager(UserCompetence.competence))
        .filter(
            UserCompetence.user_id == user_id,
            Competence.ambulance_id == ambulance_id,
            UserCompetence.is_active == True,
            Competence.is_active == True,
        )
        .all()
    )

    result = []
    for assignment in assignments:
        result.append(
            UserCompetenceResponse(
                user_id=assignment.user_id,
                competence_id=assignment.competence_id,
                competence_name=assignment.competence.name if assignment.competence else None,
                created_at=assignment.created_at,
                is_active=assignment.is_active,
            )
        )
    return result


def list_employees_by_competence(
    db: Session,
    ambulance_id: int,
    competence_id: int,
    after_id: int | None = None,
    limit: int | None = None,
) -> list[UserListResponse]:
    """List active ambulance employees assigned to a competence.

    The competence is validated against the requested ambulance first, so an
    invalid or cross-ambulance competence ID returns ``404`` instead of an
    indistinguishable empty list.
    """
    _validate_competence_in_ambulance(db, ambulance_id, competence_id)

    query = (
        db.query(User)
        .join(UserCompetence, UserCompetence.user_id == User.id)
        .join(
            UserAmbulance,
            (UserAmbulance.user_id == User.id)
            & (UserAmbulance.ambulance_id == ambulance_id),
        )
        .filter(
            UserCompetence.competence_id == competence_id,
            UserCompetence.is_active.is_(True),
            UserAmbulance.is_active.is_(True),
            User.is_active.is_(True),
        )
    )
    if after_id is not None:
        query = query.filter(User.id > after_id)
    if after_id is not None or limit is not None:
        query = query.order_by(User.id)
    else:
        query = query.order_by(User.full_name, User.email)
    if limit is not None:
        query = query.limit(limit)
    users = query.all()
    return [UserListResponse.model_validate(user) for user in users]


def assign_competence(
    db: Session, ambulance_id: int, user_id: int, competence_id: int
) -> UserCompetenceResponse:
    """Assign a competence to an employee in an ambulance.

    Args:
        db: Active database session.
        ambulance_id: The ambulance scope.
        user_id: The employee to assign the competence to.
        competence_id: The competence to assign.

    Returns:
        A :class:`UserCompetenceResponse` for the new assignment.

    Raises:
        HTTPException 400: If the employee is not in the ambulance.
        HTTPException 404: If the competence does not belong to the ambulance.
        HTTPException 409: If the assignment already exists.
    """
    _validate_employee_in_ambulance(db, ambulance_id, user_id)
    competence = _validate_competence_in_ambulance(db, ambulance_id, competence_id)

    # Check for duplicate
    existing = (
        db.query(UserCompetence)
        .filter(
            UserCompetence.user_id == user_id,
            UserCompetence.competence_id == competence_id,
        )
        .first()
    )
    if existing:
        if existing.is_active:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Competence {competence_id} is already assigned to user {user_id}.",
            )
        # Re-activate a previously deactivated assignment
        existing.is_active = True
        db.commit()
        db.refresh(existing)
        return UserCompetenceResponse(
            user_id=existing.user_id,
            competence_id=existing.competence_id,
            competence_name=competence.name,
            created_at=existing.created_at,
            is_active=existing.is_active,
        )

    assignment = UserCompetence(
        user_id=user_id,
        competence_id=competence_id,
        is_active=True,
    )
    db.add(assignment)
    db.commit()
    db.refresh(assignment)

    return UserCompetenceResponse(
        user_id=assignment.user_id,
        competence_id=assignment.competence_id,
        competence_name=competence.name,
        created_at=assignment.created_at,
        is_active=assignment.is_active,
    )


def remove_competence(
    db: Session, ambulance_id: int, user_id: int, competence_id: int
) -> None:
    """Remove a competence from an employee.

    Args:
        db: Active database session.
        ambulance_id: The ambulance scope (for authorization).
        user_id: The employee to remove the competence from.
        competence_id: The competence to remove.

    Raises:
        HTTPException 400: If the employee is not in the ambulance.
        HTTPException 404: If the competence is not assigned to the employee.
    """
    _validate_employee_in_ambulance(db, ambulance_id, user_id)
    _validate_competence_in_ambulance(db, ambulance_id, competence_id)

    assignment = (
        db.query(UserCompetence)
        .filter(
            UserCompetence.user_id == user_id,
            UserCompetence.competence_id == competence_id,
            UserCompetence.is_active == True,
        )
        .first()
    )
    if not assignment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Competence {competence_id} is not assigned to user {user_id}.",
        )
    db.delete(assignment)
    db.commit()
