from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user
from app.db.session import get_db
from app.models.role import Role
from app.models.user import User

router = APIRouter()

@router.get("/me", response_model=list[dict])
def get_user_roles(current_user: User = Depends(get_current_user)) -> list[dict]:
    return [
        {"name": ur.role.code, "index": ur.role.id}
        for ur in current_user.user_roles
        if ur.role and ur.role.is_active
    ]

@router.get("", response_model=list[dict])
def list_all_roles(db: Session = Depends(get_db)) -> list[dict]:
    return [{"name": role.code, "index": role.id} for role in db.query(Role).filter(Role.is_active.is_(True)).order_by(Role.id)]
