"""Authentication provider boundary.

The API depends on this small contract instead of a concrete identity provider.
Replacing Google, an internal SSO, or another provider therefore does not
require changing endpoint dependencies.
"""

from typing import Protocol

from sqlalchemy.orm import Session

from app.models.user import User


class AuthenticationProvider(Protocol):
    def resolve_user(self, db: Session, credential: str) -> User:
        """Resolve and return an active local user from an external credential."""


class UserIdAuthenticationProvider:
    """Compatibility provider for the current X-User-Id integration."""

    def resolve_user(self, db: Session, credential: str) -> User:
        user = (
            db.query(User)
            .filter(User.id == int(credential), User.is_active.is_(True))
            .first()
        )
        if not user:
            raise LookupError("User not found or inactive")
        return user
