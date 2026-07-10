from sqlalchemy import Column, Integer, ForeignKey, DateTime, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.session import Base

class UserRole(Base):
    __tablename__ = "user_roles"
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    role_id = Column(Integer, ForeignKey("roles.id"), primary_key=True)

    user = relationship("User", back_populates="user_roles")
    role = relationship("Role", back_populates="user_roles")

class UserAmbulance(Base):
    __tablename__ = "user_ambulances"
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    ambulance_id = Column(Integer, ForeignKey("ambulances.id"), primary_key=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    is_active = Column(Boolean, default=True)

    user = relationship("User", back_populates="user_ambulances")
    ambulance = relationship("Ambulance", back_populates="user_ambulances")


class UserCompetence(Base):
    __tablename__ = "user_competences"
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    competence_id = Column(Integer, ForeignKey("competences.id"), primary_key=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    is_active = Column(Boolean, default=True)

    user = relationship("User", back_populates="user_competences")
    competence = relationship("Competence", back_populates="user_competences")
