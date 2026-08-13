"""Authorization and CRUD tests for manager-edited employee restrictions."""

import unittest
from datetime import date, timedelta

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.dependencies import get_manager_ambulance, require_manager_role
from app.db.session import Base
from app.models.ambulance import Ambulance
from app.models.associations import UserAmbulance, UserRole
from app.models.role import Role
from app.models.unavailability import Unavailability
from app.models.user import User
from app.schemas.unavailability import UnavailabilityCreate, UnavailabilityUpdate
from app.services.ambulance_employee_service import get_active_employee
from app.services.unavailability_service import (
    create_unavailability,
    delete_unavailability,
    get_unavailabilities,
    update_unavailability,
)


class ManagerUnavailabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = sessionmaker(bind=self.engine)()
        self.session.add_all(
            [
                Role(id=1, code="EMPLOYEE", name="Employee", level=1, is_active=True),
                Role(id=2, code="LEADER", name="Leader", level=2, is_active=True),
            ]
        )
        self.session.commit()

        self.manager = self._user("manager@example.com", 2)
        self.other_manager = self._user("other-manager@example.com", 2)
        self.employee = self._user("employee@example.com", 1)
        self.outsider = self._user("outsider@example.com", 1)

        self.ambulance = Ambulance(
            name="Managed workplace",
            managed_by_user_id=self.manager.id,
            is_active=True,
        )
        self.session.add(self.ambulance)
        self.session.flush()
        self.session.add(
            UserAmbulance(
                user_id=self.employee.id,
                ambulance_id=self.ambulance.id,
                is_active=True,
            )
        )
        self.session.commit()
        self.session.refresh(self.ambulance)

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def _user(self, email: str, role_id: int) -> User:
        user = User(email=email, full_name=email.split("@")[0], is_active=True)
        self.session.add(user)
        self.session.flush()
        self.session.add(UserRole(user_id=user.id, role_id=role_id))
        self.session.commit()
        self.session.refresh(user)
        return user

    def test_role_one_cannot_pass_manager_guard(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            require_manager_role(self.employee)
        self.assertEqual(raised.exception.status_code, 403)

    def test_manager_cannot_access_another_managers_workplace(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            get_manager_ambulance(self.ambulance.id, self.other_manager, self.session)
        self.assertEqual(raised.exception.status_code, 403)

    def test_only_active_workplace_employee_can_be_selected(self) -> None:
        selected = get_active_employee(self.session, self.ambulance.id, self.employee.id)
        self.assertEqual(selected.id, self.employee.id)

        with self.assertRaises(HTTPException) as raised:
            get_active_employee(self.session, self.ambulance.id, self.outsider.id)
        self.assertEqual(raised.exception.status_code, 404)

    def test_manager_flow_edits_only_selected_employees_records(self) -> None:
        managed = get_manager_ambulance(self.ambulance.id, self.manager, self.session)
        selected = get_active_employee(self.session, managed.id, self.employee.id)
        target_date = date.today()

        record = create_unavailability(
            self.session,
            selected.id,
            UnavailabilityCreate(date_absent=target_date, reason="UNAVAILABLE"),
        )
        self.assertEqual(record.user_id, self.employee.id)
        self.assertEqual(
            [item.id for item in get_unavailabilities(self.session, selected.id)],
            [record.id],
        )

        updated = update_unavailability(
            self.session,
            record.id,
            selected.id,
            UnavailabilityUpdate(reason="PREFERRED"),
        )
        self.assertEqual(updated.reason, "PREFERRED")

        with self.assertRaises(HTTPException) as raised:
            update_unavailability(
                self.session,
                record.id,
                self.outsider.id,
                UnavailabilityUpdate(reason="UNAVAILABLE"),
            )
        self.assertEqual(raised.exception.status_code, 404)

        delete_unavailability(self.session, record.id, selected.id)
        self.assertEqual(get_unavailabilities(self.session, selected.id), [])

    def test_unavailability_keyset_cursor_has_no_gaps(self) -> None:
        """A date-and-ID cursor neither repeats nor skips ordered rows."""
        target_date = date.today()
        records = [
            Unavailability(
                user_id=self.employee.id,
                date_absent=target_date,
                reason="UNAVAILABLE",
                is_active=True,
            ),
            Unavailability(
                user_id=self.employee.id,
                date_absent=target_date + timedelta(days=1),
                reason="PREFERRED",
                is_active=True,
            ),
            Unavailability(
                user_id=self.employee.id,
                date_absent=target_date + timedelta(days=2),
                reason="UNAVAILABLE",
                is_active=True,
            ),
        ]
        self.session.add_all(records)
        self.session.commit()

        first_page = get_unavailabilities(
            self.session,
            self.employee.id,
            limit=2,
        )
        second_page = get_unavailabilities(
            self.session,
            self.employee.id,
            limit=2,
            after_date=first_page[-1].date_absent,
            after_id=first_page[-1].id,
        )
        self.assertEqual(
            [item.id for item in [*first_page, *second_page]],
            [item.id for item in records],
        )

    def test_unavailability_cursor_requires_complete_non_offset_cursor(self) -> None:
        """Invalid cursor combinations fail instead of returning ambiguous pages."""
        with self.assertRaises(HTTPException) as partial_cursor:
            get_unavailabilities(
                self.session,
                self.employee.id,
                after_date=date.today(),
            )
        self.assertEqual(partial_cursor.exception.status_code, 422)

        with self.assertRaises(HTTPException) as mixed_pagination:
            get_unavailabilities(
                self.session,
                self.employee.id,
                skip=1,
                after_date=date.today(),
                after_id=1,
            )
        self.assertEqual(mixed_pagination.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()
