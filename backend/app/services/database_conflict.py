"""Helpers for translating database-enforced race conflicts to HTTP errors."""

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


def commit_or_conflict(db: Session, detail: str) -> None:
    """Commit, rolling back and returning 409 on an integrity race.

    Service-level duplicate checks provide useful early errors, while unique
    indexes are the final guard when two requests pass that check together.
    """
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=detail,
        ) from exc
