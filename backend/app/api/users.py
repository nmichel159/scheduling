"""
FastAPI router for user listing endpoints.

Restricted to managers (Role Level >= 2), used to pick employees
when managing ambulance assignments.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, require_manager_role
from app.db.session import get_db
from app.models.user import User
from app.schemas.user import UserListResponse
from app.services.user_service import list_user_role_ids, list_users

router = APIRouter()


@router.get(
    "/",
    response_model=list[UserListResponse],
    summary="List all active users",
)
def list_users_endpoint(
    _manager: User = Depends(require_manager_role),
    db: Session = Depends(get_db),
) -> list[UserListResponse]:
    """Retrieve all active users. Manager role required."""
    return list_users(db)


@router.get(
    "/{user_id}/roles",
    response_model=list[int],
    summary="Get roles assigned to a user",
)
def list_user_roles_endpoint(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[int]:
    """Return role IDs for the authenticated user."""
    if current_user.id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only read your own roles.",
        )
    return list_user_role_ids(db, user_id)
