"""Signing in with an e-mail and a password, and looking after that password.

The password is an addition to Google sign-in, not a way to register: only
an account a scheduler or an administrator created can sign in. Until the
employee picks a password of their own, the password is the account's
e-mail; the stored hash stays NULL so a later change of the e-mail moves the
initial password along with it.

Hashes use :func:`hashlib.scrypt` from the standard library, so no extra
dependency is needed. Failed sign-ins and reset requests are throttled per
address in process memory -- enough for a single API instance, and the cost
of a restart is only a forgotten counter.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.user import User
from app.services.email_service import (
    EmailError,
    EmailNotConfiguredError,
    build_message,
    is_email_configured,
    send_message,
)

logger = logging.getLogger(__name__)

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128
RESET_TOKEN_TTL = timedelta(hours=1)

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1

MAX_FAILED_LOGINS = 5
FAILED_LOGIN_WINDOW_SECONDS = 15 * 60
RESET_REQUEST_INTERVAL_SECONDS = 60


class PasswordError(ValueError):
    """A password or reset link was rejected; the message is a stable code."""


class TooManyAttemptsError(Exception):
    """Too many failed sign-ins for one address in a short time."""

    def __init__(self, retry_after: int) -> None:
        super().__init__("Too many attempts.")
        self.retry_after = retry_after


class _Throttle:
    """Timestamps of recent events per key, kept in memory."""

    def __init__(self) -> None:
        self._events: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def recent(self, key: str, window: float) -> list[float]:
        now = time.monotonic()
        with self._lock:
            kept = [t for t in self._events.get(key, []) if now - t < window]
            if kept:
                self._events[key] = kept
            else:
                self._events.pop(key, None)
            return kept

    def add(self, key: str) -> None:
        with self._lock:
            self._events.setdefault(key, []).append(time.monotonic())

    def clear(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._events.clear()
            else:
                self._events.pop(key, None)


failed_logins = _Throttle()
reset_requests = _Throttle()


def normalize_email(value: str) -> str:
    return (value or "").strip().lower()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P
    )
    return "$".join(
        (
            "scrypt",
            str(_SCRYPT_N),
            str(_SCRYPT_R),
            str(_SCRYPT_P),
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(digest).decode("ascii"),
        )
    )


def _verify_hash(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, expected = stored.split("$")
        if scheme != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=base64.b64decode(salt),
            n=int(n),
            r=int(r),
            p=int(p),
        )
        return hmac.compare_digest(digest, base64.b64decode(expected))
    except (ValueError, TypeError):
        return False


def verify_password(user: User, password: str) -> bool:
    """Check ``password`` against the user's own one, or their e-mail before that."""
    if user.password_hash:
        return _verify_hash(password, user.password_hash)
    return hmac.compare_digest(
        normalize_email(password).encode("utf-8"),
        normalize_email(user.email).encode("utf-8"),
    )


def _validate_new_password(user: User, password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordError("password_too_short")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise PasswordError("password_too_long")
    if normalize_email(password) == normalize_email(user.email):
        raise PasswordError("password_equals_email")


def authenticate_with_password(db: Session, email: str, password: str) -> User:
    """Return the active account matching the credentials.

    Raises:
        TooManyAttemptsError: When the address failed too often recently.
        ValueError: When the e-mail or the password does not match. The two
            are deliberately indistinguishable.
    """
    key = normalize_email(email)
    attempts = failed_logins.recent(key, FAILED_LOGIN_WINDOW_SECONDS)
    if len(attempts) >= MAX_FAILED_LOGINS:
        retry_after = int(FAILED_LOGIN_WINDOW_SECONDS - (time.monotonic() - attempts[0])) + 1
        raise TooManyAttemptsError(max(1, retry_after))

    user = db.query(User).filter(User.email == key).first() if key else None
    if user is None or not user.is_active or not verify_password(user, password):
        failed_logins.add(key)
        raise ValueError("Invalid e-mail or password")

    failed_logins.clear(key)
    user.login_count = (user.login_count or 0) + 1
    db.commit()
    db.refresh(user)
    return user


def change_password(db: Session, user: User, current_password: str, new_password: str) -> None:
    if not verify_password(user, current_password):
        raise PasswordError("wrong_current_password")
    _validate_new_password(user, new_password)
    user.password_hash = hash_password(new_password)
    user.password_reset_token = None
    user.password_reset_expires_at = None
    db.commit()


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def request_password_reset(db: Session, email: str) -> None:
    """Mail a reset link to the account, if there is one.

    Returns quietly whether or not the address belongs to an account, so the
    endpoint cannot be used to find out who has one.

    Raises:
        EmailNotConfiguredError: When no mail can go out at all. This says
            nothing about the address and is worth reporting.
    """
    if not is_email_configured():
        raise EmailNotConfiguredError("Mail is not configured.")
    key = normalize_email(email)
    if not key:
        return
    if reset_requests.recent(key, RESET_REQUEST_INTERVAL_SECONDS):
        return
    reset_requests.add(key)

    user = db.query(User).filter(User.email == key).first()
    if user is None or not user.is_active:
        return

    token = secrets.token_urlsafe(32)
    user.password_reset_token = _digest(token)
    user.password_reset_expires_at = datetime.now(timezone.utc) + RESET_TOKEN_TTL
    db.commit()

    link = f"{settings.APP_URL.rstrip('/')}/reset-password?token={token}"
    text = (
        "Dobrý deň,\n\n"
        "na zmenu hesla k vášmu účtu použite tento odkaz:\n"
        f"{link}\n\n"
        "Odkaz platí jednu hodinu. Ak ste o zmenu nežiadali, správu môžete ignorovať.\n"
    )
    try:
        send_message(
            build_message(
                subject="Zmena hesla",
                recipients=[user.email],
                text_body=text,
            )
        )
    except EmailError:
        logger.exception("Password reset mail to user %s could not be sent", user.id)


def _user_for_reset_token(db: Session, token: str) -> User:
    if not token:
        raise PasswordError("invalid_reset_link")
    user = (
        db.query(User)
        .filter(User.password_reset_token == _digest(token), User.is_active.is_(True))
        .first()
    )
    if user is None or user.password_reset_expires_at is None:
        raise PasswordError("invalid_reset_link")
    expires_at = user.password_reset_expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        raise PasswordError("invalid_reset_link")
    return user


def reset_password(db: Session, token: str, new_password: str) -> None:
    """Set a new password from a reset link and sign the account out everywhere."""
    user = _user_for_reset_token(db, token)
    _validate_new_password(user, new_password)
    user.password_hash = hash_password(new_password)
    user.password_reset_token = None
    user.password_reset_expires_at = None
    user.auth_token = None
    user.auth_token_expires_at = None
    db.commit()
    failed_logins.clear(normalize_email(user.email))
