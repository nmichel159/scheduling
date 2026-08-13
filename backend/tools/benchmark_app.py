"""Opt-in local ASGI factory for authenticated read-only benchmarks.

This module is never imported by the production application. It avoids
changing a real user's session token by overriding authentication only in the
explicit benchmark process.
"""

from __future__ import annotations

import os

from sqlalchemy.orm import selectinload

from app.core.dependencies import get_current_user
from app.db.session import SessionLocal
from app.main import app
from app.models.associations import UserRole
from app.models.user import User


def create_benchmark_app():
    """Return the application with a guarded, process-local user override."""
    if os.getenv("BENCHMARK_ALLOW_AUTH_OVERRIDE", "").lower() != "true":
        raise RuntimeError(
            "Set BENCHMARK_ALLOW_AUTH_OVERRIDE=true only in the local "
            "benchmark process."
        )
    raw_user_id = os.getenv("BENCHMARK_USER_ID")
    if raw_user_id is None:
        raise RuntimeError("BENCHMARK_USER_ID is required.")

    with SessionLocal() as db:
        user = (
            db.query(User)
            .options(selectinload(User.user_roles).selectinload(UserRole.role))
            .filter(User.id == int(raw_user_id), User.is_active.is_(True))
            .first()
        )
        if user is None:
            raise RuntimeError("Benchmark user does not exist or is inactive.")
        # All relationships used by the authorization guards are now loaded.
        db.expunge_all()

    app.dependency_overrides[get_current_user] = lambda: user
    return app
