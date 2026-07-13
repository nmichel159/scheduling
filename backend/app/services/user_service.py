"""
Service layer for user listing operations.
"""

from sqlalchemy.orm import Session

from app.models.user import User


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
