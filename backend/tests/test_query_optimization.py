"""Regression tests for bounded query counts on ambulance read operations."""

from datetime import date
import unittest
from collections.abc import Callable

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models import Ambulance, Competence, Schedule, User
from app.models.associations import UserAmbulance, UserCompetence
from app.services.ambulance_competence_service import get_employee_competence_table
from app.services.ambulance_employee_service import list_employees
from app.services.schedule_service import get_ambulance_schedule
from app.api.schedules import get_ambulance_schedule_endpoint


class AmbulanceReadQueryTests(unittest.TestCase):
    """Ensure result size does not increase the number of SELECT statements."""

    def setUp(self) -> None:
        """Create an isolated ambulance with multiple employees and shifts."""
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = sessionmaker(bind=self.engine)()

        ambulance = Ambulance(name="Cardiology", is_active=True)
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

        for index in range(5):
            user = User(
                email=f"employee{index}@example.com",
                full_name=f"Employee {index}",
                is_active=True,
            )
            self.session.add(user)
            self.session.flush()
            self.session.add(
                UserAmbulance(
                    user_id=user.id,
                    ambulance_id=ambulance.id,
                    is_active=True,
                )
            )
            self.session.add(
                UserCompetence(
                    user_id=user.id,
                    competence_id=competence.id,
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

    def test_employee_competence_table_uses_one_query(self) -> None:
        """All employee competence rows are loaded by one outer-joined query."""
        result = self._assert_query_count(
            1,
            lambda: get_employee_competence_table(self.session, self.ambulance_id)
        )
        self.assertEqual(len(result), 5)
        self.assertTrue(all(len(row.competences) == 1 for row in result))

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


if __name__ == "__main__":
    unittest.main()
