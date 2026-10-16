from pydantic import BaseModel, Field
from typing import Optional

class GoogleLoginRequest(BaseModel):
    token: str

class UserResponse(BaseModel):
    id: int
    email: str
    full_name: Optional[str]
    login_count: int
    
    class Config:
        from_attributes = True

class PasswordLoginRequest(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=256)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(max_length=256)


class PasswordForgotRequest(BaseModel):
    email: str = Field(max_length=320)


class PasswordResetRequest(BaseModel):
    token: str = Field(max_length=256)
    new_password: str = Field(max_length=256)
