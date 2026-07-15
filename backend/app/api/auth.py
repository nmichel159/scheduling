from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.schemas.auth import GoogleLoginRequest, UserResponse
from app.services.auth_service import GoogleAuthenticationProvider, authenticate_user

# Musí tu byť router, nie app!
router = APIRouter()

def get_authentication_provider() -> GoogleAuthenticationProvider:
    """Dependency seam for swapping Google for another identity provider."""
    return GoogleAuthenticationProvider()

@router.post("/google", response_model=UserResponse)
async def google_auth(
    data: GoogleLoginRequest,
    db: Session = Depends(get_db),
    provider: GoogleAuthenticationProvider = Depends(get_authentication_provider),
):
    try:
        return authenticate_user(db, data.token, provider)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
