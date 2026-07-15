"""
Service layer for user listing operations.
"""

from sqlalchemy.orm import Session

from app.models.user import User
from app.models.associations import UserRole
from app.models.role import Role


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
