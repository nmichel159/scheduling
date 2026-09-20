"""Sending mail out of the application.

One place knows SMTP. Everything above it builds an :class:`EmailMessage`
and hands it over, so a later switch to a hosted mail API touches this file
and nothing else.

Two things are deliberate here. Delivery is all-or-nothing per message: a
single SMTP conversation carries every recipient, and a refused address
fails the whole send rather than leaving the caller guessing who got it --
the caller writes a dispatch record, and a half-true one is worse than a
failed one. And an unconfigured mail server is an ordinary, reported state
(:class:`EmailNotConfiguredError`), not a crash: development and test runs
have no SMTP server, and ``MAIL_DRY_RUN`` lets them exercise the whole path
with the message going to the log.
"""

from __future__ import annotations

import logging
import smtplib
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import parseaddr

from app.core.config import settings

logger = logging.getLogger(__name__)


class EmailError(Exception):
    """Base class for anything that stops a message from being delivered."""


class EmailNotConfiguredError(EmailError):
    """No mail server (or no sender address) is configured."""


class EmailDeliveryError(EmailError):
    """The mail server refused or could not be reached."""


def is_email_configured() -> bool:
    """Whether a real send could happen right now."""
    if settings.MAIL_DRY_RUN:
        return bool(settings.MAIL_FROM)
    return bool(settings.SMTP_HOST) and bool(settings.MAIL_FROM)


def is_valid_email(address: str) -> bool:
    """Accept what an SMTP server would plausibly accept.

    Deliberately shallow: the authoritative verdict comes from the mail
    server, and a strict regex here would only reject valid addresses.
    """
    candidate = (address or "").strip()
    if not candidate or " " in candidate:
        return False
    _name, parsed = parseaddr(candidate)
    if parsed != candidate or candidate.count("@") != 1:
        return False
    local, _sep, domain = candidate.partition("@")
    return bool(local) and "." in domain and not domain.startswith(".") and not domain.endswith(".")


def build_message(
    *,
    subject: str,
    recipients: list[str],
    text_body: str,
    html_body: str | None = None,
    attachments: list[tuple[str, str, bytes]] | None = None,
    reply_to: str | None = None,
    from_name: str | None = None,
) -> EmailMessage:
    """Assemble a message from the configured sender to ``recipients``.

    Args:
        subject: Subject line.
        recipients: Mailboxes to deliver to, at least one.
        text_body: Plain-text body, the part every client can render.
        html_body: Optional richer alternative.
        attachments: ``(filename, mime_subtype, content)`` triples, attached
            as ``text/<mime_subtype>`` in UTF-8.
        reply_to: Where a reply should go. The envelope sender is always the
            configured mailbox -- the application has no access to anybody
            else's -- so this is what makes a reply reach the person who
            pressed the button.
        from_name: Display name to show instead of ``MAIL_FROM_NAME``.

    Returns:
        A ready-to-send :class:`EmailMessage`.

    Raises:
        EmailNotConfiguredError: If no sender address is configured.
    """
    if not settings.MAIL_FROM:
        raise EmailNotConfiguredError("MAIL_FROM is not configured.")
    if not recipients:
        raise EmailDeliveryError("A message needs at least one recipient.")

    message = EmailMessage()
    message["Subject"] = subject
    local, _sep, domain = settings.MAIL_FROM.partition("@")
    message["From"] = Address(
        from_name or settings.MAIL_FROM_NAME or "", local, domain
    )
    message["To"] = ", ".join(recipients)
    if reply_to:
        message["Reply-To"] = reply_to
    message.set_content(text_body)
    if html_body:
        message.add_alternative(html_body, subtype="html")
    for filename, subtype, content in attachments or []:
        message.add_attachment(
            content,
            maintype="text",
            subtype=subtype,
            filename=filename,
        )
    return message


def send_message(message: EmailMessage) -> str:
    """Deliver one message and report how it was handled.

    Returns:
        ``"sent"`` when the mail server accepted it, ``"dry-run"`` when
        ``MAIL_DRY_RUN`` is on and it only reached the log.

    Raises:
        EmailNotConfiguredError: If no SMTP host or sender is configured and
            dry-run mode is off.
        EmailDeliveryError: If the mail server refused or was unreachable.
    """
    if settings.MAIL_DRY_RUN:
        logger.info(
            "MAIL_DRY_RUN: not sending %r to %s",
            message["Subject"],
            message["To"],
        )
        return "dry-run"
    if not settings.SMTP_HOST:
        raise EmailNotConfiguredError("SMTP_HOST is not configured.")
    if not settings.MAIL_FROM:
        raise EmailNotConfiguredError("MAIL_FROM is not configured.")

    try:
        if settings.SMTP_USE_SSL:
            client = smtplib.SMTP_SSL(
                settings.SMTP_HOST,
                settings.SMTP_PORT,
                timeout=settings.SMTP_TIMEOUT_SECONDS,
            )
        else:
            client = smtplib.SMTP(
                settings.SMTP_HOST,
                settings.SMTP_PORT,
                timeout=settings.SMTP_TIMEOUT_SECONDS,
            )
        with client:
            if settings.SMTP_USE_TLS and not settings.SMTP_USE_SSL:
                client.starttls()
            if settings.SMTP_USERNAME:
                client.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            client.send_message(message)
    except (smtplib.SMTPException, OSError) as exc:
        raise EmailDeliveryError(str(exc)) from exc
    return "sent"
