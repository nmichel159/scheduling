from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.schemas.auth import GoogleLoginRequest, UserResponse
from app.services.auth_service import authenticate_google_user

# Musí tu byť router, nie app!
router = APIRouter()

@router.post("/google", response_model=UserResponse)
async def google_auth(data: GoogleLoginRequest, db: Session = Depends(get_db)):
    return authenticate_google_user(db, data.token)