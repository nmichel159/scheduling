from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.schemas.auth import GoogleLoginRequest, UserResponse
from app.core.config import settings
from app.core.dependencies import get_current_user
from app.models.user import User
from app.services.auth_service import GoogleAuthenticationProvider, authenticate_user, issue_session, revoke_session

# Musí tu byť router, nie app!
router = APIRouter()

def get_authentication_provider() -> GoogleAuthenticationProvider:
    """Dependency seam for swapping Google for another identity provider."""
    return GoogleAuthenticationProvider()

@router.post("/google", response_model=UserResponse)
async def google_auth(
    data: GoogleLoginRequest,
    response: Response,
    db: Session = Depends(get_db),
    provider: GoogleAuthenticationProvider = Depends(get_authentication_provider),
):
    try:
        user = authenticate_user(db, data.token, provider)
        token = issue_session(db, user)
        response.set_cookie(
            key=settings.SESSION_COOKIE_NAME,
            value=token,
            httponly=True,
            secure=settings.COOKIE_SECURE,
            samesite="lax",
            max_age=settings.SESSION_TTL_HOURS * 3600,
            path="/",
        )
        return user
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Revoke the active server-side session and remove the browser cookie."""
    revoke_session(db, current_user)
    response.delete_cookie(settings.SESSION_COOKIE_NAME, path="/")
