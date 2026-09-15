"""Clear every application table and rebuild the database from one seed profile.

Seeding alone cannot produce a clean database: it upserts by natural key and
only ever deletes inside the narrow scopes a profile declares, so rows left by
an earlier profile survive it. Rebuilding a demo or test environment from
scratch therefore needs an explicit wipe, which is what this module adds.

The tables come from the ORM metadata rather than a hardcoded list, so a model
added later is covered without touching this file, and Alembic's own
``alembic_version`` table -- which that metadata does not describe -- is never
cleared. The schema and its migration history survive a reset; only rows go.
"""

import argparse
import sys

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.seed import apply_seed_profile, lock_seed_writes
from app.db.session import Base, SessionLocal, engine

# Importing the package registers every mapped class on Base.metadata, which is
# what makes the table list below complete.
import app.models  # noqa: F401  (imported for its registration side effect)


def application_tables() -> list[str]:
    """Names of the tables a reset clears, ordered children first."""
    return [table.name for table in reversed(Base.metadata.sorted_tables)]


def wipe_application_tables(db: Session) -> list[str]:
    """Delete every row of every mapped table inside the caller's transaction.

    PostgreSQL truncates all of them in one statement, so sequences restart and
    the foreign keys between them are resolved by CASCADE rather than by
    ordering. Other dialects -- the SQLite test harness -- have no TRUNCATE, so
    the rows are deleted children-first instead.

    Returns:
        The names of the cleared tables.
    """
    tables = list(reversed(Base.metadata.sorted_tables))
    if not tables:
        return []

    bind = db.get_bind()
    if bind.dialect.name == "postgresql":
        preparer = bind.dialect.identifier_preparer
        targets = ", ".join(preparer.format_table(table) for table in tables)
        db.execute(text(f"TRUNCATE TABLE {targets} RESTART IDENTITY CASCADE"))
    else:
        for table in tables:
            db.execute(table.delete())

    db.flush()
    return [table.name for table in tables]


def reset_database(config_name: str | None = None, *, confirmed: bool = False) -> str:
    """Clear every application table and reapply one seed profile atomically.

    The wipe and the reseed share a transaction, so a profile the solver cannot
    satisfy rolls the whole thing back and leaves the database as it was rather
    than empty.

    Args:
        config_name: Seed profile to rebuild from; defaults to ``SEED_CONFIG``.
        confirmed: Must be True. The flag exists so that no call with default
            arguments can destroy a database by accident.

    Returns:
        The seed version recorded in ``seed_versions``.

    Raises:
        PermissionError: When the caller did not confirm the wipe.
    """
    if not confirmed:
        raise PermissionError(
            "reset_database() deletes every row; pass confirmed=True to proceed."
        )

    selected_config_name = config_name or settings.SEED_CONFIG
    db: Session = SessionLocal()
    try:
        lock_seed_writes(db)
        cleared = wipe_application_tables(db)
        version = apply_seed_profile(db, selected_config_name)
        db.commit()
        print(
            f"Cleared {len(cleared)} tables and rebuilt from "
            f"{selected_config_name}:{version}."
        )
        return version
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def target_database() -> str:
    """The connection target, with the password removed so it can be printed."""
    return engine.url.render_as_string(hide_password=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.db.reset",
        description="Delete all application data and rebuild it from a seed profile.",
    )
    parser.add_argument(
        "config",
        nargs="?",
        default=None,
        help="Seed profile to rebuild from (default: the SEED_CONFIG setting).",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm that every row in the target database may be deleted.",
    )
    args = parser.parse_args(argv)

    target = target_database()
    if not args.yes:
        parser.error(
            f"refusing to delete every row of {target} without --yes"
        )

    print(f"Rebuilding {target} from {args.config or settings.SEED_CONFIG}...")
    reset_database(args.config, confirmed=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
