"""Tests for competence staffing requirements by ISO weekday."""

import unittest

from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models import Ambulance, Competence
from app.schemas.competence import CompetenceCreate, CompetenceResponse, CompetenceUpdate
from app.services.competence_service import create_competence, update_competence


def _week(counts: list[int]) -> list[dict[str, int]]:
    return [
        {"weekday": weekday, "required_count": count}
        for weekday, count in enumerate(counts)
    ]


class CompetenceWeekdayRequirementTests(unittest.TestCase):
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

    def test_create_and_replace_complete_week(self) -> None:
        competence = create_competence(
            self.db,
            self.ambulance_id,
            CompetenceCreate(
                name="Anaesthesia",
                weekday_requirements=_week([5, 5, 3, 3, 5, 2, 10]),
            ),
        )
        self.assertEqual(
            [item.required_count for item in competence.weekday_requirements],
            [5, 5, 3, 3, 5, 2, 10],
        )
        response = CompetenceResponse.model_validate(competence)
        self.assertEqual(
            [item.required_count for item in response.weekday_requirements],
            [5, 5, 3, 3, 5, 2, 10],
        )

        updated = update_competence(
            self.db,
            competence.id,
            self.ambulance_id,
            CompetenceUpdate(weekday_requirements=_week([1, 1, 1, 1, 1, 0, 0])),
        )
        self.assertEqual(
            [item.required_count for item in updated.weekday_requirements],
            [1, 1, 1, 1, 1, 0, 0],
        )

    def test_rejects_incomplete_or_duplicate_weekdays(self) -> None:
        with self.assertRaises(ValidationError):
            CompetenceUpdate(weekday_requirements=_week([1, 2, 3]))

        duplicate = _week([1, 1, 1, 1, 1, 1, 1])
        duplicate[-1]["weekday"] = 5
        with self.assertRaises(ValidationError):
            CompetenceUpdate(weekday_requirements=duplicate)

    def test_legacy_count_update_applies_to_existing_week(self) -> None:
        competence = create_competence(
            self.db,
            self.ambulance_id,
            CompetenceCreate(name="Sampling", weekday_requirements=_week([1] * 7)),
        )
        updated = update_competence(
            self.db,
            competence.id,
            self.ambulance_id,
            CompetenceUpdate(required_count=4),
        )
        self.assertEqual(
            [item.required_count for item in updated.weekday_requirements],
            [4] * 7,
        )

    def test_response_keeps_pre_migration_empty_week_readable(self) -> None:
        """Missing child rows use required_count instead of causing HTTP 500."""
        competence = Competence(
            name="Legacy",
            ambulance_id=self.ambulance_id,
            required_count=3,
            is_active=True,
        )
        self.db.add(competence)
        self.db.commit()
        self.db.refresh(competence)

        response = CompetenceResponse.model_validate(competence)

        self.assertIsNone(response.weekday_requirements)
        self.assertEqual(response.required_count, 3)

    def test_response_still_rejects_incomplete_nonempty_week(self) -> None:
        """Compatibility must not hide partially corrupt weekly definitions."""
        payload = {
            "id": 1,
            "ambulance_id": self.ambulance_id,
            "name": "Partial",
            "required_count": 2,
            "count": 2,
            "weekday_requirements": _week([2, 2, 2]),
        }
        with self.assertRaises(ValidationError):
            CompetenceResponse.model_validate(payload)


if __name__ == "__main__":
    unittest.main()
