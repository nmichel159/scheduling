"""Custom days: a workplace's own kinds of day, placed on chosen dates.

The scenarios staff a date from its weekday, or from the day-of-rest slot
when the calendar calls it one. Some dates fit neither -- a day the clinic
runs a reduced service, an inspection, a day before a holiday. A custom day
is a named set of parameters for such a date: how many people each
competence needs, how long the duty is, what rest it earns and whether it
is surcharged.

A custom day does nothing until it is placed on a date. One
:class:`CustomDayDate` row says "this date is staffed as that custom day",
and it outranks both the weekday and the day of rest. Removing the row hands
the date back to the calendar.

The parameters belong to the workplace, not to a scenario: a custom day is
the answer for one particular date, and that answer should not change
because a different model case is selected.
"""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func, text

from app.db.session import Base


class CustomDay(Base):
    """One named kind of day of one workplace."""

    __tablename__ = "custom_days"
    __table_args__ = (Index("ix_custom_days_ambulance", "ambulance_id"),)

    id = Column(Integer, primary_key=True, index=True)
    ambulance_id = Column(
        Integer,
        ForeignKey("ambulances.id", ondelete="CASCADE"),
        nullable=False,
    )
    name = Column(String, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), onupdate=func.now(), server_default=func.now()
    )

    requirements = relationship(
        "CustomDayRequirement",
        back_populates="custom_day",
        cascade="all, delete-orphan",
    )
    dates = relationship(
        "CustomDayDate",
        back_populates="custom_day",
        cascade="all, delete-orphan",
    )


class CustomDayRequirement(Base):
    """What one competence needs on one custom day.

    A competence with no row here is not staffed on that day: a custom day
    is defined by what it asks for, and a competence added to the workplace
    later must not start demanding people on it unasked.
    """

    __tablename__ = "custom_day_requirements"
    __table_args__ = (
        UniqueConstraint(
            "custom_day_id",
            "competence_id",
            name="uq_custom_day_requirement",
        ),
        CheckConstraint(
            "required_count >= 0", name="ck_custom_day_requirement_count"
        ),
        CheckConstraint(
            "recovery_days >= 0 AND recovery_days <= 6",
            name="ck_custom_day_requirement_recovery",
        ),
        CheckConstraint(
            "shift_hours >= 0 AND shift_hours <= 24",
            name="ck_custom_day_requirement_shift_hours",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    custom_day_id = Column(
        Integer,
        ForeignKey("custom_days.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    competence_id = Column(
        Integer,
        ForeignKey("competences.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    required_count = Column(Integer, nullable=False, default=0)
    recovery_days = Column(Integer, nullable=False, default=1, server_default="1")
    shift_hours = Column(Float, nullable=False, default=4.0, server_default="4")
    is_surcharge = Column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    custom_day = relationship("CustomDay", back_populates="requirements")


class CustomDayDate(Base):
    """One date of one workplace staffed as a custom day."""

    __tablename__ = "custom_day_dates"
    __table_args__ = (
        UniqueConstraint("ambulance_id", "day", name="uq_custom_day_dates_ambulance_day"),
        Index("ix_custom_day_dates_ambulance_day", "ambulance_id", "day"),
    )

    id = Column(Integer, primary_key=True, index=True)
    ambulance_id = Column(
        Integer,
        ForeignKey("ambulances.id", ondelete="CASCADE"),
        nullable=False,
    )
    day = Column(Date, nullable=False)
    custom_day_id = Column(
        Integer,
        ForeignKey("custom_days.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    custom_day = relationship("CustomDay", back_populates="dates")
