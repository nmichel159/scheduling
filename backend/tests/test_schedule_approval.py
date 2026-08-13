"""Schedule package approval and employee visibility regression tests."""

from datetime import date
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.schedules import get_my_schedule
from app.db.session import Base
from app.models import Ambulance, Competence, Schedule, User
from app.models.associations import UserAmbulance, UserCompetence
from app.schemas.schedule import ScheduleEntry
from app.services.schedule_service import (
    approve_ambulance_monthly_schedule,
    get_next_user_schedule,
    get_user_monthly_statistics,
    get_user_schedule,
    get_user_worked_statistics,
    save_ambulance_monthly_schedule,
)


class ScheduleApprovalTests(unittest.TestCase):
    """Keep manager drafts hidden until the whole monthly package is approved."""

    def setUp(self) -> None:
        """Create one qualified employee and one unapproved draft duty."""
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()

        self.user = User(
            email="employee@example.com",
            full_name="Employee",
            is_active=True,
        )
        self.ambulance = Ambulance(
            name="Cardiology",
            isurgent=False,
            is_active=True,
        )
        self.db.add_all([self.user, self.ambulance])
        self.db.flush()
        self.competence = Competence(
            name="Physician",
            ambulance_id=self.ambulance.id,
            required_count=1,
            is_active=True,
        )
        self.db.add(self.competence)
        self.db.flush()
        self.db.add_all(
            [
                UserAmbulance(
                    user_id=self.user.id,
                    ambulance_id=self.ambulance.id,
                    is_active=True,
                ),
                UserCompetence(
                    user_id=self.user.id,
                    competence_id=self.competence.id,
                    is_active=True,
                ),
                Schedule(
                    user_id=self.user.id,
                    ambulance_id=self.ambulance.id,
                    competence_id=self.competence.id,
                    work_date=date(2026, 8, 15),
                    is_active=True,
                    is_approved=False,
                ),
            ]
        )
        self.db.commit()

    def tearDown(self) -> None:
        """Close isolated database resources."""
        self.db.close()
        self.engine.dispose()

    def test_employee_reads_only_approved_entries(self) -> None:
        """Every role-1 read path excludes an unapproved package."""
        self.assertEqual(
            get_my_schedule(
                month=8,
                year=2026,
                current_user=self.user,
                db=self.db,
            ),
            [],
        )
        self.assertEqual(
            get_user_schedule(
                self.db,
                self.user.id,
                8,
                2026,
                approved_only=True,
            ),
            [],
        )
        self.assertIsNone(
            get_next_user_schedule(self.db, self.user.id, date(2026, 8, 1))
        )
        self.assertEqual(
            get_user_monthly_statistics(
                self.db,
                self.user.id,
                date(2026, 8, 13),
            )["scheduled_shift_count"],
            0,
        )
        self.assertEqual(
            get_user_worked_statistics(
                self.db,
                self.user.id,
                date(2026, 8, 31),
            )["worked_day_count"],
            0,
        )

    def test_approval_publishes_and_later_save_revokes_entire_package(self) -> None:
        """The manager button publishes once; any subsequent save hides it again."""
        approval = approve_ambulance_monthly_schedule(
            self.db,
            self.ambulance.id,
            8,
            2026,
        )
        self.assertTrue(approval.is_approved)
        self.assertEqual(approval.approved_entry_count, 1)
        visible = get_user_schedule(
            self.db,
            self.user.id,
            8,
            2026,
            approved_only=True,
        )
        self.assertEqual(len(visible), 1)
        self.assertTrue(visible[0].is_approved)

        save_ambulance_monthly_schedule(
            self.db,
            self.ambulance.id,
            8,
            2026,
            [
                ScheduleEntry(
                    user_id=self.user.id,
                    competence_id=self.competence.id,
                    work_date=date(2026, 8, 15),
                )
            ],
        )
        self.assertEqual(
            get_user_schedule(
                self.db,
                self.user.id,
                8,
                2026,
                approved_only=True,
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()
