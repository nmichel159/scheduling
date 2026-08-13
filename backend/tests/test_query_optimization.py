"""Regression tests for bounded query counts on ambulance read operations."""

from datetime import date
import unittest
from collections.abc import Callable

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models import (
    Ambulance,
    Competence,
    CompetenceWeekdayRequirement,
    Role,
    Schedule,
    User,
)
from app.models.associations import UserAmbulance, UserCompetence, UserRole
from app.schemas.ambulance_competences import (
    AmbulanceEmployeeCompetenceTableUpdate,
    AmbulanceEmployeeCompetenceUpdate,
)
from app.schemas.schedule import MonthlyScheduleSave, ScheduleCreate, ScheduleEntry
from app.services.ambulance_competence_service import (
    _get_employee_competence_rows,
    get_employee_competence_table,
    update_employee_competence_table,
)
from app.services.ambulance_employee_service import list_employees
from app.services.user_competence_service import (
    list_employees_by_competence,
    list_user_competences,
)
from app.services.user_service import list_users, list_users_by_role
from app.services.schedule_service import (
    get_ambulance_schedule,
    save_ambulance_monthly_schedule,
    save_monthly_schedule,
)
from app.api.schedules import (
    _bounded_schedule_period,
    get_ambulance_schedule_endpoint,
    get_user_schedule_endpoint,
    save_monthly_schedule_endpoint,
)
from app.api.competence import my_ambulance_competences


class AmbulanceReadQueryTests(unittest.TestCase):
    """Ensure result size does not increase the number of SELECT statements."""

    def setUp(self) -> None:
        """Create an isolated ambulance with multiple employees and shifts."""
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = sessionmaker(bind=self.engine)()

        role = Role(
            id=1,
            code="EMPLOYEE",
            name="Employee",
            level=1,
            is_active=True,
        )
        self.session.add(role)

        ambulance = Ambulance(
            name="Cardiology",
            managed_by_user_id=999,
            is_active=True,
        )
        self.session.add(ambulance)
        self.session.flush()
        competence = Competence(
            name="Physician",
            ambulance_id=ambulance.id,
            required_count=1,
            is_active=True,
        )
        self.session.add(competence)
        self.session.flush()
        self.competence_id = competence.id
        external_ambulance = Ambulance(
            name="Neurology",
            managed_by_user_id=999,
            is_active=True,
        )
        self.session.add(external_ambulance)
        self.session.flush()
        external_competence = Competence(
            name="Neurologist",
            ambulance_id=external_ambulance.id,
            required_count=1,
            is_active=True,
        )
        self.session.add(external_competence)
        self.session.flush()
        self.external_competence_id = external_competence.id
        self.session.add_all(
            [
                CompetenceWeekdayRequirement(
                    competence_id=competence_id,
                    weekday=weekday,
                    required_count=1,
                )
                for competence_id in (
                    self.competence_id,
                    self.external_competence_id,
                )
                for weekday in range(7)
            ]
        )
        self.employee_ids: list[int] = []

        for index in range(5):
            user = User(
                email=f"employee{index}@example.com",
                full_name=f"Employee {index}",
                is_active=True,
            )
            self.session.add(user)
            self.session.flush()
            self.employee_ids.append(user.id)
            self.session.add(
                UserAmbulance(
                    user_id=user.id,
                    ambulance_id=ambulance.id,
                    is_active=True,
                )
            )
            self.session.add(UserRole(user_id=user.id, role_id=role.id))
            self.session.add(
                UserCompetence(
                    user_id=user.id,
                    competence_id=competence.id,
                    is_active=True,
                )
            )
            self.session.add(
                UserCompetence(
                    user_id=user.id,
                    competence_id=external_competence.id,
                    is_active=True,
                )
            )
            self.session.add(
                Schedule(
                    user_id=user.id,
                    ambulance_id=ambulance.id,
                    competence_id=competence.id,
                    work_date=date(2026, 8, index + 1),
                    is_active=True,
                )
            )
        self.session.commit()
        self.ambulance_id = ambulance.id
        self.session.expunge_all()

    def tearDown(self) -> None:
        """Close the isolated database resources."""
        self.session.close()
        self.engine.dispose()

    def _assert_query_count(
        self, expected_count: int, operation: Callable[[], object]
    ) -> object:
        """Run an operation and assert its exact number of SQL statements."""
        statements: list[str] = []

        def record_statement(
            _connection: object,
            _cursor: object,
            statement: str,
            _parameters: object,
            _context: object,
            _executemany: bool,
        ) -> None:
            statements.append(statement)

        event.listen(self.engine, "before_cursor_execute", record_statement)
        try:
            result = operation()
        finally:
            event.remove(self.engine, "before_cursor_execute", record_statement)
        self.assertEqual(len(statements), expected_count, statements)
        return result

    def test_employee_list_uses_one_query(self) -> None:
        """Employee details are joined instead of loaded once per assignment."""
        result = self._assert_query_count(
            1,
            lambda: list_employees(self.session, self.ambulance_id)
        )
        self.assertEqual(len(result), 5)

    def test_user_and_employee_lists_support_id_cursor_pages(self) -> None:
        """Large listings can page without a deep database offset."""
        first_users = list_users(self.session, limit=2)
        remaining_users = list_users(
            self.session,
            after_id=first_users[-1].id,
            limit=10,
        )
        self.assertEqual(
            [user.id for user in [*first_users, *remaining_users]],
            self.employee_ids,
        )

        first_employees = list_employees(
            self.session,
            self.ambulance_id,
            limit=2,
        )
        remaining_employees = list_employees(
            self.session,
            self.ambulance_id,
            after_id=first_employees[-1].user_id,
            limit=10,
        )
        self.assertEqual(
            [employee.user_id for employee in [*first_employees, *remaining_employees]],
            self.employee_ids,
        )

        first_by_role = list_users_by_role(self.session, role_id=1, limit=2)
        remaining_by_role = list_users_by_role(
            self.session,
            role_id=1,
            after_id=first_by_role[-1].id,
            limit=10,
        )
        self.assertEqual(
            [user.id for user in [*first_by_role, *remaining_by_role]],
            self.employee_ids,
        )

    def test_unfiltered_schedule_api_defaults_to_current_month(self) -> None:
        """History reads cannot accidentally return every schedule row."""
        self.assertEqual(
            _bounded_schedule_period(None, None, date(2026, 8, 13)),
            (8, 2026),
        )
        self.assertEqual(
            _bounded_schedule_period(7, 2026, date(2026, 8, 13)),
            (7, 2026),
        )

    def test_employee_competence_table_uses_one_query(self) -> None:
        """All employee competence rows are loaded by one outer-joined query."""
        result = self._assert_query_count(
            1,
            lambda: get_employee_competence_table(self.session, self.ambulance_id)
        )
        self.assertEqual(len(result), 5)
        self.assertTrue(all(len(row.competences) == 1 for row in result))

    def test_employee_competence_table_supports_employee_cursor_pages(self) -> None:
        """Matrix pages are limited by employees rather than joined rows."""
        first_page = self._assert_query_count(
            1,
            lambda: get_employee_competence_table(
                self.session,
                self.ambulance_id,
                limit=2,
            ),
        )
        second_page = self._assert_query_count(
            1,
            lambda: get_employee_competence_table(
                self.session,
                self.ambulance_id,
                after_id=first_page[-1].user_id,
                limit=2,
            ),
        )
        self.assertEqual(len(first_page), 2)
        self.assertEqual(len(second_page), 2)
        self.assertTrue(all(len(row.competences) == 1 for row in first_page))

    def test_competence_table_does_not_load_cross_ambulance_rows(self) -> None:
        """External competence assignments do not amplify joined result rows."""
        rows = self._assert_query_count(
            1,
            lambda: _get_employee_competence_rows(
                self.session,
                self.ambulance_id,
            ),
        )
        self.assertEqual(len(rows), 5)

    def test_users_by_role_uses_bounded_eager_loading(self) -> None:
        """Roles and ambulances are select-in loaded independently of user count."""
        result = self._assert_query_count(
            6,
            lambda: list_users_by_role(self.session, role_id=1),
        )
        self.assertEqual(len(result), 5)
        self.assertTrue(all(len(user.roles) == 1 for user in result))

    def test_user_competences_use_bounded_eager_loading(self) -> None:
        """Competence names are loaded by the scoped assignment query itself."""
        result = self._assert_query_count(
            2,
            lambda: list_user_competences(
                self.session,
                self.ambulance_id,
                self.employee_ids[0],
            ),
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].competence_id, self.competence_id)

    def test_competence_employee_list_uses_bounded_cursor_pages(self) -> None:
        """A large qualification group pages by user ID in two queries."""
        first_page = self._assert_query_count(
            2,
            lambda: list_employees_by_competence(
                self.session,
                self.ambulance_id,
                self.competence_id,
                limit=2,
            ),
        )
        second_page = self._assert_query_count(
            2,
            lambda: list_employees_by_competence(
                self.session,
                self.ambulance_id,
                self.competence_id,
                after_id=first_page[-1].id,
                limit=10,
            ),
        )
        self.assertEqual(
            [user.id for user in [*first_page, *second_page]],
            self.employee_ids,
        )

    def test_managed_ambulance_competences_use_three_queries(self) -> None:
        """All managed ambulances and weekly definitions load in three queries."""
        manager = User(
            id=999,
            email="manager@example.com",
            full_name="Manager",
            is_active=True,
        )
        result = self._assert_query_count(
            3,
            lambda: my_ambulance_competences(
                current_user=manager,
                db=self.session,
            ),
        )
        self.assertEqual(len(result), 2)

    def test_ambulance_schedule_uses_one_query(self) -> None:
        """Schedule serialization eagerly loads users and competences."""
        result = self._assert_query_count(
            1,
            lambda: get_ambulance_schedule(
                self.session, self.ambulance_id, month=8, year=2026
            )
        )
        self.assertEqual(len(result), 5)
        self.assertTrue(all(item.user_full_name for item in result))
        self.assertTrue(all(item.competence_name == "Physician" for item in result))

    def test_ambulance_schedule_endpoint_uses_two_bounded_queries(self) -> None:
        """The endpoint loads all employees and all entries in two queries total."""
        ambulance = Ambulance(id=self.ambulance_id, name="Cardiology", is_active=True)
        result = self._assert_query_count(
            2,
            lambda: get_ambulance_schedule_endpoint(
                ambulance=ambulance,
                month=8,
                year=2026,
                db=self.session,
            ),
        )
        self.assertEqual(len(result), 5)
        self.assertTrue(all(len(item.entries) == 1 for item in result))

    def test_ambulance_schedule_endpoint_pages_employees_and_entries_together(self) -> None:
        """A schedule page fetches duties only for employees on that page."""
        ambulance = Ambulance(id=self.ambulance_id, name="Cardiology", is_active=True)
        first_page = self._assert_query_count(
            2,
            lambda: get_ambulance_schedule_endpoint(
                ambulance=ambulance,
                month=8,
                year=2026,
                after_id=None,
                limit=2,
                db=self.session,
            ),
        )
        second_page = self._assert_query_count(
            2,
            lambda: get_ambulance_schedule_endpoint(
                ambulance=ambulance,
                month=8,
                year=2026,
                after_id=first_page[-1].user_id,
                limit=2,
                db=self.session,
            ),
        )
        self.assertEqual(len(first_page), 2)
        self.assertEqual(len(second_page), 2)
        self.assertTrue(all(len(item.entries) == 1 for item in first_page))

    def test_competence_table_save_uses_bounded_queries(self) -> None:
        """Saving more employee rows does not add one SELECT per employee."""
        payload = AmbulanceEmployeeCompetenceTableUpdate(
            employees=[
                AmbulanceEmployeeCompetenceUpdate(
                    user_id=user_id,
                    competence_ids=[self.competence_id],
                )
                for user_id in self.employee_ids
            ]
        )
        result = self._assert_query_count(
            4,
            lambda: update_employee_competence_table(
                self.session,
                self.ambulance_id,
                payload,
            ),
        )
        self.assertEqual(len(result), 5)

    def test_ambulance_schedule_save_uses_bounded_queries(self) -> None:
        """Ambulance-wide validation is batched before synchronizing entries."""
        entries = [
            ScheduleEntry(
                user_id=user_id,
                competence_id=self.competence_id,
                work_date=date(2026, 8, index + 1),
            )
            for index, user_id in enumerate(self.employee_ids)
        ]
        result = self._assert_query_count(
            8,
            lambda: save_ambulance_monthly_schedule(
                self.session,
                self.ambulance_id,
                8,
                2026,
                entries,
            ),
        )
        self.assertEqual(len(result), 5)

    def test_user_schedule_save_uses_bounded_queries(self) -> None:
        """User-month validation remains constant as submitted entries grow."""
        entries = [
            ScheduleCreate(
                ambulance_id=self.ambulance_id,
                competence_id=self.competence_id,
                work_date=date(2026, 8, 1),
            )
        ]
        result = self._assert_query_count(
            9,
            lambda: save_monthly_schedule(
                self.session,
                self.employee_ids[0],
                8,
                2026,
                entries,
            ),
        )
        self.assertEqual(len(result), 1)

    def test_user_schedule_endpoint_batches_authorization(self) -> None:
        """Monthly endpoint authorization adds one query, not one per entry."""
        payload = MonthlyScheduleSave(
            user_id=self.employee_ids[0],
            month=8,
            year=2026,
            entries=[
                ScheduleCreate(
                    ambulance_id=self.ambulance_id,
                    competence_id=self.competence_id,
                    work_date=date(2026, 8, 1),
                )
            ],
        )
        manager = User(
            id=999,
            email="manager@example.com",
            full_name="Manager",
            is_active=True,
        )
        result = self._assert_query_count(
            11,
            lambda: save_monthly_schedule_endpoint(
                data=payload,
                current_user=manager,
                db=self.session,
            ),
        )
        self.assertEqual(len(result), 1)

    def test_user_schedule_read_does_not_leak_another_managers_clinic(self) -> None:
        """A shared employee's duties are limited to clinics owned by the caller."""
        external_ambulance = (
            self.session.query(Ambulance)
            .filter(Ambulance.id != self.ambulance_id)
            .one()
        )
        external_ambulance.managed_by_user_id = 1000
        employee_id = self.employee_ids[0]
        self.session.add(
            UserAmbulance(
                user_id=employee_id,
                ambulance_id=external_ambulance.id,
                is_active=True,
            )
        )
        self.session.add(
            Schedule(
                user_id=employee_id,
                ambulance_id=external_ambulance.id,
                competence_id=self.external_competence_id,
                work_date=date(2026, 8, 2),
                is_active=True,
            )
        )
        self.session.commit()
        manager = User(
            id=999,
            email="manager@example.com",
            full_name="Manager",
            is_active=True,
        )

        result = self._assert_query_count(
            2,
            lambda: get_user_schedule_endpoint(
                user_id=employee_id,
                month=8,
                year=2026,
                current_user=manager,
                db=self.session,
            ),
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].ambulance_id, self.ambulance_id)


if __name__ == "__main__":
    unittest.main()
