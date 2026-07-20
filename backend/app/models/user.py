from sqlalchemy import Column, Integer, String, DateTime, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.session import Base
from sqlalchemy.ext.associationproxy import association_proxy
from app.models.associations import UserRole, UserAmbulance, UserCompetence

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    full_name = Column(String, nullable=True)
    # Stores only a SHA-256 digest of an opaque browser-session token.
    auth_token = Column(String(64), nullable=True, index=True)
    auth_token_expires_at = Column(DateTime(timezone=True), nullable=True)
    login_count = Column(Integer, default=0)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())
    is_active = Column(Boolean, default=True)

    # Core relationship mappings
    user_roles = relationship("UserRole", back_populates="user", cascade="all, delete-orphan")
    user_ambulances = relationship("UserAmbulance", back_populates="user", cascade="all, delete-orphan")
    user_competences = relationship("UserCompetence", back_populates="user", cascade="all, delete-orphan")
    
    unavailabilities = relationship("Unavailability", back_populates="user")
    schedules = relationship("Schedule", back_populates="user")
    managed_ambulances = relationship("Ambulance", back_populates="manager")

    # Proxies for direct collection manipulation
    roles = association_proxy("user_roles", "role", creator=lambda r: UserRole(role=r))
    ambulances = association_proxy("user_ambulances", "ambulance", creator=lambda a: UserAmbulance(ambulance=a))
    competences = association_proxy("user_competences", "competence", creator=lambda c: UserCompetence(competence=c))
