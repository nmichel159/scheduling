"""FastAPI router for mailing a workplace's monthly schedule to the clinic.

Every route is scoped to an ambulance the caller manages, which
``get_manager_ambulance`` enforces: a scheduler mails the schedules of the
workplaces they run, and nothing else.
"""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_manager_ambulance
from app.db.session import get_db
from app.models.ambulance import Ambulance
from app.models.schedule_mail import ScheduleMailDispatch
from app.models.user import User
from app.schemas.schedule_mail import (
    FillRequestGroup,
    FillRequestResult,
    FillRequestSend,
    FillRequestTemplate,
    ScheduleMailDispatchResponse,
    ScheduleMailPreview,
    ScheduleMailRecipientCreate,
    ScheduleMailRecipientResponse,
    ScheduleMailRequest,
)
from app.services.schedule_mail_service import (
    DEFAULT_DISPATCH_LIMIT,
    add_recipient,
    build_schedule_mail,
    delete_recipient,
    list_dispatches,
    fill_request_template,
    list_fill_request_groups,
    list_recipients,
    send_fill_request,
    send_schedule_mail,
)

router = APIRouter()


@router.get(
    "/mail/fill-request-groups",
    response_model=list[FillRequestGroup],
    summary="The caller's workplaces with their employees, for a group mailing",
)
def list_fill_request_groups_endpoint(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[FillRequestGroup]:
    return list_fill_request_groups(db, current_user)


@router.get(
    "/mail/fill-request-template",
    response_model=FillRequestTemplate,
    summary="The default wording of the fill-in request",
)
def fill_request_template_endpoint(
    _current_user: User = Depends(get_current_user),
) -> FillRequestTemplate:
    return FillRequestTemplate(**fill_request_template())


@router.post(
    "/mail/fill-request",
    response_model=FillRequestResult,
    summary="Ask the chosen employees to fill their schedule in",
)
def send_fill_request_endpoint(
    data: FillRequestSend,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FillRequestResult:
    result = send_fill_request(
        db, current_user, data.user_ids, data.subject, data.body
    )
    return FillRequestResult(**result)


def _dispatch_response(item: ScheduleMailDispatch) -> ScheduleMailDispatchResponse:
    return ScheduleMailDispatchResponse(
        id=item.id,
        ambulance_id=item.ambulance_id,
        month=item.month,
        year=item.year,
        recipients=item.recipients,
        status=item.status,
        error=item.error,
        entry_count=item.entry_count,
        sent_by_user_id=item.sent_by_user_id,
        sent_by_full_name=item.sent_by.full_name if item.sent_by else None,
        created_at=item.created_at,
    )


@router.get(
    "/{ambulance_id}/mail-recipients",
    response_model=list[ScheduleMailRecipientResponse],
    summary="Addresses one workplace's schedules are mailed to",
)
def list_mail_recipients_endpoint(
    ambulance: Ambulance = Depends(get_manager_ambulance),
    db: Session = Depends(get_db),
) -> list[ScheduleMailRecipientResponse]:
    return list_recipients(db, ambulance.id)


@router.post(
    "/{ambulance_id}/mail-recipients",
    response_model=ScheduleMailRecipientResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add one address to a workplace's schedule mailing",
)
def add_mail_recipient_endpoint(
    data: ScheduleMailRecipientCreate,
    ambulance: Ambulance = Depends(get_manager_ambulance),
    db: Session = Depends(get_db),
) -> ScheduleMailRecipientResponse:
    return add_recipient(db, ambulance.id, data.email, data.label)


@router.delete(
    "/{ambulance_id}/mail-recipients/{recipient_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Stop mailing one address",
)
def delete_mail_recipient_endpoint(
    recipient_id: int,
    ambulance: Ambulance = Depends(get_manager_ambulance),
    db: Session = Depends(get_db),
) -> None:
    delete_recipient(db, ambulance.id, recipient_id)


@router.get(
    "/{ambulance_id}/schedule/mail-preview",
    response_model=ScheduleMailPreview,
    summary="What would be mailed for one workplace-month",
)
def preview_schedule_mail_endpoint(
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2000, le=2100),
    note: str | None = Query(None, max_length=2000),
    ambulance: Ambulance = Depends(get_manager_ambulance),
    db: Session = Depends(get_db),
) -> ScheduleMailPreview:
    content = build_schedule_mail(db, ambulance, month, year, note)
    return ScheduleMailPreview(
        ambulance_id=ambulance.id,
        month=month,
        year=year,
        subject=content["subject"],
        text_body=content["text_body"],
        entry_count=content["entry_count"],
        recipients=list_recipients(db, ambulance.id),
    )


@router.post(
    "/{ambulance_id}/schedule/mail",
    response_model=ScheduleMailDispatchResponse,
    summary="Mail one approved workplace-month to its clinic addresses",
)
def send_schedule_mail_endpoint(
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2000, le=2100),
    data: ScheduleMailRequest | None = None,
    ambulance: Ambulance = Depends(get_manager_ambulance),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ScheduleMailDispatchResponse:
    request = data or ScheduleMailRequest()
    dispatch = send_schedule_mail(
        db,
        ambulance,
        month,
        year,
        current_user,
        request.recipient_ids,
        request.note,
    )
    return _dispatch_response(dispatch)


@router.get(
    "/{ambulance_id}/schedule/mail-log",
    response_model=list[ScheduleMailDispatchResponse],
    summary="Recent send attempts for one workplace",
)
def list_schedule_mail_log_endpoint(
    limit: int = Query(DEFAULT_DISPATCH_LIMIT, ge=1, le=100),
    ambulance: Ambulance = Depends(get_manager_ambulance),
    db: Session = Depends(get_db),
) -> list[ScheduleMailDispatchResponse]:
    return [_dispatch_response(item) for item in list_dispatches(db, ambulance.id, limit)]
