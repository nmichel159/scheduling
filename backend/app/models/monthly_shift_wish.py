"""An employee's duty wish for one particular month."""

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from app.db.session import Base


class MonthlyShiftWish(Base):
    """The most duties an employee wants in one month.

    It outranks the standing wish on the user for that month only; the
    scheduler's cap on the user outranks both. A month without a row falls
    back to the standing wish.
    """

    __tablename__ = "monthly_shift_wishes"
    __table_args__ = (
        UniqueConstraint("user_id", "year", "month", name="uq_monthly_shift_wishes_month"),
        CheckConstraint("month >= 1 AND month <= 12", name="ck_monthly_shift_wishes_month"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)
    max_shifts_per_month = Column(Integer, nullable=False)
    updated_at = Column(
        DateTime(timezone=True), onupdate=func.now(), server_default=func.now()
    )
