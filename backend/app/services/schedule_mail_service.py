"""Mailing a workplace's monthly schedule to the clinic.

The scheduler finishes a month, approves it, and the clinic needs it in
writing. This module owns that step: the address book of one workplace, the
message built from its schedule, and the record of every attempt.

Two rules shape it.

*Only an approved month goes out.* An unapproved package is a draft the
employees themselves cannot see yet; mailing it to the clinic would make a
draft look like the plan. The check is the same one the schedule editor
applies -- the month holds duties and every one of them is published.

*The message is readable without opening an attachment.* The body is the
month as a day-by-day list, because that is what someone reads on a phone;
the CSV is attached for whoever wants to put it in a spreadsheet.
"""

from __future__ import annotations

import csv
import io
from calendar import monthrange
from datetime import date
from html import escape

from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.models.ambulance import Ambulance
from app.models.schedule import Schedule
from app.models.schedule_mail import (
    DISPATCH_STATUS_DRY_RUN,
    DISPATCH_STATUS_FAILED,
    DISPATCH_STATUS_SENT,
    ScheduleMailDispatch,
    ScheduleMailRecipient,
)
from app.models.user import User
from app.services.ambulance_employee_service import (
    list_employees,
    list_manager_ambulances,
)
from app.services.database_conflict import commit_or_conflict
from app.services.email_service import (
    EmailError,
    EmailNotConfiguredError,
    build_message,
    is_valid_email,
    send_message,
)

#: Monday-first weekday names, matching how the rest of the app writes them.
WEEKDAY_NAMES = ["Po", "Ut", "St", "Št", "Pi", "So", "Ne"]

MONTH_NAMES = [
    "január",
    "február",
    "marec",
    "apríl",
    "máj",
    "jún",
    "júl",
    "august",
    "september",
    "október",
    "november",
    "december",
]

#: How many past attempts the log endpoint hands back by default.
DEFAULT_DISPATCH_LIMIT = 20

#: Why a send was refused, as a stable code the screen can translate.
#: The message beside it is for the API log and for anyone reading the raw
#: response; the screen never shows it.
REFUSAL_CODES = ("empty_schedule", "not_approved", "no_recipients")


def _period_bounds(month: int, year: int) -> tuple[date, date]:
    if not 1 <= month <= 12 or not 2000 <= year <= 2100:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="month and year must be valid.",
        )
    return date(year, month, 1), date(year, month, monthrange(year, month)[1])


# --------------------------------------------------------------------------
# Address book
# --------------------------------------------------------------------------


def list_recipients(db: Session, ambulance_id: int) -> list[ScheduleMailRecipient]:
    """Every mailbox currently subscribed to one workplace's schedules."""
    return (
        db.query(ScheduleMailRecipient)
        .filter(
            ScheduleMailRecipient.ambulance_id == ambulance_id,
            ScheduleMailRecipient.is_active.is_(True),
        )
        .order_by(ScheduleMailRecipient.email)
        .all()
    )


def add_recipient(
    db: Session,
    ambulance_id: int,
    email: str,
    label: str | None = None,
) -> ScheduleMailRecipient:
    """Subscribe one mailbox, or revive the row a previous removal left.

    Raises:
        HTTPException 422: If the address is not a usable mailbox.
        HTTPException 409: If the workplace already mails to it.
    """
    address = (email or "").strip()
    if not is_valid_email(address):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A valid e-mail address is required.",
        )
    cleaned_label = (label or "").strip() or None

    existing = (
        db.query(ScheduleMailRecipient)
        .filter(
            ScheduleMailRecipient.ambulance_id == ambulance_id,
            ScheduleMailRecipient.email == address,
        )
        .first()
    )
    if existing:
        if existing.is_active:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This address already receives the schedule.",
            )
        existing.is_active = True
        existing.label = cleaned_label
        commit_or_conflict(db, "This address already receives the schedule.")
        db.refresh(existing)
        return existing

    item = ScheduleMailRecipient(
        ambulance_id=ambulance_id,
        email=address,
        label=cleaned_label,
        is_active=True,
    )
    db.add(item)
    commit_or_conflict(db, "This address already receives the schedule.")
    db.refresh(item)
    return item


def delete_recipient(db: Session, ambulance_id: int, recipient_id: int) -> None:
    """Stop mailing one address.

    The row is deactivated rather than deleted: past dispatch records name
    the address they went to, and a removal must not make them unreadable.
    """
    item = (
        db.query(ScheduleMailRecipient)
        .filter(
            ScheduleMailRecipient.id == recipient_id,
            ScheduleMailRecipient.ambulance_id == ambulance_id,
            ScheduleMailRecipient.is_active.is_(True),
        )
        .first()
    )
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recipient not found.",
        )
    item.is_active = False
    commit_or_conflict(db, "The recipient was changed by another request.")


# --------------------------------------------------------------------------
# The message
# --------------------------------------------------------------------------


def _month_entries(db: Session, ambulance_id: int, month: int, year: int) -> list[Schedule]:
    start, end = _period_bounds(month, year)
    return (
        db.query(Schedule)
        .options(joinedload(Schedule.user), joinedload(Schedule.competence))
        .filter(
            Schedule.ambulance_id == ambulance_id,
            Schedule.is_active.is_(True),
            Schedule.work_date.between(start, end),
        )
        .order_by(Schedule.work_date, Schedule.competence_id, Schedule.user_id)
        .all()
    )


def _employee_name(entry: Schedule) -> str:
    if entry.user and entry.user.full_name:
        return entry.user.full_name
    if entry.user and entry.user.email:
        return entry.user.email
    return str(entry.user_id)


def _period_label(month: int, year: int) -> str:
    return f"{MONTH_NAMES[month - 1]} {year}"


def build_subject(ambulance: Ambulance, month: int, year: int) -> str:
    return f"Rozpis služieb — {ambulance.name} — {_period_label(month, year)}"


def _text_body(
    ambulance: Ambulance,
    month: int,
    year: int,
    entries: list[Schedule],
    note: str | None,
) -> str:
    lines = [build_subject(ambulance, month, year), ""]
    if note:
        lines += [note, ""]
    current_day: date | None = None
    for entry in entries:
        if entry.work_date != current_day:
            current_day = entry.work_date
            weekday = WEEKDAY_NAMES[entry.work_date.weekday()]
            lines.append(f"{entry.work_date.isoformat()} ({weekday})")
        competence = entry.competence.name if entry.competence else ""
        lines.append(f"    {competence}: {_employee_name(entry)}")
    lines += ["", f"Počet služieb: {len(entries)}"]
    return "\n".join(lines) + "\n"


def _html_body(
    ambulance: Ambulance,
    month: int,
    year: int,
    entries: list[Schedule],
    note: str | None,
) -> str:
    rows = []
    for entry in entries:
        weekday = WEEKDAY_NAMES[entry.work_date.weekday()]
        rows.append(
            "<tr>"
            f"<td>{entry.work_date.isoformat()}</td>"
            f"<td>{weekday}</td>"
            f"<td>{escape(entry.competence.name if entry.competence else '')}</td>"
            f"<td>{escape(_employee_name(entry))}</td>"
            "</tr>"
        )
    note_html = f"<p>{escape(note)}</p>" if note else ""
    return (
        "<html><body style=\"font-family:Arial,Helvetica,sans-serif;font-size:14px\">"
        f"<h2>{escape(build_subject(ambulance, month, year))}</h2>"
        f"{note_html}"
        "<table cellspacing=\"0\" cellpadding=\"6\" border=\"1\" "
        "style=\"border-collapse:collapse\">"
        "<thead><tr><th>Dátum</th><th>Deň</th><th>Kompetencia</th>"
        "<th>Zamestnanec</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
        f"<p>Počet služieb: {len(entries)}</p>"
        "</body></html>"
    )


def _csv_attachment(entries: list[Schedule]) -> tuple[str, str, bytes]:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(["datum", "den", "kompetencia", "zamestnanec", "email"])
    for entry in entries:
        writer.writerow(
            [
                entry.work_date.isoformat(),
                WEEKDAY_NAMES[entry.work_date.weekday()],
                entry.competence.name if entry.competence else "",
                _employee_name(entry),
                entry.user.email if entry.user else "",
            ]
        )
    return ("rozpis.csv", "csv", buffer.getvalue().encode("utf-8"))


def build_schedule_mail(
    db: Session,
    ambulance: Ambulance,
    month: int,
    year: int,
    note: str | None = None,
) -> dict:
    """Render one workplace-month into a subject and both message bodies.

    Returns:
        ``subject``, ``text_body``, ``html_body``, ``attachment`` and
        ``entry_count`` -- everything a send needs, and everything the
        preview endpoint shows before one happens.

    Raises:
        HTTPException 409: If the month is empty or not fully approved.
    """
    entries = _month_entries(db, ambulance.id, month, year)
    if not entries:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "empty_schedule",
                "message": "An empty schedule cannot be sent.",
            },
        )
    if not all(entry.is_approved for entry in entries):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "not_approved",
                "message": "Only an approved schedule can be sent.",
            },
        )
    return {
        "subject": build_subject(ambulance, month, year),
        "text_body": _text_body(ambulance, month, year, entries, note),
        "html_body": _html_body(ambulance, month, year, entries, note),
        "attachment": _csv_attachment(entries),
        "entry_count": len(entries),
    }


# --------------------------------------------------------------------------
# Sending
# --------------------------------------------------------------------------


def _resolve_recipients(
    db: Session,
    ambulance_id: int,
    recipient_ids: list[int] | None,
) -> list[ScheduleMailRecipient]:
    recipients = list_recipients(db, ambulance_id)
    if recipient_ids is not None:
        wanted = set(recipient_ids)
        recipients = [item for item in recipients if item.id in wanted]
    if not recipients:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "no_recipients",
                "message": "This workplace has no schedule recipients.",
            },
        )
    return recipients


def send_schedule_mail(
    db: Session,
    ambulance: Ambulance,
    month: int,
    year: int,
    sender: User | None,
    recipient_ids: list[int] | None = None,
    note: str | None = None,
) -> ScheduleMailDispatch:
    """Mail one approved workplace-month out and record what happened.

    A delivery failure is not raised past this point: it is written into the
    dispatch log with its reason and returned, so the screen can show the
    scheduler that the send failed and why. Only a refusal to even attempt
    the send -- an empty or unapproved month, no recipients, no configured
    mail server -- comes back as an error.

    Args:
        db: Active database session.
        ambulance: The workplace whose schedule is being sent.
        month: Calendar month, 1-12.
        year: Calendar year.
        sender: The signed-in scheduler, recorded on the dispatch.
        recipient_ids: Which of the workplace's addresses to use; ``None``
            means all of them.
        note: A line from the scheduler, placed above the schedule.

    Returns:
        The persisted :class:`ScheduleMailDispatch`, successful or failed.

    Raises:
        HTTPException 409: Empty or unapproved month, or no recipients.
        HTTPException 503: No mail server is configured.
    """
    content = build_schedule_mail(db, ambulance, month, year, note)
    recipients = _resolve_recipients(db, ambulance.id, recipient_ids)
    addresses = [item.email for item in recipients]

    dispatch = ScheduleMailDispatch(
        ambulance_id=ambulance.id,
        month=month,
        year=year,
        sent_by_user_id=sender.id if sender else None,
        recipients=", ".join(addresses),
        status=DISPATCH_STATUS_SENT,
        entry_count=content["entry_count"],
    )

    try:
        message = build_message(
            subject=content["subject"],
            recipients=addresses,
            text_body=content["text_body"],
            html_body=content["html_body"],
            attachments=[content["attachment"]],
        )
        outcome = send_message(message)
    except EmailNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Mail sending is not configured: {exc}",
        ) from exc
    except EmailError as exc:
        dispatch.status = DISPATCH_STATUS_FAILED
        dispatch.error = str(exc)
    else:
        dispatch.status = (
            DISPATCH_STATUS_DRY_RUN if outcome == "dry-run" else DISPATCH_STATUS_SENT
        )

    db.add(dispatch)
    commit_or_conflict(db, "The dispatch record could not be written.")
    db.refresh(dispatch)
    return dispatch


def list_dispatches(
    db: Session,
    ambulance_id: int,
    limit: int = DEFAULT_DISPATCH_LIMIT,
) -> list[ScheduleMailDispatch]:
    """The most recent send attempts for one workplace, newest first."""
    return (
        db.query(ScheduleMailDispatch)
        .options(joinedload(ScheduleMailDispatch.sent_by))
        .filter(ScheduleMailDispatch.ambulance_id == ambulance_id)
        .order_by(ScheduleMailDispatch.id.desc())
        .limit(limit)
        .all()
    )


# --------------------------------------------------------------------------
# Asking the employees to fill their availability in
# --------------------------------------------------------------------------


FILL_REQUEST_SUBJECT = "Vyplňte si rozvrh"


def list_fill_request_groups(db: Session, manager: User) -> list[dict]:
    """The manager's workplaces, each with the employees assigned to it.

    One employee works in several workplaces, so the same address shows up
    in several groups. That is the point of the grouping -- the scheduler
    picks people the way they think of them, by workplace -- and the send
    deduplicates afterwards.
    """
    groups = []
    for ambulance in list_manager_ambulances(db, manager.id):
        groups.append(
            {
                "ambulance_id": ambulance.id,
                "ambulance_name": ambulance.name,
                "employees": [
                    {
                        "user_id": employee.user_id,
                        "email": employee.email,
                        "full_name": employee.full_name,
                    }
                    for employee in list_employees(db, ambulance.id)
                    if is_valid_email(employee.email or "")
                ],
            }
        )
    return groups


def fill_request_template() -> dict:
    """The default message, with the sign-in link already in it.

    The scheduler edits this before sending, so it is a starting point,
    not a fixed format -- the only thing the send really needs is an
    address list.
    """
    return {
        "subject": FILL_REQUEST_SUBJECT,
        "body": (
            "Dobrý deň,\n\n"
            "prosím, vyplňte si rozvrh.\n\n"
            f"{settings.APP_URL}\n"
        ),
    }


def send_fill_request(
    db: Session,
    manager: User,
    user_ids: list[int],
    subject: str | None = None,
    body: str | None = None,
) -> dict:
    """Mail the chosen employees a short request to fill their schedule in.

    Only employees of the workplaces the caller manages can be addressed;
    an id outside that set is dropped rather than refused, because the
    screen builds the selection from those same groups and a stale one is a
    reload, not an error.

    ``subject`` and ``body`` are what the scheduler edited on the screen;
    left out, the default template goes instead.

    Returns:
        ``status`` (``sent`` or ``dry-run``) and the addresses written to.

    Raises:
        HTTPException 409: If the selection resolves to no address.
        HTTPException 422: If the edited message is empty.
        HTTPException 503: If no mail server is configured.
    """
    wanted = set(user_ids or [])
    addresses: list[str] = []
    seen: set[str] = set()
    for group in list_fill_request_groups(db, manager):
        for employee in group["employees"]:
            if employee["user_id"] in wanted and employee["email"] not in seen:
                seen.add(employee["email"])
                addresses.append(employee["email"])

    if not addresses:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "no_recipients",
                "message": "No employee was selected.",
            },
        )

    template = fill_request_template()
    final_subject = (subject if subject is not None else template["subject"]).strip()
    final_body = (body if body is not None else template["body"]).strip()
    if not final_subject or not final_body:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A subject and a message are required.",
        )

    try:
        message = build_message(
            subject=final_subject,
            recipients=addresses,
            text_body=final_body + "\n",
            reply_to=manager.email or None,
            from_name=manager.full_name or None,
        )
        outcome = send_message(message)
    except EmailNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Mail sending is not configured: {exc}",
        ) from exc
    except EmailError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    return {"status": outcome, "recipients": addresses}
