from sqlalchemy import Column, Integer, DateTime, Boolean, ForeignKey, Date
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.session import Base

class Schedule(Base):
    __tablename__ = "schedules"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    ambulance_id = Column(Integer, ForeignKey("ambulances.id"), nullable=False)
    competence_id = Column(Integer, ForeignKey("competences.id"), nullable=False)
    
    work_date = Column(Date, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())
    is_active = Column(Boolean, default=True)

    user = relationship("User", back_populates="schedules")
    ambulance = relationship("Ambulance", back_populates="schedules")
    competence = relationship("Competence", back_populates="schedules")
