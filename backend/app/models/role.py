from sqlalchemy import Column, Integer, String, DateTime, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.session import Base
from sqlalchemy.ext.associationproxy import association_proxy
from app.models.associations import UserRole

class Role(Base):
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    level = Column(Integer, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())
    is_active = Column(Boolean, default=True)

    # Core relationship mappings
    user_roles = relationship("UserRole", back_populates="role", cascade="all, delete-orphan")
    
    # Proxies for direct collection manipulation
    users = association_proxy("user_roles", "user", creator=lambda u: UserRole(user=u))
