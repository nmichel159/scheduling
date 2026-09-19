"""Per-workplace corrections to the public-holiday library.

Which calendar days are days of rest ("dni pracovného pokoja") is answered
by the ``holidays`` library for Slovakia, not by this table: the law is the
same for every workplace and nobody should have to type it in. What a
workplace does own are the exceptions -- a day the library does not call a
day of rest but this clinic closes on anyway, and a day of rest this clinic
staffs regardless.

One row is therefore one override of the library for one workplace and one
date, in whichever direction ``is_rest_day`` points. Deleting the row does
not change the day; it returns it to whatever the library says.
"""

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.session import Base


class SpecialDay(Base):
    """One workplace's verdict on one date, overriding the library."""

    __tablename__ = "special_days"
    __table_args__ = (
        UniqueConstraint("ambulance_id", "day", name="uq_special_days_ambulance_day"),
        Index("ix_special_days_ambulance_day", "ambulance_id", "day"),
    )

    id = Column(Integer, primary_key=True, index=True)
    ambulance_id = Column(
        Integer,
        ForeignKey("ambulances.id", ondelete="CASCADE"),
        nullable=False,
    )
    day = Column(Date, nullable=False)
    #: ``True`` adds a day of rest the library does not know, ``False``
    #: takes one away. There is no third state -- that is the absent row.
    is_rest_day = Column(Boolean, nullable=False, default=True)
    #: What the workplace calls the day. Only ever set on added days; a day
    #: the library already names keeps that name.
    name = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), onupdate=func.now(), server_default=func.now()
    )

    ambulance = relationship("Ambulance", back_populates="special_days")
