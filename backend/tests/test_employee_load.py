"""Employee load per month: how many duties, and how many of them paid extra."""

from datetime import date
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models import Ambulance, Competence, Schedule, User
from app.models.associations import UserAmbulance
from app.models.competence_scenario import CompetenceScenario
from app.models.competence_weekday_requirement import CompetenceWeekdayRequirement
from app.models.special_day import SpecialDay
from app.schemas.ambulance_employee import EmployeeSchedulingSettings
from app.services.employee_load_service import (
    get_monthly_employee_load,
    set_scheduling_settings,
)


class EmployeeLoadTests(unittest.TestCase):
    """One workplace, two employees, a weekend and a special day."""

    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()

        self.ambulance = Ambulance(name="Anaesthesia", isurgent=False, is_active=True)
        self.db.add(self.ambulance)
        self.db.flush()

        self.busy = User(email="busy@example.com", full_name="Busy", is_active=True)
        self.idle = User(email="idle@example.com", full_name="Idle", is_active=True)
        self.db.add_all([self.busy, self.idle])
        self.db.flush()
        self.db.add_all(
            [
                UserAmbulance(
                    user_id=user.id, ambulance_id=self.ambulance.id, is_active=True
                )
                for user in (self.busy, self.idle)
            ]
        )

        self.competence = Competence(
            name="Physician",
            ambulance_id=self.ambulance.id,
            required_count=1,
            is_active=True,
        )
        self.db.add(self.competence)
        self.db.flush()

        scenario = CompetenceScenario(
            ambulance_id=self.ambulance.id,
            name="Default",
            is_selected=True,
            is_active=True,
        )
        self.db.add(scenario)
        self.db.flush()
        # Weekdays are plain four-hour duties; the weekend and the day of
        # rest are surcharged, which is what the screen counts separately.
        for slot in range(8):
            self.db.add(
                CompetenceWeekdayRequirement(
                    competence_id=self.competence.id,
                    scenario_id=scenario.id,
                    weekday=slot,
                    required_count=1,
                    recovery_days=1,
                    shift_hours=4.0,
                    is_surcharge=slot in (5, 6, 7),
                )
            )

        # 2026-09-01 is a Tuesday, 2026-09-05 a Saturday. The workplace
        # also declares 2026-09-02 a day of rest of its own.
        self.db.add(
            SpecialDay(
                ambulance_id=self.ambulance.id,
                day=date(2026, 9, 2),
                is_rest_day=True,
                name="Closed",
            )
        )
        for day in (date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 5)):
            self.db.add(
                Schedule(
                    user_id=self.busy.id,
                    ambulance_id=self.ambulance.id,
                    competence_id=self.competence.id,
                    work_date=day,
                    is_active=True,
                )
            )
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_counts_duties_and_surcharged_ones(self) -> None:
        """The weekend and the workplace's own day of rest are surcharged."""
        report = get_monthly_employee_load(self.db, self.ambulance.id, 9, 2026)
        rows = {row.user_id: row for row in report.employees}

        busy = rows[self.busy.id]
        self.assertEqual(busy.shift_count, 3)
        self.assertEqual(busy.surcharge_shift_count, 2)
        self.assertEqual(busy.total_hours, 12.0)
        self.assertEqual(len(busy.days), 3)
        self.assertEqual(
            [day.is_surcharge for day in busy.days], [False, True, True]
        )

    def test_employee_without_duties_is_still_reported(self) -> None:
        """"Nothing yet" is exactly what the scheduler is looking for."""
        report = get_monthly_employee_load(self.db, self.ambulance.id, 9, 2026)
        rows = {row.user_id: row for row in report.employees}

        idle = rows[self.idle.id]
        self.assertEqual(idle.shift_count, 0)
        self.assertEqual(idle.surcharge_shift_count, 0)
        self.assertEqual(idle.days, [])

    def test_settings_round_trip_into_the_report(self) -> None:
        """What the scheduler saves is what the next report carries."""
        set_scheduling_settings(
            self.db,
            self.busy,
            EmployeeSchedulingSettings(
                max_shifts_per_month=6, shift_preference="surcharge"
            ),
        )
        report = get_monthly_employee_load(self.db, self.ambulance.id, 9, 2026)
        rows = {row.user_id: row for row in report.employees}

        self.assertEqual(rows[self.busy.id].max_shifts_per_month, 6)
        self.assertEqual(rows[self.busy.id].shift_preference, "surcharge")
        # Untouched employees keep the default, which is "no opinion".
        self.assertIsNone(rows[self.idle.id].max_shifts_per_month)
        self.assertEqual(rows[self.idle.id].shift_preference, "any")


if __name__ == "__main__":
    unittest.main()
