"""The planner may place anybody anywhere; conflicts are reported, not refused."""

from datetime import date
import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models import Ambulance, Competence, Schedule, Unavailability, User
from app.models.associations import UserAmbulance, UserCompetence
from app.schemas.schedule import ScheduleCreate, ScheduleEntry
from app.services.schedule_context_service import get_schedule_context
from app.services.schedule_service import (
    create_schedule,
    save_ambulance_monthly_schedule,
)


class PlannerConflictTests(unittest.TestCase):
    """One workplace, one employee with every kind of commitment around August."""

    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()

        self.employee = User(
            email="employee@example.com",
            full_name="Employee",
            is_active=True,
            max_shifts_per_month=3,
        )
        self.outsider = User(email="outsider@example.com", full_name="Outsider", is_active=True)
        self.ambulance = Ambulance(name="Cardiology", isurgent=False, is_active=True)
        self.other = Ambulance(name="Surgery", isurgent=False, is_active=True)
        self.db.add_all([self.employee, self.outsider, self.ambulance, self.other])
        self.db.flush()
        self.physician = Competence(
            name="Physician", ambulance_id=self.ambulance.id, required_count=1, is_active=True
        )
        self.nurse = Competence(
            name="Nurse", ambulance_id=self.ambulance.id, required_count=1, is_active=True
        )
        self.surgeon = Competence(
            name="Surgeon", ambulance_id=self.other.id, required_count=1, is_active=True
        )
        self.db.add_all([self.physician, self.nurse, self.surgeon])
        self.db.flush()
        self.db.add_all(
            [
                UserAmbulance(user_id=self.employee.id, ambulance_id=self.ambulance.id, is_active=True),
                UserAmbulance(user_id=self.employee.id, ambulance_id=self.other.id, is_active=True),
                # Qualified for the physician's duty only, never the nurse's.
                UserCompetence(user_id=self.employee.id, competence_id=self.physician.id, is_active=True),
                UserCompetence(user_id=self.employee.id, competence_id=self.surgeon.id, is_active=True),
                Schedule(
                    user_id=self.employee.id,
                    ambulance_id=self.other.id,
                    competence_id=self.surgeon.id,
                    work_date=date(2026, 8, 10),
                    is_active=True,
                ),
                Schedule(
                    user_id=self.employee.id,
                    ambulance_id=self.ambulance.id,
                    competence_id=self.physician.id,
                    work_date=date(2026, 7, 31),
                    is_active=True,
                ),
                Unavailability(
                    user_id=self.employee.id,
                    date_absent=date(2026, 8, 12),
                    reason="VACATION",
                    is_active=True,
                ),
                Unavailability(
                    user_id=self.employee.id,
                    date_absent=date(2026, 8, 13),
                    reason="SOFT_DECLINE",
                    is_active=True,
                ),
                Unavailability(
                    user_id=self.employee.id,
                    date_absent=date(2026, 8, 14),
                    reason="PREFERRED",
                    is_active=True,
                ),
            ]
        )
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def _entry(self, competence: Competence, day: int, user: User | None = None) -> ScheduleEntry:
        return ScheduleEntry(
            user_id=(user or self.employee).id,
            competence_id=competence.id,
            work_date=date(2026, 8, day),
        )

    def test_planner_save_keeps_placements_that_break_the_rules(self) -> None:
        """Unqualified, doubled, absent and busy elsewhere are all stored as placed."""
        saved = save_ambulance_monthly_schedule(
            self.db,
            self.ambulance.id,
            8,
            2026,
            [
                self._entry(self.nurse, 5),
                self._entry(self.physician, 6),
                self._entry(self.nurse, 6),
                self._entry(self.physician, 12),
                self._entry(self.physician, 10),
            ],
        )

        self.assertEqual(
            sorted((item.work_date.day, item.competence_id) for item in saved),
            sorted(
                [
                    (5, self.nurse.id),
                    (6, self.physician.id),
                    (6, self.nurse.id),
                    (10, self.physician.id),
                    (12, self.physician.id),
                ]
            ),
        )

    def test_planner_save_still_refuses_somebody_from_outside_the_workplace(self) -> None:
        with self.assertRaises(HTTPException) as refused:
            save_ambulance_monthly_schedule(
                self.db,
                self.ambulance.id,
                8,
                2026,
                [self._entry(self.physician, 5, self.outsider)],
            )
        self.assertEqual(refused.exception.status_code, 400)

    def test_planner_save_refuses_a_competence_of_another_workplace(self) -> None:
        with self.assertRaises(HTTPException) as refused:
            save_ambulance_monthly_schedule(
                self.db,
                self.ambulance.id,
                8,
                2026,
                [self._entry(self.surgeon, 5)],
            )
        self.assertEqual(refused.exception.status_code, 400)

    def test_single_entry_writes_stay_strict(self) -> None:
        """Only the planner's save lets a rule be broken on purpose."""
        with self.assertRaises(HTTPException) as refused:
            create_schedule(
                self.db,
                self.employee.id,
                ScheduleCreate(
                    ambulance_id=self.ambulance.id,
                    competence_id=self.nurse.id,
                    work_date=date(2026, 8, 5),
                ),
            )
        self.assertEqual(refused.exception.status_code, 400)

    def test_context_reports_marks_surrounding_duties_and_the_wish(self) -> None:
        # A duty inside the month at this workplace is the planner's own.
        self.db.add(
            Schedule(
                user_id=self.employee.id,
                ambulance_id=self.ambulance.id,
                competence_id=self.physician.id,
                work_date=date(2026, 8, 20),
                is_active=True,
            )
        )
        self.db.commit()

        context = get_schedule_context(self.db, self.ambulance.id, 8, 2026)

        self.assertEqual([item.user_id for item in context.employees], [self.employee.id])
        employee = context.employees[0]
        self.assertEqual(employee.max_shifts_per_month, 3)
        self.assertEqual(
            [(mark.work_date.day, mark.reason) for mark in employee.marks],
            [(12, "VACATION"), (13, "SOFT_DECLINE")],
        )
        self.assertEqual(
            [
                (duty.work_date, duty.ambulance_id, duty.ambulance_name, duty.recovery_days)
                for duty in employee.duties
            ],
            [
                (date(2026, 7, 31), self.ambulance.id, "Cardiology", 1),
                (date(2026, 8, 10), self.other.id, "Surgery", 1),
            ],
        )


if __name__ == "__main__":
    unittest.main()
