"""Regression tests for database migrations."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from alembic import command
from alembic.config import Config
import sqlalchemy as sa


BACKEND_ROOT = Path(__file__).resolve().parents[1]


class CompetenceWeekdayMigrationTests(unittest.TestCase):
    """Verify legacy competence counts are expanded to a complete week."""

    def setUp(self) -> None:
        handle, database_path = tempfile.mkstemp(suffix=".sqlite3")
        os.close(handle)
        self.database_path = Path(database_path)
        self.database_url = f"sqlite:///{self.database_path.as_posix()}"
        self.engine = sa.create_engine(self.database_url)

        metadata = sa.MetaData()
        competences = sa.Table(
            "competences",
            metadata,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("required_count", sa.Integer(), nullable=False),
        )
        metadata.create_all(self.engine)
        with self.engine.begin() as connection:
            connection.execute(
                competences.insert(),
                [
                    {"id": 1, "required_count": 2},
                    {"id": 2, "required_count": 4},
                ],
            )

    def tearDown(self) -> None:
        self.engine.dispose()
        self.database_path.unlink(missing_ok=True)

    def _upgrade(self) -> None:
        """Run all migrations against the temporary legacy database."""
        config = Config(str(BACKEND_ROOT / "alembic.ini"))
        config.set_main_option("sqlalchemy.url", self.database_url)

        with unittest.mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DATABASE_URL", None)
            command.upgrade(config, "head")

    def _load_requirements(self) -> list[sa.Row]:
        """Load all migrated weekday requirements in deterministic order."""
        requirements = sa.Table(
            "competence_weekday_requirements",
            sa.MetaData(),
            autoload_with=self.engine,
        )
        with self.engine.connect() as connection:
            return connection.execute(
                sa.select(
                    requirements.c.competence_id,
                    requirements.c.weekday,
                    requirements.c.required_count,
                ).order_by(requirements.c.competence_id, requirements.c.weekday)
            ).all()

    def test_backfills_monday_through_sunday_from_legacy_count(self) -> None:
        """Each old competence receives seven rows with its previous count."""
        self._upgrade()
        rows = self._load_requirements()

        self.assertEqual(len(rows), 14)
        self.assertEqual(
            [(row.weekday, row.required_count) for row in rows[:7]],
            [(weekday, 2) for weekday in range(7)],
        )
        self.assertEqual(
            [(row.weekday, row.required_count) for row in rows[7:]],
            [(weekday, 4) for weekday in range(7)],
        )

    def test_preserves_existing_day_and_only_adds_missing_weekdays(self) -> None:
        """An already configured weekday must not be overwritten."""
        metadata = sa.MetaData()
        requirements = sa.Table(
            "competence_weekday_requirements",
            metadata,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("competence_id", sa.Integer(), nullable=False),
            sa.Column("weekday", sa.Integer(), nullable=False),
            sa.Column("required_count", sa.Integer(), nullable=False),
            sa.UniqueConstraint("competence_id", "weekday"),
        )
        metadata.create_all(self.engine)
        with self.engine.begin() as connection:
            connection.execute(
                requirements.insert(),
                {"competence_id": 1, "weekday": 0, "required_count": 9},
            )

        self._upgrade()
        rows = self._load_requirements()

        self.assertEqual(len(rows), 14)
        self.assertEqual(rows[0].required_count, 9)
        self.assertEqual(
            [(row.weekday, row.required_count) for row in rows[1:7]],
            [(weekday, 2) for weekday in range(1, 7)],
        )


if __name__ == "__main__":
    unittest.main()
