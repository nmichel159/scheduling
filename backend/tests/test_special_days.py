"""Tests for the special-day calendar: the library and one workplace's edits.

The library is ``holidays``, so these tests assert the two things that make
it the right source rather than re-listing Slovakia's calendar: it knows the
moving feasts, and it knows the 2024 split between the days of rest and the
state holidays that are commemorated but worked.
"""

from collections import Counter
from datetime import date
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.dependencies import get_current_user
from app.db.session import Base, get_db
from app.main import app
from app.models import (
    Ambulance,
    Competence,
    CompetenceScenario,
    CompetenceWeekdayRequirement,
    Role,
    SpecialDay,
    User,
)
from app.models.associations import UserAmbulance, UserCompetence, UserRole
from app.models.competence_weekday_requirement import SPECIAL_DAY_SLOT
from app.services.schedule_generation_service import (
    generate_ambulance_monthly_schedule,
)
from app.services.special_day_service import (
    clear_special_day,
    copy_special_days,
    library_rest_days,
    library_state_workdays,
    rest_days_between,
    set_special_day,
    year_entries,
)


class HolidayLibraryTests(unittest.TestCase):
    """What the library knows, and what it deliberately does not call rest."""

    def test_it_computes_the_moving_feasts(self) -> None:
        """Easter moves every year, which is why this is not a hard-coded list."""
        self.assertIn(date(2026, 4, 3), library_rest_days(2026))  # Good Friday
        self.assertIn(date(2026, 4, 6), library_rest_days(2026))  # Easter Monday
        self.assertIn(date(2027, 3, 26), library_rest_days(2027))
        self.assertIn(date(2027, 3, 29), library_rest_days(2027))

    def test_it_keeps_the_fixed_days_of_rest(self) -> None:
        for day in (
            date(2026, 1, 1),
            date(2026, 1, 6),
            date(2026, 5, 1),
            date(2026, 7, 5),
            date(2026, 8, 29),
            date(2026, 11, 1),
            date(2026, 12, 24),
            date(2026, 12, 25),
            date(2026, 12, 26),
        ):
            with self.subTest(day=day):
                self.assertIn(day, library_rest_days(2026))

    def test_state_holidays_that_are_worked_are_not_days_of_rest(self) -> None:
        """The 2024 amendment, which a hand-written list would have missed."""
        worked = library_state_workdays(2026)
        rest = library_rest_days(2026)
        for day in (
            date(2026, 5, 8),
            date(2026, 9, 1),
            date(2026, 9, 15),
            date(2026, 10, 28),
            date(2026, 11, 17),
        ):
            with self.subTest(day=day):
                self.assertIn(day, worked)
                self.assertNotIn(day, rest)

        # Before the amendment they were days of rest, and the library says so.
        self.assertIn(date(2023, 9, 1), library_rest_days(2023))


class SpecialDayOverrideTests(unittest.TestCase):
    """A workplace may add a day of rest, or take one away."""

    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        ambulance = Ambulance(name="Clinic", is_active=True)
        self.db.add(ambulance)
        self.db.commit()
        self.ambulance_id = ambulance.id

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def _rest_days(self, year: int = 2026) -> set[date]:
        return rest_days_between(
            self.db, self.ambulance_id, date(year, 1, 1), date(year, 12, 31)
        )

    def test_an_added_day_joins_the_library_and_a_removed_one_leaves(self) -> None:
        set_special_day(self.db, self.ambulance_id, date(2026, 9, 15), True)
        set_special_day(self.db, self.ambulance_id, date(2026, 12, 24), False)

        rest = self._rest_days()
        self.assertIn(date(2026, 9, 15), rest)
        self.assertNotIn(date(2026, 12, 24), rest)
        # Untouched days are still the library's answer.
        self.assertIn(date(2026, 12, 25), rest)

    def test_agreeing_with_the_library_stores_nothing(self) -> None:
        """An inherited day must not be shown as a local decision."""
        set_special_day(self.db, self.ambulance_id, date(2026, 1, 1), True)
        self.assertEqual(self.db.query(SpecialDay).count(), 0)

        # And undoing an override removes the row rather than inverting it.
        set_special_day(self.db, self.ambulance_id, date(2026, 1, 1), False)
        self.assertEqual(self.db.query(SpecialDay).count(), 1)
        set_special_day(self.db, self.ambulance_id, date(2026, 1, 1), True)
        self.assertEqual(self.db.query(SpecialDay).count(), 0)
        self.assertIn(date(2026, 1, 1), self._rest_days())

    def test_clearing_hands_the_date_back_to_the_library(self) -> None:
        set_special_day(self.db, self.ambulance_id, date(2026, 12, 25), False)
        self.assertNotIn(date(2026, 12, 25), self._rest_days())

        clear_special_day(self.db, self.ambulance_id, date(2026, 12, 25))
        self.assertIn(date(2026, 12, 25), self._rest_days())
        self.assertEqual(self.db.query(SpecialDay).count(), 0)

    def test_the_year_listing_says_where_each_verdict_came_from(self) -> None:
        set_special_day(
            self.db, self.ambulance_id, date(2026, 6, 2), True, name="Clinic day"
        )
        set_special_day(self.db, self.ambulance_id, date(2026, 12, 24), False)
        by_day = {entry["day"]: entry for entry in year_entries(self.db, self.ambulance_id, 2026)}

        inherited = by_day[date(2026, 12, 25)]
        self.assertEqual(
            (inherited["in_library"], inherited["is_rest_day"], inherited["is_overridden"]),
            (True, True, False),
        )

        added = by_day[date(2026, 6, 2)]
        self.assertEqual(
            (added["in_library"], added["is_rest_day"], added["is_overridden"]),
            (False, True, True),
        )
        self.assertEqual(added["name"], "Clinic day")

        taken_away = by_day[date(2026, 12, 24)]
        self.assertEqual(
            (
                taken_away["in_library"],
                taken_away["library_rest_day"],
                taken_away["is_rest_day"],
                taken_away["is_overridden"],
            ),
            (True, True, False, True),
        )

        # A state holiday that is worked is listed too, so it can be added.
        worked = by_day[date(2026, 9, 1)]
        self.assertEqual(
            (worked["in_library"], worked["library_rest_day"], worked["is_rest_day"]),
            (True, False, False),
        )

    def test_copying_replaces_the_target_year(self) -> None:
        other = Ambulance(name="Second clinic", is_active=True)
        self.db.add(other)
        self.db.commit()
        set_special_day(self.db, self.ambulance_id, date(2026, 9, 15), True)
        set_special_day(self.db, other.id, date(2026, 12, 25), False)

        copied = copy_special_days(self.db, self.ambulance_id, other.id, 2026)

        self.assertEqual(copied, 1)
        rest = rest_days_between(self.db, other.id, date(2026, 1, 1), date(2026, 12, 31))
        self.assertIn(date(2026, 9, 15), rest)
        self.assertIn(date(2026, 12, 25), rest, "the target's own override is replaced")


class SpecialDaySolverTests(unittest.TestCase):
    """A day of rest is staffed from its own slot, not from its weekday."""

    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        ambulance = Ambulance(name="Holiday clinic", is_active=True)
        users = [User(email=f"duty{index}@example.com", is_active=True) for index in range(4)]
        self.db.add_all([ambulance, *users])
        self.db.flush()
        scenario = CompetenceScenario(
            name="Scenario 1",
            ambulance_id=ambulance.id,
            is_selected=True,
            is_active=True,
        )
        self.db.add(scenario)
        self.db.flush()
        competence = Competence(
            name="Holiday duty",
            required_count=0,
            ambulance_id=ambulance.id,
            is_active=True,
        )
        # Nobody on any weekday, one person on a day of rest: whatever the
        # solver produces is therefore exactly the special days.
        competence.weekday_requirements = [
            CompetenceWeekdayRequirement(
                weekday=weekday, required_count=0, scenario_id=scenario.id
            )
            for weekday in range(7)
        ] + [
            CompetenceWeekdayRequirement(
                weekday=SPECIAL_DAY_SLOT, required_count=1, scenario_id=scenario.id
            )
        ]
        self.db.add(competence)
        self.db.flush()
        self.db.add_all(
            [
                UserAmbulance(user_id=user.id, ambulance_id=ambulance.id, is_active=True)
                for user in users
            ]
            + [
                UserCompetence(
                    user_id=user.id, competence_id=competence.id, is_active=True
                )
                for user in users
            ]
        )
        self.db.commit()
        self.ambulance_id = ambulance.id

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def _staffed_days(self, month: int) -> set[date]:
        result = generate_ambulance_monthly_schedule(
            self.db, self.ambulance_id, month=month, year=2026
        )
        coverage = Counter(entry.work_date for entry in result.entries)
        return {day for day, count in coverage.items() if count > 0}

    def test_only_the_library_days_of_rest_are_staffed(self) -> None:
        # December 2026: 24, 25 and 26 December, and nothing else.
        self.assertEqual(
            self._staffed_days(12),
            {date(2026, 12, 24), date(2026, 12, 25), date(2026, 12, 26)},
        )

    def test_the_workplace_can_add_and_remove_a_day(self) -> None:
        set_special_day(self.db, self.ambulance_id, date(2026, 12, 25), False)
        set_special_day(self.db, self.ambulance_id, date(2026, 12, 7), True)

        self.assertEqual(
            self._staffed_days(12),
            {date(2026, 12, 7), date(2026, 12, 24), date(2026, 12, 26)},
        )


class SpecialDayRouterTests(unittest.TestCase):
    """Drive the endpoints the special-day screen calls, over HTTP.

    The screen has two audiences with different rights, so the tests sign in
    as both: only the role checks are real here, and who the caller is comes
    from the one override the endpoints all resolve through.
    """

    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()

        leader = Role(id=1, code="LEADER", name="Scheduler", level=2, is_active=True)
        overseer = Role(
            id=2, code="AMBULANCE_OVERSEER", name="Admin", level=3, is_active=True
        )
        self.scheduler = User(id=1, email="scheduler@example.com", is_active=True)
        self.admin = User(id=2, email="admin@example.com", is_active=True)
        self.db.add_all([leader, overseer, self.scheduler, self.admin])
        self.db.flush()
        self.db.add_all(
            [
                UserRole(user_id=self.scheduler.id, role_id=leader.id),
                # The administrator schedules nowhere and still reaches every
                # workplace, which is the point of the level.
                UserRole(user_id=self.admin.id, role_id=overseer.id),
            ]
        )
        ambulance = Ambulance(
            name="Clinic", managed_by_user_id=self.scheduler.id, is_active=True
        )
        self.foreign = Ambulance(name="Other clinic", managed_by_user_id=99, is_active=True)
        self.db.add_all([ambulance, self.foreign])
        self.db.commit()
        self.base = f"/ambulances/{ambulance.id}/special-days"

        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)
        self._as(self.admin)

    def _as(self, user: User) -> None:
        """Sign the test client in as one of the two callers."""
        app.dependency_overrides[get_current_user] = lambda: user

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.db.close()
        self.engine.dispose()

    def _entry(self, payload, day: str) -> dict:
        return next(item for item in payload["entries"] if item["day"] == day)

    def test_the_screen_round_trips(self) -> None:
        listed = self.client.get(self.base, params={"year": 2026})
        self.assertEqual(listed.status_code, 200)
        self.assertTrue(self._entry(listed.json(), "2026-01-01")["is_rest_day"])
        self.assertFalse(self._entry(listed.json(), "2026-09-01")["is_rest_day"])

        added = self.client.put(
            self.base,
            json={"day": "2026-09-01", "is_rest_day": True, "name": "Constitution Day"},
        )
        self.assertEqual(added.status_code, 200)
        entry = self._entry(added.json(), "2026-09-01")
        self.assertTrue(entry["is_rest_day"])
        self.assertTrue(entry["is_overridden"])

        removed = self.client.put(
            self.base, json={"day": "2026-12-24", "is_rest_day": False}
        )
        self.assertFalse(self._entry(removed.json(), "2026-12-24")["is_rest_day"])

        reset = self.client.delete(f"{self.base}/2026-12-24")
        self.assertEqual(reset.status_code, 200)
        entry = self._entry(reset.json(), "2026-12-24")
        self.assertTrue(entry["is_rest_day"])
        self.assertFalse(entry["is_overridden"])

    def test_a_day_the_workplace_invented_appears_in_its_year(self) -> None:
        self.client.put(
            self.base,
            json={"day": "2026-06-02", "is_rest_day": True, "name": "Clinic day"},
        )
        listed = self.client.get(self.base, params={"year": 2026}).json()
        entry = self._entry(listed, "2026-06-02")
        self.assertEqual(entry["name"], "Clinic day")
        self.assertFalse(entry["in_library"])
        self.assertTrue(entry["is_rest_day"])

    def test_an_impossible_year_is_refused(self) -> None:
        self.assertEqual(
            self.client.get(self.base, params={"year": 1900}).status_code, 422
        )

    def test_a_workplace_the_scheduler_does_not_manage_is_refused(self) -> None:
        self._as(self.scheduler)
        response = self.client.get(
            f"/ambulances/{self.foreign.id}/special-days", params={"year": 2026}
        )
        self.assertEqual(response.status_code, 403)

    def test_the_administrator_reaches_a_workplace_they_do_not_manage(self) -> None:
        response = self.client.get(
            f"/ambulances/{self.foreign.id}/special-days", params={"year": 2026}
        )
        self.assertEqual(response.status_code, 200)

    def test_the_scheduler_reads_the_year_but_cannot_change_it(self) -> None:
        """The screen is open to the scheduler and read-only in their hands."""
        self._as(self.scheduler)

        listed = self.client.get(self.base, params={"year": 2026})
        self.assertEqual(listed.status_code, 200)

        added = self.client.put(
            self.base, json={"day": "2026-09-01", "is_rest_day": True}
        )
        self.assertEqual(added.status_code, 403)

        reset = self.client.delete(f"{self.base}/2026-12-24")
        self.assertEqual(reset.status_code, 403)

        copied = self.client.post(
            f"{self.base}/copy",
            json={"source_ambulance_id": self.foreign.id, "year": 2026},
        )
        self.assertEqual(copied.status_code, 403)

        self.assertEqual(self.db.query(SpecialDay).count(), 0)


if __name__ == "__main__":
    unittest.main()
