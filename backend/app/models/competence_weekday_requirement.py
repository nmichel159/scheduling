"""Weekday-specific staffing parameters for ambulance competences."""

from sqlalchemy import CheckConstraint, Column, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import relationship

from app.db.session import Base

#: Days of rest a duty costs when nothing else is configured. One day off
#: means a Monday duty frees the holder again on Wednesday.
DEFAULT_RECOVERY_DAYS = 1


class CompetenceWeekdayRequirement(Base):
    """Parameters of one competence, on one ISO weekday, in one scenario.

    Weekdays use Python's ``date.weekday()`` convention: Monday is 0 and
    Sunday is 6. A zero ``required_count`` means the competence is not
    staffed that day.

    ``recovery_days`` says how many days off a duty on this weekday costs
    its holder before the same competence may be assigned to them again:
    0 allows the very next day, 1 (the default) skips one day. It is stored
    and edited but not yet enforced by the schedule solver.
    """

    __tablename__ = "competence_weekday_requirements"
    __table_args__ = (
        UniqueConstraint(
            "scenario_id",
            "competence_id",
            "weekday",
            name="uq_competence_weekday_requirement",
        ),
        CheckConstraint(
            "weekday >= 0 AND weekday <= 6",
            name="ck_competence_weekday_requirement_weekday",
        ),
        CheckConstraint(
            "required_count >= 0",
            name="ck_competence_weekday_requirement_count",
        ),
        CheckConstraint(
            "recovery_days >= 0 AND recovery_days <= 6",
            name="ck_competence_weekday_requirement_recovery",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    competence_id = Column(
        Integer,
        ForeignKey("competences.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scenario_id = Column(
        Integer,
        ForeignKey("competence_scenarios.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    weekday = Column(Integer, nullable=False)
    required_count = Column(Integer, nullable=False, default=0)
    recovery_days = Column(
        Integer, nullable=False, default=DEFAULT_RECOVERY_DAYS, server_default="1"
    )

    competence = relationship("Competence", back_populates="weekday_requirements")
    scenario = relationship("CompetenceScenario", back_populates="weekday_requirements")
