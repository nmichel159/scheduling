from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.session import Base
from sqlalchemy.ext.associationproxy import association_proxy
from app.models.associations import UserAmbulance

class Ambulance(Base):
    __tablename__ = "ambulances"
    __table_args__ = (
        Index(
            "ix_ambulances_manager_active_name",
            "managed_by_user_id",
            "is_active",
            "name",
        ),
        Index(
            "ix_ambulances_active_urgent_name",
            "is_active",
            "isurgent",
            "name",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    managed_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    isurgent = Column(Boolean, default=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())
    is_active = Column(Boolean, default=True)

    # Core relationship mappings
    user_ambulances = relationship("UserAmbulance", back_populates="ambulance", cascade="all, delete-orphan")
    competences = relationship("Competence", back_populates="ambulance", cascade="all, delete-orphan")
    schedules = relationship("Schedule", back_populates="ambulance")
    manager = relationship("User", back_populates="managed_ambulances")

    # Proxies for direct collection manipulation
    users = association_proxy("user_ambulances", "user", creator=lambda u: UserAmbulance(user=u))
