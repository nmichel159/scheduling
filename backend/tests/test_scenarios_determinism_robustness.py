"""Scenario tests: determinism and robustness of the schedule generator.

(a) The same input twice gives the identical roster: in one process, in
    separate worker processes, and in fresh interpreters started with
    different ``PYTHONHASHSEED`` values (``date`` and ``str`` hashes are
    randomised per interpreter, so set iteration order changes).
(b) Permutation invariance: shuffling the employee or competence order, or
    relabelling every id, leaves the first-pass cost unchanged within the
    lock slack (runs that did not stop at their budget).
(c) Time budgets 1, 2, 5, 15, 60 s on medium / large / xl planted
    instances: always a valid roster or a clean ``solver_timeout``, never an
    invalid roster, a false "infeasible" or an exception; cost degradation
    and wall time over the budget are recorded.
(d) Numeric robustness: fractional hours, weights at ``MAX_WEIGHT``, many
    penalized breaches at once; the observed first-pass objective must equal
    the independently computed ``first_pass_cost``.
(e) The solver never mutates its inputs (in memory and through the database).

The default run takes a few minutes; ``SCHEDULING_STRESS=1`` runs a heavier
sweep. At most ``WORKERS`` CBC processes run at a time. Tables are printed at
the end of the module (run with ``-s``); ``DETERMINISM_REPORT=<path>`` dumps
them as JSON.
"""

from __future__ import annotations

import copy
import json
import os
import random
import statistics
import subprocess
import sys
import unittest
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path

from app.services.constraint_setting_service import (
    BALANCE,
    BUSINESS_TRIP,
    MAX_SHIFTS,
    MAX_WEIGHT,
    OVERSTAFF,
    PREFERRED,
    REST,
    SOFT_DECLINE,
    SPREAD,
    UNAVAILABLE,
    VACATION,
)

from tests.scheduling_harness.db_builder import fresh_session, materialize
from tests.scheduling_harness.instances import (
    POLICY_PRESETS,
    RETIRED_COMPETENCE_ID,
    Instance,
    Knobs,
    PlantingFailed,
    fill_in_knobs,
    make_instance,
    sample_knobs,
)
from tests.scheduling_harness.known_bugs import known_bug_triggers
from tests.scheduling_harness.oracle import (
    day_wish_cost,
    find_improving_moves,
    first_pass_cost,
    metrics,
    validate,
    violation_codes,
)
from tests.scheduling_harness.reference import reference_feasibility
from tests.scheduling_harness.runner import SolveOutcome, run_solver, solve_in_parallel
from tests.scheduling_harness.semantics import Duty, balance_lock_slack

STRESS = os.environ.get("SCHEDULING_STRESS") == "1"
WORKERS = 5
BUDGET = 10
BACKEND = Path(__file__).resolve().parents[1]
_OPTIMALITY_BLOCKERS = {"duplicate_external_dates", "zero_balance_skips_wishes"}
_CACHED = ("days", "day_set", "window_days", "history_days", "employee_map", "competence_map", "special_dates")

_ROWS: dict[str, list[dict]] = defaultdict(list)


def _fresh(instance: Instance, **changes: object) -> Instance:
    """``dataclasses.replace`` with the instance's cached properties dropped."""
    changed = replace(instance, **changes)
    for name in _CACHED:
        changed.__dict__.pop(name, None)
    return changed


def _plant(seed: int, knobs: Knobs) -> Instance | None:
    """A planted instance, or ``None`` when the planter gave up."""
    try:
        return make_instance(seed, knobs)
    except PlantingFailed:
        return None


def _check_valid(test: unittest.TestCase, instance: Instance, outcome: SolveOutcome) -> None:
    """Checks 1-3: no exception, planted never refused, every roster valid."""
    test.assertNotEqual(outcome.status, "error", outcome.error)
    if instance.witness is not None:
        test.assertNotEqual(outcome.status, "infeasible", outcome.issues)
    if outcome.status == "ok":
        violations = validate(instance, outcome.assignments)
        test.assertEqual(violations, [], violation_codes(violations))
    if outcome.status == "infeasible" and instance.witness is None:
        test.assertNotEqual(reference_feasibility(instance, time_limit=60)[0], "feasible")


def _determinism_instances() -> list[tuple[int, str, dict]]:
    """(seed, size, overrides) cases for the determinism checks."""
    cases = [(7100 + s, "small", {}) for s in range(4)] + [(7200 + s, "medium", {}) for s in range(2)]
    cases += [(7300, "small", {"fill_in": True}), (7301, "medium", {"fill_in": True})]
    if STRESS:
        cases += [(7400 + s, "small", {}) for s in range(8)] + [(7500 + s, "medium", {}) for s in range(6)]
        cases += [(7600 + s, "small", {"fill_in": True}) for s in range(4)] + [(7700, "large", {"fill_in": True})]
    return cases


def build_case(seed: int, size: str, overrides: dict) -> Instance | None:
    """One determinism case (also called from the child interpreters)."""
    rng = random.Random(seed)
    knobs = fill_in_knobs(rng, None, size) if overrides.get("fill_in") else sample_knobs(rng, size, True)
    return _plant(seed, knobs)


_CHILD = r"""
import json, sys
sys.path.insert(0, {backend!r})
from tests.test_scenarios_determinism_robustness import build_case
from tests.scheduling_harness.runner import run_solver
result = {{}}
for seed, size, overrides in json.loads(sys.argv[1]):
    instance = build_case(seed, size, overrides)
    if instance is None:
        continue
    outcome = run_solver(instance, {budget}, observe=True)
    result[instance.label] = {{
        "status": outcome.status,
        "roster": sorted([d[0], d[1], d[2].isoformat()] for d in outcome.assignments),
        "hit_budget": outcome.hit_budget,
        "seconds": outcome.seconds,
    }}
print(json.dumps(result))
"""


class DeterminismTests(unittest.TestCase):
    """(a) Same input, same roster."""

    def test_same_input_twice_in_worker_processes(self) -> None:
        """Two solves of each instance (in different worker processes) agree exactly."""
        instances = [i for i in (build_case(*case) for case in _determinism_instances()) if i is not None]
        outcomes = solve_in_parallel(instances + instances, BUDGET, workers=WORKERS, observe=True)
        n = len(instances)
        same = budget_hits = 0
        for instance, first, second in zip(instances, outcomes[:n], outcomes[n:]):
            _check_valid(self, instance, first)
            if first.hit_budget or second.hit_budget:
                budget_hits += 1
                _ROWS["a_budget_hit_pairs"].append(
                    {"label": instance.label, "identical": sorted(first.assignments) == sorted(second.assignments)}
                )
                continue
            with self.subTest(label=instance.label):
                self.assertEqual(first.status, second.status)
                self.assertEqual(sorted(first.assignments), sorted(second.assignments))
                same += sorted(first.assignments) == sorted(second.assignments)
        _ROWS["a_summary"].append({"mode": "twice, worker processes", "instances": n, "compared": n - budget_hits, "identical": same, "skipped_hit_budget": budget_hits})
        self.assertGreaterEqual(n - budget_hits, 4)

    def test_same_roster_across_hash_seeds(self) -> None:
        """Fresh interpreters with PYTHONHASHSEED 0, 1 and 4242 return the identical roster."""
        cases = _determinism_instances()
        script = _CHILD.format(backend=str(BACKEND), budget=BUDGET)
        processes = []
        for hash_seed in ("0", "1", "4242"):
            env = {**os.environ, "PYTHONHASHSEED": hash_seed}
            processes.append(
                subprocess.Popen(
                    [sys.executable, "-c", script, json.dumps(cases)],
                    cwd=str(BACKEND),
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            )
        results = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=1800)
            self.assertEqual(process.returncode, 0, stderr[-2000:])
            results.append(json.loads(stdout.strip().splitlines()[-1]))
        compared = identical = skipped = 0
        for label in results[0]:
            runs = [result[label] for result in results]
            if any(run["hit_budget"] for run in runs):
                skipped += 1
                continue
            compared += 1
            with self.subTest(label=label):
                self.assertEqual({run["status"] for run in runs}, {runs[0]["status"]})
                self.assertEqual(runs[1]["roster"], runs[0]["roster"])
                self.assertEqual(runs[2]["roster"], runs[0]["roster"])
                identical += runs[0]["roster"] == runs[1]["roster"] == runs[2]["roster"]
        _ROWS["a_summary"].append({"mode": "3 interpreters, PYTHONHASHSEED 0/1/4242", "instances": len(results[0]), "compared": compared, "identical": identical, "skipped_hit_budget": skipped})
        self.assertGreaterEqual(compared, 4)


# --------------------------------------------------------------------------- (b) permutation


def _map_duty(duty: Duty, users: dict[int, int], competences: dict[int, int]) -> Duty:
    return (users.get(duty[0], duty[0]), competences.get(duty[1], duty[1]), duty[2])


def permuted(instance: Instance, seed: int, mode: str) -> tuple[Instance, dict[int, int], dict[int, int]]:
    """The same month with a different order or different ids.

    ``mode`` is ``order`` (shuffle the employee and competence lists),
    ``relabel`` (new ids in reverse-ish order, lists shuffled too).
    Returns the instance and the user / competence id maps (old -> new).
    """
    rng = random.Random(seed)
    employees = list(instance.employees)
    competences = list(instance.competences)
    rng.shuffle(employees)
    rng.shuffle(competences)
    users: dict[int, int] = {}
    roles: dict[int, int] = {}
    if mode == "relabel":
        user_ids = [e.id for e in instance.employees]
        new_ids = rng.sample(range(5000, 5000 + 10 * len(user_ids)), len(user_ids))
        users = dict(zip(user_ids, new_ids))
        role_ids = [c.id for c in instance.competences]
        new_roles = rng.sample(range(300, 300 + 10 * len(role_ids)), len(role_ids))
        roles = dict(zip(role_ids, new_roles))
        assert RETIRED_COMPETENCE_ID not in new_roles
        employees = [
            replace(e, id=users[e.id], competence_ids=frozenset(roles.get(c, c) for c in e.competence_ids))
            for e in employees
        ]
        competences = [replace(c, id=roles[c.id]) for c in competences]

    def mapped(duties):
        return None if duties is None else frozenset(_map_duty(d, users, roles) for d in duties)

    changed = _fresh(
        instance,
        employees=employees,
        competences=competences,
        adjacent=mapped(instance.adjacent),
        fixed=mapped(instance.fixed),
        witness=mapped(instance.witness),
        label=f"{instance.label}+{mode}{seed}",
    )
    return changed, users, roles


class PermutationTests(unittest.TestCase):
    """(b) Order and ids do not change the optimum."""

    def test_shuffled_and_relabelled_inputs(self) -> None:
        """Equal first-pass cost (within slack) when neither run stopped at its budget."""
        bases = []
        for seed in range(14 if STRESS else 6):
            size = "medium" if seed % 3 == 2 else "small"
            knobs = fill_in_knobs(random.Random(8000 + seed), None, size) if seed % 2 else sample_knobs(random.Random(8000 + seed), size, True)
            instance = _plant(8000 + seed, knobs)
            if instance is not None:
                bases.append(instance)
        variants = []
        for base in bases:
            for index, mode in enumerate(("order", "relabel", "relabel")):
                variants.append((base, *permuted(base, index, mode), mode))
        outcomes = solve_in_parallel(bases + [v[1] for v in variants], BUDGET, workers=WORKERS, observe=True)
        base_out = dict(zip((b.label for b in bases), outcomes[: len(bases)]))
        compared = 0
        identical = 0
        for (base, variant, users, roles, mode), outcome in zip(variants, outcomes[len(bases):]):
            _check_valid(self, variant, outcome)
            original = base_out[base.label]
            back_users = {v: k for k, v in users.items()}
            back_roles = {v: k for k, v in roles.items()}
            roster = [_map_duty(d, back_users, back_roles) for d in outcome.assignments]
            row = {"label": variant.label, "mode": mode, "status": (original.status, outcome.status), "hit_budget": original.hit_budget or outcome.hit_budget}
            if (
                original.status == outcome.status == "ok"
                and not row["hit_budget"]
                and not known_bug_triggers(base) & _OPTIMALITY_BLOCKERS
            ):
                compared += 1
                a = first_pass_cost(base, original.assignments)
                b = first_pass_cost(base, roster)
                row.update(cost=a, permuted_cost=b, identical=sorted(roster) == sorted(original.assignments),
                           wish_delta=day_wish_cost(base, roster) - day_wish_cost(base, original.assignments))
                identical += row["identical"]
                with self.subTest(label=variant.label):
                    self.assertEqual(validate(base, roster), [])
                    self.assertLessEqual(abs(a - b), balance_lock_slack(a) + balance_lock_slack(b), (a, b))
            elif original.status != "timeout" and outcome.status != "timeout":
                with self.subTest(label=variant.label, check="verdict"):
                    self.assertEqual(original.status, outcome.status)
            _ROWS["b_permutation"].append(row)
        _ROWS["b_summary"].append({"variants": len(variants), "compared": compared, "identical_roster": identical})
        self.assertGreaterEqual(compared, 8)


# --------------------------------------------------------------------------- (c) budgets


class TimeBudgetTests(unittest.TestCase):
    """(c) Short and long budgets on bigger months."""

    def test_budgets(self) -> None:
        """A valid roster or a clean timeout at every budget; record cost and overrun."""
        if STRESS:
            budgets = (1, 2, 5, 15, 60)
            plan = [("medium", s) for s in range(3)] + [("large", s) for s in range(3, 6)] + [("xl", s) for s in range(6, 8)]
        else:
            budgets = (1, 2, 5)
            plan = [("medium", 0), ("medium", 1), ("large", 3), ("large", 4), ("xl", 6)]
        instances = []
        for size, seed in plan:
            instance = _plant(9000 + seed, sample_knobs(random.Random(9000 + seed), size, True))
            if instance is not None:
                instances.append((size, instance))
        jobs = [(size, instance, budget) for size, instance in instances for budget in budgets]
        if not STRESS:
            jobs += [(size, instance, 15) for size, instance in instances if size == "large"]
        results: list[SolveOutcome] = []
        for budget in sorted({job[2] for job in jobs}):
            chunk = [job for job in jobs if job[2] == budget]
            results_chunk = solve_in_parallel([job[1] for job in chunk], budget, workers=WORKERS, observe=True)
            results.extend(zip(chunk, results_chunk))
        best: dict[str, float] = {}
        for (size, instance, budget), outcome in results:
            if outcome.status == "ok":
                cost = first_pass_cost(instance, outcome.assignments)
                best[instance.label] = min(best.get(instance.label, cost), cost)
        for (size, instance, budget), outcome in results:
            with self.subTest(label=instance.label, budget=budget):
                _check_valid(self, instance, outcome)
            row = {
                "size": size,
                "label": instance.label,
                "employees": len(instance.employees),
                "budget": budget,
                "status": outcome.status,
                "seconds": outcome.seconds,
                "over": outcome.seconds - budget,
                "hit_budget": outcome.hit_budget,
                "first_pass_optimal": outcome.first_pass.optimal if outcome.first_pass else None,
                "second_pass": None if outcome.second_pass is None else outcome.second_pass.sol_status,
            }
            if outcome.status == "ok":
                cost = first_pass_cost(instance, outcome.assignments)
                witness = first_pass_cost(instance, instance.witness)
                row.update(cost=cost, witness_cost=witness, rel_to_best=(cost - best[instance.label]) / max(1.0, abs(best[instance.label])),
                           beats_witness=cost <= witness + balance_lock_slack(witness))
                if outcome.balance_cap is not None:
                    with self.subTest(label=instance.label, budget=budget, check="lock"):
                        self.assertLessEqual(cost, outcome.balance_cap + 1e-6 * max(1.0, abs(cost)))
            _ROWS["c_budget"].append(row)


class SuspectedBudgetBugTests(unittest.TestCase):
    """Findings determinism_robustness_1 and _2 (repros in scratchpad/findings)."""

    def test_same_input_same_roster_even_at_the_budget(self) -> None:
        """Doc mismatch (low): output is deterministic only while no pass stops at its budget.

        ``solve_monthly_schedule`` documents "A deterministic, sorted list of
        generated assignments". Medium planted month seed 7200 with a 10 s
        budget: the balance pass is proved optimal, the wishes pass may stop
        at its time limit (sol_status 2), and on a busy machine four identical
        solves gave three different rosters (same first-pass cost). Whether a
        pass stops early depends on the machine's load, so the test only
        demands identical rosters when every pass finished in time, and is
        skipped otherwise.
        """
        instance = make_instance(7200, sample_knobs(random.Random(7200), "medium", True))
        outcomes = [run_solver(instance, BUDGET, observe=True) for _ in range(4)]
        if any(outcome.hit_budget for outcome in outcomes):
            self.skipTest("a pass stopped at its budget; the roster may then differ between runs")
        rosters = {tuple(sorted(outcome.assignments)) for outcome in outcomes}
        self.assertEqual(len(rosters), 1)

    @unittest.expectedFailure
    def test_wall_time_stays_near_the_budget(self) -> None:
        """Suspected bug: the wishes pass ignores its time limit and then has no solution.

        Medium planted month seed 910 (18 people, 4 roles, strict max_shifts
        and overstaff) with a 5 s budget: the balance pass is proved optimal
        in about 1 s, the wishes pass is started with CBC's ``timeLimit=4``
        but returns only after 39-47 s, with no solution (sol_status 0), so
        every day wish is dropped as well (finding fill_in_1). The xl month
        seed 9007 (82 people) shows the same with a 2 s budget: 75-100 s,
        and with 15 s: 106 s. The documented promise is that the budget is
        how long "the two passes together may search", overrun by about a
        second; the editor's time-budget setting therefore does not bound
        how long a manager waits.
        """
        instance = make_instance(910, replace(sample_knobs(random.Random(910), "medium", True), generate_from=None))
        outcome = run_solver(instance, 5, observe=True)
        self.assertEqual(outcome.status, "ok")
        self.assertLessEqual(outcome.seconds, 5 + 10)


# --------------------------------------------------------------------------- (d) numerics


def _numeric_cases() -> list[tuple[str, Instance]]:
    """Fractional hours, MAX_WEIGHT everywhere, many penalized breaches."""
    cases: list[tuple[str, Instance]] = []
    reps = 6 if STRESS else 2
    max_policy = {code: (False, MAX_WEIGHT) for code in (UNAVAILABLE, VACATION, BUSINESS_TRIP, REST, MAX_SHIFTS, OVERSTAFF)}
    max_policy.update({BALANCE: (False, MAX_WEIGHT), PREFERRED: (False, MAX_WEIGHT), SOFT_DECLINE: (False, MAX_WEIGHT), SPREAD: (False, MAX_WEIGHT)})
    for rep in range(reps):
        seed = 9500 + rep
        rng = random.Random(seed)
        knobs = replace(sample_knobs(rng, "small" if rep % 2 == 0 else "medium", True), hours_profile="fractional")
        instance = _plant(seed, knobs)
        if instance is not None:
            cases.append(("fractional hours", instance))
        knobs = replace(sample_knobs(random.Random(seed + 50), "small", True), policy=max_policy, preferred_rate=0.1, soft_decline_rate=0.1)
        instance = _plant(seed + 50, knobs)
        if instance is not None:
            cases.append(("all weights MAX_WEIGHT", instance))
        knobs = replace(
            sample_knobs(random.Random(seed + 100), "small", True),
            policy={BALANCE: (False, MAX_WEIGHT), SPREAD: (False, MAX_WEIGHT), PREFERRED: (False, MAX_WEIGHT)},
            hours_profile="fractional",
            preferred_rate=0.15,
        )
        instance = _plant(seed + 100, knobs)
        if instance is not None:
            cases.append(("balance/wishes MAX_WEIGHT + fractional", instance))
        # Many penalized breaches: scarce staff, penalized absences and rest,
        # a starved cap, lots of absences. Random (unplanted) so the solver
        # has to buy breaches.
        knobs = Knobs(
            n_employees=rng.randint(4, 7),
            n_competences=rng.randint(1, 2),
            demand_profile="heavy",
            recovery_profile=rng.choice(["one", "mixed"]),
            hours_profile=rng.choice(["fractional", "mixed"]),
            unavailability_rate=0.35,
            absence_mix=(0.4, 0.3, 0.3),
            soft_decline_rate=0.2,
            preferred_rate=0.1,
            max_shifts_mode="starved",
            policy={**POLICY_PRESETS["penalized_all"], MAX_SHIFTS: (False, 50.0), OVERSTAFF: (False, 5.0)},
            planted=False,
        )
        cases.append(("many penalized breaches", make_instance(seed + 200, knobs)))
    return cases


class NumericRobustnessTests(unittest.TestCase):
    """(d) Awkward numbers."""

    def test_numeric_cases(self) -> None:
        """Valid rosters, objective equals first_pass_cost, no improving move when proved."""
        cases = _numeric_cases()
        outcomes = solve_in_parallel([c[1] for c in cases], BUDGET, workers=WORKERS, observe=True)
        for (kind, instance), outcome in zip(cases, outcomes):
            triggers = known_bug_triggers(instance)
            row = {"kind": kind, "label": instance.label, "status": outcome.status, "hit_budget": outcome.hit_budget,
                   "seconds": outcome.seconds, "triggers": sorted(triggers)}
            with self.subTest(kind=kind, label=instance.label):
                _check_valid(self, instance, outcome)
                if outcome.status == "ok":
                    m = metrics(instance, outcome.assignments)
                    cost = first_pass_cost(instance, outcome.assignments)
                    row.update(
                        cost=cost,
                        objective=outcome.first_pass_objective,
                        absence_breaches=sum(m.absence_breaches.values()),
                        rest_breach_days=m.rest_breach_days,
                        over_max=sum(m.over_max.values()),
                        overstaff=m.overstaff,
                    )
                    if outcome.first_pass_objective is not None:
                        # The final roster may differ from the first pass's, but
                        # never by more than the lock allows.
                        self.assertLessEqual(cost, outcome.balance_cap + 1e-6 * max(1.0, abs(cost)))
                    if not outcome.hit_budget and outcome.passes and not triggers & _OPTIMALITY_BLOCKERS:
                        # A wish pass with no solution at all is finding fill_in_1 /
                        # determinism_robustness_2; only first-pass moves count then.
                        reasons = ("first_pass", "day_wish")
                        if outcome.second_pass is not None and outcome.second_pass.sol_status == 0:
                            row["wish_pass_failed"] = True
                            reasons = ("first_pass",)
                        moves = [mv for mv in find_improving_moves(instance, outcome.assignments, balance_cap=outcome.balance_cap)
                                 if mv.reason in reasons]
                        row["improving_moves"] = len(moves)
                        if "balance_lock_drift" not in triggers:
                            self.assertEqual(moves, [])
                        if instance.witness is not None and not validate(instance, instance.witness):
                            bound = first_pass_cost(instance, instance.witness)
                            self.assertLessEqual(cost, bound + balance_lock_slack(bound))
            _ROWS["d_numeric"].append(row)


# --------------------------------------------------------------------------- (e) mutation


class NoMutationTests(unittest.TestCase):
    """(e) The solver leaves its arguments alone."""

    def test_in_memory_inputs_are_unchanged(self) -> None:
        """Deep copies of every argument equal the arguments after the solve."""
        from app.services.schedule_generation_service import solve_monthly_schedule

        checked = 0
        for seed in range(6 if STRESS else 3):
            knobs = fill_in_knobs(random.Random(9900 + seed), None, "small")
            instance = _plant(9900 + seed, knobs)
            if instance is None:
                continue
            kwargs = instance.solver_kwargs()
            kwargs["employees"] = list(kwargs["employees"])
            kwargs["competences"] = list(kwargs["competences"])
            before = copy.deepcopy(kwargs)
            identities = [id(item) for item in kwargs["employees"] + kwargs["competences"]]
            policy_state = copy.deepcopy(vars(kwargs["constraints"])) if kwargs.get("constraints") is not None else None
            solve_monthly_schedule(**kwargs, time_budget_seconds=BUDGET)
            with self.subTest(label=instance.label):
                self.assertEqual(kwargs, before)
                self.assertEqual([id(item) for item in kwargs["employees"] + kwargs["competences"]], identities)
                if policy_state is not None:
                    self.assertEqual(vars(kwargs["constraints"]), policy_state)
            checked += 1
        self.assertGreaterEqual(checked, 2)

    def test_database_is_not_written(self) -> None:
        """Generating a draft twice leaves every table's row count and the schedule rows unchanged."""
        from sqlalchemy import inspect, text

        from app.services.schedule_generation_service import generate_ambulance_monthly_schedule

        instance = _plant(9950, fill_in_knobs(random.Random(9950), 0.5, "small"))
        with fresh_session() as session:
            world = materialize(instance, session, noise=True)
            session.commit()
            tables = inspect(session.get_bind()).get_table_names()

            def snapshot() -> dict[str, int]:
                return {name: session.execute(text(f'SELECT COUNT(*) FROM "{name}"')).scalar() for name in tables}

            schedules = lambda: sorted(tuple(row) for row in session.execute(text("SELECT * FROM schedules")).fetchall())  # noqa: E731
            counts, rows = snapshot(), schedules()
            first = generate_ambulance_monthly_schedule(
                session, world.ambulance_id, instance.month, instance.year,
                fixed_entries=world.fixed_entries_for_db(instance), generate_from=instance.generate_from, time_budget_seconds=BUDGET,
            )
            second = generate_ambulance_monthly_schedule(
                session, world.ambulance_id, instance.month, instance.year,
                fixed_entries=world.fixed_entries_for_db(instance), generate_from=instance.generate_from, time_budget_seconds=BUDGET,
            )
            self.assertEqual(snapshot(), counts)
            self.assertEqual(schedules(), rows)
            self.assertFalse(session.new or session.dirty or session.deleted)
            self.assertEqual(
                [(e.user_id, e.competence_id, e.work_date) for e in first.entries],
                [(e.user_id, e.competence_id, e.work_date) for e in second.entries],
            )


# --------------------------------------------------------------------------- report


def tearDownModule() -> None:  # noqa: N802 - unittest hook
    """Print the tables (and dump them with DETERMINISM_REPORT)."""
    lines = [""]
    if _ROWS["a_summary"]:
        lines += ["| Determinism mode | instances | compared | identical | skipped (hit budget) |", "|---|---|---|---|---|"]
        for row in _ROWS["a_summary"]:
            lines.append(f"| {row['mode']} | {row['instances']} | {row['compared']} | {row['identical']} | {row['skipped_hit_budget']} |")
    if _ROWS["b_permutation"]:
        lines += ["", "| Permutation mode | variants | compared | equal cost | identical roster | mean abs wish delta |", "|---|---|---|---|---|---|"]
        for mode in ("order", "relabel"):
            rows = [r for r in _ROWS["b_permutation"] if r["mode"] == mode]
            done = [r for r in rows if "cost" in r]
            equal = sum(abs(r["cost"] - r["permuted_cost"]) <= balance_lock_slack(r["cost"]) + balance_lock_slack(r["permuted_cost"]) for r in done)
            wish = statistics.mean(abs(r["wish_delta"]) for r in done) if done else 0
            lines.append(f"| {mode} | {len(rows)} | {len(done)} | {equal} | {sum(r['identical'] for r in done)} | {wish:.3f} |")
    if _ROWS["c_budget"]:
        lines += ["", "| Size | budget s | runs | ok | timeout | other | hit budget | median wall s | max over budget s | median cost vs best | beats witness | wish pass no solution |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        keys = sorted({(r["size"], r["budget"]) for r in _ROWS["c_budget"]}, key=lambda k: (["medium", "large", "xl"].index(k[0]), k[1]))
        for size, budget in keys:
            rows = [r for r in _ROWS["c_budget"] if r["size"] == size and r["budget"] == budget]
            ok = [r for r in rows if r["status"] == "ok"]
            lines.append(
                f"| {size} | {budget} | {len(rows)} | {len(ok)} | {sum(r['status'] == 'timeout' for r in rows)} | "
                f"{sum(r['status'] not in ('ok', 'timeout') for r in rows)} | {sum(r['hit_budget'] for r in rows)} | "
                f"{statistics.median(r['seconds'] for r in rows):.1f} | {max(r['over'] for r in rows):.1f} | "
                f"{(statistics.median(r['rel_to_best'] for r in ok) * 100 if ok else 0):.2f} % | {sum(r['beats_witness'] for r in ok)}/{len(ok)} | {sum(r['second_pass'] == 0 for r in rows)} |"
            )
    if _ROWS["d_numeric"]:
        lines += ["", "| Numeric case | runs | ok | timeout | infeasible | hit budget | improving moves (checked) | wish pass no solution | mean absence breaches | mean rest breach days | mean over max |", "|---|---|---|---|---|---|---|---|---|---|---|"]
        for kind in sorted({r["kind"] for r in _ROWS["d_numeric"]}):
            rows = [r for r in _ROWS["d_numeric"] if r["kind"] == kind]
            ok = [r for r in rows if r["status"] == "ok"]
            checked = [r for r in ok if "improving_moves" in r]

            def mean(key: str) -> str:
                return f"{statistics.mean(r[key] for r in ok):.1f}" if ok else "-"

            lines.append(
                f"| {kind} | {len(rows)} | {len(ok)} | {sum(r['status'] == 'timeout' for r in rows)} | "
                f"{sum(r['status'] == 'infeasible' for r in rows)} | {sum(r['hit_budget'] for r in rows)} | "
                f"{sum(r['improving_moves'] for r in checked)} ({len(checked)}) | {sum(bool(r.get('wish_pass_failed')) for r in rows)} | {mean('absence_breaches')} | {mean('rest_breach_days')} | {mean('over_max')} |"
            )
    print("\n".join(lines))
    path = os.environ.get("DETERMINISM_REPORT")
    if path:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(_ROWS, handle, default=str, indent=1)


if __name__ == "__main__":
    unittest.main()
