from typing import Optional
from pydantic import BaseModel, Field

class AmbulanceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)
    isurgent: bool = False
    manager_id: Optional[int] = None

class AmbulanceUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)
    isurgent: Optional[bool] = None
    manager_id: Optional[int] = None

class AmbulanceResponse(AmbulanceCreate):
    id: int
    managed_by_user_id: Optional[int] = None
    is_active: bool = True
    class Config:
        from_attributes = True
