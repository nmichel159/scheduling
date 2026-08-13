from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, Date, Index, text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.session import Base

class Unavailability(Base):
    __tablename__ = "unavailabilities"
    __table_args__ = (
        Index(
            "ix_unavailabilities_user_active_date",
            "user_id",
            "is_active",
            "date_absent",
            "id",
        ),
        Index(
            "uq_unavailabilities_active_user_date",
            "user_id",
            "date_absent",
            unique=True,
            postgresql_where=text("is_active IS TRUE"),
            sqlite_where=text("is_active = 1"),
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    date_absent = Column(Date, nullable=False)
    reason = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())
    is_active = Column(Boolean, default=True)

    user = relationship("User", back_populates="unavailabilities")
