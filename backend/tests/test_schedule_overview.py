"""Admin schedule overview: which ambulances have a month planned."""

from datetime import date
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models import Ambulance, Competence, Schedule, User
from app.services.schedule_service import get_monthly_schedule_overview


class ScheduleOverviewTests(unittest.TestCase):
    """Cover the three states the overview has to tell apart."""

    def setUp(self) -> None:
        """Three ambulances: one approved, one draft, one never generated."""
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()

        self.manager = User(
            email="manager@example.com",
            full_name="Manager",
            is_active=True,
        )
        self.employee = User(
            email="employee@example.com",
            full_name="Employee",
            is_active=True,
        )
        self.db.add_all([self.manager, self.employee])
        self.db.flush()

        self.approved, self.draft, self.empty = (
            Ambulance(name=name, isurgent=False, is_active=True)
            for name in ("Anaesthesia", "Cardiology", "Zoology")
        )
        self.approved.managed_by_user_id = self.manager.id
        self.db.add_all([self.approved, self.draft, self.empty])
        self.db.flush()

        self.competences = {}
        for ambulance in (self.approved, self.draft, self.empty):
            competence = Competence(
                name="Physician",
                ambulance_id=ambulance.id,
                required_count=1,
                is_active=True,
            )
            self.db.add(competence)
            self.db.flush()
            self.competences[ambulance.id] = competence

        self.db.add_all(
            [
                self._shift(self.approved, date(2026, 8, 3), is_approved=True),
                self._shift(self.approved, date(2026, 8, 4), is_approved=True),
                self._shift(self.draft, date(2026, 8, 3), is_approved=False),
                # A published shift outside the queried month must not make
                # August look planned.
                self._shift(self.empty, date(2026, 9, 1), is_approved=True),
            ]
        )
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def _shift(
        self,
        ambulance: Ambulance,
        work_date: date,
        *,
        is_approved: bool,
    ) -> Schedule:
        return Schedule(
            user_id=self.employee.id,
            ambulance_id=ambulance.id,
            competence_id=self.competences[ambulance.id].id,
            work_date=work_date,
            is_active=True,
            is_approved=is_approved,
        )

    def _overview(self) -> dict[int, object]:
        result = get_monthly_schedule_overview(self.db, 8, 2026)
        return {item.ambulance_id: item for item in result.ambulances}

    def test_lists_every_active_ambulance_by_name(self) -> None:
        """An ambulance with no shifts is the point of the report, not a gap."""
        result = get_monthly_schedule_overview(self.db, 8, 2026)
        self.assertEqual(
            [item.ambulance_name for item in result.ambulances],
            ["Anaesthesia", "Cardiology", "Zoology"],
        )
        self.assertEqual((result.month, result.year), (8, 2026))

    def test_fully_published_package_reads_as_approved(self) -> None:
        status = self._overview()[self.approved.id]
        self.assertEqual(status.shift_count, 2)
        self.assertEqual(status.approved_shift_count, 2)
        self.assertTrue(status.is_approved)
        self.assertEqual(status.manager_full_name, "Manager")
        self.assertEqual(status.manager_email, "manager@example.com")

    def test_unapproved_package_reads_as_draft(self) -> None:
        status = self._overview()[self.draft.id]
        self.assertEqual(status.shift_count, 1)
        self.assertEqual(status.approved_shift_count, 0)
        self.assertFalse(status.is_approved)
        self.assertIsNone(status.manager_full_name)

    def test_month_without_shifts_is_not_approved(self) -> None:
        """Zero shifts must never be reported as an approved month."""
        status = self._overview()[self.empty.id]
        self.assertEqual(status.shift_count, 0)
        self.assertFalse(status.is_approved)

    def test_partially_approved_package_is_not_approved(self) -> None:
        self.db.add(self._shift(self.approved, date(2026, 8, 5), is_approved=False))
        self.db.commit()
        status = self._overview()[self.approved.id]
        self.assertEqual((status.shift_count, status.approved_shift_count), (3, 2))
        self.assertFalse(status.is_approved)

    def test_inactive_shifts_are_ignored(self) -> None:
        """Deactivated rows are history, not a planned month."""
        for entry in self.db.query(Schedule).filter(
            Schedule.ambulance_id == self.draft.id
        ):
            entry.is_active = False
        self.db.commit()
        status = self._overview()[self.draft.id]
        self.assertEqual(status.shift_count, 0)

    def test_inactive_ambulance_is_dropped(self) -> None:
        self.empty.is_active = False
        self.db.commit()
        self.assertNotIn(self.empty.id, self._overview())


if __name__ == "__main__":
    unittest.main()
