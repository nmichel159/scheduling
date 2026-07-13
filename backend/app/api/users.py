"""
FastAPI router for user listing endpoints.

Restricted to managers (Role Level >= 2), used to pick employees
when managing ambulance assignments.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import require_manager_role
from app.db.session import get_db
from app.models.user import User
from app.schemas.user import UserListResponse
from app.services.user_service import list_users

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
