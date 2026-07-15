from typing import Any

import requests
from sqlalchemy.orm import Session
from app.models.user import User
from app.core.auth_provider import AuthenticationProvider

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
        if not email:
            raise ValueError("Google account has no email address")

        user = db.query(User).filter(User.email == email).first()
        if not user:
            user = User(email=email, full_name=info.get("name"), login_count=0)
            db.add(user)
        user.login_count = (user.login_count or 0) + 1
        db.commit()
        db.refresh(user)
        return user


def authenticate_user(db: Session, credential: str, provider: AuthenticationProvider) -> User:
    """Authenticate through the selected provider and translate errors at the API boundary."""
    return provider.resolve_user(db, credential)


def authenticate_google_user(db: Session, token: str):
    """Backward-compatible wrapper for existing callers."""
    return authenticate_user(db, token, GoogleAuthenticationProvider())
