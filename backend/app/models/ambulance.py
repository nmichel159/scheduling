from sqlalchemy import Column, Integer, String, DateTime, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.session import Base
from app.models.associations import user_ambulances, ambulance_competences

class Ambulance(Base):
    __tablename__ = "ambulances"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())
    is_active = Column(Boolean, default=True)

    users = relationship("User", secondary=user_ambulances, back_populates="ambulances")
    competences = relationship("Competence", secondary=ambulance_competences, back_populates="ambulances")
    schedules = relationship("Schedule", back_populates="ambulance")
