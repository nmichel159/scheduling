"""Tests for custom days: a workplace's own kinds of day on chosen dates."""

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
    User,
)
from app.models.associations import UserAmbulance, UserCompetence, UserRole
from app.models.competence_weekday_requirement import SPECIAL_DAY_SLOT
from app.schemas.custom_day import CustomDayCreate, CustomDayRequirementData
from app.services.custom_day_service import (
    create_custom_day,
    delete_custom_day,
    month_needs,
    set_custom_date,
)
from app.services.schedule_generation_service import (
    SchedulingCompetence,
    generate_ambulance_monthly_schedule,
)


def _build(db) -> tuple[int, int]:
    """A workplace whose one competence needs nobody on any day."""
    ambulance = Ambulance(name="Clinic", managed_by_user_id=1, is_active=True)
    users = [User(email=f"duty{index}@example.com", is_active=True) for index in range(4)]
    db.add_all([ambulance, *users])
    db.flush()
    scenario = CompetenceScenario(
        name="Scenario 1", ambulance_id=ambulance.id, is_selected=True, is_active=True
    )
    db.add(scenario)
    db.flush()
    competence = Competence(
        name="Duty", required_count=0, ambulance_id=ambulance.id, is_active=True
    )
    competence.weekday_requirements = [
        CompetenceWeekdayRequirement(
            weekday=slot, required_count=0, scenario_id=scenario.id
        )
        for slot in range(SPECIAL_DAY_SLOT + 1)
    ]
    db.add(competence)
    db.flush()
    db.add_all(
        [
            UserAmbulance(user_id=user.id, ambulance_id=ambulance.id, is_active=True)
            for user in users
        ]
        + [
            UserCompetence(user_id=user.id, competence_id=competence.id, is_active=True)
            for user in users
        ]
    )
    db.commit()
    return ambulance.id, competence.id


class CompetenceCustomDayTests(unittest.TestCase):
    def test_a_custom_date_outranks_the_weekday(self) -> None:
        competence = SchedulingCompetence(
            id=1,
            name="Duty",
            required_count=1,
            weekday_required_counts=(1,) * 7,
            custom_days=((date(2026, 11, 4), 3, True, 2, 6.0),),
        )
        self.assertEqual(competence.required_on(date(2026, 11, 4)), 3)
        self.assertTrue(competence.is_surcharge_on(date(2026, 11, 4)))
        self.assertEqual(competence.recovery_days_on(date(2026, 11, 4)), 2)
        self.assertEqual(competence.shift_hours_on(date(2026, 11, 4)), 6.0)
        self.assertEqual(competence.required_on(date(2026, 11, 5)), 1)
        self.assertFalse(competence.is_surcharge_on(date(2026, 11, 5)))


class CustomDaySolverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.ambulance_id, self.competence_id = _build(self.db)

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def _custom_day(self, count: int) -> int:
        return create_custom_day(
            self.db,
            self.ambulance_id,
            CustomDayCreate(
                name="Inspection",
                requirements=[
                    CustomDayRequirementData(
                        competence_id=self.competence_id, required_count=count
                    )
                ],
            ),
        ).id

    def _coverage(self) -> Counter:
        result = generate_ambulance_monthly_schedule(
            self.db, self.ambulance_id, month=11, year=2026
        )
        return Counter(entry.work_date for entry in result.entries)

    def test_only_the_custom_dates_are_staffed(self) -> None:
        custom_day_id = self._custom_day(2)
        set_custom_date(self.db, self.ambulance_id, date(2026, 11, 10), custom_day_id)
        # A day of rest placed on a custom day is staffed as the custom day.
        set_custom_date(self.db, self.ambulance_id, date(2026, 11, 17), custom_day_id)

        self.assertEqual(
            self._coverage(), Counter({date(2026, 11, 10): 2, date(2026, 11, 17): 2})
        )

        needs = month_needs(self.db, self.ambulance_id, 2026, 11)
        by_day = {item.day: item for item in needs.days}
        self.assertEqual(by_day[date(2026, 11, 10)].kind, "custom")
        self.assertEqual(by_day[date(2026, 11, 10)].needs[0].required_count, 2)
        self.assertEqual(by_day[date(2026, 11, 1)].kind, "rest")
        self.assertEqual(by_day[date(2026, 11, 2)].kind, "weekday")

    def test_clearing_or_deleting_returns_the_date_to_the_calendar(self) -> None:
        custom_day_id = self._custom_day(1)
        set_custom_date(self.db, self.ambulance_id, date(2026, 11, 10), custom_day_id)
        set_custom_date(self.db, self.ambulance_id, date(2026, 11, 11), custom_day_id)
        set_custom_date(self.db, self.ambulance_id, date(2026, 11, 10), None)
        self.assertEqual(self._coverage(), Counter({date(2026, 11, 11): 1}))

        delete_custom_day(self.db, self.ambulance_id, custom_day_id)
        self.assertEqual(self._coverage(), Counter())


class CustomDayRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        leader = Role(id=1, code="LEADER", name="Scheduler", level=2, is_active=True)
        self.scheduler = User(id=1, email="scheduler@example.com", is_active=True)
        self.db.add_all([leader, self.scheduler])
        self.db.flush()
        self.db.add(UserRole(user_id=self.scheduler.id, role_id=leader.id))
        self.db.commit()
        self.ambulance_id, self.competence_id = _build(self.db)
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_current_user] = lambda: self.scheduler
        self.client = TestClient(app)
        self.base = f"/ambulances/{self.ambulance_id}"

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.db.close()
        self.engine.dispose()

    def test_the_screen_round_trips(self) -> None:
        created = self.client.post(f"{self.base}/custom-days", json={"name": "Reduced"})
        self.assertEqual(created.status_code, 201)
        body = created.json()
        self.assertEqual(body["requirements"][0]["required_count"], 0)

        updated = self.client.put(
            f"{self.base}/custom-days/{body['id']}",
            json={
                "requirements": [
                    {
                        "competence_id": self.competence_id,
                        "required_count": 2,
                        "shift_hours": 6,
                        "recovery_days": 1,
                        "is_surcharge": True,
                    }
                ]
            },
        )
        self.assertEqual(updated.status_code, 200)

        placed = self.client.put(
            f"{self.base}/custom-day-dates",
            json={"day": "2026-11-12", "custom_day_id": body["id"]},
        )
        self.assertEqual(placed.status_code, 204)

        needs = self.client.get(
            f"{self.base}/competence-needs", params={"year": 2026, "month": 11}
        ).json()
        day = next(item for item in needs["days"] if item["day"] == "2026-11-12")
        self.assertEqual(day["kind"], "custom")
        self.assertEqual(day["custom_day_id"], body["id"])
        self.assertEqual(day["needs"][0]["required_count"], 2)
        self.assertTrue(day["needs"][0]["is_surcharge"])

        listed = self.client.get(f"{self.base}/custom-days").json()
        self.assertEqual(listed[0]["date_count"], 1)

    def test_a_competence_of_another_workplace_is_refused(self) -> None:
        created = self.client.post(
            f"{self.base}/custom-days",
            json={"name": "X", "requirements": [{"competence_id": 999}]},
        )
        self.assertEqual(created.status_code, 422)


if __name__ == "__main__":
    unittest.main()
