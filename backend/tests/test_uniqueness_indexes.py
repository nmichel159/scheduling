"""Regression tests for race-safe endpoint uniqueness indexes."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from datetime import date

from alembic import command
from alembic.config import Config
import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.db.session import Base
import app.models  # noqa: F401 - register every model in Base.metadata
from app.services.database_conflict import commit_or_conflict


BACKEND_ROOT = Path(__file__).resolve().parents[1]

EXPECTED_UNIQUE_INDEXES = {
    "schedules": {
        "uq_schedules_entry": (
            "user_id",
            "ambulance_id",
            "competence_id",
            "work_date",
        ),
    },
    "unavailabilities": {
        "uq_unavailabilities_active_user_date": (
            "user_id",
            "date_absent",
        ),
    },
    "competences": {
        "uq_competences_active_ambulance_name": (
            "ambulance_id",
            "name",
        ),
    },
}


class UniquenessIndexMetadataTests(unittest.TestCase):
    """Keep fresh database metadata aligned with the migration."""

    def test_models_declare_every_unique_index(self) -> None:
        for table_name, expected_indexes in EXPECTED_UNIQUE_INDEXES.items():
            table = Base.metadata.tables[table_name]
            actual = {
                index.name: (
                    tuple(column.name for column in index.columns),
                    index.unique,
                )
                for index in table.indexes
            }
            for index_name, columns in expected_indexes.items():
                self.assertEqual(actual.get(index_name), (columns, True))

    def test_integrity_race_is_rolled_back_and_returned_as_conflict(self) -> None:
        session = mock.Mock()
        session.commit.side_effect = IntegrityError(
            "duplicate",
            {},
            Exception("unique violation"),
        )

        with self.assertRaises(HTTPException) as raised:
            commit_or_conflict(session, "Duplicate endpoint value.")

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.detail, "Duplicate endpoint value.")
        session.rollback.assert_called_once_with()


class UniquenessIndexMigrationTests(unittest.TestCase):
    """Exercise clean upgrades, duplicate preflights, and downgrades."""

    def setUp(self) -> None:
        handle, database_path = tempfile.mkstemp(suffix=".sqlite3")
        os.close(handle)
        self.database_path = Path(database_path)
        self.database_url = f"sqlite:///{self.database_path.as_posix()}"
        self.engine = sa.create_engine(self.database_url)
        self.tables = self._create_legacy_tables()

    def tearDown(self) -> None:
        self.engine.dispose()
        self.database_path.unlink(missing_ok=True)

    def _create_legacy_tables(self) -> dict[str, sa.Table]:
        metadata = sa.MetaData()
        tables = {
            "competences": sa.Table(
                "competences",
                metadata,
                sa.Column("id", sa.Integer(), primary_key=True),
                sa.Column("ambulance_id", sa.Integer(), nullable=False),
                sa.Column("name", sa.String(), nullable=False),
                sa.Column("required_count", sa.Integer(), nullable=False),
                sa.Column("is_active", sa.Boolean(), nullable=False),
            ),
            "schedules": sa.Table(
                "schedules",
                metadata,
                sa.Column("id", sa.Integer(), primary_key=True),
                sa.Column("user_id", sa.Integer(), nullable=False),
                sa.Column("ambulance_id", sa.Integer(), nullable=False),
                sa.Column("competence_id", sa.Integer(), nullable=False),
                sa.Column("work_date", sa.Date(), nullable=False),
                sa.Column("is_active", sa.Boolean(), nullable=False),
            ),
            "unavailabilities": sa.Table(
                "unavailabilities",
                metadata,
                sa.Column("id", sa.Integer(), primary_key=True),
                sa.Column("user_id", sa.Integer(), nullable=False),
                sa.Column("date_absent", sa.Date(), nullable=False),
                sa.Column("is_active", sa.Boolean(), nullable=False),
            ),
        }
        metadata.create_all(self.engine)
        return tables

    def _config(self) -> Config:
        config = Config(str(BACKEND_ROOT / "alembic.ini"))
        config.set_main_option("sqlalchemy.url", self.database_url)
        return config

    def _upgrade(self, revision: str = "head") -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DATABASE_URL", None)
            command.upgrade(self._config(), revision)

    def _downgrade(self, revision: str) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DATABASE_URL", None)
            command.downgrade(self._config(), revision)

    def _actual_indexes(self, table_name: str) -> dict[str, dict[str, object]]:
        return {
            index["name"]: index
            for index in sa.inspect(self.engine).get_indexes(table_name)
        }

    def test_clean_upgrade_creates_unique_indexes_and_downgrade_removes_them(self) -> None:
        self._upgrade()
        for table_name, expected_indexes in EXPECTED_UNIQUE_INDEXES.items():
            actual = self._actual_indexes(table_name)
            for index_name, columns in expected_indexes.items():
                self.assertEqual(tuple(actual[index_name]["column_names"]), columns)
                self.assertTrue(actual[index_name]["unique"])

        self._downgrade("20260813_01")
        for table_name, expected_indexes in EXPECTED_UNIQUE_INDEXES.items():
            self.assertTrue(
                set(expected_indexes).isdisjoint(self._actual_indexes(table_name))
            )

    def _assert_duplicate_preflight(
        self,
        table_name: str,
        rows: list[dict[str, object]],
        expected_index_name: str,
    ) -> None:
        with self.engine.begin() as connection:
            connection.execute(self.tables[table_name].insert(), rows)
        self._upgrade("20260813_01")
        with self.assertRaisesRegex(RuntimeError, expected_index_name):
            self._upgrade()
        with self.engine.connect() as connection:
            count = connection.scalar(
                sa.select(sa.func.count()).select_from(self.tables[table_name])
            )
        self.assertEqual(count, len(rows))
        self.assertNotIn(
            expected_index_name,
            self._actual_indexes(table_name),
        )

    def test_schedule_duplicate_stops_migration_without_changing_rows(self) -> None:
        duplicate = {
            "user_id": 1,
            "ambulance_id": 2,
            "competence_id": 3,
            "work_date": date(2026, 8, 13),
            "is_active": True,
        }
        self._assert_duplicate_preflight(
            "schedules",
            [{"id": 1, **duplicate}, {"id": 2, **duplicate}],
            "uq_schedules_entry",
        )

    def test_active_unavailability_duplicate_stops_migration(self) -> None:
        duplicate = {
            "user_id": 1,
            "date_absent": date(2026, 8, 13),
            "is_active": True,
        }
        self._assert_duplicate_preflight(
            "unavailabilities",
            [{"id": 1, **duplicate}, {"id": 2, **duplicate}],
            "uq_unavailabilities_active_user_date",
        )

    def test_active_competence_duplicate_stops_migration(self) -> None:
        duplicate = {
            "ambulance_id": 1,
            "name": "Physician",
            "required_count": 1,
            "is_active": True,
        }
        self._assert_duplicate_preflight(
            "competences",
            [{"id": 1, **duplicate}, {"id": 2, **duplicate}],
            "uq_competences_active_ambulance_name",
        )

    def test_partial_indexes_allow_inactive_historical_duplicates(self) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                self.tables["unavailabilities"].insert(),
                [
                    {
                        "id": 1,
                        "user_id": 1,
                        "date_absent": date(2026, 8, 13),
                        "is_active": False,
                    },
                    {
                        "id": 2,
                        "user_id": 1,
                        "date_absent": date(2026, 8, 13),
                        "is_active": False,
                    },
                ],
            )
        self._upgrade()
        self.assertIn(
            "uq_unavailabilities_active_user_date",
            self._actual_indexes("unavailabilities"),
        )


if __name__ == "__main__":
    unittest.main()
