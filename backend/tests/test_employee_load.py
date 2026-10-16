"""Employee load per month: how many duties, and how many of them paid extra."""

from datetime import date
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models import Ambulance, Competence, Schedule, User
from app.models.associations import UserAmbulance, UserCompetence
from app.models.competence_scenario import CompetenceScenario
from app.models.competence_weekday_requirement import CompetenceWeekdayRequirement
from app.models.special_day import SpecialDay
from app.models.unavailability import Unavailability
from app.schemas.ambulance_employee import EmployeeSchedulingSettings
from app.services.employee_load_service import (
    get_monthly_employee_load,
    set_scheduling_settings,
)
from app.services.schedule_generation_service import generate_ambulance_monthly_schedule


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

    def test_inactive_employee_is_reported_but_never_planned(self) -> None:
        """Switched off stays on the roster and out of every new plan."""
        # A day of recovery after each duty takes two people to cover a month.
        spare = User(email="spare@example.com", full_name="Spare", is_active=True)
        self.db.add(spare)
        self.db.flush()
        self.db.add(
            UserAmbulance(user_id=spare.id, ambulance_id=self.ambulance.id, is_active=True)
        )
        self.db.add_all(
            [
                UserCompetence(
                    user_id=user.id, competence_id=self.competence.id, is_active=True
                )
                for user in (self.busy, self.idle, spare)
            ]
        )
        self.db.commit()
        set_scheduling_settings(
            self.db,
            self.busy,
            EmployeeSchedulingSettings(scheduling_active=False),
        )

        report = get_monthly_employee_load(self.db, self.ambulance.id, 9, 2026)
        rows = {row.user_id: row for row in report.employees}
        self.assertFalse(rows[self.busy.id].scheduling_active)
        self.assertTrue(rows[self.idle.id].scheduling_active)

        response = generate_ambulance_monthly_schedule(
            self.db, self.ambulance.id, 10, 2026
        )
        self.assertGreater(response.assignment_count, 0)
        self.assertEqual(
            {entry.user_id for entry in response.entries}, {self.idle.id, spare.id}
        )

    def test_settings_left_out_keep_the_active_flag(self) -> None:
        """An older client that knows nothing of the flag does not reset it."""
        set_scheduling_settings(
            self.db, self.busy, EmployeeSchedulingSettings(scheduling_active=False)
        )
        set_scheduling_settings(
            self.db, self.busy, EmployeeSchedulingSettings(max_shifts_per_month=4)
        )
        self.assertFalse(self.busy.scheduling_active)

    def test_vip_flag_is_stored_and_kept_when_left_out(self) -> None:
        """The VIP mark is reported back and survives a save that omits it."""
        set_scheduling_settings(
            self.db, self.busy, EmployeeSchedulingSettings(is_vip=True)
        )
        set_scheduling_settings(
            self.db, self.busy, EmployeeSchedulingSettings(max_shifts_per_month=4)
        )
        report = get_monthly_employee_load(self.db, self.ambulance.id, 9, 2026)
        rows = {row.user_id: row for row in report.employees}
        self.assertTrue(rows[self.busy.id].is_vip)
        self.assertFalse(rows[self.idle.id].is_vip)

    def test_availability_calendar_is_counted_by_what_it_says(self) -> None:
        """Wishes and absences are split; an unknown reason blocks the day."""
        self.db.add_all(
            [
                Unavailability(
                    user_id=self.busy.id,
                    date_absent=date(2026, 9, 10),
                    reason="PREFERRED",
                    is_active=True,
                ),
                Unavailability(
                    user_id=self.busy.id,
                    date_absent=date(2026, 9, 11),
                    reason="SOFT_DECLINE",
                    is_active=True,
                ),
                Unavailability(
                    user_id=self.busy.id,
                    date_absent=date(2026, 9, 12),
                    reason="VACATION",
                    is_active=True,
                ),
                # Written by an older client, which left the reason empty.
                Unavailability(
                    user_id=self.busy.id,
                    date_absent=date(2026, 9, 13),
                    reason=None,
                    is_active=True,
                ),
                # Another month, so this screen must not see it.
                Unavailability(
                    user_id=self.busy.id,
                    date_absent=date(2026, 10, 1),
                    reason="VACATION",
                    is_active=True,
                ),
            ]
        )
        self.db.commit()

        report = get_monthly_employee_load(self.db, self.ambulance.id, 9, 2026)
        rows = {row.user_id: row for row in report.employees}

        busy = rows[self.busy.id]
        self.assertEqual(busy.marked_days, 4)
        self.assertEqual(busy.preferred_days, 1)
        self.assertEqual(busy.declined_days, 1)
        self.assertEqual(busy.blocked_days, 2)
        self.assertEqual(
            [(d.day, d.reason) for d in busy.marked_dates],
            [
                (date(2026, 9, 10), "PREFERRED"),
                (date(2026, 9, 11), "SOFT_DECLINE"),
                (date(2026, 9, 12), "VACATION"),
                (date(2026, 9, 13), None),
            ],
        )

        # An untouched calendar reports zeroes rather than being left out.
        idle = rows[self.idle.id]
        self.assertEqual(idle.marked_days, 0)
        self.assertEqual(idle.blocked_days, 0)
        self.assertEqual(idle.marked_dates, [])


if __name__ == "__main__":
    unittest.main()
