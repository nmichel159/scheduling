from sqlalchemy import Column, Integer, String, DateTime, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.session import Base
from app.models.associations import user_competences, ambulance_competences

class Competence(Base):
    __tablename__ = "competences"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())
    is_active = Column(Boolean, default=True)

    users = relationship("User", secondary=user_competences, back_populates="competences")
    ambulances = relationship("Ambulance", secondary=ambulance_competences, back_populates="competences")
    schedules = relationship("Schedule", back_populates="competence")
