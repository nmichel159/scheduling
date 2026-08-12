"""
Service layer for user listing operations.
"""

from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.models.user import User
from app.models.associations import UserRole
from app.models.role import Role
from app.models.associations import UserAmbulance
from app.models.ambulance import Ambulance
from app.schemas.user import (
    UserAmbulanceInfo,
    UserByRoleResponse,
    UserRoleAssignmentInfo,
    UserRoleAssignmentResponse,
    UserRoleInfo,
)


MANAGEABLE_ROLE_IDS = {1, 2, 3}


def list_users(db: Session) -> list[User]:
    """List all active users ordered by name.

    Args:
        db: Active database session.

    Returns:
        A list of active :class:`User` instances.
    """
    return (
        db.query(User)
        .filter(User.is_active == True)
        .order_by(User.full_name, User.email)
        .all()
    )


def list_user_role_ids(db: Session, user_id: int) -> list[int]:
    """Return IDs of all active roles assigned to an active user."""
    return [role_id for (role_id,) in (
        db.query(UserRole.role_id)
        .join(Role, Role.id == UserRole.role_id)
        .filter(
            UserRole.user_id == user_id,
            Role.is_active == True,
        )
        .order_by(UserRole.role_id)
        .all()
    )]


def list_users_by_role(db: Session, role_id: int) -> list[UserByRoleResponse]:
    role = db.query(Role).filter(Role.id == role_id, Role.is_active.is_(True)).first()
    if not role:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Role not found or inactive.")
    users = db.query(User).join(UserRole).filter(UserRole.role_id == role_id).order_by(User.full_name, User.email).all()
    result = []
    for user in users:
        roles = [UserRoleInfo(id=item.role.id, code=item.role.code) for item in user.user_roles if item.role and item.role.is_active]
        ambulances = [UserAmbulanceInfo(id=item.ambulance.id, name=item.ambulance.name) for item in user.user_ambulances if item.is_active and item.ambulance and item.ambulance.is_active]
        result.append(UserByRoleResponse(id=user.id, email=user.email, full_name=user.full_name, is_active=user.is_active, roles=roles, ambulances=ambulances))
    return result


def list_user_role_assignments(db: Session) -> list[UserRoleAssignmentResponse]:
    """List active users and their active roles without per-user queries."""
    users = (
        db.query(User)
        .options(joinedload(User.user_roles).joinedload(UserRole.role))
        .filter(User.is_active.is_(True))
        .order_by(User.full_name, User.email)
        .all()
    )
    return [_serialize_user_role_assignment(user) for user in users]


def update_user_roles(
    db: Session,
    user_id: int,
    requested_role_ids: list[int],
) -> UserRoleAssignmentResponse:
    """Synchronize assignable roles 1-3 while preserving higher roles."""
    requested = set(requested_role_ids)
    invalid = sorted(requested - MANAGEABLE_ROLE_IDS)
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Only role IDs 1, 2 and 3 can be managed. Invalid IDs: {invalid}",
        )

    user = (
        db.query(User)
        .options(joinedload(User.user_roles).joinedload(UserRole.role))
        .filter(User.id == user_id, User.is_active.is_(True))
        .first()
    )
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found or inactive.",
        )

    active_manageable_roles = {
        role.id
        for role in db.query(Role)
        .filter(Role.id.in_(MANAGEABLE_ROLE_IDS), Role.is_active.is_(True))
        .all()
    }
    unavailable = sorted(requested - active_manageable_roles)
    if unavailable:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Requested roles are not active: {unavailable}",
        )

    existing_manageable = {
        assignment.role_id
        for assignment in user.user_roles
        if assignment.role_id in MANAGEABLE_ROLE_IDS
    }
    for assignment in list(user.user_roles):
        if assignment.role_id in MANAGEABLE_ROLE_IDS and assignment.role_id not in requested:
            db.delete(assignment)
    for role_id in requested - existing_manageable:
        db.add(UserRole(user_id=user.id, role_id=role_id))

    db.commit()
    db.expire(user, ["user_roles"])
    return _serialize_user_role_assignment(user)


def _serialize_user_role_assignment(user: User) -> UserRoleAssignmentResponse:
    roles = sorted(
        (
            UserRoleAssignmentInfo(
                id=assignment.role.id,
                code=assignment.role.code,
                name=assignment.role.name,
                level=assignment.role.level,
            )
            for assignment in user.user_roles
            if assignment.role and assignment.role.is_active
        ),
        key=lambda role: role.id,
    )
    return UserRoleAssignmentResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        roles=roles,
    )
