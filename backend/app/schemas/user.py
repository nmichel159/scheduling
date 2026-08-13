"""
Pydantic schemas for user listing.

Used by managers to pick users when assigning employees to ambulances.
"""

from typing import Optional

from pydantic import BaseModel, Field


class UserListResponse(BaseModel):
    """Lightweight schema for listing users."""

    id: int
    email: str
    full_name: Optional[str] = None

    class Config:
        from_attributes = True


class UserRoleInfo(BaseModel):
    id: int
    code: str


class UserRoleAssignmentInfo(UserRoleInfo):
    name: str
    level: int


class UserAmbulanceInfo(BaseModel):
    id: int
    name: str


class UserByRoleResponse(UserListResponse):
    is_active: bool
    roles: list[UserRoleInfo]
    ambulances: list[UserAmbulanceInfo]


class UserRoleAssignmentResponse(UserListResponse):
    roles: list[UserRoleAssignmentInfo]


class UserRolesUpdate(BaseModel):
    role_ids: list[int] = Field(max_length=3)
