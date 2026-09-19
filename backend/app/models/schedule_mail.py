"""Where a workplace's schedule is mailed, and what was mailed when.

A clinic is not a user of this system: nobody there logs in, and the people
who need the finished monthly schedule -- the head of the clinic, the ward
secretary -- read it in their mailbox. So the addresses cannot be derived
from the employee list; they are their own list, owned by the workplace and
maintained by the scheduler who manages it.

The second table is the record of what left the building. A schedule that
was mailed to a clinic is a statement the clinic will plan around, and
"which version did they get, and when" is a question that gets asked. Every
attempt is written down, the failed ones too -- a send that silently did not
happen is the failure mode worth guarding against.
"""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.session import Base


class ScheduleMailRecipient(Base):
    """One mailbox that receives one workplace's monthly schedules."""

    __tablename__ = "schedule_mail_recipients"
    __table_args__ = (
        UniqueConstraint(
            "ambulance_id",
            "email",
            name="uq_schedule_mail_recipients_ambulance_email",
        ),
        Index(
            "ix_schedule_mail_recipients_ambulance_active",
            "ambulance_id",
            "is_active",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    ambulance_id = Column(
        Integer,
        ForeignKey("ambulances.id", ondelete="CASCADE"),
        nullable=False,
    )
    email = Column(String, nullable=False)
    #: What to call the mailbox in the list -- "sekretariát", a person's
    #: name. Optional, because an address is often self-explanatory.
    label = Column(String, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), onupdate=func.now(), server_default=func.now()
    )

    ambulance = relationship("Ambulance", back_populates="mail_recipients")


class ScheduleMailDispatch(Base):
    """One attempt to mail one workplace-month package out."""

    __tablename__ = "schedule_mail_dispatches"
    __table_args__ = (
        Index(
            "ix_schedule_mail_dispatches_ambulance_period",
            "ambulance_id",
            "year",
            "month",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    ambulance_id = Column(
        Integer,
        ForeignKey("ambulances.id", ondelete="CASCADE"),
        nullable=False,
    )
    month = Column(Integer, nullable=False)
    year = Column(Integer, nullable=False)
    sent_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    #: The addresses as they were at the moment of sending, comma separated.
    #: Stored flat on purpose: this is a record of what happened, and it must
    #: survive the recipient rows being edited or deleted afterwards.
    recipients = Column(Text, nullable=False, default="")
    #: ``sent``, ``dry-run`` or ``failed`` -- see ``DISPATCH_STATUS_*``.
    status = Column(String, nullable=False)
    #: Why a failed attempt failed; null on success.
    error = Column(Text, nullable=True)
    #: How many duties the mailed schedule contained.
    entry_count = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    ambulance = relationship("Ambulance", back_populates="mail_dispatches")
    sent_by = relationship("User")


DISPATCH_STATUS_SENT = "sent"
DISPATCH_STATUS_DRY_RUN = "dry-run"
DISPATCH_STATUS_FAILED = "failed"
