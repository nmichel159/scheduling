"""Weekday-specific staffing parameters for ambulance competences."""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Float,
    ForeignKey,
    Integer,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from app.db.session import Base

#: Days of rest a duty costs when nothing else is configured. One day off
#: means a Monday duty frees the holder again on Wednesday.
DEFAULT_RECOVERY_DAYS = 1

#: People a duty needs when a scenario is started from the defaults.
DEFAULT_REQUIRED_COUNT = 1

#: Hours a duty lasts when nothing else is configured. It is what the
#: competence editor pre-fills a new competence with.
DEFAULT_SHIFT_HOURS = 4.0

#: The eighth slot of the week: a day of rest that is not a weekday at all.
#: A date the special-day library (or the workplace) calls a day of rest is
#: staffed from this slot instead of from its calendar weekday, so a public
#: holiday falling on a Tuesday is staffed like a holiday and not like a
#: Tuesday.
SPECIAL_DAY_SLOT = 7

#: Every slot a competence carries parameters for: Monday to Sunday plus
#: the special day.
REQUIREMENT_SLOTS = tuple(range(8))

#: Weekdays a duty is paid with a surcharge unless the editor says
#: otherwise. Saturday and Sunday, in ``date.weekday()`` numbering, and the
#: special day, which is a day of rest by definition.
DEFAULT_SURCHARGE_WEEKDAYS = (5, 6, SPECIAL_DAY_SLOT)


def default_is_surcharge(weekday: int) -> bool:
    """Whether a freshly created weekday starts out surcharged."""
    return weekday in DEFAULT_SURCHARGE_WEEKDAYS


class CompetenceWeekdayRequirement(Base):
    """Parameters of one competence, on one day slot, in one scenario.

    Weekdays use Python's ``date.weekday()`` convention: Monday is 0 and
    Sunday is 6. Slot 7 (:data:`SPECIAL_DAY_SLOT`) is not a weekday but the
    day of rest: a date the special-day library or the workplace marks as
    one is staffed from that slot whatever weekday it falls on. A zero
    ``required_count`` means the competence is not staffed that day.

    ``recovery_days`` says how many days off a duty on this weekday costs
    its holder before the same competence may be assigned to them again:
    0 allows the very next day, 1 (the default) skips one day. It is stored
    and edited but not yet enforced by the schedule solver.

    ``shift_hours`` is how long a duty on this weekday lasts. Like the
    counts it belongs to one scenario, so the same competence can be a
    four-hour duty in one model case and a twelve-hour one in another.

    ``is_surcharge`` says whether that duty is paid with a surcharge. It is
    per weekday because that is what the distinction actually follows: the
    same competence is ordinary on a Tuesday and surcharged on a Sunday.
    New weekdays start out surcharged exactly on the weekend.
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
            "weekday >= 0 AND weekday <= 7",
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
        CheckConstraint(
            "shift_hours >= 0 AND shift_hours <= 24",
            name="ck_competence_weekday_requirement_shift_hours",
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
    shift_hours = Column(
        Float, nullable=False, default=DEFAULT_SHIFT_HOURS, server_default="4"
    )
    is_surcharge = Column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    competence = relationship("Competence", back_populates="weekday_requirements")
    scenario = relationship("CompetenceScenario", back_populates="weekday_requirements")
