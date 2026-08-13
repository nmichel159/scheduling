"""Prepare the database schema, migrate it, and optionally seed mock data."""

from pathlib import Path

from alembic import command
from alembic.config import Config

from app.core.config import settings
from app.db.seed import seed_db


def migrate_database() -> None:
    """Run all committed migrations before optional seed writes."""
    alembic_config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    command.upgrade(alembic_config, "head")


def bootstrap_database() -> bool:
    migrate_database()
    if not settings.AUTO_SEED:
        print("Automatic database seeding is disabled (AUTO_SEED=false).")
        return False
    return seed_db(settings.SEED_CONFIG, only_if_outdated=True)


if __name__ == "__main__":
    bootstrap_database()
