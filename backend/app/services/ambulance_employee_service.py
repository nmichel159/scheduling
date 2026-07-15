"""
Service layer for Ambulance Employee Management.

Business rules enforced:
- Managers may only manage ambulances they own (enforced at dependency level).
- Prevents duplicate employee assignments.
- Validates that the target user exists and is active.
"""

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.ambulance import Ambulance
from app.models.associations import UserAmbulance
from app.models.user import User
from app.schemas.ambulance_employee import AmbulanceListResponse, EmployeeListResponse


def list_employees(db: Session, ambulance_id: int) -> list[EmployeeListResponse]:
    """List all active employees assigned to an ambulance.

    Args:
        db: Active database session.
        ambulance_id: The ambulance to query.

    Returns:
        A list of :class:`User` instances assigned to the ambulance.
    """
    assignments = (
        db.query(UserAmbulance)
        .filter(
            UserAmbulance.ambulance_id == ambulance_id,
            UserAmbulance.is_active == True,
        )
        .all()
    )
    return [
        EmployeeListResponse(
            user_id=assignment.user.id,
            email=assignment.user.email,
            full_name=assignment.user.full_name,
        )
        for assignment in assignments
        if assignment.user and assignment.user.is_active
    ]


def list_employee_ambulances(db: Session, user_id: int) -> list[AmbulanceListResponse]:
    """List all active ambulances where the user works as an employee."""
    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with id {user_id} not found or inactive.",
        )

    assignments = (
        db.query(UserAmbulance)
        .join(Ambulance)
        .filter(
            UserAmbulance.user_id == user_id,
            UserAmbulance.is_active == True,
            Ambulance.is_active == True,
        )
        .all()
    )
    return [
        AmbulanceListResponse(
            id=assignment.ambulance.id,
            name=assignment.ambulance.name,
            description=assignment.ambulance.description,
            managed_by_user_id=assignment.ambulance.managed_by_user_id,
            isurgent=assignment.ambulance.isurgent,
        )
        for assignment in assignments
        if assignment.ambulance
    ]


def list_manager_ambulances(db: Session, user_id: int) -> list[AmbulanceListResponse]:
    """List all active ambulances managed by the user."""
    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with id {user_id} not found or inactive.",
        )

    ambulances = (
        db.query(Ambulance)
        .filter(
            Ambulance.managed_by_user_id == user_id,
            Ambulance.is_active == True,
        )
        .all()
    )
    return [
        AmbulanceListResponse(
            id=ambulance.id,
            name=ambulance.name,
            description=ambulance.description,
            managed_by_user_id=ambulance.managed_by_user_id,
            isurgent=ambulance.isurgent,
        )
        for ambulance in ambulances
    ]


def add_employee(db: Session, ambulance_id: int, user_id: int) -> UserAmbulance:
    """Assign an employee to an ambulance.

    Args:
        db: Active database session.
        ambulance_id: The target ambulance.
        user_id: The user to assign.

    Returns:
        The created :class:`UserAmbulance` assignment record.

    Raises:
        HTTPException 404: If the user does not exist or is inactive.
        HTTPException 409: If the user is already assigned to the ambulance.
    """
    # Validate that the user exists and is active
    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with id {user_id} not found or inactive.",
        )

    # Check for duplicate assignment
    existing = (
        db.query(UserAmbulance)
        .filter(
            UserAmbulance.user_id == user_id,
            UserAmbulance.ambulance_id == ambulance_id,
        )
        .first()
    )
    if existing:
        if existing.is_active:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"User {user_id} is already assigned to ambulance {ambulance_id}.",
            )
        # Re-activate a previously deactivated assignment
        existing.is_active = True
        db.commit()
        db.refresh(existing)
        return existing

    assignment = UserAmbulance(
        user_id=user_id,
        ambulance_id=ambulance_id,
        is_active=True,
    )
    db.add(assignment)
    db.commit()
    db.refresh(assignment)
    return assignment


def remove_employee(db: Session, ambulance_id: int, user_id: int) -> None:
    """Remove an employee from an ambulance.

    Args:
        db: Active database session.
        ambulance_id: The target ambulance.
        user_id: The user to remove.

    Raises:
        HTTPException 404: If the assignment does not exist.
    """
    assignment = (
        db.query(UserAmbulance)
        .filter(
            UserAmbulance.user_id == user_id,
            UserAmbulance.ambulance_id == ambulance_id,
            UserAmbulance.is_active == True,
        )
        .first()
    )
    if not assignment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User {user_id} is not assigned to ambulance {ambulance_id}.",
        )
    db.delete(assignment)
    db.commit()
