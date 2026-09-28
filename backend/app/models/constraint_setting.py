"""One workplace's setting for one rule of schedule generation.

The rules themselves are code -- ``constraint_setting_service.CONSTRAINTS``
lists them with their defaults. A row exists only where a workplace chose
something other than the default, so deleting it hands the rule back to
whatever the code says.
"""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.session import Base


class ConstraintSetting(Base):
    """How strictly, or at what price, one workplace applies one rule."""

    __tablename__ = "constraint_settings"
    __table_args__ = (
        UniqueConstraint(
            "ambulance_id", "code", name="uq_constraint_settings_ambulance_code"
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    ambulance_id = Column(
        Integer,
        ForeignKey("ambulances.id", ondelete="CASCADE"),
        nullable=False,
    )
    #: Which rule, as named in ``constraint_setting_service``.
    code = Column(String, nullable=False)
    #: ``True`` means the generator never breaks the rule.
    is_strict = Column(Boolean, nullable=False, default=False)
    #: What one breach costs while the rule is penalized.
    weight = Column(Float, nullable=False, default=0.0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), onupdate=func.now(), server_default=func.now()
    )

    ambulance = relationship("Ambulance", back_populates="constraint_settings")
