from sqlalchemy import Column, Integer, String, DateTime, Boolean, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func, true as sa_true
from app.db.session import Base
from sqlalchemy.ext.associationproxy import association_proxy
from app.models.associations import UserRole, UserAmbulance, UserCompetence

class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        Index(
            "ix_users_active_full_name_email",
            "is_active",
            "full_name",
            "email",
        ),
    )
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    full_name = Column(String, nullable=True)
    # Stores only a SHA-256 digest of an opaque browser-session token.
    auth_token = Column(String(64), nullable=True, index=True)
    auth_token_expires_at = Column(DateTime(timezone=True), nullable=True)
    # Scrypt hash of the password the employee chose. NULL means none was
    # chosen yet, and the account still signs in with its e-mail as the
    # password -- the one it was given when a scheduler or admin created it.
    password_hash = Column(String(255), nullable=True)
    # SHA-256 digest of the single outstanding "forgot password" link.
    password_reset_token = Column(String(64), nullable=True, index=True)
    password_reset_expires_at = Column(DateTime(timezone=True), nullable=True)
    login_count = Column(Integer, default=0)
    # How many duties a month the employee wants at most. NULL means no
    # opinion, which is not the same as wishing for zero duties.
    max_shifts_per_month = Column(Integer, nullable=True)
    # The same wish narrowed to surcharged duties; NULL again means no
    # opinion, while zero asks for no surcharged duty at all.
    max_surcharge_shifts_per_month = Column(Integer, nullable=True)
    # Which kind of duty the employee would rather be given: "surcharge",
    # "standard" or "any". It is a preference and not a filter -- the
    # solver may still hand out the other kind when a day needs staffing.
    shift_preference = Column(
        String(16), nullable=False, default="any", server_default="any"
    )
    # Whether the generator may give the employee duties. An inactive
    # employee -- on long leave, say -- stays in the workplace with their
    # competences and wishes, but is left out of every new plan. Not to be
    # confused with is_active, which removes the account itself.
    scheduling_active = Column(
        Boolean, nullable=False, default=True, server_default=sa_true()
    )
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())
    is_active = Column(Boolean, default=True)

    # Core relationship mappings
    user_roles = relationship("UserRole", back_populates="user", cascade="all, delete-orphan")
    user_ambulances = relationship("UserAmbulance", back_populates="user", cascade="all, delete-orphan")
    user_competences = relationship("UserCompetence", back_populates="user", cascade="all, delete-orphan")
    
    unavailabilities = relationship(
        "Unavailability",
        back_populates="user",
        foreign_keys="Unavailability.user_id",
    )
    schedules = relationship("Schedule", back_populates="user")
    managed_ambulances = relationship("Ambulance", back_populates="manager")

    # Proxies for direct collection manipulation
    roles = association_proxy("user_roles", "role", creator=lambda r: UserRole(role=r))
    ambulances = association_proxy("user_ambulances", "ambulance", creator=lambda a: UserAmbulance(ambulance=a))
    competences = association_proxy("user_competences", "competence", creator=lambda c: UserCompetence(competence=c))
