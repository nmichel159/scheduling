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
from app.db.seed_configs.accounts import (
    IKAIM_EMPLOYEE_EMAIL,
    IKAIM_SCHEDULER_EMAIL,
    OVERSEER_EMAIL,
)
from app.db.seed_configs.availability import PREFERRED_REASON
from app.db.seed_configs.extra_clinics import (
    SECOND_KAIM_NAME,
    KDAIM_NAME,
    URGENT_NAME,
)
from app.db.seed_configs.ikaim import (
    AMBULANCE_NAME,
    APPROVED_THROUGH_MONTH,
    COMPETENCE_NAMES,
    MEMBERS,
    MONTHLY_REQUIREMENTS,
    MONTHS,
    STAFF,
    UNAVAILABILITIES,
    YEAR,
)
from app.models import Ambulance, Competence, Schedule, SeedVersion, Unavailability, User
from app.models.associations import UserAmbulance
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
            self.assertEqual(ambulance.manager.email, IKAIM_SCHEDULER_EMAIL)
            self.assertEqual(len(STAFF), 33)

            competences = {
                row.name: row
                for row in db.query(Competence)
                .filter_by(ambulance_id=ambulance.id)
                .all()
            }
            # Generation leaves the last month's staffing levels behind, so
            # what the database holds is that month's profile -- with a zero on
            # every role the month does not staff.
            self.assertEqual(
                {name: row.required_count for name, row in competences.items()},
                {
                    name: MONTHLY_REQUIREMENTS[MONTHS[-1]].get(name, 0)
                    for name in COMPETENCE_NAMES
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

            entries_per_person_month = Counter(
                (
                    entry["user_email"],
                    entry["date_absent"].month,
                    entry["reason"] == PREFERRED_REASON,
                )
                for entry in UNAVAILABILITIES
            )
            absences = [
                count
                for (_, _, is_preferred), count in entries_per_person_month.items()
                if not is_preferred
            ]
            requests = [
                count
                for (_, _, is_preferred), count in entries_per_person_month.items()
                if is_preferred
            ]
            self.assertEqual(len(absences), len(MEMBERS) * len(MONTHS))
            self.assertTrue(all(8 <= count <= 12 for count in absences))
            self.assertTrue(all(2 <= count <= 4 for count in requests))

        with patch.object(seed, "_apply_seed") as apply_seed:
            self.assertFalse(seed.seed_db("config_1", only_if_outdated=True))
            apply_seed.assert_not_called()

        with self.session_factory() as db:
            self.assertEqual(db.query(User).count(), user_count)

    def test_demo_profile_approves_a_full_year_in_every_workplace(self) -> None:
        seed.seed_db("config_1", only_if_outdated=True)

        with self.session_factory() as db:
            ambulances = {
                ambulance.name: ambulance for ambulance in db.query(Ambulance).all()
            }
            self.assertEqual(
                set(ambulances),
                {AMBULANCE_NAME, SECOND_KAIM_NAME, KDAIM_NAME, URGENT_NAME},
            )
            self.assertEqual(
                [name for name, row in ambulances.items() if row.isurgent],
                [URGENT_NAME],
            )

            for name, ambulance in ambulances.items():
                months = {
                    (row.work_date.year, row.work_date.month)
                    for row in db.query(Schedule).filter_by(ambulance_id=ambulance.id)
                }
                self.assertEqual(
                    months,
                    {(YEAR, month) for month in MONTHS},
                    f"{name} is not scheduled for the whole demo year",
                )
            # Months up to the cutoff are signed off; the ones after it are
            # generated drafts still waiting for their manager.
            approval_by_month = defaultdict(set)
            for row in db.query(Schedule).all():
                approval_by_month[row.work_date.month].add(row.is_approved)
            self.assertEqual(
                {month: sorted(flags) for month, flags in approval_by_month.items()},
                {month: [month <= APPROVED_THROUGH_MONTH] for month in MONTHS},
            )

            # The clinic the demo account manages changes how many roles it
            # staffs from month to month, and each month's duties have to match
            # the profile that month was generated from.
            staffed_per_month = defaultdict(Counter)
            for row in db.query(Schedule).filter_by(
                ambulance_id=ambulances[AMBULANCE_NAME].id
            ):
                staffed_per_month[row.work_date.month][
                    (row.work_date, row.competence.name)
                ] += 1
            for month, staffed in staffed_per_month.items():
                required = MONTHLY_REQUIREMENTS[month]
                self.assertEqual(
                    {name for _, name in staffed}, set(required), f"month {month}"
                )
                for (_, name), count in staffed.items():
                    self.assertEqual(count, required[name], f"month {month}, {name}")
            role_counts = {len(MONTHLY_REQUIREMENTS[month]) for month in MONTHS}
            self.assertEqual(min(role_counts), 3)
            self.assertEqual(max(role_counts), 7)

            # The rest day between duties has to hold across workplaces too,
            # which is the whole point of staffing the urgent one from rosters
            # that are already busy.
            duty_dates = defaultdict(set)
            for row in db.query(Schedule).all():
                self.assertNotIn(row.work_date, duty_dates[row.user_id])
                duty_dates[row.user_id].add(row.work_date)
            for work_dates in duty_dates.values():
                for work_date in work_dates:
                    self.assertNotIn(work_date + timedelta(days=1), work_dates)

            blocked = {
                (row.user_id, row.date_absent)
                for row in db.query(Unavailability).filter(
                    Unavailability.reason != PREFERRED_REASON
                )
            }
            self.assertFalse(
                blocked & {
                    (user_id, work_date)
                    for user_id, work_dates in duty_dates.items()
                    for work_date in work_dates
                }
            )

            # The account that builds I.KAIM's schedule, the account that
            # oversees the clinics, and the account that is an employee of
            # I.KAIM and of nothing else are three different people.
            scheduler = db.query(User).filter_by(email=IKAIM_SCHEDULER_EMAIL).one()
            self.assertEqual({row.role.code for row in scheduler.user_roles}, {"LEADER"})
            self.assertEqual(ambulances[AMBULANCE_NAME].managed_by_user_id, scheduler.id)

            overseer = db.query(User).filter_by(email=OVERSEER_EMAIL).one()
            self.assertEqual(
                {row.role.code for row in overseer.user_roles},
                {"EMPLOYEE", "AMBULANCE_OVERSEER"},
            )
            self.assertEqual(
                db.query(UserAmbulance).filter_by(user_id=overseer.id).count(), 3
            )
            self.assertTrue(duty_dates[overseer.id])

            employee = db.query(User).filter_by(email=IKAIM_EMPLOYEE_EMAIL).one()
            self.assertEqual({row.role.code for row in employee.user_roles}, {"EMPLOYEE"})
            self.assertEqual(
                [
                    db.get(Ambulance, row.ambulance_id).name
                    for row in db.query(UserAmbulance).filter_by(user_id=employee.id)
                ],
                [AMBULANCE_NAME],
            )
            self.assertTrue(duty_dates[employee.id])

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
            patch.object(bootstrap, "migrate_database") as migrate_database,
        ):
            self.assertFalse(bootstrap.bootstrap_database())

        migrate_database.assert_called_once_with()
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
