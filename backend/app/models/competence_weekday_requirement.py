"""Weekday-specific staffing requirements for ambulance competences."""

from sqlalchemy import CheckConstraint, Column, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import relationship

from app.db.session import Base


class CompetenceWeekdayRequirement(Base):
    """Required headcount for one competence on one ISO weekday.

    Weekdays use Python's ``date.weekday()`` convention: Monday is 0 and
    Sunday is 6. A zero count means the competence is not staffed that day.
    """

    __tablename__ = "competence_weekday_requirements"
    __table_args__ = (
        UniqueConstraint(
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
    )

    id = Column(Integer, primary_key=True, index=True)
    competence_id = Column(
        Integer,
        ForeignKey("competences.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    weekday = Column(Integer, nullable=False)
    required_count = Column(Integer, nullable=False, default=0)

    competence = relationship("Competence", back_populates="weekday_requirements")
