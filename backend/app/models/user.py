from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.sql import func
from app.db.session import Base

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    full_name = Column(String)
    google_id = Column(String, unique=True, index=True)
    picture_url = Column(String)
    login_count = Column(Integer, default=0)
    last_login = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())