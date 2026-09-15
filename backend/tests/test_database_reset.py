"""Tests for the destructive rebuild-from-scratch path."""

import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import reset, seed
from app.db.session import Base
from app.models import Ambulance, SeedVersion, User


class DatabaseResetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        self.patches = [
            patch.object(seed, "engine", self.engine),
            patch.object(seed, "SessionLocal", self.session_factory),
            patch.object(reset, "SessionLocal", self.session_factory),
        ]
        for active in self.patches:
            active.start()

    def tearDown(self) -> None:
        for active in reversed(self.patches):
            active.stop()
        self.engine.dispose()

    def _add_stray_rows(self) -> None:
        """Insert data no seed profile declares, as a leftover environment would."""
        with self.session_factory() as db:
            db.add(Ambulance(name="Leftover clinic", is_active=True))
            db.add(User(email="leftover@example.test", full_name="Leftover", login_count=0))
            db.commit()

    def test_reset_removes_rows_no_profile_declares(self) -> None:
        self.assertTrue(seed.seed_db("config_2", only_if_outdated=True))
        self._add_stray_rows()

        reset.reset_database("config_2", confirmed=True)

        with self.session_factory() as db:
            self.assertIsNone(
                db.query(Ambulance).filter_by(name="Leftover clinic").one_or_none()
            )
            self.assertIsNone(
                db.query(User).filter_by(email="leftover@example.test").one_or_none()
            )
            # The profile's own data is rebuilt, and recorded as applied.
            self.assertIsNotNone(
                db.query(Ambulance).filter_by(name="ambulancia1").one_or_none()
            )
            self.assertEqual(
                db.get(SeedVersion, "config_2").version,
                seed.SEED_CONFIGS["config_2"]["version"],
            )

    def test_reset_without_confirmation_deletes_nothing(self) -> None:
        seed.seed_db("config_2", only_if_outdated=True)
        with self.session_factory() as db:
            before = db.query(User).count()

        with self.assertRaises(PermissionError):
            reset.reset_database("config_2")

        with self.session_factory() as db:
            self.assertEqual(db.query(User).count(), before)

    def test_failed_reseed_rolls_the_wipe_back(self) -> None:
        """An infeasible profile must not leave the database empty."""
        seed.seed_db("config_2", only_if_outdated=True)
        with self.session_factory() as db:
            before = db.query(User).count()
        self.assertGreater(before, 0)

        with patch.object(
            reset, "apply_seed_profile", side_effect=RuntimeError("infeasible profile")
        ):
            with self.assertRaisesRegex(RuntimeError, "infeasible profile"):
                reset.reset_database("config_2", confirmed=True)

        with self.session_factory() as db:
            self.assertEqual(db.query(User).count(), before)

    def test_migration_history_is_never_cleared(self) -> None:
        """Alembic owns alembic_version; clearing it would re-run every migration."""
        self.assertNotIn("alembic_version", Base.metadata.tables)
        self.assertNotIn("alembic_version", reset.application_tables())

    def test_every_mapped_table_is_covered(self) -> None:
        self.assertEqual(
            set(reset.application_tables()), set(Base.metadata.tables)
        )


if __name__ == "__main__":
    unittest.main()
