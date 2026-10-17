"""When employees may fill in their restrictions for a month.

Restrictions are the employee's own, not a workplace's, so the window is one
for the whole application: a single settings row with the two days of the
month the scheduler chose, and one row per month for what happened to that
month -- a lock or an unlock the scheduler pressed by hand, and the reminder
the server sent.
"""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from app.db.session import Base


class AvailabilitySettings(Base):
    """The days of the previous month on which a month is announced and closed.

    There is at most one row; without it the code defaults apply.
    """

    __tablename__ = "availability_settings"
    __table_args__ = (
        CheckConstraint(
            "reminder_day >= 1 AND reminder_day < lock_day AND lock_day <= 28",
            name="ck_availability_settings_days",
        ),
    )

    id = Column(Integer, primary_key=True)
    #: Day of the previous month the employees are reminded to fill it in.
    reminder_day = Column(Integer, nullable=False)
    #: Day of the previous month from which the month is closed.
    lock_day = Column(Integer, nullable=False)
    updated_at = Column(
        DateTime(timezone=True), onupdate=func.now(), server_default=func.now()
    )


class AvailabilityPeriod(Base):
    """What the scheduler and the server did about one month."""

    __tablename__ = "availability_periods"
    __table_args__ = (
        UniqueConstraint("year", "month", name="uq_availability_periods_month"),
        CheckConstraint(
            "month >= 1 AND month <= 12", name="ck_availability_periods_month"
        ),
    )

    id = Column(Integer, primary_key=True)
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)
    #: ``True``/``False`` when the scheduler closed or opened the month by
    #: hand; ``None`` leaves it to the lock day.
    is_locked = Column(Boolean, nullable=True)
    #: When the server claimed the reminder for this month, so it goes once.
    reminder_sent_at = Column(DateTime(timezone=True), nullable=True)
    #: ``sent``, ``dry-run``, ``failed``, ``not-configured`` or ``skipped``.
    reminder_status = Column(String(32), nullable=True)
    reminder_recipients = Column(Integer, nullable=True)
    updated_at = Column(
        DateTime(timezone=True), onupdate=func.now(), server_default=func.now()
    )


class AvailabilityDayLimit(Base):
    """How many people of one workplace may have one kind of absence a day.

    One row per workplace and reason (``VACATION``, ``BUSINESS_TRIP``,
    ``UNAVAILABLE``); a reason without a row has no limit there.
    """

    __tablename__ = "availability_day_limits"
    __table_args__ = (
        CheckConstraint("max_per_day >= 0", name="ck_availability_day_limits_max"),
    )

    ambulance_id = Column(Integer, ForeignKey("ambulances.id"), primary_key=True)
    reason = Column(String(32), primary_key=True)
    max_per_day = Column(Integer, nullable=False)
    updated_at = Column(
        DateTime(timezone=True), onupdate=func.now(), server_default=func.now()
    )
