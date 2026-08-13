from sqlalchemy import Column, Integer, DateTime, Boolean, ForeignKey, Date, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.session import Base

class Schedule(Base):
    __tablename__ = "schedules"
    __table_args__ = (
        Index(
            "ix_schedules_user_active_work_date",
            "user_id",
            "is_active",
            "work_date",
        ),
        Index(
            "ix_schedules_ambulance_active_work_date",
            "ambulance_id",
            "is_active",
            "work_date",
        ),
        Index(
            "uq_schedules_entry",
            "user_id",
            "ambulance_id",
            "competence_id",
            "work_date",
            unique=True,
        ),
    )

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
