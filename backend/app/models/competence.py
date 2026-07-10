from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.session import Base
from sqlalchemy.ext.associationproxy import association_proxy
from app.models.associations import UserCompetence

class Competence(Base):
    __tablename__ = "competences"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    ambulance_id = Column(Integer, ForeignKey("ambulances.id"), nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())
    is_active = Column(Boolean, default=True)

    # Core relationship mappings
    user_competences = relationship("UserCompetence", back_populates="competence", cascade="all, delete-orphan")
    ambulance = relationship("Ambulance", back_populates="competences")
    schedules = relationship("Schedule", back_populates="competence")

    # Proxies for direct collection manipulation
    users = association_proxy("user_competences", "user", creator=lambda u: UserCompetence(user=u))

