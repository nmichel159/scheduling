from datetime import datetime, timezone
from hashlib import sha256
import secrets
from typing import Any

import requests
from sqlalchemy.orm import Session
from app.models.associations import UserRole
from app.models.role import Role
from app.models.user import User
from app.core.auth_provider import AuthenticationProvider
from app.core.config import session_ttl

class GoogleAuthenticationProvider:
    """Google implementation of the application authentication contract."""

    def resolve_user(self, db: Session, credential: str) -> User:
        res = requests.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {credential}"},
            timeout=10,
        )
        if res.status_code != 200:
            raise ValueError("Invalid Google token")
        info: dict[str, Any] = res.json()
        email = info.get("email")
        if not email or info.get("email_verified") is not True:
            raise ValueError("Google account does not have a verified email address")

        user = db.query(User).filter(User.email == email).first()
        if not user:
            user = User(email=email, full_name=info.get("name"), login_count=0)
            db.add(user)
        elif not user.is_active:
            raise ValueError("User account is inactive")
        user.login_count = (user.login_count or 0) + 1
        db.commit()
        db.refresh(user)
        return user


def issue_session(db: Session, user: User) -> str:
    """Rotate the user's session and store only a SHA-256 token digest."""
    token = secrets.token_urlsafe(32)
    user.auth_token = sha256(token.encode("utf-8")).hexdigest()
    user.auth_token_expires_at = datetime.now(timezone.utc) + session_ttl()
    db.commit()
    return token


def revoke_session(db: Session, user: User) -> None:
    user.auth_token = None
    user.auth_token_expires_at = None
    db.commit()


def authenticate_user(db: Session, credential: str, provider: AuthenticationProvider) -> User:
    """Authenticate through the selected provider and translate errors at the API boundary."""
    user = provider.resolve_user(db, credential)
    ensure_default_role(db, user)
    return user


def ensure_default_role(db: Session, user: User) -> None:
    """Assign EMPLOYEE only when the user has no active role at all."""
    has_active_role = (
        db.query(UserRole)
        .join(Role, Role.id == UserRole.role_id)
        .filter(UserRole.user_id == user.id, Role.is_active.is_(True))
        .first()
        is not None
    )
    if has_active_role:
        return

    employee_role = (
        db.query(Role)
        .filter(
            Role.id == 1,
            Role.code == "EMPLOYEE",
            Role.is_active.is_(True),
        )
        .first()
    )
    if employee_role is None:
        raise RuntimeError("Active default role EMPLOYEE with id 1 is not configured.")

    db.add(UserRole(user_id=user.id, role_id=employee_role.id))
    db.commit()
    db.refresh(user)


def authenticate_google_user(db: Session, token: str):
    """Backward-compatible wrapper for existing callers."""
    return authenticate_user(db, token, GoogleAuthenticationProvider())
