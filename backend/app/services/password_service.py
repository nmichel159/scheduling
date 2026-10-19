"""Signing in with an e-mail and a password, and looking after that password.

The password is an addition to Google sign-in, not a way to register: only
an account a scheduler or an administrator created can sign in. An account
has no password until its owner sets one through a link sent to their
mailbox -- automatically when the account is created, or on request through
"forgot password" -- so knowing somebody's e-mail is never enough to get in.
Somebody already signed in through Google may also set one from the app.

Hashes use :func:`hashlib.scrypt` from the standard library, so no extra
dependency is needed. Failed sign-ins and link requests are throttled in
process memory -- enough for a single API instance, and the cost of a
restart is only a forgotten counter.
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

from sqlalchemy import func
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
# A new employee may not read the welcome mail the same hour.
SETUP_TOKEN_TTL = timedelta(days=7)

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1

# Failures are counted per (client, account): one client guessing is stopped
# quickly, while somebody else failing on purpose cannot lock the owner out.
# The looser per-account cap still stops guessing spread over many clients.
MAX_FAILED_LOGINS = 5
MAX_FAILED_LOGINS_PER_ACCOUNT = 50
FAILED_LOGIN_WINDOW_SECONDS = 15 * 60
RESET_REQUEST_INTERVAL_SECONDS = 60


class PasswordError(ValueError):
    """A password or link was rejected; the message is a stable code."""


class TooManyAttemptsError(Exception):
    """Too many failed sign-ins in a short time."""

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
    """Check ``password``; an account without a password never matches."""
    if not user.password_hash:
        return False
    return _verify_hash(password, user.password_hash)


def _validate_new_password(user: User, password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordError("password_too_short")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise PasswordError("password_too_long")
    if normalize_email(password) == normalize_email(user.email):
        raise PasswordError("password_equals_email")


def _retry_after(attempts: list[float]) -> int:
    return max(1, int(FAILED_LOGIN_WINDOW_SECONDS - (time.monotonic() - attempts[0])) + 1)


def authenticate_with_password(
    db: Session, email: str, password: str, client: str = ""
) -> User:
    """Return the active account matching the credentials.

    Args:
        client: Who is asking, normally the client IP address.

    Raises:
        TooManyAttemptsError: When this client, or everybody together,
            failed too often on the address recently.
        ValueError: When the e-mail or the password does not match, or the
            account has no password yet. All are deliberately alike.
    """
    account_key = normalize_email(email)
    pair_key = f"{client}|{account_key}"
    for key, limit in (
        (pair_key, MAX_FAILED_LOGINS),
        (account_key, MAX_FAILED_LOGINS_PER_ACCOUNT),
    ):
        attempts = failed_logins.recent(key, FAILED_LOGIN_WINDOW_SECONDS)
        if len(attempts) >= limit:
            raise TooManyAttemptsError(_retry_after(attempts))

    user = db.query(User).filter(func.lower(User.email) == account_key).first() if account_key else None
    if user is None or not user.is_active or not verify_password(user, password):
        failed_logins.add(pair_key)
        failed_logins.add(account_key)
        raise ValueError("Invalid e-mail or password")

    failed_logins.clear(pair_key)
    user.login_count = (user.login_count or 0) + 1
    db.commit()
    db.refresh(user)
    return user


def change_password(db: Session, user: User, current_password: str, new_password: str) -> None:
    """Set a new password for a signed-in user.

    The current password is checked only when there is one: an account
    without a password got its session from Google, which already proved who
    is asking.
    """
    if user.password_hash and not verify_password(user, current_password):
        raise PasswordError("wrong_current_password")
    _validate_new_password(user, new_password)
    user.password_hash = hash_password(new_password)
    user.password_reset_token = None
    user.password_reset_expires_at = None
    db.commit()


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _send_link(db: Session, user: User, *, setup: bool, ttl: timedelta) -> None:
    """Store a fresh link for ``user`` and mail it. Delivery errors are logged."""
    token = secrets.token_urlsafe(32)
    user.password_reset_token = _digest(token)
    user.password_reset_expires_at = datetime.now(timezone.utc) + ttl
    db.commit()

    link = f"{settings.APP_URL.rstrip('/')}/reset-password?token={token}"
    if setup:
        subject = "Nastavenie hesla"
        days = ttl.days
        validity = f"{days} dní" if days >= 2 else "jednu hodinu"
        text = (
            "Dobrý deň,\n\n"
            "v aplikácii Službička vám bol vytvorený účet. "
            "Prihlasovacie meno je tento e-mail. Heslo si nastavíte cez tento odkaz:\n"
            f"{link}\n\n"
            f"Odkaz platí {validity}. Neskôr si nový odkaz vypýtate cez "
            "„Zabudli ste heslo?“ na prihlasovacej stránke.\n"
        )
    else:
        subject = "Zmena hesla"
        text = (
            "Dobrý deň,\n\n"
            "na zmenu hesla k vášmu účtu použite tento odkaz:\n"
            f"{link}\n\n"
            "Odkaz platí jednu hodinu. Ak ste o zmenu nežiadali, správu môžete ignorovať.\n"
        )
    try:
        send_message(build_message(subject=subject, recipients=[user.email], text_body=text))
    except EmailError:
        logger.exception("Password link mail to user %s could not be sent", user.id)


def send_setup_link(db: Session, user: User) -> bool:
    """Mail a new account the link to set its first password.

    Returns:
        Whether a mail went out; without a mail server the account is still
        created and the owner can ask for a link later.
    """
    if not is_email_configured():
        logger.warning("Mail is not configured; no setup link for user %s", user.id)
        return False
    _send_link(db, user, setup=True, ttl=SETUP_TOKEN_TTL)
    return True


def request_password_reset(db: Session, email: str) -> None:
    """Mail a link to set a new password, if the account exists.

    The same request sets the first password of an account that has none.
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

    user = db.query(User).filter(func.lower(User.email) == key).first()
    if user is None or not user.is_active:
        return
    _send_link(db, user, setup=not user.password_hash, ttl=RESET_TOKEN_TTL)


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
    """Set a password from a mailed link and sign the account out everywhere."""
    user = _user_for_reset_token(db, token)
    _validate_new_password(user, new_password)
    user.password_hash = hash_password(new_password)
    user.password_reset_token = None
    user.password_reset_expires_at = None
    user.auth_token = None
    user.auth_token_expires_at = None
    db.commit()
    failed_logins.clear(normalize_email(user.email))
