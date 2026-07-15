"""
Core authentication and authorization dependencies for FastAPI endpoints.

Provides reusable dependency functions for:
- Extracting the current user from request headers
- Enforcing role-based access control (manager level)
- Verifying ambulance ownership for manager operations
"""

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.user import User
from app.models.ambulance import Ambulance
from app.core.auth_provider import UserIdAuthenticationProvider

_authentication_provider = UserIdAuthenticationProvider()


def get_current_user(
    x_user_id: int = Header(..., description="ID of the authenticated user"),
    db: Session = Depends(get_db),
) -> User:
    """Resolve the current user from the X-User-Id request header.

    Args:
        x_user_id: User ID passed via the ``X-User-Id`` header.
        db: Database session injected by FastAPI.

    Returns:
        The active :class:`User` instance.

    Raises:
        HTTPException 404: If no active user with the given ID exists.
    """
    try:
        user = _authentication_provider.resolve_user(db, str(x_user_id))
    except (LookupError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"User with id {x_user_id} not found or inactive.",
        )
    return user


def require_manager_role(
    current_user: User = Depends(get_current_user),
) -> User:
    """Ensure the current user holds a manager role (level >= 2).

    Args:
        current_user: The resolved :class:`User` from :func:`get_current_user`.

    Returns:
        The same :class:`User` if they satisfy the role requirement.

    Raises:
        HTTPException 403: If the user does not have a role with level >= 2.
    """
    has_manager_role = any(
        ur.role.level >= 2
        for ur in current_user.user_roles
        if ur.role and ur.role.is_active
    )
    if not has_manager_role:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions. Manager role (level >= 2) required.",
        )
    return current_user


def require_admin_role(current_user: User = Depends(get_current_user)) -> User:
    """Require role level 3 or higher."""
    if not any(ur.role and ur.role.is_active and ur.role.level >= 3 for ur in current_user.user_roles):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator role required.")
    return current_user


def get_manager_ambulance(
    ambulance_id: int,
    manager: User = Depends(require_manager_role),
    db: Session = Depends(get_db),
) -> Ambulance:
    """Verify that the ambulance exists, is active, and is managed by the current user.

    Args:
        ambulance_id: Path parameter identifying the ambulance.
        manager: The manager :class:`User` resolved by :func:`require_manager_role`.
        db: Database session injected by FastAPI.

    Returns:
        The :class:`Ambulance` instance owned by the manager.

    Raises:
        HTTPException 404: If the ambulance does not exist or is inactive.
        HTTPException 403: If the ambulance is not managed by the current user.
    """
    ambulance: Ambulance | None = (
        db.query(Ambulance)
        .filter(Ambulance.id == ambulance_id, Ambulance.is_active == True)
        .first()
    )
    if not ambulance:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ambulance with id {ambulance_id} not found or inactive.",
        )
    is_admin = any(ur.role and ur.role.is_active and ur.role.level >= 3 for ur in manager.user_roles)
    if not is_admin and ambulance.managed_by_user_id != manager.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not manage this ambulance.",
        )
    return ambulance
