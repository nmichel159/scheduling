"""
Service layer for Ambulance Employee Management.

Business rules enforced:
- Managers may only manage ambulances they own (enforced at dependency level).
- Prevents duplicate employee assignments.
- Validates that the target user exists and is active.
"""

import re

from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.models.ambulance import Ambulance
from app.models.associations import UserAmbulance
from app.models.user import User
from app.services.password_service import send_setup_link
from app.schemas.ambulance_employee import (
    AmbulanceListResponse,
    EmployeeAccountCreate,
    EmployeeListResponse,
    EmployeeProfileUpdate,
)


def list_employees(
    db: Session,
    ambulance_id: int,
    after_id: int | None = None,
    limit: int | None = None,
) -> list[EmployeeListResponse]:
    """List all active employees assigned to an ambulance.

    Args:
        db: Active database session.
        ambulance_id: The ambulance to query.

    Returns:
        A list of :class:`User` instances assigned to the ambulance.
    """
    query = (
        db.query(User)
        .join(UserAmbulance, UserAmbulance.user_id == User.id)
        .filter(
            UserAmbulance.ambulance_id == ambulance_id,
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
    employees = query.all()
    return [
        EmployeeListResponse(
            user_id=employee.id,
            email=employee.email,
            full_name=employee.full_name,
        )
        for employee in employees
    ]


def get_active_employee(db: Session, ambulance_id: int, user_id: int) -> User:
    """Return an active user assigned to an ambulance.

    Manager-facing employee operations use this guard after ambulance ownership
    has been verified. Keeping the membership check in one place prevents a
    manager from reading or changing data for an employee from another
    ambulance by submitting a different user ID.
    """
    employee = (
        db.query(User)
        .join(UserAmbulance, UserAmbulance.user_id == User.id)
        .filter(
            User.id == user_id,
            User.is_active.is_(True),
            UserAmbulance.ambulance_id == ambulance_id,
            UserAmbulance.is_active.is_(True),
        )
        .first()
    )
    if not employee:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User {user_id} is not an active employee of ambulance {ambulance_id}.",
        )
    return employee


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
        .options(joinedload(UserAmbulance.ambulance))
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


_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _clean_email(value: str) -> str:
    email = value.strip().lower()
    if not _EMAIL_PATTERN.match(email):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid e-mail address.",
        )
    return email


def _clean_name(value: str) -> str:
    name = " ".join(value.split())
    if not name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Name must not be empty.",
        )
    return name


def _email_taken(db: Session, email: str, except_user_id: int | None = None) -> bool:
    query = db.query(User.id).filter(User.email == email)
    if except_user_id is not None:
        query = query.filter(User.id != except_user_id)
    return query.first() is not None


def create_employee_account(
    db: Session, ambulance_id: int, data: EmployeeAccountCreate
) -> EmployeeListResponse:
    """Create a new account and assign it to the ambulance.

    The default role is handed out on the first sign-in, so the account only
    needs an identity here; the e-mail is what the sign-in matches on.
    """
    email = _clean_email(data.email)
    _clean_name(data.first_name)
    _clean_name(data.last_name)
    name = " ".join(
        part for part in (data.title_before, data.first_name, data.last_name) if part.strip()
    )
    if data.title_after.strip():
        name = f"{name}, {data.title_after}"
    full_name = _clean_name(name)
    if _email_taken(db, email):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this e-mail already exists.",
        )
    user = User(email=email, full_name=full_name, login_count=0, is_active=True)
    db.add(user)
    db.flush()
    db.add(UserAmbulance(user_id=user.id, ambulance_id=ambulance_id, is_active=True))
    db.commit()
    db.refresh(user)
    send_setup_link(db, user)
    return EmployeeListResponse(
        user_id=user.id, email=user.email, full_name=user.full_name
    )


def update_employee_profile(
    db: Session, ambulance_id: int, employee: User, data: EmployeeProfileUpdate
) -> EmployeeListResponse:
    """Change the name and e-mail of an employee of the workplace."""
    email = _clean_email(data.email)
    full_name = _clean_name(data.full_name)
    if email != employee.email:
        # The e-mail is the sign-in identity. Moving it on an account that
        # holds a manager/admin role, or that works on other workplaces,
        # would let one scheduler take over somebody else's access.
        privileged = any(
            link.role and link.role.is_active and link.role.level >= 2
            for link in employee.user_roles
        )
        elsewhere = (
            db.query(UserAmbulance.user_id)
            .filter(
                UserAmbulance.user_id == employee.id,
                UserAmbulance.is_active.is_(True),
                UserAmbulance.ambulance_id != ambulance_id,
            )
            .first()
            is not None
        )
        if privileged or elsewhere:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="The e-mail of this account cannot be changed from here.",
            )
    if _email_taken(db, email, except_user_id=employee.id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this e-mail already exists.",
        )
    employee.email = email
    employee.full_name = full_name
    db.commit()
    db.refresh(employee)
    return EmployeeListResponse(
        user_id=employee.id, email=employee.email, full_name=employee.full_name
    )
