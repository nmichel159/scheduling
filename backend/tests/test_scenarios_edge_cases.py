"""Degenerate inputs of the monthly schedule generator.

Each case is a deliberately odd input -- nobody to schedule, nothing to
staff, a single employee, rest of zero or six days everywhere, leap months,
the year's end, windows of one day, months already fully placed, placements
outside the month or for strangers, malformed per-weekday tuples, extreme
weights, one-second budgets -- with the behaviour the documentation (model
doc, README, docstrings) leads one to expect. Every returned roster is also
held to ``oracle.validate``.

``SCHEDULING_STRESS=1`` repeats the calendar cases over every month of
2026-2028 and the budget case over more and larger instances.
``EDGE_CASES_METRICS=<path>`` writes the case table as JSON.
"""

from __future__ import annotations

import json
import os
import random
import unittest
from collections import Counter
from dataclasses import replace
from datetime import date, timedelta
from typing import Any

from app.services.constraint_setting_service import (
    BALANCE,
    BUSINESS_TRIP,
    MAX_SHIFTS,
    OVERSTAFF,
    PREFERRED,
    REST,
    SOFT_DECLINE,
    SPREAD,
    UNAVAILABLE,
    VACATION,
    policy_from_settings,
)
from app.services.schedule_generation_service import (
    ScheduleGenerationError,
    SchedulingCompetence,
    SchedulingEmployee,
    solve_monthly_schedule,
)

from tests.scheduling_harness.instances import (
    Instance,
    Knobs,
    make_instance,
    sample_knobs,
    symmetric_instance,
)
from tests.scheduling_harness.oracle import metrics, validate, violation_codes
from tests.scheduling_harness.runner import SolveOutcome, run_solver, solve_in_parallel
from tests.scheduling_harness.scenarios import chain_months
from tests.scheduling_harness.semantics import month_days

STRESS = os.environ.get("SCHEDULING_STRESS") == "1"
#: One other agent shares the machine: never more than six CBC processes.
WORKERS = 6
BUDGET = 10.0

_ROWS: list[list[Any]] = []
_METRICS: dict[str, Any] = {}


def _row(case: str, behaviour: str, correct: bool | str) -> None:
    """One line of the case table."""
    _ROWS.append([case, behaviour, correct])


def tearDownModule() -> None:
    """Write the case table when ``EDGE_CASES_METRICS`` names a file."""
    path = os.environ.get("EDGE_CASES_METRICS")
    if path:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"rows": _ROWS, **_METRICS}, handle, default=str, indent=1)


def _role(
    competence_id: int = 1,
    counts: tuple[int, ...] = (1,) * 7,
    recovery: int = 1,
    hours: float = 4.0,
    special: int | None = None,
    special_dates: frozenset[date] = frozenset(),
) -> SchedulingCompetence:
    """One role with the same rest and hours every day."""
    return SchedulingCompetence(
        id=competence_id,
        name=f"Role {competence_id}",
        required_count=counts[0],
        weekday_required_counts=tuple(counts),
        special_day_required_count=special,
        special_dates=special_dates,
        weekday_recovery_days=(recovery,) * 7,
        special_day_recovery_days=recovery,
        weekday_shift_hours=(hours,) * 7,
        special_day_shift_hours=hours,
    )


def _person(user_id: int, roles: tuple[int, ...] = (1,), **fields: Any) -> SchedulingEmployee:
    """An employee holding the given roles."""
    values: dict[str, Any] = {
        "id": user_id,
        "email": f"edge{user_id}@harness.test",
        "full_name": None,
        "competence_ids": frozenset(roles),
        "unavailable_dates": frozenset(),
        "externally_scheduled_dates": frozenset(),
    }
    values.update(fields)
    return SchedulingEmployee(**values)


def _month(month: int, year: int, people: list[SchedulingEmployee], roles: list[SchedulingCompetence], **extra: Any) -> Instance:
    """An instance from plain parts."""
    return Instance(people, roles, month, year, **extra)


def _roster_or_none(instance: Instance) -> list | None:
    """Solve one month of a chain; ``None`` stops the chain."""
    outcome = run_solver(instance, 15)
    return outcome.assignments if outcome.status == "ok" else None


class EdgeCaseTests(unittest.TestCase):
    """Each test is one degenerate input and the behaviour it should get."""

    def _solve(self, instance: Instance, budget: float = BUDGET) -> SolveOutcome:
        """Solve and, for a roster, insist that it keeps every hard rule."""
        outcome = run_solver(instance, budget, observe=True)
        self.assertNotEqual(outcome.status, "error", outcome.error)
        if outcome.status == "ok":
            self.assertEqual(violation_codes(validate(instance, outcome.assignments)), set(), instance.label)
        return outcome

    # --- Nobody, nothing --------------------------------------------------------------

    def test_single_employee(self) -> None:
        """Alone without rest: every day is theirs. With one day of rest: infeasible, before CBC."""
        outcome = self._solve(_month(2, 2027, [_person(1)], [_role(recovery=0)]))
        self.assertEqual(outcome.status, "ok")
        self.assertEqual(len(outcome.assignments), 28)
        rested = self._solve(_month(2, 2027, [_person(1)], [_role(recovery=1)]))
        self.assertEqual(rested.status, "infeasible")
        self.assertIn("insufficient_consecutive_day_rotation", rested.issue_codes)
        _row("single employee, rest 0", "28 duties, all theirs", True)
        _row("single employee, rest 1", f"infeasible {sorted(rested.issue_codes)}", True)

    def test_no_employees(self) -> None:
        """Nobody and demand: no_active_employees. Nobody and nothing to staff (in the window): []."""
        demanded = self._solve(_month(2, 2027, [], [_role()]))
        self.assertEqual(demanded.status, "infeasible")
        self.assertEqual(demanded.issue_codes, {"no_active_employees"})
        quiet = self._solve(_month(2, 2027, [], [_role(counts=(0,) * 7)]))
        self.assertEqual((quiet.status, quiet.assignments), ("ok", []))
        # Demand only on Mondays, window = Sunday 28 Feb 2027 alone.
        mondays = (1, 0, 0, 0, 0, 0, 0)
        window = self._solve(_month(2, 2027, [], [_role(counts=mondays)], generate_from=date(2027, 2, 28)))
        self.assertEqual((window.status, window.assignments), ("ok", []))
        placed = self._solve(_month(2, 2027, [], [_role()], fixed=frozenset({(1, 1, date(2027, 2, 3))})))
        self.assertEqual(placed.issue_codes, {"fixed_assignment_unknown"})
        _row("no employees, demand", "infeasible no_active_employees", True)
        _row("no employees, zero demand / zero in window", "ok, empty roster", True)
        _row("no employees, a placement", "infeasible fixed_assignment_unknown", True)

    def test_no_competences(self) -> None:
        """No roles: no_active_competences, with or without employees."""
        for people in ([_person(1)], []):
            outcome = self._solve(_month(2, 2027, people, []))
            self.assertEqual(outcome.status, "infeasible")
            self.assertEqual(outcome.issue_codes, {"no_active_competences"})
        _row("no competences (with/without employees)", "infeasible no_active_competences", True)

    def test_all_zero_demand(self) -> None:
        """Nothing to staff: an empty roster, whoever is there."""
        outcome = self._solve(_month(2, 2027, [_person(1), _person(2), _person(3, ())], [_role(counts=(0,) * 7), _role(2, counts=(0,) * 7)]))
        self.assertEqual((outcome.status, outcome.assignments), ("ok", []))
        _row("all-zero demand", "ok, empty roster", True)

    def test_one_role_all_zero(self) -> None:
        """A role asking for nobody gets nobody; the other is fully staffed."""
        people = [_person(user_id, (1, 2)) for user_id in range(1, 5)]
        outcome = self._solve(_month(2, 2027, people, [_role(1), _role(2, counts=(0,) * 7)]))
        self.assertEqual(outcome.status, "ok")
        self.assertEqual({duty[1] for duty in outcome.assignments}, {1})
        self.assertEqual(len(outcome.assignments), 28)
        _row("one role all-zero beside a normal one", "zero-role empty, other covered", True)

    def test_demand_above_staff_on_one_day(self) -> None:
        """Five people asked for on one Tuesday with four employees: the capacity check names that day."""
        people = [_person(user_id) for user_id in range(1, 5)]
        outcome = self._solve(_month(2, 2027, people, [_role(counts=(1, 5, 1, 1, 1, 1, 1))]))
        self.assertEqual(outcome.status, "infeasible")
        days = {issue["work_date"] for issue in outcome.issues if issue["code"] == "insufficient_daily_capacity"}
        tuesdays = {day.isoformat() for day in month_days(2, 2027) if day.weekday() == 1}
        self.assertEqual(days, tuesdays)
        for issue in outcome.issues:
            if issue["code"] == "insufficient_daily_capacity":
                self.assertEqual((issue["required_count"], issue["available_count"]), (5, 4))
        _row("demand > staff on a weekday", "infeasible, each such day named with 5 vs 4", True)

    # --- Rest ---------------------------------------------------------------------------

    def test_rest_zero_and_six_everywhere(self) -> None:
        """Rest 0: anyone any day. Rest 6: seven people rotate weekly, six cannot."""
        people = [_person(user_id) for user_id in range(1, 3)]
        zero = self._solve(_month(8, 2026, people, [_role(recovery=0)]))
        self.assertEqual(zero.status, "ok")
        self.assertLessEqual(metrics(_month(8, 2026, people, [_role(recovery=0)]), zero.assignments).load_spread, 1)
        cases = [(month, year) for year in (2026, 2027, 2028) for month in range(1, 13)] if STRESS else [(2, 2027), (2, 2028), (8, 2026), (4, 2026)]
        instances = []
        for month, year in cases:
            instances.append(_month(month, year, [_person(user_id) for user_id in range(1, 8)], [_role(recovery=6)], label=f"rest6-7-{year}-{month}"))
            instances.append(_month(month, year, [_person(user_id) for user_id in range(1, 7)], [_role(recovery=6)], label=f"rest6-6-{year}-{month}"))
        outcomes = solve_in_parallel(instances, 20, workers=WORKERS, observe=True)
        spreads: Counter[int] = Counter()
        for instance, outcome in zip(instances, outcomes):
            with self.subTest(instance.label):
                if instance.label.startswith("rest6-6"):
                    self.assertEqual(outcome.status, "infeasible")
                    continue
                self.assertEqual(outcome.status, "ok")
                self.assertEqual(validate(instance, outcome.assignments), [])
                self.assertEqual(len(outcome.assignments), len(instance.days))
                spread = metrics(instance, outcome.assignments).load_spread
                spreads[spread] += 1
                self.assertLessEqual(spread, 1)
        _METRICS["rest6_months"] = len(cases)
        _METRICS["rest6_spread_histogram"] = dict(spreads)
        _row("rest 0 everywhere (2 people)", "ok, spread <= 1", True)
        _row(f"rest 6 everywhere, 7 people, {len(cases)} months incl. Feb 2027/2028", f"ok, spread histogram {dict(spreads)}", True)
        _row("rest 6 everywhere, 6 people", "infeasible", True)

    def test_leap_and_month_lengths(self) -> None:
        """28/29/30/31-day months are covered day by day, 29 Feb 2028 and 2000 included, 2100 not."""
        for month, year, length in ((2, 2027, 28), (2, 2028, 29), (2, 2000, 29), (2, 2100, 28), (4, 2026, 30), (8, 2026, 31), (12, 2026, 31)):
            instance = _month(month, year, [_person(1), _person(2)], [_role(recovery=0)])
            outcome = self._solve(instance)
            self.assertEqual(outcome.status, "ok")
            self.assertEqual(sorted({duty[2] for duty in outcome.assignments}), month_days(month, year))
            self.assertEqual(len(month_days(month, year)), length)
        _row("28/29/30/31-day months, 2000 and 2100", "every day covered once", True)

    def test_year_end_chain(self) -> None:
        """Dec 2026 -> Jan 2027 -> Feb 2027 with long rests: the carried week is respected."""
        knobs = Knobs(month=12, year=2026, n_employees=10, n_competences=2, recovery_profile="long", planted=True)
        seeds = range(6) if STRESS else range(2)
        months = 0
        for seed in seeds:
            chain = chain_months(
                seed,
                knobs,
                3,
                _roster_or_none,
            )
            self.assertEqual(len(chain), 3)
            for instance, roster in chain:
                self.assertIsNotNone(roster, instance.label)
                self.assertEqual(validate(instance, roster), [], instance.label)
                months += 1
            self.assertEqual((chain[1][0].month, chain[1][0].year), (1, 2027))
            self.assertTrue(any(duty[2].year == 2026 for duty in chain[1][0].adjacent))
        _row("Dec/Jan boundary, 3-month chain, rest 2-6", f"{months} months valid, December duties carried into January", True)

    def test_adjacent_duty_with_rest_six(self) -> None:
        """A duty on 31 Jan earning six days keeps its holder off 1-6 Feb; one on 1 Mar keeps them off after 22 Feb."""
        people = [_person(user_id) for user_id in range(1, 9)]
        before = _month(2, 2027, people, [_role(recovery=6)], adjacent=frozenset({(1, 1, date(2027, 1, 31))}))
        outcome = self._solve(before, 20)
        self.assertEqual(outcome.status, "ok")
        self.assertGreaterEqual(min(duty[2] for duty in outcome.assignments if duty[0] == 1), date(2027, 2, 7))
        after = _month(2, 2027, people, [_role(recovery=6)], adjacent=frozenset({(1, 1, date(2027, 3, 1))}))
        outcome = self._solve(after, 20)
        self.assertEqual(outcome.status, "ok")
        self.assertLessEqual(max(duty[2] for duty in outcome.assignments if duty[0] == 1), date(2027, 2, 22))
        _row("adjacent duty 31 Jan with rest 6", "holder's first February duty >= 7 Feb", True)
        _row("adjacent duty 1 Mar, rest 6", "holder's last February duty <= 22 Feb", True)

    # --- The window -----------------------------------------------------------------------

    def test_generate_from_first_last_and_mid(self) -> None:
        """The window starts where asked; history keeps only its placements."""
        people = [_person(user_id, (1, 2)) for user_id in range(1, 7)]
        roles = [_role(1), _role(2)]
        base = _month(2, 2027, people, roles)
        full = self._solve(base)
        self.assertEqual(full.status, "ok")
        history = frozenset(duty for duty in full.assignments if duty[2] < date(2027, 2, 14))
        for start, placed in ((date(2027, 2, 1), frozenset()), (date(2027, 2, 28), frozenset()), (date(2027, 2, 14), history)):
            instance = replace(base, generate_from=start, fixed=placed)
            outcome = self._solve(instance)
            self.assertEqual(outcome.status, "ok")
            self.assertEqual(min(duty[2] for duty in outcome.assignments if duty not in placed), start)
            self.assertEqual({duty for duty in outcome.assignments if duty[2] < start}, set(placed))
        _row("generate_from = 1st / last day / mid (with history)", "window starts there; history = placements", True)

    def test_every_day_fixed(self) -> None:
        """A month entirely placed by hand comes back exactly as placed."""
        people = [_person(user_id, (1, 2)) for user_id in range(1, 7)]
        base = _month(2, 2027, people, [_role(1), _role(2)])
        roster = frozenset(self._solve(base).assignments)
        for generate_from in (None, date(2027, 2, 28)):
            outcome = self._solve(replace(base, fixed=roster, generate_from=generate_from))
            self.assertEqual(outcome.status, "ok")
            self.assertEqual(set(outcome.assignments), set(roster))
        _row("all days fixed (with and without generate_from)", "returned exactly as placed", True)

    def test_fixed_outside_the_month_and_duplicates(self) -> None:
        """Placements outside the month are dropped (even for strangers); a repeated one counts once."""
        people = [_person(user_id, (1, 2)) for user_id in range(1, 7)]
        roles = [_role(1), _role(2)]
        outside = frozenset({(1, 1, date(2027, 1, 31)), (1, 1, date(2027, 3, 1)), (99, 7, date(2027, 3, 1))})
        outcome = self._solve(_month(2, 2027, people, roles, fixed=outside))
        self.assertEqual(outcome.status, "ok")
        self.assertTrue(all(duty[2].month == 2 for duty in outcome.assignments))
        day = date(2027, 2, 3)
        repeated = solve_monthly_schedule(people, roles, 2, 2027, fixed_assignments=[(1, 1, day), (1, 1, day)], time_budget_seconds=BUDGET)  # type: ignore[arg-type]
        mine = [item for item in repeated if item.work_date == day and item.user_id == 1]
        self.assertEqual(len(mine), 1)
        _row("fixed outside the month (known and unknown people)", "silently dropped, roster valid", True)
        _row("duplicate fixed entries", "one duty", True)

    def test_fixed_for_unknown_user_or_competence(self) -> None:
        """fixed_assignment_unknown names each one, in the window or in the history."""
        people = [_person(user_id, (1, 2)) for user_id in range(1, 7)]
        roles = [_role(1), _role(2)]
        day = date(2027, 2, 3)
        for placed, generate_from in (((99, 1, day), None), ((1, 7, day), None), ((99, 1, day), date(2027, 2, 10))):
            outcome = self._solve(_month(2, 2027, people, roles, fixed=frozenset({placed}), generate_from=generate_from))
            self.assertEqual(outcome.status, "infeasible")
            self.assertEqual(
                outcome.issues,
                [{"code": "fixed_assignment_unknown", "work_date": day.isoformat(), "user_id": placed[0], "competence_id": placed[1]}],
            )
        _row("fixed for unknown user / competence (window or history)", "infeasible fixed_assignment_unknown with ids", True)

    # --- Malformed input --------------------------------------------------------------------

    def test_malformed_arguments_raise_value_error(self) -> None:
        """Wrong-length demand tuple, month/year out of range, window in another month."""
        people = [_person(1)]
        role = _role(recovery=0)
        for counts in ((1,) * 6, (1,) * 8, ()):
            with self.assertRaises(ValueError):
                solve_monthly_schedule(people, [replace(role, weekday_required_counts=counts)], 2, 2027, time_budget_seconds=5)
        for month, year in ((0, 2027), (13, 2027), (2, 1999), (2, 2101), (-1, 2027)):
            with self.assertRaises(ValueError):
                solve_monthly_schedule(people, [role], month, year, time_budget_seconds=5)
        for start in (date(2027, 3, 1), date(2026, 2, 1), date(2027, 1, 31)):
            with self.assertRaises(ValueError):
                solve_monthly_schedule(people, [role], 2, 2027, generate_from=start, time_budget_seconds=5)
        _row("weekday_required_counts of length 6/8/0", "ValueError", True)
        _row("month 0/13/-1, year 1999/2101", "ValueError", True)
        _row("generate_from in another month", "ValueError", True)

    @unittest.expectedFailure
    def test_other_per_weekday_tuples_of_the_wrong_length_raise_value_error(self) -> None:
        """Suspected input-validation gap: only the demand tuple is length-checked.

        ``weekday_recovery_days``, ``weekday_shift_hours`` and
        ``weekday_is_surcharge`` of six values crash with ``IndexError`` deep
        in the model (on the first Sunday) instead of the ``ValueError`` the
        same mistake in ``weekday_required_counts`` gets.
        """
        role = _role(recovery=0)
        for field, value in (("weekday_recovery_days", (0,) * 6), ("weekday_shift_hours", (4.0,) * 6), ("weekday_is_surcharge", (False,) * 6)):
            with self.subTest(field):
                with self.assertRaises(ValueError):
                    solve_monthly_schedule([_person(1)], [replace(role, **{field: value})], 2, 2027, time_budget_seconds=5)

    def test_wrong_length_tuples_are_reported(self) -> None:
        """Companion: record what each malformed tuple does today."""
        role = _role(recovery=0)
        seen = {}
        for field, value in (("weekday_recovery_days", (0,) * 6), ("weekday_shift_hours", (4.0,) * 6), ("weekday_is_surcharge", (False,) * 6)):
            try:
                solve_monthly_schedule([_person(1)], [replace(role, **{field: value})], 2, 2027, time_budget_seconds=5)
                seen[field] = "ok"
            except Exception as error:  # noqa: BLE001 - recording the behaviour
                seen[field] = type(error).__name__
        _METRICS["wrong_length_tuples"] = seen
        _row("weekday_recovery_days / shift_hours / is_surcharge of length 6", f"{seen}", "no (finding edge_cases_2)")

    @unittest.expectedFailure
    def test_duplicate_employee_ids_fail_cleanly(self) -> None:
        """Suspected input-validation gap: two employees with one id crash inside PuLP.

        ``solve_monthly_schedule`` builds constraint names from the employee
        id, so a repeated id raises ``pulp.PulpError: overlapping constraint
        names`` (an HTTP 500 if it ever reached the API) instead of a
        ``ValueError`` or ``ScheduleGenerationError``. The database loader
        cannot produce duplicates, so only direct callers are exposed.
        """
        people = [_person(1), _person(1), _person(2)]
        try:
            solve_monthly_schedule(people, [_role(recovery=1)], 2, 2027, time_budget_seconds=5)
        except (ValueError, ScheduleGenerationError):
            return
        except Exception as error:  # noqa: BLE001 - the suspected bug
            self.fail(f"{type(error).__name__}: {error}")

    def test_duplicate_employee_ids_today(self) -> None:
        """Companion: record what repeated ids do (crash, or merge when the pre-check fires first)."""
        same = self._outcome_of([_person(1), _person(1), _person(2)], [_role(recovery=1)])
        merged = self._outcome_of([_person(1, (1,)), _person(1, (2,)), _person(2, (1, 2)), _person(3, (1, 2))], [_role(1), _role(2)])
        _METRICS["duplicate_ids"] = {"identical": same, "different_roles": merged}
        _row("duplicate employee ids", f"identical: {same}; different roles: {merged}", "no (finding edge_cases_1)")

    def _outcome_of(self, people: list[SchedulingEmployee], roles: list[SchedulingCompetence]) -> str:
        outcome = run_solver(_month(2, 2027, people, roles), 5)
        return outcome.status if outcome.status != "error" else (outcome.error or "")[:60]

    # --- Calendar slots ----------------------------------------------------------------------

    def test_special_day_on_a_weekend(self) -> None:
        """An unset special slot falls back to the weekday underneath; a set one wins."""
        days = frozenset({date(2027, 2, 6), date(2027, 2, 7), date(2027, 2, 10)})  # Sat, Sun, Wed
        people = [_person(user_id) for user_id in range(1, 7)]
        unset = _role(counts=(1, 1, 1, 1, 1, 2, 2), special_dates=days)
        outcome = self._solve(_month(2, 2027, people, [unset]))
        counts = Counter(duty[2] for duty in outcome.assignments)
        self.assertEqual([counts[day] for day in sorted(days)], [2, 2, 1])
        zero = replace(unset, special_day_required_count=0)
        outcome = self._solve(_month(2, 2027, people, [zero]))
        counts = Counter(duty[2] for duty in outcome.assignments)
        self.assertEqual([counts[day] for day in sorted(days)], [0, 0, 0])
        three = replace(unset, special_day_required_count=3)
        outcome = self._solve(_month(2, 2027, people, [three]))
        counts = Counter(duty[2] for duty in outcome.assignments)
        self.assertEqual([counts[day] for day in sorted(days)], [3, 3, 3])
        _row("special day on Sat/Sun/Wed, special slot unset", "weekday counts 2/2/1 apply", True)
        _row("special slot 0 / 3", "0/0/0 and 3/3/3", True)

    def test_shift_hours_zero_and_twenty_four(self) -> None:
        """Zero-hour and day-long duties solve and stay balanced."""
        rows = []
        for hours in ((0.0, 0.0), (24.0, 24.0), (0.0, 24.0)):
            instance = symmetric_instance(6, 2, recovery=1)
            instance = replace(
                instance,
                competences=[
                    replace(role, weekday_shift_hours=(value,) * 7, special_day_shift_hours=value)
                    for role, value in zip(instance.competences, hours)
                ],
            )
            outcome = self._solve(instance, 20)
            self.assertEqual(outcome.status, "ok")
            measured = metrics(instance, outcome.assignments)
            rows.append((hours, measured.load_spread, measured.hours_spread, outcome.hit_budget))
            if not outcome.hit_budget and hours[0] == hours[1]:
                self.assertLessEqual(measured.load_spread, 1)
        _METRICS["hours_rows"] = rows
        _row("shift hours 0 / 24 / mixed 0+24", f"ok; (hours, load spread, hours spread, hit) {rows}", True)

    # --- Rules at their extremes -------------------------------------------------------------

    def test_strict_maximum_of_one(self) -> None:
        """28 people capped at one duty staff February exactly; 27 cannot and the error says why."""
        policy = policy_from_settings({MAX_SHIFTS: (True, 1000.0)})
        enough = _month(2, 2027, [_person(user_id, max_shifts_per_month=1) for user_id in range(1, 29)], [_role()], policy=policy)
        outcome = self._solve(enough, 20)
        self.assertEqual(outcome.status, "ok")
        self.assertEqual(Counter(duty[0] for duty in outcome.assignments), Counter({user_id: 1 for user_id in range(1, 29)}))
        short = _month(2, 2027, [_person(user_id, max_shifts_per_month=1) for user_id in range(1, 28)], [_role()], policy=policy)
        outcome = self._solve(short, 20)
        self.assertEqual(outcome.status, "infeasible")
        self.assertEqual(outcome.issues, [{"code": "constraint_conflict", "tightened_constraints": [MAX_SHIFTS]}])
        _row("max_shifts 1 strict, 28 people", "one duty each", True)
        _row("max_shifts 1 strict, 27 people", "constraint_conflict naming max_shifts", True)

    def test_extreme_weights(self) -> None:
        """Every rule penalized at 100000, or at 0.5, on planted small months: valid rosters."""
        codes = (UNAVAILABLE, VACATION, BUSINESS_TRIP, REST, MAX_SHIFTS, OVERSTAFF, SOFT_DECLINE)
        instances = []
        seeds = range(10) if STRESS else range(3)
        for weight in (100000.0, 0.5):
            settings = {code: (False, weight) for code in codes}
            settings.update({BALANCE: (False, weight), PREFERRED: (False, weight), SPREAD: (False, weight)})
            for seed in seeds:
                knobs = replace(sample_knobs(random.Random(seed), "small", planted=True), policy=settings, witness_keeps_rest=True)
                instances.append(make_instance(seed, knobs))
        outcomes = solve_in_parallel(instances, BUDGET, workers=WORKERS, observe=True)
        statuses = Counter()
        for instance, outcome in zip(instances, outcomes):
            statuses[(instance.effective_policy.weight(BALANCE), outcome.status)] += 1
            self.assertIn(outcome.status, ("ok", "timeout"), instance.label)
            if outcome.status == "ok":
                self.assertEqual(validate(instance, outcome.assignments), [], instance.label)
        _METRICS["extreme_weights"] = {f"{k[0]:g}:{k[1]}": v for k, v in statuses.items()}
        _row("all weights 100000 / all weights 0.5 (planted small)", f"{dict(_METRICS['extreme_weights'])}", True)

    def test_employee_qualified_for_nothing_and_working_elsewhere_every_day(self) -> None:
        """Neither gets a duty; alone, the second makes the month infeasible."""
        everywhere = frozenset(date(2027, 1, 25) + timedelta(days=offset) for offset in range(42))
        people = [_person(1, ()), _person(2, externally_scheduled_dates=everywhere)] + [_person(user_id) for user_id in range(3, 6)]
        outcome = self._solve(_month(2, 2027, people, [_role()]))
        self.assertEqual(outcome.status, "ok")
        self.assertFalse([duty for duty in outcome.assignments if duty[0] in (1, 2)])
        alone = self._solve(_month(2, 2027, [_person(2, externally_scheduled_dates=everywhere)], [_role(recovery=0)]))
        self.assertEqual(alone.status, "infeasible")
        self.assertIn("insufficient_qualified_staff", alone.issue_codes)
        _row("employee qualified for nothing", "no duty, others staff the month", True)
        _row("external commitment every day", "no duty; alone -> insufficient_qualified_staff", True)

    @unittest.expectedFailure
    def test_one_second_budget_ends_about_on_time(self) -> None:
        """Suspected weakness: a 1 s budget on an xl month takes several times as long.

        README: the solver "overruns its budget by about 1 s". Here an
        80-person, 8-role month with a 1 s budget took 6-7.4 s on a quiet
        machine (13-21 s with another CBC-heavy job running): building the
        model (0.8-1.6 s) is not counted, and CBC overran its own 1 s limit
        by 2-6 s before giving up with no roster. The outcome is clean
        (``solver_timeout``); only the time is not.
        """
        knobs = replace(sample_knobs(random.Random(5), "xl", planted=True), target_utilization=0.9)
        outcome = run_solver(make_instance(5, knobs), 1)
        self.assertIn(outcome.status, ("ok", "timeout"))
        self.assertLessEqual(outcome.seconds, 1 + 1.5)

    def test_one_second_budget_on_a_large_month(self) -> None:
        """A valid roster or a clean solver_timeout -- never anything else; wall time is recorded."""
        seeds = range(6) if STRESS else range(2)
        sizes = ("large", "xl") if STRESS else ("large",)
        instances = []
        for size in sizes:
            for seed in seeds:
                knobs = replace(sample_knobs(random.Random(seed), size, planted=True), target_utilization=0.9)
                instances.append(make_instance(seed, knobs))
        outcomes = solve_in_parallel(instances, 1, workers=min(WORKERS, 3), observe=True)
        rows = []
        for instance, outcome in zip(instances, outcomes):
            rows.append([instance.label[:40], len(instance.employees), outcome.status, round(outcome.seconds, 1), outcome.hit_budget])
            self.assertIn(outcome.status, ("ok", "timeout"), outcome.error)
            if outcome.status == "ok":
                self.assertEqual(validate(instance, outcome.assignments), [], instance.label)
            else:
                self.assertEqual(outcome.issues, [{"code": "solver_timeout", "time_limit_seconds": 1}])
        _METRICS["one_second_rows"] = rows
        statuses = Counter(row[2] for row in rows)
        _row("1 s budget on large/xl months", f"{dict(statuses)}; wall {min(r[3] for r in rows)}-{max(r[3] for r in rows)} s", True)


if __name__ == "__main__":
    unittest.main()
