from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, Date, Time
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.session import Base

class Unavailability(Base):
    __tablename__ = "unavailabilities"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    date_absent = Column(Date, nullable=False)

    # Time window of the unavailability (e.g. clinic/office hours that block
    # emergency-duty scheduling). Both NULL means the user is absent all day.
    start_time = Column(Time, nullable=True)
    end_time = Column(Time, nullable=True)

    reason = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())
    is_active = Column(Boolean, default=True)

    user = relationship("User", back_populates="unavailabilities")
