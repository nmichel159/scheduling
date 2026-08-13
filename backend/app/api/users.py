"""
FastAPI router for user listing endpoints.

Restricted to managers (Role Level >= 2), used to pick employees
when managing ambulance assignments.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, require_admin_role, require_manager_role
from app.db.session import get_db
from app.models.user import User
from app.schemas.user import (
    UserByRoleResponse,
    UserListResponse,
    UserRoleAssignmentResponse,
    UserRolesUpdate,
)
from app.services.user_service import (
    list_user_role_assignments,
    list_user_role_ids,
    list_users,
    list_users_by_role,
    update_user_roles,
)

router = APIRouter()


@router.get(
    "/role-assignments",
    response_model=list[UserRoleAssignmentResponse],
    summary="List users with assigned roles",
)
def list_role_assignments_endpoint(
    after_id: int | None = Query(None, ge=0, description="Return users after this ID"),
    limit: int | None = Query(None, ge=1, le=500, description="Max users to return"),
    _admin: User = Depends(require_admin_role),
    db: Session = Depends(get_db),
) -> list[UserRoleAssignmentResponse]:
    return list_user_role_assignments(db, after_id=after_id, limit=limit)


@router.get("/by-role", response_model=list[UserByRoleResponse], summary="List users by role")
def users_by_role_endpoint(
    role_id: int,
    after_id: int | None = Query(None, ge=0, description="Return users after this ID"),
    limit: int | None = Query(None, ge=1, le=500, description="Max users to return"),
    _admin: User = Depends(require_admin_role),
    db: Session = Depends(get_db),
) -> list[UserByRoleResponse]:
    return list_users_by_role(db, role_id, after_id=after_id, limit=limit)


@router.get(
    "",
    response_model=list[UserListResponse],
    summary="List all active users",
)
def list_users_endpoint(
    after_id: int | None = Query(None, ge=0, description="Return users after this ID"),
    limit: int | None = Query(None, ge=1, le=500, description="Max users to return"),
    _manager: User = Depends(require_manager_role),
    db: Session = Depends(get_db),
) -> list[UserListResponse]:
    """Retrieve all active users. Manager role required."""
    return list_users(db, after_id=after_id, limit=limit)


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


@router.put(
    "/{user_id}/roles",
    response_model=UserRoleAssignmentResponse,
    summary="Assign roles 1-3 to a user",
)
def update_user_roles_endpoint(
    user_id: int,
    data: UserRolesUpdate,
    _admin: User = Depends(require_admin_role),
    db: Session = Depends(get_db),
) -> UserRoleAssignmentResponse:
    return update_user_roles(db, user_id, data.role_ids)
