from pydantic import BaseModel
from typing import Optional

class GoogleLoginRequest(BaseModel):
    token: str

class UserResponse(BaseModel):
    email: str
    full_name: Optional[str]
    login_count: int
    
    class Config:
        from_attributes = True