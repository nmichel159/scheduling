"""Named parameter sets ("scenarios") for a workplace's competences.

A workplace defines its competences once; a scenario holds one complete set
of *parameters* for them -- how many people each competence needs on each
weekday and how much recovery a duty costs. Switching the selected scenario
therefore changes the numbers a schedule is built from without touching the
competence list itself or who is qualified for what.

Exactly one scenario per ambulance carries ``is_selected``; that is the one
every other part of the application reads.
"""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.session import Base


class CompetenceScenario(Base):
    __tablename__ = "competence_scenarios"
    __table_args__ = (
        Index(
            "ix_competence_scenarios_ambulance_active",
            "ambulance_id",
            "is_active",
        ),
        Index(
            "uq_competence_scenarios_active_ambulance_name",
            "ambulance_id",
            "name",
            unique=True,
            postgresql_where=text("is_active IS TRUE"),
            sqlite_where=text("is_active = 1"),
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    ambulance_id = Column(Integer, ForeignKey("ambulances.id"), nullable=False)
    is_selected = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), onupdate=func.now(), server_default=func.now()
    )
    is_active = Column(Boolean, default=True)

    ambulance = relationship("Ambulance", back_populates="competence_scenarios")
    weekday_requirements = relationship(
        "CompetenceWeekdayRequirement",
        back_populates="scenario",
        cascade="all, delete-orphan",
    )
