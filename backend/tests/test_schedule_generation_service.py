"""Tests for the MILP ambulance schedule generator."""

from collections import Counter
from datetime import date, timedelta
import unittest

from app.services.schedule_generation_service import (
    ScheduleGenerationError,
    SchedulingCompetence,
    SchedulingEmployee,
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
        """The solver covers roles without absences, overlaps, or role repetition."""
        blocked_day = date(2026, 8, 5)
        employees = [
            _employee(1, unavailable_dates=frozenset({date(2026, 8, 1)})),
            _employee(2, externally_scheduled_dates=frozenset({blocked_day})),
            _employee(3),
            _employee(4),
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
        self.assertNotIn((date(2026, 8, 1), 1), {
            (item.work_date, item.competence_id)
            for item in assignments
            if item.user_id == 1
        })
        self.assertFalse(
            any(item.user_id == 2 and item.work_date == blocked_day for item in assignments)
        )

        assignment_keys = {
            (item.user_id, item.competence_id, item.work_date) for item in assignments
        }
        self.assertFalse(
            any(
                (user_id, competence_id, work_date + timedelta(days=1)) in assignment_keys
                for user_id, competence_id, work_date in assignment_keys
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


if __name__ == "__main__":
    unittest.main()
