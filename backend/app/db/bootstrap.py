"""Prepare the database schema and optionally update deterministic mock data."""

from app.core.config import settings
from app.db.seed import seed_db
from app.db.session import Base, engine
import app.models  # noqa: F401 - registers every model in Base.metadata


def bootstrap_database() -> bool:
    Base.metadata.create_all(bind=engine)
    if not settings.AUTO_SEED:
        print("Automatic database seeding is disabled (AUTO_SEED=false).")
        return False
    return seed_db(settings.SEED_CONFIG, only_if_outdated=True)


if __name__ == "__main__":
    bootstrap_database()
