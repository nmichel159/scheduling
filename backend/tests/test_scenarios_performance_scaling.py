"""Scenario tests: how long a month takes to plan, by size.

A smoke benchmark with loose upper bounds, meant to catch a regression that
makes the model build or the solve an order of magnitude slower. It plants a
month of each size, solves it with a fixed budget and checks that the
roster is valid and that the call ended within the budget plus a generous
margin. The margin is wide on purpose: the second pass is known to overrun
its own time limit (see ``test_scenarios_determinism_robustness``), and that
is reported there, not here.

The full grid (3-120 people, 1-8 roles, two rest profiles, three
utilisation levels, 30 s and 120 s budgets) was run once on a quiet machine
for the test report; it is not repeated by the suite.
"""

from __future__ import annotations

import time
import unittest
from unittest import mock

import app.services.schedule_generation_service as generation_service

from tests.scheduling_harness.instances import Knobs, make_instance
from tests.scheduling_harness.oracle import validate

#: (employees, roles, budget in seconds, the most the whole call may take).
SHAPES: tuple[tuple[int, int, float, float], ...] = (
    (5, 1, 10.0, 30.0),
    (20, 2, 20.0, 90.0),
    (57, 7, 30.0, 240.0),
)


def _knobs(n_employees: int, n_competences: int) -> Knobs:
    """A planted month shaped like a real workplace of the given size."""
    return Knobs(
        n_employees=n_employees,
        n_competences=n_competences,
        month=10,
        year=2026,
        demand_profile="mixed",
        recovery_profile="one",
        hours_profile="mixed",
        target_utilization=0.8,
        special_days="library",
        unavailability_rate=0.1,
        preferred_rate=0.05,
        soft_decline_rate=0.05,
        max_shifts_mode="loose",
        planted=True,
    )


class PerformanceSmokeTests(unittest.TestCase):
    """Model build and solve stay within loose bounds at three sizes."""

    def test_sizes(self) -> None:
        """Each size solves to a valid roster within the ceiling."""
        for n_employees, n_competences, budget, ceiling in SHAPES:
            with self.subTest(employees=n_employees, roles=n_competences):
                instance = make_instance(1000 + n_employees, _knobs(n_employees, n_competences))
                build_seconds: list[float] = []
                original = generation_service._run_solver
                started = time.perf_counter()

                def timed(problem, seconds, close_enough=None):  # type: ignore[no-untyped-def]
                    """Record when the first CBC call starts, then solve as usual."""
                    if not build_seconds:
                        build_seconds.append(time.perf_counter() - started)
                    return original(problem, seconds, close_enough)

                with mock.patch.object(generation_service, "_run_solver", timed):
                    result = generation_service.solve_monthly_schedule(
                        **instance.solver_kwargs(), time_budget_seconds=budget
                    )
                wall = time.perf_counter() - started
                roster = [(item.user_id, item.competence_id, item.work_date) for item in result]

                self.assertEqual(validate(instance, roster), [])
                # Building the model is a small part of the call at any of these sizes.
                self.assertLess(build_seconds[0], 10.0)
                self.assertLess(wall, ceiling)


if __name__ == "__main__":
    unittest.main()
