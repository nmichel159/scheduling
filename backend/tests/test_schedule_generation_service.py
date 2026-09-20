"""Tests for the MILP ambulance schedule generator."""

from collections import Counter
from datetime import date, timedelta
import unittest

from pulp import LpVariable
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models import (
    Ambulance,
    Competence,
    CompetenceScenario,
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
    _detect_capacity_issues,
    _index_schedule_variables,
    _is_hard_unavailability,
    generate_ambulance_monthly_schedule,
    solve_monthly_schedule,
)


def _employee(
    user_id: int,
    competence_ids: frozenset[int] = frozenset({1, 2}),
    unavailable_dates: frozenset[date] = frozenset(),
    externally_scheduled_dates: frozenset[date] = frozenset(),
    preferred_dates: frozenset[date] = frozenset(),
    soft_declined_dates: frozenset[date] = frozenset(),
    max_shifts_per_month: int | None = None,
    shift_preference: str = "any",
) -> SchedulingEmployee:
    """Build a concise employee fixture for solver tests."""
    return SchedulingEmployee(
        id=user_id,
        email=f"employee{user_id}@example.com",
        full_name=f"Employee {user_id}",
        competence_ids=competence_ids,
        unavailable_dates=unavailable_dates,
        externally_scheduled_dates=externally_scheduled_dates,
        preferred_dates=preferred_dates,
        soft_declined_dates=soft_declined_dates,
        max_shifts_per_month=max_shifts_per_month,
        shift_preference=shift_preference,
    )


class ScheduleGenerationSolverTests(unittest.TestCase):
    """Verify all hard constraints and workload balancing."""

    def test_indexes_decision_variables_for_constant_time_lookup(self) -> None:
        """Every constraint view is populated by one reusable variable index."""
        first_day = date(2026, 8, 1)
        second_day = date(2026, 8, 2)
        variables = {
            (1, 1, first_day): LpVariable("a_1_1_1", cat="Binary"),
            (1, 2, first_day): LpVariable("a_1_2_1", cat="Binary"),
            (2, 1, second_day): LpVariable("a_2_1_2", cat="Binary"),
        }

        index = _index_schedule_variables(variables)

        self.assertEqual(len(index.by_competence_date[(1, first_day)]), 1)
        self.assertEqual(len(index.by_user_date[(1, first_day)]), 2)
        self.assertEqual(len(index.by_user[1]), 2)
        self.assertEqual(index.candidate_dates_by_user[1], {first_day})
        self.assertEqual(index.candidate_ids_by_date[first_day], {1})
        self.assertEqual(
            index.candidate_ids_by_competence_date[(1, second_day)],
            {2},
        )

        issues = _detect_capacity_issues(
            {},
            [SchedulingCompetence(id=1, name="Triage", required_count=1)],
            [first_day, second_day],
            index,
        )
        self.assertEqual(issues, [])

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

    def test_places_duties_on_requested_days_without_losing_balance(self) -> None:
        """Every duty of a requesting employee lands on a day they asked for."""
        requested = frozenset(date(2026, 8, day) for day in range(1, 16, 2))
        employees = [
            _employee(1, competence_ids=frozenset({1})),
            _employee(2, competence_ids=frozenset({1})),
            _employee(3, competence_ids=frozenset({1})),
            _employee(4, competence_ids=frozenset({1}), preferred_dates=requested),
        ]
        assignments = solve_monthly_schedule(
            employees,
            [SchedulingCompetence(id=1, name="Triage", required_count=1)],
            month=8,
            year=2026,
        )

        workload = Counter(item.user_id for item in assignments)
        # 31 duties over four employees: the balanced split is the only optimum.
        self.assertEqual(sorted(workload.values()), [7, 8, 8, 8])
        self.assertEqual(
            {item.work_date for item in assignments if item.user_id == 4},
            set(requested),
        )

    def test_requests_never_buy_a_less_balanced_roster(self) -> None:
        """One employee asking for the whole month still gets an even share."""
        all_month = frozenset(date(2026, 8, day) for day in range(1, 32))
        employees = [
            _employee(1, competence_ids=frozenset({1})),
            _employee(2, competence_ids=frozenset({1})),
            _employee(3, competence_ids=frozenset({1}), preferred_dates=all_month),
        ]
        assignments = solve_monthly_schedule(
            employees,
            [SchedulingCompetence(id=1, name="Triage", required_count=1)],
            month=8,
            year=2026,
        )

        workload = Counter(item.user_id for item in assignments)
        self.assertEqual(sorted(workload.values()), [10, 10, 11])

    def test_requests_on_blocked_days_are_ignored(self) -> None:
        """A day that is both requested and unavailable stays unavailable."""
        blocked = frozenset({date(2026, 8, 4)})
        employees = [
            _employee(1, competence_ids=frozenset({1})),
            _employee(2, competence_ids=frozenset({1})),
            _employee(
                3,
                competence_ids=frozenset({1}),
                unavailable_dates=blocked,
                preferred_dates=blocked,
            ),
        ]
        assignments = solve_monthly_schedule(
            employees,
            [SchedulingCompetence(id=1, name="Triage", required_count=1)],
            month=8,
            year=2026,
        )

        self.assertFalse(
            any(
                item.user_id == 3 and item.work_date == date(2026, 8, 4)
                for item in assignments
            )
        )

    def test_only_true_unavailability_is_a_hard_block(self) -> None:
        """Wishes are paid for by the objective; everything else blocks."""
        self.assertTrue(_is_hard_unavailability(None))
        self.assertTrue(_is_hard_unavailability("UNAVAILABLE"))
        self.assertTrue(_is_hard_unavailability("VACATION"))
        self.assertTrue(_is_hard_unavailability("BUSINESS_TRIP"))
        self.assertFalse(_is_hard_unavailability("PREFERRED"))
        self.assertFalse(_is_hard_unavailability("SOFT_DECLINE"))

    def test_avoids_reluctant_days_while_the_roster_stays_balanced(self) -> None:
        """A day the employee would rather not work is left to someone else."""
        reluctant = frozenset(date(2026, 8, day) for day in range(1, 16, 2))
        employees = [
            _employee(1, competence_ids=frozenset({1})),
            _employee(2, competence_ids=frozenset({1})),
            _employee(3, competence_ids=frozenset({1})),
            _employee(4, competence_ids=frozenset({1}), soft_declined_dates=reluctant),
        ]
        assignments = solve_monthly_schedule(
            employees,
            [SchedulingCompetence(id=1, name="Triage", required_count=1)],
            month=8,
            year=2026,
        )

        workload = Counter(item.user_id for item in assignments)
        self.assertEqual(sorted(workload.values()), [7, 8, 8, 8])
        self.assertFalse(
            {item.work_date for item in assignments if item.user_id == 4} & reluctant
        )

    def test_reluctant_days_are_taken_when_nobody_else_can(self) -> None:
        """Reluctance is a wish: it never leaves a day unstaffed."""
        reluctant = frozenset({date(2026, 8, 4)})
        employees = [
            _employee(1, competence_ids=frozenset({1}), soft_declined_dates=reluctant),
        ]
        assignments = solve_monthly_schedule(
            employees,
            [
                SchedulingCompetence(
                    id=1,
                    name="Triage",
                    required_count=1,
                    weekday_required_counts=(0, 1, 0, 0, 0, 0, 0),
                )
            ],
            month=8,
            year=2026,
        )

        self.assertIn(
            date(2026, 8, 4),
            {item.work_date for item in assignments if item.user_id == 1},
        )

    def test_monthly_wish_shifts_duties_onto_colleagues(self) -> None:
        """An employee wanting few duties gets them, the rest take the slack."""
        employees = [
            _employee(1, competence_ids=frozenset({1})),
            _employee(2, competence_ids=frozenset({1})),
            _employee(3, competence_ids=frozenset({1}), max_shifts_per_month=2),
        ]
        assignments = solve_monthly_schedule(
            employees,
            [SchedulingCompetence(id=1, name="Triage", required_count=1)],
            month=8,
            year=2026,
        )

        workload = Counter(item.user_id for item in assignments)
        self.assertEqual(workload[3], 2)
        self.assertEqual(sum(workload.values()), 31)

    def test_monthly_wish_is_exceeded_rather_than_leaving_a_day_unstaffed(self) -> None:
        """The wish is a wish: an unstaffable month outranks it."""
        employees = [_employee(1, competence_ids=frozenset({1}), max_shifts_per_month=1)]
        assignments = solve_monthly_schedule(
            employees,
            [
                SchedulingCompetence(
                    id=1,
                    name="Triage",
                    required_count=1,
                    weekday_required_counts=(0, 1, 0, 0, 0, 0, 0),
                )
            ],
            month=8,
            year=2026,
        )

        self.assertEqual(len(assignments), 4)

    def test_keeps_manually_placed_duties_and_plans_around_them(self) -> None:
        """A placed duty survives the solve and claims its own rest days."""
        placed_day = date(2026, 8, 10)
        employees = [_employee(index) for index in range(1, 7)]
        competences = [
            SchedulingCompetence(id=1, name="Triage", required_count=1),
            SchedulingCompetence(id=2, name="Procedure", required_count=1),
        ]

        assignments = solve_monthly_schedule(
            employees,
            competences,
            month=8,
            year=2026,
            fixed_assignments=frozenset({(1, 1, placed_day)}),
        )

        self.assertIn(
            (1, 1, placed_day),
            {
                (item.user_id, item.competence_id, item.work_date)
                for item in assignments
            },
        )
        neighbours = {placed_day - timedelta(days=1), placed_day + timedelta(days=1)}
        self.assertFalse(
            any(
                item.user_id == 1 and item.work_date in neighbours
                for item in assignments
            )
        )
        coverage = Counter(
            (item.work_date, item.competence_id) for item in assignments
        )
        self.assertEqual(coverage[(placed_day, 1)], 1)
        self.assertEqual(coverage[(placed_day, 2)], 1)

    def test_regenerates_only_from_the_requested_date_onwards(self) -> None:
        """Earlier days keep exactly what was fixed and are not staffed anew."""
        generate_from = date(2026, 8, 15)
        kept_day = date(2026, 8, 3)
        employees = [_employee(index) for index in range(1, 7)]
        competences = [SchedulingCompetence(id=1, name="Triage", required_count=1)]

        assignments = solve_monthly_schedule(
            employees,
            competences,
            month=8,
            year=2026,
            fixed_assignments=frozenset({(2, 1, kept_day)}),
            generate_from=generate_from,
        )

        past_assignments = [
            item for item in assignments if item.work_date < generate_from
        ]
        self.assertEqual(
            [(item.user_id, item.competence_id, item.work_date) for item in past_assignments],
            [(2, 1, kept_day)],
        )
        for day_number in range(15, 32):
            work_date = date(2026, 8, day_number)
            self.assertEqual(
                sum(1 for item in assignments if item.work_date == work_date),
                1,
            )

    def test_rejects_manually_placed_duties_that_break_the_rest_day(self) -> None:
        """Two placed duties on neighbouring days are reported, not solved."""
        employees = [_employee(index) for index in range(1, 7)]
        competences = [SchedulingCompetence(id=1, name="Triage", required_count=1)]

        with self.assertRaises(ScheduleGenerationError) as error:
            solve_monthly_schedule(
                employees,
                competences,
                month=8,
                year=2026,
                fixed_assignments=frozenset(
                    {(1, 1, date(2026, 8, 4)), (1, 1, date(2026, 8, 5))}
                ),
            )

        self.assertEqual(
            [issue["code"] for issue in error.exception.issues],
            ["fixed_assignment_rest_conflict"],
        )

    def test_rejects_more_manually_placed_duties_than_the_day_requires(self) -> None:
        """Overfilling a role by hand is reported before the solve starts."""
        crowded_day = date(2026, 8, 7)
        employees = [_employee(index) for index in range(1, 7)]
        competences = [SchedulingCompetence(id=1, name="Triage", required_count=1)]

        with self.assertRaises(ScheduleGenerationError) as error:
            solve_monthly_schedule(
                employees,
                competences,
                month=8,
                year=2026,
                fixed_assignments=frozenset(
                    {(1, 1, crowded_day), (2, 1, crowded_day)}
                ),
            )

        self.assertEqual(
            [issue["code"] for issue in error.exception.issues],
            ["fixed_assignment_over_requirement"],
        )

    def test_keeps_a_manually_placed_duty_on_an_unavailable_day(self) -> None:
        """The manager's own placement outranks the employee's absence."""
        placed_day = date(2026, 8, 12)
        employees = [
            _employee(1, unavailable_dates=frozenset({placed_day})),
            *(_employee(index) for index in range(2, 7)),
        ]
        competences = [SchedulingCompetence(id=1, name="Triage", required_count=1)]

        assignments = solve_monthly_schedule(
            employees,
            competences,
            month=8,
            year=2026,
            fixed_assignments=frozenset({(1, 1, placed_day)}),
        )

        self.assertIn(
            (1, 1, placed_day),
            {
                (item.user_id, item.competence_id, item.work_date)
                for item in assignments
            },
        )



class ScheduleGenerationBalanceTests(unittest.TestCase):
    """Verify what the objective balances and whose wishes tilt it."""

    #: Saturdays and Sundays of August 2026, which is the weekend rule a
    #: competence starts from when nothing else is configured.
    SURCHARGE_DAYS = frozenset(
        date(2026, 8, day) for day in (1, 2, 8, 9, 15, 16, 22, 23, 29, 30)
    )

    def test_shares_out_the_surcharged_days_as_evenly_as_the_rest(self) -> None:
        """Nobody is handed the weekends while somebody else works weekdays."""
        employees = [_employee(index, competence_ids=frozenset({1})) for index in range(1, 5)]
        assignments = solve_monthly_schedule(
            employees,
            [SchedulingCompetence(id=1, name="Triage", required_count=1)],
            month=8,
            year=2026,
        )

        surcharged = Counter(
            item.user_id for item in assignments if item.work_date in self.SURCHARGE_DAYS
        )
        ordinary = Counter(
            item.user_id
            for item in assignments
            if item.work_date not in self.SURCHARGE_DAYS
        )

        self.assertEqual(sorted(surcharged.values()), [2, 2, 3, 3])
        self.assertLessEqual(max(ordinary.values()) - min(ordinary.values()), 1)

    def test_duty_kind_wishes_trade_weekends_for_weekdays(self) -> None:
        """Who wants the surcharged days gets more of them, not more duties."""
        employees = [
            _employee(
                1,
                competence_ids=frozenset({1}),
                shift_preference="surcharge",
            ),
            _employee(
                2,
                competence_ids=frozenset({1}),
                shift_preference="standard",
            ),
            _employee(3, competence_ids=frozenset({1})),
            _employee(4, competence_ids=frozenset({1})),
        ]
        assignments = solve_monthly_schedule(
            employees,
            [SchedulingCompetence(id=1, name="Triage", required_count=1)],
            month=8,
            year=2026,
        )

        surcharged = Counter(
            item.user_id for item in assignments if item.work_date in self.SURCHARGE_DAYS
        )
        workload = Counter(item.user_id for item in assignments)

        self.assertGreater(surcharged[1], surcharged[2])
        # The wish moves which duties they work, never how many: the whole
        # roster stays as level as the month allows.
        self.assertLessEqual(max(workload.values()) - min(workload.values()), 1)

    def test_a_duty_kind_wish_never_buys_a_less_balanced_roster(self) -> None:
        """Everybody wanting the weekends still shares them out evenly."""
        employees = [
            _employee(
                index,
                competence_ids=frozenset({1}),
                shift_preference="surcharge",
            )
            for index in range(1, 5)
        ]
        assignments = solve_monthly_schedule(
            employees,
            [SchedulingCompetence(id=1, name="Triage", required_count=1)],
            month=8,
            year=2026,
        )

        surcharged = Counter(
            item.user_id for item in assignments if item.work_date in self.SURCHARGE_DAYS
        )

        self.assertEqual(sorted(surcharged.values()), [2, 2, 3, 3])

    def test_balances_the_hours_and_not_only_the_number_of_duties(self) -> None:
        """A long duty weighs more than a short one when the load is shared."""
        employees = [_employee(index, competence_ids=frozenset({1})) for index in range(1, 3)]
        competence = SchedulingCompetence(
            id=1,
            name="Triage",
            required_count=1,
            # Mondays and Wednesdays only, and a Monday lasts three times
            # as long as a Wednesday.
            weekday_required_counts=(1, 0, 1, 0, 0, 0, 0),
            weekday_shift_hours=(12.0, 4.0, 4.0, 4.0, 4.0, 4.0, 4.0),
        )
        assignments = solve_monthly_schedule(
            employees,
            [competence],
            month=8,
            year=2026,
        )

        hours = Counter()
        for item in assignments:
            hours[item.user_id] += competence.shift_hours_on(item.work_date)
        workload = Counter(item.user_id for item in assignments)

        # Five Mondays and four Wednesdays: 76 hours over two people, which
        # the duty counts alone would happily split 60 to 16.
        self.assertEqual(len(assignments), 9)
        self.assertEqual(sorted(workload.values()), [4, 5])
        self.assertLessEqual(max(hours.values()) - min(hours.values()), 8)


class ScheduleGenerationRecoveryTests(unittest.TestCase):
    """Verify the rest a duty earns under the workplace's own settings."""

    def test_a_long_recovery_keeps_an_employee_off_for_days(self) -> None:
        """Three days of recovery put four days between two duties."""
        employees = [_employee(index, competence_ids=frozenset({1})) for index in range(1, 6)]
        assignments = solve_monthly_schedule(
            employees,
            [
                SchedulingCompetence(
                    id=1,
                    name="Triage",
                    required_count=1,
                    weekday_recovery_days=(3, 3, 3, 3, 3, 3, 3),
                )
            ],
            month=8,
            year=2026,
        )

        self.assertEqual(len(assignments), 31)
        dates_by_employee: dict[int, list[date]] = {}
        for item in assignments:
            dates_by_employee.setdefault(item.user_id, []).append(item.work_date)
        for work_dates in dates_by_employee.values():
            ordered = sorted(work_dates)
            for current, following in zip(ordered, ordered[1:]):
                self.assertGreaterEqual((following - current).days, 4)

    def test_no_recovery_lets_the_same_employee_work_two_days_running(self) -> None:
        """A workplace that asks for no rest is staffed by a single person."""
        assignments = solve_monthly_schedule(
            [_employee(1, competence_ids=frozenset({1}))],
            [
                SchedulingCompetence(
                    id=1,
                    name="Triage",
                    required_count=1,
                    weekday_recovery_days=(0, 0, 0, 0, 0, 0, 0),
                )
            ],
            month=8,
            year=2026,
        )

        self.assertEqual(len(assignments), 31)

    def test_recovery_reaches_across_the_month_boundary(self) -> None:
        """A duty on the last day of the previous month still claims its rest."""
        employees = [_employee(index, competence_ids=frozenset({1})) for index in range(1, 6)]
        assignments = solve_monthly_schedule(
            employees,
            [
                SchedulingCompetence(
                    id=1,
                    name="Triage",
                    required_count=1,
                    weekday_recovery_days=(3, 3, 3, 3, 3, 3, 3),
                )
            ],
            month=8,
            year=2026,
            adjacent_assignments=frozenset({(1, 1, date(2026, 7, 31))}),
        )

        blocked = {date(2026, 8, day) for day in (1, 2, 3)}
        self.assertFalse(
            any(item.user_id == 1 and item.work_date in blocked for item in assignments)
        )

    def test_rejects_manually_placed_duties_inside_a_long_recovery(self) -> None:
        """Two placed duties three days apart break a three-day recovery."""
        with self.assertRaises(ScheduleGenerationError) as context:
            solve_monthly_schedule(
                [_employee(index, competence_ids=frozenset({1})) for index in range(1, 6)],
                [
                    SchedulingCompetence(
                        id=1,
                        name="Triage",
                        required_count=1,
                        weekday_recovery_days=(3, 3, 3, 3, 3, 3, 3),
                    )
                ],
                month=8,
                year=2026,
                fixed_assignments=frozenset(
                    {(1, 1, date(2026, 8, 10)), (1, 1, date(2026, 8, 13))}
                ),
            )

        self.assertEqual(
            [issue["code"] for issue in context.exception.issues],
            ["fixed_assignment_rest_conflict"],
        )


class ScheduleGenerationSpreadTests(unittest.TestCase):
    """Verify that duties are pushed apart when the month leaves a choice."""

    def test_keeps_one_employee_out_of_a_fully_packed_week(self) -> None:
        """Two employees take turns rather than one working a whole week."""
        employees = [_employee(index, competence_ids=frozenset({1})) for index in range(1, 3)]
        assignments = solve_monthly_schedule(
            employees,
            [
                SchedulingCompetence(
                    id=1,
                    name="Triage",
                    required_count=1,
                    # Monday, Wednesday and Friday: three duties a week, which
                    # one employee could take alone without ever breaking the
                    # day of rest between them.
                    weekday_required_counts=(1, 0, 1, 0, 1, 0, 0),
                )
            ],
            month=8,
            year=2026,
        )

        self.assertEqual(len(assignments), 13)
        dates_by_employee: dict[int, list[date]] = {}
        for item in assignments:
            dates_by_employee.setdefault(item.user_id, []).append(item.work_date)
        for work_dates in dates_by_employee.values():
            ordered = sorted(work_dates)
            for start_index, first in enumerate(ordered):
                inside_week = [
                    work_date
                    for work_date in ordered[start_index:]
                    if (work_date - first).days < 7
                ]
                self.assertLess(len(inside_week), 3)

    def test_widens_the_tightest_gaps_first(self) -> None:
        """Slack in the month goes to the duties sitting closest together."""
        employees = [
            _employee(index, competence_ids=frozenset({1})) for index in range(1, 5)
        ]
        assignments = solve_monthly_schedule(
            employees,
            [SchedulingCompetence(id=1, name="Triage", required_count=1)],
            month=8,
            year=2026,
        )

        dates_by_employee: dict[int, list[date]] = {}
        for item in assignments:
            dates_by_employee.setdefault(item.user_id, []).append(item.work_date)

        # Four employees over thirty-one days: the rest rule alone would be
        # happy with duties two days apart, and a roster that only obeys it
        # is full of them. There is room for four days between duties, and
        # the spread term is what spends it, tightest gaps first.
        gaps = [
            (later - earlier).days
            for work_dates in dates_by_employee.values()
            for earlier, later in zip(sorted(work_dates), sorted(work_dates)[1:])
        ]
        self.assertLessEqual(len([gap for gap in gaps if gap < 3]), 2)


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

    def test_regenerates_a_month_from_a_date_around_placed_duties(self) -> None:
        """The loader passes placed duties and the window through to the solver."""
        ambulance = Ambulance(name="Partial month", is_active=True)
        users = [
            User(email=f"partial{index}@example.com", is_active=True)
            for index in range(4)
        ]
        self.db.add_all([ambulance, *users])
        self.db.flush()
        competence = Competence(
            name="Triage",
            required_count=1,
            ambulance_id=ambulance.id,
            is_active=True,
        )
        self.db.add(competence)
        self.db.flush()
        self.db.add_all(
            [
                UserAmbulance(user_id=user.id, ambulance_id=ambulance.id, is_active=True)
                for user in users
            ]
            + [
                UserCompetence(
                    user_id=user.id, competence_id=competence.id, is_active=True
                )
                for user in users
            ]
        )
        self.db.commit()

        kept_day = date(2026, 8, 2)
        result = generate_ambulance_monthly_schedule(
            self.db,
            ambulance.id,
            month=8,
            year=2026,
            fixed_entries=[(users[3].id, competence.id, kept_day)],
            generate_from=date(2026, 8, 15),
        )

        planned_dates = {entry.work_date for entry in result.entries}
        self.assertEqual(
            {work_date for work_date in planned_dates if work_date < date(2026, 8, 15)},
            {kept_day},
        )
        self.assertEqual(
            {work_date for work_date in planned_dates if work_date >= date(2026, 8, 15)},
            {date(2026, 8, day) for day in range(15, 32)},
        )
        kept_entry = next(
            entry for entry in result.entries if entry.work_date == kept_day
        )
        self.assertEqual(kept_entry.user_id, users[3].id)

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
        scenario = CompetenceScenario(
            name="Scenario 1",
            ambulance_id=ambulance.id,
            is_selected=True,
            is_active=True,
        )
        self.db.add(scenario)
        self.db.flush()
        competence.weekday_requirements = [
            CompetenceWeekdayRequirement(
                weekday=0, required_count=1, scenario_id=scenario.id
            ),
            CompetenceWeekdayRequirement(
                weekday=6, required_count=2, scenario_id=scenario.id
            ),
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

        # 15 from the weekdays, plus 29 August -- a public holiday, and
        # therefore staffed from the day-of-rest slot rather than as the
        # Saturday it falls on. That slot has no row either, so it inherits
        # Sunday's two.
        self.assertEqual(result.assignment_count, 17)
        self.assertEqual(coverage[date(2026, 8, 3)], 1)
        self.assertEqual(coverage[date(2026, 8, 2)], 2)
        self.assertEqual(coverage[date(2026, 8, 4)], 0)
        self.assertEqual(coverage[date(2026, 8, 29)], 2)
        self.assertEqual(coverage[date(2026, 8, 22)], 0)


    def test_loads_recovery_days_from_the_selected_scenario(self) -> None:
        """A week of recovery stops an employee working two Mondays running."""
        ambulance = Ambulance(name="Recovery clinic", is_active=True)
        users = [User(email=f"rest{index}@example.com", is_active=True) for index in range(2)]
        self.db.add_all([ambulance, *users])
        self.db.flush()
        competence = Competence(
            name="Long duty",
            required_count=0,
            ambulance_id=ambulance.id,
            is_active=True,
        )
        scenario = CompetenceScenario(
            name="Scenario 1",
            ambulance_id=ambulance.id,
            is_selected=True,
            is_active=True,
        )
        self.db.add(scenario)
        self.db.flush()
        competence.weekday_requirements = [
            CompetenceWeekdayRequirement(
                weekday=0,
                required_count=1,
                recovery_days=6,
                scenario_id=scenario.id,
            )
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

        # Every Monday of the month is staffed, but six days of rest reach
        # past the next one, so the two employees have to take turns.
        self.assertEqual(result.assignment_count, 5)
        dates_by_employee: dict[int, list[date]] = {}
        for entry in result.entries:
            dates_by_employee.setdefault(entry.user_id, []).append(entry.work_date)
        for work_dates in dates_by_employee.values():
            ordered = sorted(work_dates)
            for current, following in zip(ordered, ordered[1:]):
                self.assertGreater((following - current).days, 6)

    def test_loads_the_surcharge_flag_and_the_employee_duty_kind_wish(self) -> None:
        """The employee who asked for the surcharged duties gets more of them."""
        ambulance = Ambulance(name="Surcharge clinic", is_active=True)
        wants_surcharge = User(
            email="surcharge@example.com",
            is_active=True,
            shift_preference="surcharge",
        )
        wants_standard = User(
            email="standard@example.com",
            is_active=True,
            shift_preference="standard",
        )
        indifferent = [
            User(email=f"any{index}@example.com", is_active=True, shift_preference="any")
            for index in range(2)
        ]
        users = [wants_surcharge, wants_standard, *indifferent]
        self.db.add_all([ambulance, *users])
        self.db.flush()
        competence = Competence(
            name="Triage",
            required_count=0,
            ambulance_id=ambulance.id,
            is_active=True,
        )
        scenario = CompetenceScenario(
            name="Scenario 1",
            ambulance_id=ambulance.id,
            is_selected=True,
            is_active=True,
        )
        self.db.add(scenario)
        self.db.flush()
        # Only Monday is paid with a surcharge here, which is the opposite of
        # what the weekend default would have said.
        competence.weekday_requirements = [
            CompetenceWeekdayRequirement(
                weekday=weekday,
                required_count=1,
                is_surcharge=weekday == 0,
                scenario_id=scenario.id,
            )
            for weekday in range(8)
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

        mondays = Counter(
            entry.user_id for entry in result.entries if entry.work_date.weekday() == 0
        )
        workload = Counter(entry.user_id for entry in result.entries)

        self.assertEqual(result.assignment_count, 31)
        self.assertGreater(mondays[wants_surcharge.id], mondays[wants_standard.id])
        self.assertLessEqual(max(workload.values()) - min(workload.values()), 1)


    def test_a_duty_elsewhere_earns_the_rest_that_workplace_asks_for(self) -> None:
        """A borrowed employee comes back when the other workplace says so."""
        target = Ambulance(name="Target", is_active=True)
        lender = Ambulance(name="Lender", is_active=True)
        users = [User(email=f"lent{index}@example.com", is_active=True) for index in range(3)]
        self.db.add_all([target, lender, *users])
        self.db.flush()

        target_competence = Competence(
            name="Triage", required_count=1, ambulance_id=target.id, is_active=True
        )
        lender_competence = Competence(
            name="Long duty", required_count=1, ambulance_id=lender.id, is_active=True
        )
        self.db.add_all([target_competence, lender_competence])
        self.db.flush()

        # The lender asks for four days of rest after its duty; this
        # workplace asks for one after its own, and has no say over the
        # other one.
        lender_scenario = CompetenceScenario(
            name="Lender scenario",
            ambulance_id=lender.id,
            is_selected=True,
            is_active=True,
        )
        self.db.add(lender_scenario)
        self.db.flush()
        self.db.add_all(
            [
                CompetenceWeekdayRequirement(
                    competence_id=lender_competence.id,
                    scenario_id=lender_scenario.id,
                    weekday=weekday,
                    required_count=1,
                    recovery_days=4,
                )
                for weekday in range(8)
            ]
        )
        self.db.add_all(
            [
                UserAmbulance(user_id=user.id, ambulance_id=target.id, is_active=True)
                for user in users
            ]
            + [
                UserCompetence(
                    user_id=user.id, competence_id=target_competence.id, is_active=True
                )
                for user in users
            ]
        )
        borrowed = users[0]
        self.db.add(
            Schedule(
                user_id=borrowed.id,
                ambulance_id=lender.id,
                competence_id=lender_competence.id,
                work_date=date(2026, 8, 10),
                is_active=True,
            )
        )
        self.db.commit()

        result = generate_ambulance_monthly_schedule(
            self.db,
            target.id,
            month=8,
            year=2026,
        )

        resting = {date(2026, 8, day) for day in (10, 11, 12, 13, 14)}
        borrowed_days = {
            entry.work_date for entry in result.entries if entry.user_id == borrowed.id
        }
        self.assertEqual(result.assignment_count, 31)
        self.assertFalse(borrowed_days & resting)
        # Blocked for five days, not idle for the month: the rest ends
        # where the lender says it ends.
        self.assertGreaterEqual(len(borrowed_days), 8)


if __name__ == "__main__":
    unittest.main()
