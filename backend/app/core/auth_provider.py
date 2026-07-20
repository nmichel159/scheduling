"""Authentication provider boundary.

The API depends on this small contract instead of a concrete identity provider.
Replacing Google, an internal SSO, or another provider therefore does not
require changing endpoint dependencies.
"""

from datetime import datetime, timezone
from hashlib import sha256
from typing import Protocol

from sqlalchemy.orm import Session

from app.models.user import User


class AuthenticationProvider(Protocol):
    def resolve_user(self, db: Session, credential: str) -> User:
        """Resolve and return an active local user from an external credential."""


class SessionAuthenticationProvider:
    """Resolve a user from an opaque session token."""

    def resolve_user(self, db: Session, credential: str) -> User:
        user = (
            db.query(User)
            .filter(User.auth_token == sha256(credential.encode("utf-8")).hexdigest(), User.is_active.is_(True))
            .first()
        )
        if not user or not user.auth_token_expires_at:
            raise LookupError("Session not found")
        expires_at = user.auth_token_expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= datetime.now(timezone.utc):
            user.auth_token = None
            user.auth_token_expires_at = None
            db.commit()
            raise LookupError("Session expired")
        return user
