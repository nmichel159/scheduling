"""Regression tests for endpoint-oriented database indexes."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from alembic import command
from alembic.config import Config
import sqlalchemy as sa

from app.db.session import Base
import app.models  # noqa: F401 - register every model in Base.metadata


BACKEND_ROOT = Path(__file__).resolve().parents[1]

EXPECTED_INDEXES = {
    "schedules": {
        "ix_schedules_user_active_work_date": (
            "user_id",
            "is_active",
            "work_date",
        ),
        "ix_schedules_ambulance_active_work_date": (
            "ambulance_id",
            "is_active",
            "work_date",
        ),
    },
    "unavailabilities": {
        "ix_unavailabilities_user_active_date": (
            "user_id",
            "is_active",
            "date_absent",
            "id",
        ),
    },
    "user_roles": {
        "ix_user_roles_role_user": ("role_id", "user_id"),
    },
    "user_ambulances": {
        "ix_user_ambulances_ambulance_active_user": (
            "ambulance_id",
            "is_active",
            "user_id",
        ),
    },
    "user_competences": {
        "ix_user_competences_competence_active_user": (
            "competence_id",
            "is_active",
            "user_id",
        ),
    },
    "competences": {
        "ix_competences_ambulance_active_name": (
            "ambulance_id",
            "is_active",
            "name",
        ),
    },
    "ambulances": {
        "ix_ambulances_manager_active_name": (
            "managed_by_user_id",
            "is_active",
            "name",
        ),
        "ix_ambulances_active_urgent_name": (
            "is_active",
            "isurgent",
            "name",
        ),
    },
    "users": {
        "ix_users_active_full_name_email": (
            "is_active",
            "full_name",
            "email",
        ),
    },
}


class PerformanceIndexMetadataTests(unittest.TestCase):
    """Keep fresh-database model metadata aligned with the migration."""

    def test_models_declare_every_performance_index(self) -> None:
        """Every expected index is present with columns in the intended order."""
        for table_name, expected_indexes in EXPECTED_INDEXES.items():
            table = Base.metadata.tables[table_name]
            actual = {
                index.name: tuple(column.name for column in index.columns)
                for index in table.indexes
            }
            for index_name, columns in expected_indexes.items():
                self.assertEqual(actual.get(index_name), columns)


class PerformanceIndexMigrationTests(unittest.TestCase):
    """Apply and roll back indexes against a minimal legacy database."""

    def setUp(self) -> None:
        handle, database_path = tempfile.mkstemp(suffix=".sqlite3")
        os.close(handle)
        self.database_path = Path(database_path)
        self.database_url = f"sqlite:///{self.database_path.as_posix()}"
        self.engine = sa.create_engine(self.database_url)
        self._create_legacy_tables()

    def tearDown(self) -> None:
        self.engine.dispose()
        self.database_path.unlink(missing_ok=True)

    def _create_legacy_tables(self) -> None:
        """Create endpoint tables without the new secondary indexes."""
        metadata = sa.MetaData()
        sa.Table(
            "users",
            metadata,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("is_active", sa.Boolean()),
            sa.Column("full_name", sa.String()),
            sa.Column("email", sa.String()),
        )
        sa.Table(
            "ambulances",
            metadata,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("managed_by_user_id", sa.Integer()),
            sa.Column("is_active", sa.Boolean()),
            sa.Column("isurgent", sa.Boolean()),
            sa.Column("name", sa.String()),
        )
        sa.Table(
            "competences",
            metadata,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("required_count", sa.Integer(), nullable=False),
            sa.Column("ambulance_id", sa.Integer()),
            sa.Column("is_active", sa.Boolean()),
            sa.Column("name", sa.String()),
        )
        sa.Table(
            "schedules",
            metadata,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer()),
            sa.Column("ambulance_id", sa.Integer()),
            sa.Column("is_active", sa.Boolean()),
            sa.Column("work_date", sa.Date()),
        )
        sa.Table(
            "unavailabilities",
            metadata,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer()),
            sa.Column("is_active", sa.Boolean()),
            sa.Column("date_absent", sa.Date()),
        )
        sa.Table(
            "user_roles",
            metadata,
            sa.Column("user_id", sa.Integer(), primary_key=True),
            sa.Column("role_id", sa.Integer(), primary_key=True),
        )
        sa.Table(
            "user_ambulances",
            metadata,
            sa.Column("user_id", sa.Integer(), primary_key=True),
            sa.Column("ambulance_id", sa.Integer(), primary_key=True),
            sa.Column("is_active", sa.Boolean()),
        )
        sa.Table(
            "user_competences",
            metadata,
            sa.Column("user_id", sa.Integer(), primary_key=True),
            sa.Column("competence_id", sa.Integer(), primary_key=True),
            sa.Column("is_active", sa.Boolean()),
        )
        metadata.create_all(self.engine)

    def _config(self) -> Config:
        config = Config(str(BACKEND_ROOT / "alembic.ini"))
        config.set_main_option("sqlalchemy.url", self.database_url)
        return config

    def _run_without_environment_database_url(self, operation) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DATABASE_URL", None)
            operation()

    def _actual_indexes(self, table_name: str) -> dict[str, tuple[str, ...]]:
        inspector = sa.inspect(self.engine)
        return {
            index["name"]: tuple(index["column_names"])
            for index in inspector.get_indexes(table_name)
        }

    def test_upgrade_creates_every_applicable_index(self) -> None:
        """The migration adds all indexes to a complete legacy schema."""
        self._run_without_environment_database_url(
            lambda: command.upgrade(self._config(), "head")
        )
        for table_name, expected_indexes in EXPECTED_INDEXES.items():
            actual = self._actual_indexes(table_name)
            for index_name, columns in expected_indexes.items():
                self.assertEqual(actual.get(index_name), columns)

    def test_downgrade_removes_only_performance_indexes(self) -> None:
        """Rolling back one revision removes the endpoint indexes cleanly."""
        config = self._config()
        self._run_without_environment_database_url(
            lambda: command.upgrade(config, "head")
        )
        self._run_without_environment_database_url(
            lambda: command.downgrade(config, "20260812_01")
        )
        for table_name, expected_indexes in EXPECTED_INDEXES.items():
            actual = self._actual_indexes(table_name)
            self.assertTrue(set(expected_indexes).isdisjoint(actual))


if __name__ == "__main__":
    unittest.main()
