"""Persistent audit log model."""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.sql import func

from app.db.session import Base


class AuditLog(Base):
    """Persist the actor and affected fields for one database mutation."""

    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action = Column(String, nullable=False)
    entity_type = Column(String, nullable=False)
    entity_id = Column(String, nullable=False)
    changes = Column(JSON, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=True,
        server_default=func.now(),
    )
