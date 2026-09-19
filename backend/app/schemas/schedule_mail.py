"""Pydantic schemas for mailing a workplace's monthly schedule out."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ScheduleMailRecipientCreate(BaseModel):
    """Subscribe one mailbox to a workplace's schedules."""

    email: str = Field(..., max_length=320)
    label: Optional[str] = Field(None, max_length=200)


class ScheduleMailRecipientResponse(BaseModel):
    """One mailbox that receives a workplace's schedules."""

    id: int
    ambulance_id: int
    email: str
    label: Optional[str] = None

    class Config:
        from_attributes = True


class ScheduleMailRequest(BaseModel):
    """Which addresses to mail, and what to write above the schedule.

    ``recipient_ids`` left out means every address of the workplace; that is
    the usual send, and naming a subset is for the case where one mailbox
    needs a resend.
    """

    recipient_ids: Optional[list[int]] = Field(None, max_length=200)
    note: Optional[str] = Field(None, max_length=2000)


class ScheduleMailPreview(BaseModel):
    """What would be sent, rendered without sending it."""

    ambulance_id: int
    month: int
    year: int
    subject: str
    text_body: str
    entry_count: int
    recipients: list[ScheduleMailRecipientResponse]


class ScheduleMailDispatchResponse(BaseModel):
    """One recorded send attempt.

    ``status`` is ``sent``, ``dry-run`` (mail is in dry-run mode and the
    message only reached the server log) or ``failed``, in which case
    ``error`` says why.
    """

    id: int
    ambulance_id: int
    month: int
    year: int
    recipients: str
    status: str
    error: Optional[str] = None
    entry_count: int
    sent_by_user_id: Optional[int] = None
    sent_by_full_name: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True
