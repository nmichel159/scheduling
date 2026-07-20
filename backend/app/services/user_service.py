"""
Service layer for user listing operations.
"""

from sqlalchemy.orm import Session

from app.models.user import User
from app.models.associations import UserRole
from app.models.role import Role
from app.models.associations import UserAmbulance
from app.models.ambulance import Ambulance
from app.schemas.user import UserByRoleResponse, UserRoleInfo, UserAmbulanceInfo


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
