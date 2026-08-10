"""Tests for version-aware deterministic database seeding."""

from collections import Counter, defaultdict
from copy import deepcopy
from datetime import date, timedelta
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import seed
from app.db import bootstrap
from app.db.session import Base
from app.db.seed_configs.ikaim import (
    AMBULANCE_NAME,
    STAFF,
    UNAVAILABILITIES,
)
from app.models import Ambulance, Competence, Schedule, SeedVersion, Unavailability, User
from app.services.schedule_generation_service import ScheduleGenerationError


class SeedVersioningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        self.engine_patch = patch.object(seed, "engine", self.engine)
        self.session_patch = patch.object(seed, "SessionLocal", self.session_factory)
        self.engine_patch.start()
        self.session_patch.start()

    def tearDown(self) -> None:
        self.session_patch.stop()
        self.engine_patch.stop()
        self.engine.dispose()

    def test_first_run_applies_seed_and_second_run_is_noop(self) -> None:
        self.assertTrue(seed.seed_db("config_1", only_if_outdated=True))
        with self.session_factory() as db:
            user_count = db.query(User).count()
            applied = db.get(SeedVersion, "config_1")
            self.assertEqual(applied.version, seed.SEED_CONFIGS["config_1"]["version"])

            ambulance = db.query(Ambulance).filter_by(name=AMBULANCE_NAME).one()
            self.assertEqual(ambulance.manager.email, "noro.michel159@gmail.com")
            self.assertEqual(len(STAFF), 33)

            competences = {
                row.name: row
                for row in db.query(Competence)
                .filter_by(ambulance_id=ambulance.id)
                .all()
            }
            self.assertEqual(
                {name: row.required_count for name, row in competences.items()},
                {
                    "Lôžko": 2,
                    "Anestézia": 2,
                    "Replantácie": 1,
                    "15:00–19:00": 1,
                },
            )
            august_schedule = (
                db.query(Schedule)
                .filter(
                    Schedule.ambulance_id == ambulance.id,
                    Schedule.work_date.between("2026-08-01", "2026-08-31"),
                )
                .all()
            )
            self.assertEqual(len(august_schedule), 186)
            coverage = Counter(
                (entry.work_date, entry.competence.name) for entry in august_schedule
            )
            for day in range(1, 32):
                work_date = date(2026, 8, day)
                self.assertEqual(coverage[(work_date, "Lôžko")], 2)
                self.assertEqual(coverage[(work_date, "Anestézia")], 2)
                self.assertEqual(coverage[(work_date, "Replantácie")], 1)
                self.assertEqual(coverage[(work_date, "15:00–19:00")], 1)

            duties_by_user = defaultdict(set)
            for entry in august_schedule:
                self.assertNotIn(entry.work_date, duties_by_user[entry.user_id])
                duties_by_user[entry.user_id].add(entry.work_date)
            self.assertTrue(
                all(
                    work_date + timedelta(days=1) not in work_dates
                    for work_dates in duties_by_user.values()
                    for work_date in work_dates
                )
            )
            unavailable = {
                (row.user_id, row.date_absent)
                for row in db.query(Unavailability)
                .filter_by(reason="MOCK_IKAIM_UNAVAILABLE")
                .all()
            }
            self.assertTrue(
                all((entry.user_id, entry.work_date) not in unavailable for entry in august_schedule)
            )

            absence_counts = {}
            for entry in UNAVAILABILITIES:
                absence_counts[entry["user_email"]] = (
                    absence_counts.get(entry["user_email"], 0) + 1
                )
            self.assertTrue(all(count in (4, 5) for count in absence_counts.values()))

        with patch.object(seed, "_apply_seed") as apply_seed:
            self.assertFalse(seed.seed_db("config_1", only_if_outdated=True))
            apply_seed.assert_not_called()

        with self.session_factory() as db:
            self.assertEqual(db.query(User).count(), user_count)

    def test_new_profile_version_is_applied_and_recorded(self) -> None:
        self.assertTrue(seed.seed_db("config_1", only_if_outdated=True))
        upgraded = deepcopy(seed.SEED_CONFIGS["config_1"])
        upgraded["version"] = str(int(upgraded["version"]) + 1)
        upgraded["users"][0]["full_name"] = "Updated by seed v2"

        with patch.dict(seed.SEED_CONFIGS, {"config_1": upgraded}):
            self.assertTrue(seed.seed_db("config_1", only_if_outdated=True))

        with self.session_factory() as db:
            applied = db.get(SeedVersion, "config_1")
            user = db.query(User).filter_by(email=upgraded["users"][0]["email"]).one()
            self.assertEqual(applied.version, upgraded["version"])
            self.assertEqual(user.full_name, "Updated by seed v2")

    def test_failed_seed_does_not_advance_version(self) -> None:
        with patch.object(seed, "_apply_seed", side_effect=RuntimeError("broken seed")):
            with self.assertRaisesRegex(RuntimeError, "broken seed"):
                seed.seed_db("config_1", only_if_outdated=True)

        with self.session_factory() as db:
            self.assertIsNone(db.get(SeedVersion, "config_1"))

    def test_bootstrap_does_not_seed_when_auto_seed_is_disabled(self) -> None:
        with (
            patch.object(bootstrap.settings, "AUTO_SEED", False),
            patch.object(bootstrap, "seed_db") as seed_db,
            patch.object(bootstrap.Base.metadata, "create_all") as create_all,
        ):
            self.assertFalse(bootstrap.bootstrap_database())

        create_all.assert_called_once_with(bind=bootstrap.engine)
        seed_db.assert_not_called()

    def test_seed_schedule_failure_exposes_solver_reasons(self) -> None:
        with self.session_factory() as db:
            ambulance = Ambulance(name="Impossible clinic", is_active=True)
            db.add(ambulance)
            db.flush()
            solver_error = ScheduleGenerationError(
                "Not enough qualified people.",
                [{"code": "insufficient_qualified_staff", "available_count": 1}],
            )
            with patch.object(
                seed,
                "generate_ambulance_monthly_schedule",
                side_effect=solver_error,
            ):
                with self.assertRaises(seed.SeedScheduleGenerationError) as context:
                    seed._generate_and_seed_schedules(
                        db,
                        [
                            {
                                "ambulance_name": ambulance.name,
                                "month": 8,
                                "year": 2026,
                            }
                        ],
                        {ambulance.name: ambulance},
                    )

            self.assertEqual(
                context.exception.detail["issues"][0]["code"],
                "insufficient_qualified_staff",
            )


if __name__ == "__main__":
    unittest.main()
