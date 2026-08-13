"""Persistent claim and result for one automatic monthly generation run."""

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Integer,
    JSON,
    String,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from app.db.session import Base


class AutomaticScheduleGenerationRun(Base):
    """Ensure one server-side automatic generation attempt per target month."""

    __tablename__ = "automatic_schedule_generation_runs"
    __table_args__ = (
        UniqueConstraint(
            "target_year",
            "target_month",
            name="uq_auto_schedule_runs_target_period",
        ),
        CheckConstraint(
            "target_month >= 1 AND target_month <= 12",
            name="ck_auto_schedule_runs_target_month",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    target_year = Column(Integer, nullable=False)
    target_month = Column(Integer, nullable=False)
    status = Column(String(32), nullable=False)
    summary = Column(JSON, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
