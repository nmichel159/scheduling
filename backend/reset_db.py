import os
import sys

from sqlalchemy import create_engine
from app.db.session import Base

# Import all models explicitly to ensure they are registered with Base.metadata
from app.models.user import User
from app.models.role import Role
from app.models.ambulance import Ambulance
from app.models.competence import Competence
from app.models.unavailability import Unavailability
from app.models.schedule import Schedule
from app.models.audit import AuditLog
from app.models.associations import UserRole, UserAmbulance, UserCompetence

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:password@postgres:5432/appdb")
engine = create_engine(DATABASE_URL)

def reset_db():
    print(f"Registered tables: {Base.metadata.tables.keys()}")
    print("Dropping tables...")
    Base.metadata.drop_all(bind=engine)
    print("Creating tables...")
    Base.metadata.create_all(bind=engine)
    print("Database reset successful.")

if __name__ == "__main__":
    reset_db()
