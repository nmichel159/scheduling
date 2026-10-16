from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.schemas.auth import (
    GoogleLoginRequest,
    PasswordChangeRequest,
    PasswordForgotRequest,
    PasswordLoginRequest,
    PasswordResetRequest,
    UserResponse,
)
from app.core.config import settings
from app.core.dependencies import get_current_user
from app.models.user import User
from app.services.auth_service import (
    GoogleAuthenticationProvider,
    authenticate_user,
    ensure_default_role,
    issue_session,
    revoke_session,
)
from app.services.email_service import EmailNotConfiguredError
from app.services.password_service import (
    PasswordError,
    TooManyAttemptsError,
    authenticate_with_password,
    change_password,
    request_password_reset,
    reset_password,
)

# Musí tu byť router, nie app!
router = APIRouter()


def _start_session(db: Session, user: User, request: Request, response: Response) -> None:
    token = issue_session(db, user)
    # Vercel -> Render is cross-site. A Secure/SameSite=None cookie is
    # required there, while localhost remains usable over plain HTTP.
    origin = request.headers.get("origin", "")
    cross_site_https = origin.startswith("https://")
    response.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=settings.COOKIE_SECURE or cross_site_https,
        samesite="none" if cross_site_https else "lax",
        max_age=settings.SESSION_TTL_HOURS * 3600,
        path="/",
    )


def get_authentication_provider() -> GoogleAuthenticationProvider:
    """Dependency seam for swapping Google for another identity provider."""
    return GoogleAuthenticationProvider()

@router.post("/google", response_model=UserResponse)
def google_auth(
    data: GoogleLoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    provider: GoogleAuthenticationProvider = Depends(get_authentication_provider),
):
    try:
        user = authenticate_user(db, data.token, provider)
        _start_session(db, user, request, response)
        return user
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Revoke the active server-side session and remove the browser cookie."""
    revoke_session(db, current_user)
    response.delete_cookie(settings.SESSION_COOKIE_NAME, path="/")


@router.post("/login", response_model=UserResponse)
def password_login(
    data: PasswordLoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Sign in with the e-mail and password of an existing account."""
    try:
        user = authenticate_with_password(db, data.email, data.password)
    except TooManyAttemptsError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed attempts.",
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    ensure_default_role(db, user)
    _start_session(db, user, request, response)
    return user


@router.post("/password/change", status_code=status.HTTP_204_NO_CONTENT)
def password_change(
    data: PasswordChangeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        change_password(db, current_user, data.current_password, data.new_password)
    except PasswordError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/password/forgot", status_code=status.HTTP_204_NO_CONTENT)
def password_forgot(data: PasswordForgotRequest, db: Session = Depends(get_db)):
    """Mail a reset link. Answers the same whether or not the account exists."""
    try:
        request_password_reset(db, data.email)
    except EmailNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Mail is not configured.",
        ) from exc


@router.post("/password/reset", status_code=status.HTTP_204_NO_CONTENT)
def password_reset(data: PasswordResetRequest, db: Session = Depends(get_db)):
    try:
        reset_password(db, data.token, data.new_password)
    except PasswordError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
