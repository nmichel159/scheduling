from sqlalchemy import Column, DateTime, String
from sqlalchemy.sql import func

from app.db.session import Base


class SeedVersion(Base):
    """Tracks the deterministic mock-data version applied to a database."""

    __tablename__ = "seed_versions"

    profile = Column(String, primary_key=True)
    version = Column(String, nullable=False)
    applied_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

