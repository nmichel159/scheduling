"""Tests for the MILP ambulance schedule generator."""

from collections import Counter
from datetime import date, timedelta
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models import (
    Ambulance,
    Competence,
    CompetenceWeekdayRequirement,
    Schedule,
    Unavailability,
    User,
)
from app.models.associations import UserAmbulance, UserCompetence
from app.services.schedule_generation_service import (
    ScheduleGenerationError,
    SchedulingCompetence,
    SchedulingEmployee,
    _is_hard_unavailability,
    generate_ambulance_monthly_schedule,
    solve_monthly_schedule,
)


def _employee(
    user_id: int,
    competence_ids: frozenset[int] = frozenset({1, 2}),
    unavailable_dates: frozenset[date] = frozenset(),
    externally_scheduled_dates: frozenset[date] = frozenset(),
) -> SchedulingEmployee:
    """Build a concise employee fixture for solver tests."""
    return SchedulingEmployee(
        id=user_id,
        email=f"employee{user_id}@example.com",
        full_name=f"Employee {user_id}",
        competence_ids=competence_ids,
        unavailable_dates=unavailable_dates,
        externally_scheduled_dates=externally_scheduled_dates,
    )


class ScheduleGenerationSolverTests(unittest.TestCase):
    """Verify all hard constraints and workload balancing."""

    def test_generates_covered_balanced_schedule_with_hard_constraints(self) -> None:
        """The solver covers roles without absences, overlaps, or adjacent duties."""
        blocked_day = date(2026, 8, 5)
        employees = [
            _employee(1, unavailable_dates=frozenset({date(2026, 8, 1)})),
            _employee(2, externally_scheduled_dates=frozenset({blocked_day})),
            _employee(3),
            _employee(4),
            _employee(5),
            _employee(6),
        ]
        competences = [
            SchedulingCompetence(id=1, name="Triage", required_count=1),
            SchedulingCompetence(id=2, name="Procedure", required_count=1),
        ]
        assignments = solve_monthly_schedule(
            employees,
            competences,
            month=8,
            year=2026,
            adjacent_assignments=frozenset({(1, 1, date(2026, 7, 31))}),
        )

        coverage = Counter(
            (assignment.work_date, assignment.competence_id)
            for assignment in assignments
        )
        daily_employee_load = Counter(
            (assignment.work_date, assignment.user_id) for assignment in assignments
        )
        employee_workload = Counter(assignment.user_id for assignment in assignments)

        self.assertEqual(len(assignments), 62)
        for day_number in range(1, 32):
            work_date = date(2026, 8, day_number)
            self.assertEqual(coverage[(work_date, 1)], 1)
            self.assertEqual(coverage[(work_date, 2)], 1)
        self.assertTrue(all(count <= 1 for count in daily_employee_load.values()))
        self.assertFalse(
            any(item.user_id == 1 and item.work_date == date(2026, 8, 1) for item in assignments)
        )
        self.assertFalse(
            any(
                item.user_id == 2
                and item.work_date in {
                    blocked_day - timedelta(days=1),
                    blocked_day,
                    blocked_day + timedelta(days=1),
                }
                for item in assignments
            )
        )

        assignment_keys = {(item.user_id, item.work_date) for item in assignments}
        self.assertFalse(
            any(
                (user_id, work_date + timedelta(days=1)) in assignment_keys
                for user_id, work_date in assignment_keys
            )
        )
        self.assertLessEqual(max(employee_workload.values()) - min(employee_workload.values()), 1)

    def test_reports_consecutive_day_rotation_shortage(self) -> None:
        """A single qualified employee cannot cover the same role every day."""
        with self.assertRaises(ScheduleGenerationError) as context:
            solve_monthly_schedule(
                [_employee(1, competence_ids=frozenset({1}))],
                [SchedulingCompetence(id=1, name="Triage", required_count=1)],
                month=8,
                year=2026,
            )

        issue_codes = {issue["code"] for issue in context.exception.issues}
        self.assertIn("insufficient_consecutive_day_rotation", issue_codes)

    def test_reports_total_consecutive_day_capacity_shortage(self) -> None:
        """Two daily roles require four distinct people across adjacent days."""
        with self.assertRaises(ScheduleGenerationError) as context:
            solve_monthly_schedule(
                [_employee(user_id) for user_id in range(1, 4)],
                [
                    SchedulingCompetence(id=1, name="Triage", required_count=1),
                    SchedulingCompetence(id=2, name="Procedure", required_count=1),
                ],
                month=8,
                year=2026,
            )

        issue_codes = {issue["code"] for issue in context.exception.issues}
        self.assertIn("insufficient_consecutive_day_capacity", issue_codes)

    def test_balances_available_employee_workloads_evenly(self) -> None:
        """A fully unavailable employee must not make the fairness objective degenerate."""
        all_month = frozenset(date(2026, 8, day) for day in range(1, 32))
        employees = [
            _employee(1, unavailable_dates=all_month),
            _employee(2),
            _employee(3),
            _employee(4),
            _employee(5),
        ]
        assignments = solve_monthly_schedule(
            employees,
            [
                SchedulingCompetence(id=1, name="Triage", required_count=1),
                SchedulingCompetence(id=2, name="Procedure", required_count=1),
            ],
            month=8,
            year=2026,
        )

        employee_workload = Counter(item.user_id for item in assignments)
        self.assertEqual(employee_workload[1], 0)
        self.assertEqual(
            sorted(employee_workload[user_id] for user_id in range(2, 6)),
            [15, 15, 16, 16],
        )

    def test_boundary_duties_block_every_competence_on_month_edges(self) -> None:
        """A fixed adjacent duty blocks the employee regardless of its competence."""
        employees = [_employee(user_id) for user_id in range(1, 6)]
        assignments = solve_monthly_schedule(
            employees,
            [SchedulingCompetence(id=1, name="Triage", required_count=1)],
            month=8,
            year=2026,
            adjacent_assignments=frozenset(
                {
                    (1, 999, date(2026, 7, 31)),
                    (2, 999, date(2026, 9, 1)),
                }
            ),
        )

        self.assertFalse(
            any(item.user_id == 1 and item.work_date == date(2026, 8, 1) for item in assignments)
        )
        self.assertFalse(
            any(item.user_id == 2 and item.work_date == date(2026, 8, 31) for item in assignments)
        )

    def test_external_boundary_duties_block_month_edges(self) -> None:
        """Duties in another ambulance enforce rest across month boundaries."""
        employees = [
            _employee(
                1,
                externally_scheduled_dates=frozenset(
                    {date(2026, 7, 31), date(2026, 9, 1)}
                ),
            ),
            _employee(2),
            _employee(3),
        ]
        assignments = solve_monthly_schedule(
            employees,
            [SchedulingCompetence(id=1, name="Triage", required_count=1)],
            month=8,
            year=2026,
        )

        self.assertFalse(
            any(
                item.user_id == 1
                and item.work_date in {date(2026, 8, 1), date(2026, 8, 31)}
                for item in assignments
            )
        )

    def test_uses_each_ambulance_competence_required_count_every_day(self) -> None:
        """Coverage follows the supplied ambulance's own competence requirements."""
        employees = [_employee(user_id) for user_id in range(1, 9)]
        competences = [
            SchedulingCompetence(id=1, name="Triage", required_count=1),
            SchedulingCompetence(id=2, name="Procedure", required_count=2),
        ]
        assignments = solve_monthly_schedule(employees, competences, month=8, year=2026)
        coverage = Counter(
            (assignment.work_date, assignment.competence_id)
            for assignment in assignments
        )

        self.assertEqual(len(assignments), 93)
        for day_number in range(1, 32):
            work_date = date(2026, 8, day_number)
            self.assertEqual(coverage[(work_date, 1)], 1)
            self.assertEqual(coverage[(work_date, 2)], 2)

    def test_uses_different_headcounts_for_grouped_weekdays(self) -> None:
        """Monday and Sunday can require different counts while other days are closed."""
        employees = [_employee(user_id, frozenset({1})) for user_id in range(1, 7)]
        competence = SchedulingCompetence(
            id=1,
            name="Triage",
            required_count=1,
            weekday_required_counts=(1, 0, 0, 0, 0, 0, 2),
        )

        assignments = solve_monthly_schedule(
            employees,
            [competence],
            month=8,
            year=2026,
        )
        coverage = Counter(item.work_date for item in assignments)

        self.assertEqual(len(assignments), 15)
        for day_number in range(1, 32):
            work_date = date(2026, 8, day_number)
            expected = 1 if work_date.weekday() == 0 else 2 if work_date.weekday() == 6 else 0
            self.assertEqual(coverage[work_date], expected)

    def test_all_zero_week_allows_empty_employee_pool(self) -> None:
        """A fully closed competence produces an empty draft without requiring staff."""
        assignments = solve_monthly_schedule(
            [],
            [
                SchedulingCompetence(
                    id=1,
                    name="Closed role",
                    required_count=0,
                    weekday_required_counts=(0, 0, 0, 0, 0, 0, 0),
                )
            ],
            month=8,
            year=2026,
        )
        self.assertEqual(assignments, [])

    def test_only_true_unavailability_is_a_hard_block(self) -> None:
        """Preferred days stay neutral until preference optimization is implemented."""
        self.assertTrue(_is_hard_unavailability(None))
        self.assertTrue(_is_hard_unavailability("UNAVAILABLE"))
        self.assertTrue(_is_hard_unavailability("Vacation"))
        self.assertFalse(_is_hard_unavailability("PREFERRED"))


class ScheduleGenerationLoadingTests(unittest.TestCase):
    """Verify database inputs used to build the monthly solver model."""

    def setUp(self) -> None:
        """Create a disposable relational database for service-level tests."""
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        self.db = self.session_factory()

    def tearDown(self) -> None:
        """Close and dispose the temporary database."""
        self.db.close()
        self.engine.dispose()

    def test_loads_own_competences_unavailability_and_cross_ambulance_rest(self) -> None:
        """The service uses target demand and all fixed duties around the month."""
        target = Ambulance(name="Target", is_active=True)
        external = Ambulance(name="External", is_active=True)
        users = [
            User(email=f"employee{user_id}@example.com", is_active=True)
            for user_id in range(1, 5)
        ]
        self.db.add_all([target, external, *users])
        self.db.flush()

        target_competence = Competence(
            name="Triage",
            required_count=1,
            ambulance_id=target.id,
            is_active=True,
        )
        external_competence = Competence(
            name="External role",
            required_count=7,
            ambulance_id=external.id,
            is_active=True,
        )
        self.db.add_all([target_competence, external_competence])
        self.db.flush()

        self.db.add_all(
            [
                UserAmbulance(
                    user_id=user.id,
                    ambulance_id=target.id,
                    is_active=True,
                )
                for user in users
            ]
            + [
                UserCompetence(
                    user_id=user.id,
                    competence_id=target_competence.id,
                    is_active=True,
                )
                for user in users
            ]
        )
        self.db.add_all(
            [
                Unavailability(
                    user_id=users[0].id,
                    date_absent=date(2026, 8, 1),
                    reason="PREFERRED",
                    is_active=True,
                ),
                Unavailability(
                    user_id=users[2].id,
                    date_absent=date(2026, 8, 1),
                    reason="UNAVAILABLE",
                    is_active=True,
                ),
                Schedule(
                    user_id=users[1].id,
                    ambulance_id=external.id,
                    competence_id=external_competence.id,
                    work_date=date(2026, 7, 31),
                    is_active=True,
                ),
                Schedule(
                    user_id=users[2].id,
                    ambulance_id=external.id,
                    competence_id=external_competence.id,
                    work_date=date(2026, 8, 10),
                    is_active=True,
                ),
                Schedule(
                    user_id=users[3].id,
                    ambulance_id=target.id,
                    competence_id=target_competence.id,
                    work_date=date(2026, 7, 31),
                    is_active=True,
                ),
            ]
        )
        self.db.commit()

        result = generate_ambulance_monthly_schedule(
            self.db,
            target.id,
            month=8,
            year=2026,
        )

        self.assertEqual(result.assignment_count, 31)
        self.assertTrue(
            all(entry.competence_id == target_competence.id for entry in result.entries)
        )
        first_day_entry = next(
            entry for entry in result.entries if entry.work_date == date(2026, 8, 1)
        )
        self.assertEqual(first_day_entry.user_id, users[0].id)
        self.assertFalse(
            any(
                entry.user_id == users[2].id
                and entry.work_date in {
                    date(2026, 8, 9),
                    date(2026, 8, 10),
                    date(2026, 8, 11),
                }
                for entry in result.entries
            )
        )

    def test_loads_weekday_requirements_with_legacy_fallback(self) -> None:
        """Database rows override only their weekday while absent days use legacy demand."""
        ambulance = Ambulance(name="Weekday clinic", is_active=True)
        users = [User(email=f"weekly{index}@example.com", is_active=True) for index in range(4)]
        self.db.add_all([ambulance, *users])
        self.db.flush()
        competence = Competence(
            name="Procedure",
            required_count=0,
            ambulance_id=ambulance.id,
            is_active=True,
        )
        competence.weekday_requirements = [
            CompetenceWeekdayRequirement(weekday=0, required_count=1),
            CompetenceWeekdayRequirement(weekday=6, required_count=2),
        ]
        self.db.add(competence)
        self.db.flush()
        self.db.add_all(
            [
                UserAmbulance(user_id=user.id, ambulance_id=ambulance.id, is_active=True)
                for user in users
            ]
            + [
                UserCompetence(user_id=user.id, competence_id=competence.id, is_active=True)
                for user in users
            ]
        )
        self.db.commit()

        result = generate_ambulance_monthly_schedule(
            self.db,
            ambulance.id,
            month=8,
            year=2026,
        )
        coverage = Counter(entry.work_date for entry in result.entries)

        self.assertEqual(result.assignment_count, 15)
        self.assertEqual(coverage[date(2026, 8, 3)], 1)
        self.assertEqual(coverage[date(2026, 8, 2)], 2)
        self.assertEqual(coverage[date(2026, 8, 4)], 0)


if __name__ == "__main__":
    unittest.main()
