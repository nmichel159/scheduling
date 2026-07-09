from sqlalchemy import Column, Integer, String, DateTime, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.session import Base
from app.models.associations import user_roles, user_ambulances, user_competences

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    full_name = Column(String, nullable=True)
    auth_token = Column(String, nullable=True)
    login_count = Column(Integer, default=0)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())
    is_active = Column(Boolean, default=True)

    roles = relationship("Role", secondary=user_roles, back_populates="users")
    ambulances = relationship("Ambulance", secondary=user_ambulances, back_populates="users")
    competences = relationship("Competence", secondary=user_competences, back_populates="users")
    unavailabilities = relationship("Unavailability", back_populates="user")
    schedules = relationship("Schedule", back_populates="user")