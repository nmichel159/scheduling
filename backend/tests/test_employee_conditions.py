"""An employee's duty limits in three layers, and their weekday wishes."""

from datetime import date
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models import Ambulance, Competence, User
from app.models.associations import UserAmbulance, UserCompetence
from app.models.competence_scenario import CompetenceScenario
from app.models.competence_weekday_requirement import CompetenceWeekdayRequirement
from app.models.unavailability import Unavailability
from app.schemas.ambulance_employee import EmployeeConditions
from app.schemas.unavailability import MonthlyDutyWish
from app.services.schedule_generation_service import generate_ambulance_monthly_schedule
from app.services.shift_wish_service import (
    effective_weekday_preferences,
    encode_weekdays,
    shift_limits,
)
from app.services.unavailability_service import (
    get_employee_conditions,
    get_monthly_duty_wish,
    set_employee_conditions,
    set_monthly_duty_wish,
)

YEAR, MONTH = 2026, 11
ANY7 = ["any"] * 7


def weekdays(**answers: str) -> list[str]:
    names = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    return [answers.get(name, "any") for name in names]


class EmployeeConditionsTests(unittest.TestCase):
    """Four interchangeable employees, one duty a day, no rest between."""

    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()

        self.ambulance = Ambulance(name="Ward", isurgent=False, is_active=True)
        self.db.add(self.ambulance)
        self.db.flush()
        self.users = [
            User(email=f"u{index}@example.com", full_name=f"U{index}", is_active=True)
            for index in range(4)
        ]
        self.db.add_all(self.users)
        self.db.flush()
        competence = Competence(
            name="Physician",
            ambulance_id=self.ambulance.id,
            required_count=1,
            is_active=True,
        )
        self.db.add(competence)
        self.db.flush()
        scenario = CompetenceScenario(
            ambulance_id=self.ambulance.id, name="Default", is_selected=True, is_active=True
        )
        self.db.add(scenario)
        self.db.flush()
        for slot in range(8):
            self.db.add(
                CompetenceWeekdayRequirement(
                    competence_id=competence.id,
                    scenario_id=scenario.id,
                    weekday=slot,
                    required_count=1,
                    recovery_days=0,
                    shift_hours=8.0,
                    is_surcharge=False,
                )
            )
        for user in self.users:
            self.db.add(
                UserAmbulance(user_id=user.id, ambulance_id=self.ambulance.id, is_active=True)
            )
            self.db.add(
                UserCompetence(user_id=user.id, competence_id=competence.id, is_active=True)
            )
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def _duties(self) -> dict[int, list[date]]:
        response = generate_ambulance_monthly_schedule(
            self.db, self.ambulance.id, MONTH, YEAR, time_budget_seconds=5
        )
        duties: dict[int, list[date]] = {user.id: [] for user in self.users}
        for entry in response.entries:
            duties[entry.user_id].append(entry.work_date)
        return duties

    def test_the_scheduler_cap_outranks_every_wish(self) -> None:
        capped, month_wisher, standing, free = self.users
        capped.max_shifts_per_month = 10
        capped.scheduler_max_shifts_per_month = 4
        month_wisher.max_shifts_per_month = 2
        standing.max_shifts_per_month = 6
        self.db.commit()
        set_monthly_duty_wish(
            self.db, month_wisher.id, MonthlyDutyWish(max_shifts_per_month=9), (YEAR, MONTH)
        )

        limits = shift_limits(self.db, self.users, YEAR, MONTH)
        self.assertEqual((limits[capped.id].cap, limits[capped.id].wish), (4, 4))
        self.assertEqual(limits[month_wisher.id].wish, 9)
        self.assertEqual(limits[standing.id].wish, 6)
        self.assertIsNone(limits[free.id].wish)
        # Another month falls back to the standing wish.
        other = shift_limits(self.db, [month_wisher], YEAR, MONTH + 1)
        self.assertEqual(other[month_wisher.id].wish, 2)

        self.assertLessEqual(len(self._duties()[capped.id]), 4)

    def test_month_wish_round_trips_beside_the_standing_one(self) -> None:
        user = self.users[0]
        user.max_shifts_per_month = 5
        user.scheduler_max_shifts_per_month = 3
        self.db.commit()
        wish = get_monthly_duty_wish(self.db, user.id, (YEAR, MONTH))
        self.assertIsNone(wish.max_shifts_per_month)
        self.assertEqual(wish.standing_max_shifts_per_month, 5)
        self.assertEqual(wish.scheduler_max_shifts_per_month, 3)
        set_monthly_duty_wish(
            self.db, user.id, MonthlyDutyWish(max_shifts_per_month=7), (YEAR, MONTH)
        )
        self.assertEqual(
            get_monthly_duty_wish(self.db, user.id, (YEAR, MONTH)).max_shifts_per_month, 7
        )
        set_monthly_duty_wish(
            self.db, user.id, MonthlyDutyWish(max_shifts_per_month=None), (YEAR, MONTH)
        )
        self.assertIsNone(
            get_monthly_duty_wish(self.db, user.id, (YEAR, MONTH)).max_shifts_per_month
        )
        self.assertEqual(self.db.get(User, user.id).max_shifts_per_month, 5)

    def test_the_employee_cannot_write_the_scheduler_fields(self) -> None:
        user = self.users[0]
        user.scheduler_max_shifts_per_month = 3
        self.db.commit()
        saved = set_employee_conditions(
            self.db,
            user.id,
            EmployeeConditions(
                max_shifts_per_month=8,
                weekday_preferences=weekdays(mon="avoid", fri="want"),
                scheduler_max_shifts_per_month=20,
                scheduler_weekday_preferences=weekdays(mon="want"),
            ),
        )
        self.assertEqual(saved.max_shifts_per_month, 8)
        self.assertEqual(saved.scheduler_max_shifts_per_month, 3)
        self.assertEqual(saved.scheduler_weekday_preferences, ANY7)
        self.assertEqual(
            get_employee_conditions(self.db, user.id).weekday_preferences,
            weekdays(mon="avoid", fri="want"),
        )

    def test_the_scheduler_weekday_answer_replaces_the_employee_one(self) -> None:
        user = self.users[0]
        user.weekday_preferences = encode_weekdays(weekdays(mon="want", tue="avoid"))
        user.scheduler_weekday_preferences = encode_weekdays(weekdays(mon="avoid"))
        self.assertEqual(
            effective_weekday_preferences(user), weekdays(mon="avoid", tue="avoid")
        )

    def test_avoided_weekdays_are_left_free(self) -> None:
        mondays_off, tuesdays_off, _third, _fourth = self.users
        mondays_off.weekday_preferences = encode_weekdays(weekdays(mon="want"))
        mondays_off.scheduler_weekday_preferences = encode_weekdays(weekdays(mon="avoid"))
        tuesdays_off.weekday_preferences = encode_weekdays(weekdays(tue="avoid"))
        self.db.commit()

        duties = self._duties()
        self.assertFalse([d for d in duties[mondays_off.id] if d.weekday() == 0])
        self.assertFalse([d for d in duties[tuesdays_off.id] if d.weekday() == 1])

    def test_a_marked_day_outranks_the_weekday(self) -> None:
        user = self.users[0]
        user.weekday_preferences = encode_weekdays(weekdays(mon="avoid"))
        # 2 November 2026 is a Monday the employee asked for in particular.
        self.db.add(
            Unavailability(
                user_id=user.id,
                date_absent=date(2026, 11, 2),
                reason="PREFERRED",
                is_active=True,
            )
        )
        self.db.commit()
        self.assertIn(date(2026, 11, 2), self._duties()[user.id])


if __name__ == "__main__":
    unittest.main()
