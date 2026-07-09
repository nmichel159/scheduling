from sqlalchemy import Column, Integer, ForeignKey, Table, DateTime, Boolean
from sqlalchemy.sql import func
from app.db.session import Base

user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
    Column("role_id", Integer, ForeignKey("roles.id"), primary_key=True),
)

user_ambulances = Table(
    "user_ambulances",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
    Column("ambulance_id", Integer, ForeignKey("ambulances.id"), primary_key=True),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("is_active", Boolean, default=True)
)

ambulance_competences = Table(
    "ambulance_competences",
    Base.metadata,
    Column("ambulance_id", Integer, ForeignKey("ambulances.id"), primary_key=True),
    Column("competence_id", Integer, ForeignKey("competences.id"), primary_key=True),
    Column("required_count", Integer, default=1),
)

user_competences = Table(
    "user_competences",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
    Column("competence_id", Integer, ForeignKey("competences.id"), primary_key=True),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("is_active", Boolean, default=True)
)
