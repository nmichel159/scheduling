from typing import Optional
from pydantic import BaseModel

class AmbulanceCreate(BaseModel):
    name: str
    description: Optional[str] = None
    isurgent: bool = False
    manager_id: Optional[int] = None

class AmbulanceUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    isurgent: Optional[bool] = None
    manager_id: Optional[int] = None

class AmbulanceResponse(AmbulanceCreate):
    id: int
    managed_by_user_id: Optional[int] = None
    is_active: bool = True
    class Config:
        from_attributes = True
