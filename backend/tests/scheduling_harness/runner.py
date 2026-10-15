"""Run the solver under test on an instance and record what happened.

:func:`run_solver` calls ``solve_monthly_schedule`` and classifies the
outcome. With ``observe=True`` it also records, for every CBC call the
solver makes, the objective value and solution status it ended with. That
is observation only -- the solver's private ``_run_solver`` is wrapped, not
reused to judge anything -- and it is what lets a test see the first-pass
value the second pass was locked to, whether a pass hit its time limit, and
whether the second pass ran at all.

:func:`solve_in_parallel` spreads many instances over worker processes
(CBC is single-threaded; the machine has many cores).
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from time import perf_counter
from typing import Iterable
from unittest import mock

from pulp import LpSolutionIntegerFeasible, LpSolutionOptimal, value

import app.services.schedule_generation_service as generation_service
from app.services.schedule_generation_service import (
    ScheduleGenerationError,
    solve_monthly_schedule,
)

from tests.scheduling_harness.instances import Instance
from tests.scheduling_harness.semantics import Duty, as_duties, balance_lock_slack


@dataclass(frozen=True)
class PassRecord:
    """What one CBC call inside the solver ended with.

    ``kind`` is ``'balance'`` for the first pass and ``'wishes'`` for the
    second (the second is the one given an optimality tolerance).
    ``sol_status`` is PuLP's: 1 optimal, 2 feasible but stopped early (time
    limit), 0 nothing found, -1 infeasible.
    """

    kind: str
    objective: float | None
    sol_status: int
    time_limit: float
    close_enough: float | None

    @property
    def optimal(self) -> bool:
        """Whether CBC proved this pass optimal (within its tolerance)."""
        return self.sol_status == LpSolutionOptimal

    @property
    def stopped_early(self) -> bool:
        """Whether CBC returned a feasible answer it had not proved optimal."""
        return self.sol_status == LpSolutionIntegerFeasible


@dataclass
class SolveOutcome:
    """The solver's answer for one instance.

    ``status`` is ``'ok'`` with a roster, ``'infeasible'`` when the solver
    reported a conflict, ``'timeout'`` when it found nothing in time, and
    ``'error'`` for any other exception. ``passes`` is filled by observed
    runs only.
    """

    status: str
    assignments: list[Duty] = field(default_factory=list)
    issues: list[dict] = field(default_factory=list)
    seconds: float = 0.0
    error: str | None = None
    budget: float | None = None
    passes: list[PassRecord] = field(default_factory=list)

    @property
    def issue_codes(self) -> set[str]:
        """The codes of the reported issues."""
        return {str(issue.get("code")) for issue in self.issues}

    @property
    def hit_budget(self) -> bool:
        """Whether the run used (nearly) its whole time budget.

        A run that did may have returned a roster the first pass had not
        proved optimal, so optimality findings on it are not bugs. Observed
        runs answer exactly (some pass stopped early); others guess from the
        wall time.
        """
        if self.passes:
            return any(record.stopped_early for record in self.passes)
        return self.budget is not None and self.seconds >= 0.9 * self.budget

    @property
    def first_pass(self) -> PassRecord | None:
        """The first (balance) pass, for observed runs."""
        return next((record for record in self.passes if record.kind == "balance"), None)

    @property
    def second_pass(self) -> PassRecord | None:
        """The second (wishes) pass, for observed runs; ``None`` if skipped."""
        return next((record for record in self.passes if record.kind == "wishes"), None)

    @property
    def first_pass_objective(self) -> float | None:
        """The balance value the first pass reached, for observed runs."""
        record = self.first_pass
        return record.objective if record else None

    @property
    def balance_cap(self) -> float | None:
        """The most the solver lets the final roster's first-pass cost be."""
        reached = self.first_pass_objective
        if reached is None:
            return None
        return reached + balance_lock_slack(reached)


def _observer(records: list[PassRecord]):
    """A stand-in for the solver's CBC call that records what each call ended with."""
    original = generation_service._run_solver

    def observed(problem, seconds, close_enough=None):
        original(problem, seconds, close_enough)
        objective = value(problem.objective) if problem.objective is not None else None
        records.append(
            PassRecord(
                kind="balance" if close_enough is None and not records else "wishes",
                objective=float(objective) if objective is not None else None,
                sol_status=int(problem.sol_status),
                time_limit=float(seconds),
                close_enough=close_enough,
            )
        )

    return observed


def run_solver(
    instance: Instance, time_budget_seconds: float = 30, observe: bool = False
) -> SolveOutcome:
    """Call ``solve_monthly_schedule`` on an instance and classify the result.

    With ``observe=True`` every CBC call is recorded in ``passes``.
    """
    records: list[PassRecord] = []
    patcher = (
        mock.patch.object(generation_service, "_run_solver", _observer(records))
        if observe
        else None
    )
    started = perf_counter()
    try:
        if patcher is not None:
            patcher.start()
        assignments = solve_monthly_schedule(
            **instance.solver_kwargs(), time_budget_seconds=time_budget_seconds
        )
    except ScheduleGenerationError as error:
        seconds = perf_counter() - started
        issues = list(error.issues)
        status = (
            "timeout"
            if any(issue.get("code") == "solver_timeout" for issue in issues)
            else "infeasible"
        )
        return SolveOutcome(
            status, [], issues, seconds, error.message, time_budget_seconds, records
        )
    except Exception as error:  # noqa: BLE001 - every other failure is a finding
        return SolveOutcome(
            "error",
            [],
            [],
            perf_counter() - started,
            f"{type(error).__name__}: {error}",
            time_budget_seconds,
            records,
        )
    finally:
        if patcher is not None:
            patcher.stop()
    return SolveOutcome(
        "ok",
        as_duties(assignments),
        [],
        perf_counter() - started,
        None,
        time_budget_seconds,
        records,
    )


def _solve_one(job: tuple[Instance, float, bool]) -> SolveOutcome:
    """Worker body of :func:`solve_in_parallel`."""
    instance, budget, observe = job
    return run_solver(instance, budget, observe)


def solve_in_parallel(
    instances: Iterable[Instance],
    time_budget_seconds: float = 30,
    workers: int = 16,
    observe: bool = False,
) -> list[SolveOutcome]:
    """Solve many instances in worker processes, outcomes in input order.

    Each worker runs one CBC at a time, so ``workers`` CBC processes run at
    once; keep it below the core count (the machine has 32) so wall-clock
    time budgets still mean what they say.
    """
    jobs = [(instance, time_budget_seconds, observe) for instance in instances]
    if workers <= 1 or len(jobs) <= 1:
        return [_solve_one(job) for job in jobs]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(_solve_one, jobs))
