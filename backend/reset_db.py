import os
import sys
import argparse

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
from app.db.seed import seed_db

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:password@postgres:5432/appdb")
engine = create_engine(DATABASE_URL)

def reset_db(config_name: str = "config_1"):
    print(f"Registered tables: {Base.metadata.tables.keys()}")
    print("Dropping tables...")
    Base.metadata.drop_all(bind=engine)
    print("Creating tables...")
    Base.metadata.create_all(bind=engine)
    seed_db(config_name)
    print(f"Database reset and seeded successfully with {config_name}.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Reset and seed the scheduling database.")
    parser.add_argument(
        "config_name",
        nargs="?",
        default=os.getenv("SEED_CONFIG", "config_1"),
        choices=("config_1", "config_2"),
        help="Seed profile to initialize (default: config_1).",
    )
    reset_db(parser.parse_args().config_name)
