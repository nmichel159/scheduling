"""Optimality of the monthly schedule generator: not just valid, but good rosters.

Five angles, each judged with the independent harness:

(a) Exhaustive search. On >= 1,000 tiny instances (>= 2,000 under stress) (``tiny_knobs`` planted and
    random, ``ultra_tiny_knobs``) the solver's first-pass cost must equal the
    brute-force optimum within the balance-lock slack, and -- when it sits
    exactly at the optimum -- its day-wish cost must be within the documented
    slack of the best day-wish cost among optimal rosters. A random instance
    the solver calls infeasible must be one the exhaustive search finds
    infeasible too.
(b) Local search. On observed small and medium runs that did not hit their
    budget, ``find_improving_moves`` must find no ``first_pass`` and no
    ``day_wish`` move; ``lock_drift`` moves are the known bug and tallied.
(c) Fairness. On ``symmetric_instance`` (identical people, one per role per
    day) the load spread is at most one duty; with too few people for the
    rest rule the month is reported infeasible; near-symmetric variants
    (shift preferences, one absent person, one capped person) keep the others
    within one duty.
(d) Spread. An exact re-implementation of the second pass's spread term
    (verified against the observed second-pass objective) gives gap
    histograms, how often duties sit at the tightest allowed gap, and how
    often an equally balanced roster with wider gaps is one swap away.
(e) Planted. The solver's first-pass cost against the hidden witness's.

Default mode runs in a few minutes; ``SCHEDULING_STRESS=1`` widens every
sweep. ``OPTIMALITY_METRICS=<path>`` writes the measured numbers as JSON.
"""

from __future__ import annotations

import json
import os
import random
import statistics
import unittest
from bisect import bisect_left
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from datetime import date, timedelta
from time import perf_counter
from typing import Any, Callable, Iterable

from app.services.constraint_setting_service import (
    MAX_SHIFTS,
    REST,
    SPREAD,
    UNAVAILABLE,
    policy_from_settings,
)

from tests.scheduling_harness.instances import (
    Instance,
    PlantingFailed,
    make_instance,
    sample_knobs,
    symmetric_instance,
    tiny_knobs,
    ultra_tiny_knobs,
)
from tests.scheduling_harness.known_bugs import known_bug_triggers
from tests.scheduling_harness.oracle import (
    day_wish_cost,
    eligible,
    eligible_slots,
    find_improving_moves,
    first_pass_cost,
    metrics,
    validate,
    violation_codes,
)
from tests.scheduling_harness.reference import brute_force, reference_feasibility
from tests.scheduling_harness.runner import SolveOutcome, run_solver, solve_in_parallel
from tests.scheduling_harness.semantics import Duty, balance_lock_slack

STRESS = os.environ.get("SCHEDULING_STRESS") == "1"
#: One other agent shares the machine: never more than six CBC processes.
WORKERS = 6
#: Brute-force node limit per tiny instance.
NODE_LIMIT = 200_000 if STRESS else 50_000
#: The spread term looks this many days ahead (``SPREAD_HORIZON_DAYS``).
SPREAD_HORIZON = 7

_METRICS: dict[str, Any] = {}


def _record(key: str, value: Any) -> None:
    """Keep one measured number (or table) for the JSON report."""
    _METRICS[key] = value


def tearDownModule() -> None:
    """Write the measured numbers when ``OPTIMALITY_METRICS`` names a file."""
    path = os.environ.get("OPTIMALITY_METRICS")
    if path:
        existing: dict[str, Any] = {}
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as handle:
                    existing = json.load(handle)
            except (OSError, ValueError):
                existing = {}
        existing.update(_METRICS)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(existing, handle, default=str, indent=1)


def _map(function: Callable[[Any], Any], jobs: list[Any]) -> list[Any]:
    """Run jobs in at most ``WORKERS`` processes, results in input order."""
    if len(jobs) <= 1:
        return [function(job) for job in jobs]
    with ProcessPoolExecutor(max_workers=WORKERS) as pool:
        return list(pool.map(function, jobs, chunksize=4))


def _quantiles(values: list[float]) -> dict[str, float]:
    """Median, p90 and max of a list (zeros when empty)."""
    if not values:
        return {"n": 0, "median": 0.0, "p90": 0.0, "max": 0.0}
    ordered = sorted(values)
    return {
        "n": len(ordered),
        "median": round(statistics.median(ordered), 4),
        "p90": round(ordered[min(len(ordered) - 1, int(0.9 * len(ordered)))], 4),
        "max": round(ordered[-1], 4),
    }


# --- (a) Tiny instances against the exhaustive search --------------------------------


def _second_pass_empty(outcome: SolveOutcome) -> bool:
    """Whether the wish pass ran out of time without any roster (status 0).

    The solver then restores the first pass's roster, so every day wish is
    left to chance. ``SolveOutcome.hit_budget`` only counts passes stopped
    with an incumbent (status 2), so this is tallied on its own.
    """
    second = outcome.second_pass
    return second is not None and second.sol_status == 0


def _tiny_job(job: tuple[str, int, bool]) -> dict[str, Any]:
    """Solve one tiny instance and search it exhaustively (worker body)."""
    kind, seed, planted = job
    sampler = tiny_knobs if kind == "tiny" else ultra_tiny_knobs
    record: dict[str, Any] = {"kind": kind, "seed": seed, "planted": planted}
    try:
        instance = make_instance(seed, sampler(random.Random(seed), planted))
    except PlantingFailed:
        record["skipped"] = "planting_failed"
        return record
    record["label"] = instance.label
    record["triggers"] = sorted(known_bug_triggers(instance))
    outcome = run_solver(instance, 5, observe=True)
    record.update(
        status=outcome.status,
        error=outcome.error,
        seconds=round(outcome.seconds, 3),
        hit_budget=outcome.hit_budget,
        second_pass_ran=outcome.second_pass is not None,
        second_pass_empty=_second_pass_empty(outcome),
        issue_codes=sorted(outcome.issue_codes),
    )
    if outcome.status == "ok":
        record["violations"] = sorted(violation_codes(validate(instance, outcome.assignments)))
        record["cost"] = first_pass_cost(instance, outcome.assignments)
        record["wish"] = day_wish_cost(instance, outcome.assignments)
        record["first_pass_objective"] = outcome.first_pass_objective
    if instance.witness is not None:
        record["witness_cost"] = first_pass_cost(instance, instance.witness)
    started = perf_counter()
    exhaustive = brute_force(instance, node_limit=NODE_LIMIT)
    record["bf_seconds"] = round(perf_counter() - started, 3)
    record.update(
        bf_complete=exhaustive.complete,
        bf_feasible=exhaustive.feasible,
        bf_cost=exhaustive.best_cost,
        bf_wish=exhaustive.best_wish,
        bf_slack=exhaustive.wish_slack,
        bf_nodes=exhaustive.nodes,
    )
    if outcome.status == "infeasible" and not exhaustive.complete:
        record["reference"] = reference_feasibility(instance, time_limit=30)[0]
    return record


def _tiny_jobs() -> list[tuple[str, int, bool]]:
    """The tiny and ultra-tiny seeds of this run."""
    tiny_seeds = range(1100) if STRESS else range(460)
    ultra_seeds = range(300) if STRESS else range(130)
    jobs = [("tiny", seed, planted) for seed in tiny_seeds for planted in (True, False)]
    jobs += [("ultra", seed, planted) for seed in ultra_seeds for planted in (True, False)]
    return jobs


class ExhaustiveSearchTests(unittest.TestCase):
    """(a) The solver against the brute-force optimum on tiny instances."""

    def test_tiny_rosters_match_the_exhaustive_optimum(self) -> None:
        """First-pass cost equals the optimum; day wishes are within the slack."""
        records = _map(_tiny_job, _tiny_jobs())
        tally: Counter[str] = Counter()
        problems: list[str] = []
        gaps: list[float] = []
        wish_gaps: list[float] = []
        per_kind: dict[str, Counter[str]] = {}
        for record in records:
            kind_tally = per_kind.setdefault(
                f"{record['kind']}-{'planted' if record['planted'] else 'random'}", Counter()
            )
            if record.get("skipped"):
                tally["skipped_planting_failed"] += 1
                kind_tally["skipped"] += 1
                continue
            kind_tally["instances"] += 1
            tally["instances"] += 1
            for trigger in record["triggers"]:
                tally[f"trigger:{trigger}"] += 1
            status = record["status"]
            tally[f"status:{status}"] += 1
            kind_tally[f"status:{status}"] += 1
            where = f"{record['kind']} seed={record['seed']} planted={record['planted']}"
            if status == "error":
                problems.append(f"{where}: solver error {record['error']}")
                continue
            if status == "timeout":
                tally["timeout"] += 1
                continue
            if record["planted"] and status != "ok":
                problems.append(f"{where}: planted instance reported {status} {record['issue_codes']}")
                continue
            if not record["bf_complete"]:
                tally["bf_incomplete"] += 1
                kind_tally["bf_incomplete"] += 1
            if status == "infeasible":
                if record["bf_complete"]:
                    if record["bf_feasible"]:
                        problems.append(f"{where}: solver infeasible, brute force found a roster")
                    else:
                        tally["infeasible_confirmed_bf"] += 1
                else:
                    verdict = record.get("reference")
                    tally[f"infeasible_reference_{verdict}"] += 1
                    if verdict == "feasible":
                        problems.append(f"{where}: solver infeasible, reference found a roster")
                continue
            if record["violations"]:
                problems.append(f"{where}: roster breaks {record['violations']}")
                continue
            if not record["bf_complete"]:
                continue
            if not record["bf_feasible"]:
                problems.append(f"{where}: solver found a valid roster, brute force none")
                continue
            if record["hit_budget"]:
                tally["hit_budget"] += 1
                kind_tally["hit_budget"] += 1
                continue
            if record["second_pass_empty"]:
                tally["second_pass_empty"] += 1
            tally["compared"] += 1
            kind_tally["compared"] += 1
            best = record["bf_cost"]
            gap = record["cost"] - best
            gaps.append(gap)
            if gap < -1e-6 * max(1.0, abs(best)):
                problems.append(f"{where}: solver cost {record['cost']} below brute-force optimum {best}")
            elif gap > balance_lock_slack(best) + 1e-9:
                problems.append(f"{where}: solver cost {record['cost']} above optimum {best}")
            elif gap > 1e-6:
                tally["lock_drift"] += 1
                kind_tally["lock_drift"] += 1
            else:
                tally["first_pass_optimal"] += 1
                kind_tally["first_pass_optimal"] += 1
                if "zero_balance_skips_wishes" in record["triggers"]:
                    tally["wish_skipped_known_bug"] += 1
                    continue
                if record["second_pass_empty"]:
                    continue
                wish_gap = record["wish"] - record["bf_wish"]
                wish_gaps.append(wish_gap)
                if wish_gap > record["bf_slack"] + 1e-9:
                    problems.append(
                        f"{where}: day-wish cost {record['wish']} vs best {record['bf_wish']}"
                        f" + slack {record['bf_slack']}"
                    )
                elif wish_gap > 1e-6:
                    tally["wish_within_slack_not_best"] += 1
                else:
                    tally["wish_best"] += 1
                    kind_tally["wish_best"] += 1
        _record("tiny_tally", dict(tally))
        _record("tiny_per_kind", {key: dict(value) for key, value in per_kind.items()})
        _record("tiny_cost_gap", _quantiles(gaps))
        _record("tiny_wish_gap", _quantiles(wish_gaps))
        _record(
            "tiny_solver_seconds",
            _quantiles([record["seconds"] for record in records if "seconds" in record]),
        )
        _record(
            "tiny_bf_seconds",
            _quantiles([record["bf_seconds"] for record in records if "bf_seconds" in record]),
        )
        _record(
            "tiny_bf_nodes",
            _quantiles([record["bf_nodes"] for record in records if "bf_nodes" in record]),
        )
        self.assertGreaterEqual(tally["instances"], 2000 if STRESS else 1000)
        self.assertFalse(problems, "\n".join(problems[:20]))


# --- (b) + (e) Local search and the planted witness ----------------------------------


def _move_job(job: tuple[str, int, float]) -> dict[str, Any]:
    """Solve one planted instance, observe it and look for improving moves."""
    size, seed, budget = job
    instance = make_instance(seed, sample_knobs(random.Random(seed), size, planted=True))
    outcome = run_solver(instance, budget, observe=True)
    record: dict[str, Any] = {
        "size": size,
        "seed": seed,
        "label": instance.label,
        "employees": len(instance.employees),
        "status": outcome.status,
        "error": outcome.error,
        "seconds": round(outcome.seconds, 2),
        "hit_budget": outcome.hit_budget,
        "triggers": sorted(known_bug_triggers(instance)),
        "witness_cost": first_pass_cost(instance, instance.witness or ()),
        "second_pass_empty": _second_pass_empty(outcome),
    }
    if outcome.status != "ok":
        return record
    violations = validate(instance, outcome.assignments)
    record["violations"] = sorted(violation_codes(violations))
    if violations:
        return record
    record["cost"] = first_pass_cost(instance, outcome.assignments)
    record["first_pass_objective"] = outcome.first_pass_objective
    record["balance_cap"] = outcome.balance_cap
    if outcome.hit_budget:
        return record
    moves = find_improving_moves(
        instance, outcome.assignments, max_checks=20000, balance_cap=outcome.balance_cap
    )
    record["moves"] = dict(Counter(move.reason for move in moves))
    record["move_examples"] = [
        (move.kind, move.removed, move.added, move.first_pass_delta, move.day_wish_delta, move.reason)
        for move in moves
        if move.reason in ("first_pass", "day_wish")
    ][:3]
    return record


class LocalSearchAndWitnessTests(unittest.TestCase):
    """(b) No improving move on optimal runs; (e) never worse than the witness."""

    def test_no_improving_moves_and_no_worse_than_witness(self) -> None:
        """Observed small/medium planted runs that finished in time."""
        small = range(400, 500) if STRESS else range(400, 424)
        medium = range(500, 530) if STRESS else range(500, 506)
        budgets = (10.0, 30.0) if STRESS else (8.0, 20.0)
        jobs = [("small", seed, budgets[0]) for seed in small] + [("medium", seed, budgets[1]) for seed in medium]
        records = _map(_move_job, jobs)
        problems: list[str] = []
        tally: dict[str, Counter[str]] = {"small": Counter(), "medium": Counter()}
        ratios: dict[str, list[float]] = {"small": [], "medium": []}
        for record in records:
            counts = tally[record["size"]]
            counts["instances"] += 1
            where = f"{record['size']} seed={record['seed']} {record['label']}"
            if record["status"] == "timeout":
                counts["timeout"] += 1
                continue
            if record["status"] != "ok":
                problems.append(f"{where}: planted instance reported {record['status']} {record['error']}")
                continue
            if record["violations"]:
                problems.append(f"{where}: roster breaks {record['violations']}")
                continue
            counts["ok_valid"] += 1
            if record["witness_cost"] > 0:
                ratios[record["size"]].append(record["cost"] / record["witness_cost"])
            if record["hit_budget"]:
                counts["hit_budget"] += 1
                continue
            counts["finished"] += 1
            if record["second_pass_empty"]:
                counts["second_pass_empty"] += 1
            if record["cost"] > record["witness_cost"] + balance_lock_slack(record["witness_cost"]):
                problems.append(f"{where}: cost {record['cost']} above witness {record['witness_cost']}")
            if record["cost"] > record["balance_cap"] + 1e-6:
                problems.append(f"{where}: final cost {record['cost']} above the lock {record['balance_cap']}")
            for reason, number in record["moves"].items():
                counts[f"moves:{reason}"] += number
                counts[f"runs_with:{reason}"] += 1
            judged = ("first_pass",) if record["second_pass_empty"] else ("first_pass", "day_wish")
            bad = {reason: number for reason, number in record["moves"].items() if reason in judged}
            if record["second_pass_empty"] and record["moves"].get("day_wish"):
                counts["day_wish_after_empty_second_pass"] += 1
            if bad:
                problems.append(f"{where}: improving moves {bad} e.g. {record['move_examples'][:1]}")
        _record("moves_tally", {size: dict(counts) for size, counts in tally.items()})
        _record("witness_ratio", {size: _quantiles(values) for size, values in ratios.items()})
        _record(
            "witness_ratio_better_share",
            {
                size: round(sum(value < 1 - 1e-9 for value in values) / max(1, len(values)), 3)
                for size, values in ratios.items()
            },
        )
        _record(
            "move_run_seconds",
            {size: _quantiles([r["seconds"] for r in records if r["size"] == size]) for size in tally},
        )
        self.assertFalse(problems, "\n".join(problems[:20]))


class WishPassTests(unittest.TestCase):
    """The second pass on a small month whose first pass is easy."""

    @unittest.expectedFailure
    def test_wish_pass_finds_a_roster_on_a_small_month(self) -> None:
        """Suspected weakness: the wish pass starts from nothing and can end with no roster.

        Planted small instance (9 people, 2 roles, no rest). The first pass is
        proved optimal in about a second; the wish pass gets the remaining
        ~9 s, ends with CBC status 0 (no incumbent) and the solver silently
        restores the first-pass roster, dropping every day wish. Single swaps
        with an identical first-pass cost gain a whole day wish (10) each.
        With 60 s the pass finds a roster but no better wish value, with
        180 s it reaches -70 against -20. The first-pass roster satisfies the
        balance lock, so handing it to CBC as a starting point would make
        "no roster" impossible. ``hit_budget`` is False (it counts status 2
        only), so this is reported as a second-pass timeout, not a lock miss.
        """
        instance = make_instance(421, sample_knobs(random.Random(421), "small", planted=True))
        outcome = run_solver(instance, 10, observe=True)
        self.assertEqual(outcome.status, "ok")
        self.assertTrue(outcome.first_pass.optimal)
        self.assertFalse(_second_pass_empty(outcome), "the wish pass returned no roster")
        moves = find_improving_moves(instance, outcome.assignments, balance_cap=outcome.balance_cap)
        self.assertFalse([move for move in moves if move.reason == "day_wish"])


# --- (c) Fairness on symmetric instances -------------------------------------------


def _symmetric_combos() -> list[tuple[int, int, int, float]]:
    """``(n, k, recovery, hours)`` combinations to solve."""
    every = [
        (n, k, recovery, hours)
        for n in range(2, 21)
        for k in range(1, 5)
        for recovery in range(0, 4)
        for hours in (4.0, 12.0)
    ]
    rng = random.Random(2026)
    if STRESS:
        feasible = [combo for combo in every if combo[0] >= combo[1] * (combo[2] + 1)]
        return sorted(rng.sample(feasible, 150))
    chosen = [
        (2, 1, 0, 4.0), (2, 1, 1, 12.0), (3, 1, 2, 4.0), (4, 1, 3, 12.0), (4, 2, 1, 4.0),
        (5, 2, 1, 12.0), (6, 2, 2, 4.0), (6, 3, 1, 4.0), (7, 1, 0, 12.0), (8, 4, 1, 4.0),
        (9, 3, 2, 12.0), (10, 2, 3, 4.0), (11, 1, 3, 4.0), (12, 4, 0, 12.0), (13, 3, 3, 4.0),
        (14, 2, 0, 4.0), (16, 4, 3, 12.0), (20, 1, 1, 4.0),
    ]
    return chosen


def _sym_job(job: tuple[int, int, int, float]) -> dict[str, Any]:
    """Solve one symmetric instance and measure its loads (worker body)."""
    n, k, recovery, hours = job
    instance = symmetric_instance(n, k, recovery=recovery, hours=hours)
    outcome = run_solver(instance, 20, observe=True)
    record: dict[str, Any] = {
        "combo": job,
        "status": outcome.status,
        "seconds": round(outcome.seconds, 2),
        "hit_budget": outcome.hit_budget,
        "issue_codes": sorted(outcome.issue_codes),
    }
    if outcome.status == "ok":
        record["violations"] = sorted(violation_codes(validate(instance, outcome.assignments)))
        measured = metrics(instance, outcome.assignments)
        record.update(
            load_spread=measured.load_spread,
            hours_spread=measured.hours_spread,
            surcharge_spread=measured.surcharge_spread,
            tight=measured.tightest_gaps,
            gaps=sum(measured.gap_histogram.values()),
        )
    return record


def _near_symmetric_instances() -> list[tuple[str, Instance]]:
    """Symmetric months with one deliberate asymmetry each."""
    cases: list[tuple[str, Instance]] = []
    for n, k, recovery in ((6, 1, 1), (9, 2, 1), (8, 2, 2)):
        base = symmetric_instance(n, k, recovery=recovery)
        tilted = [
            replace(employee, shift_preference=("surcharge", "standard", "any")[employee.id % 3])
            for employee in base.employees
        ]
        cases.append((f"preferences-{n}-{k}-{recovery}", replace(base, employees=tilted)))
        block = frozenset(base.days[3:13])
        absent = [
            replace(employee, unavailable_dates=block) if employee.id == 1 else employee
            for employee in base.employees
        ]
        cases.append((f"absent-{n}-{k}-{recovery}", replace(base, employees=absent)))
        capped = [
            replace(employee, max_shifts_per_month=3) if employee.id == 1 else employee
            for employee in base.employees
        ]
        cases.append((f"capped-{n}-{k}-{recovery}", replace(base, employees=capped)))
        cases.append(
            (
                f"capped-strict-{n}-{k}-{recovery}",
                replace(base, employees=capped, policy=policy_from_settings({MAX_SHIFTS: (True, 1000.0)})),
            )
        )
    return cases


class FairnessTests(unittest.TestCase):
    """(c) Identical people get the same load, give or take one duty."""

    def test_symmetric_months_are_balanced_within_one_duty(self) -> None:
        """``load_spread <= 1`` wherever the first pass was proved optimal."""
        combos = _symmetric_combos()
        records = _map(_sym_job, combos)
        problems: list[str] = []
        tally: Counter[str] = Counter()
        spreads: Counter[int] = Counter()
        for record in records:
            n, k, recovery, _hours = record["combo"]
            feasible = n >= k * (recovery + 1)
            tally["instances"] += 1
            if not feasible:
                tally["pigeonhole"] += 1
                if record["status"] != "infeasible":
                    problems.append(f"{record['combo']}: too few people, solver said {record['status']}")
                continue
            if record["status"] != "ok":
                problems.append(f"{record['combo']}: feasible month reported {record['status']}")
                continue
            if record["violations"]:
                problems.append(f"{record['combo']}: roster breaks {record['violations']}")
                continue
            spreads[record["load_spread"]] += 1
            if record["hit_budget"]:
                tally["hit_budget"] += 1
                tally[f"hit_budget_spread_{record['load_spread']}"] += 1
                continue
            tally["checked"] += 1
            if record["load_spread"] > 1:
                problems.append(f"{record['combo']}: load spread {record['load_spread']}")
            if record["surcharge_spread"] > 1:
                tally["surcharge_spread_over_1"] += 1
        _record("symmetric_tally", dict(tally))
        _record("symmetric_load_spread_histogram", dict(spreads))
        _record("symmetric_seconds", _quantiles([r["seconds"] for r in records]))
        _record(
            "symmetric_rows",
            [
                [r["combo"], r["status"], r.get("load_spread"), r.get("surcharge_spread"), r.get("hours_spread"), r["seconds"], r["hit_budget"]]
                for r in records
            ],
        )
        self.assertFalse(problems, "\n".join(problems[:20]))

    def test_too_few_people_for_the_rest_rule_is_infeasible(self) -> None:
        """``n < k * (rest + 1)`` cannot staff a month; the solver must say so."""
        combos = [(n, k, r) for k in range(1, 5) for r in range(0, 4) for n in range(1, k * (r + 1))]
        if not STRESS:
            combos = combos[::4]
        instances = [symmetric_instance(n, k, recovery=r) for n, k, r in combos]
        outcomes = solve_in_parallel(instances, 10, workers=WORKERS)
        wrong = [
            (combo, outcome.status)
            for combo, outcome in zip(combos, outcomes)
            if outcome.status != "infeasible"
        ]
        _record("pigeonhole_cases", {"cases": len(combos), "wrong": len(wrong)})
        self.assertFalse(wrong)

    def test_near_symmetric_months_keep_the_others_level(self) -> None:
        """Preferences tilt kinds, not totals; an absent or capped person does not unbalance the rest."""
        cases = _near_symmetric_instances()
        outcomes = solve_in_parallel([instance for _name, instance in cases], 20, workers=WORKERS, observe=True)
        problems: list[str] = []
        rows: list[list[Any]] = []
        for (name, instance), outcome in zip(cases, outcomes):
            if outcome.status != "ok":
                problems.append(f"{name}: {outcome.status} {outcome.issue_codes}")
                continue
            self.assertEqual(validate(instance, outcome.assignments), [], name)
            loads = metrics(instance, outcome.assignments).loads
            totals = {user_id: load.total for user_id, load in loads.items()}
            others = [total for user_id, total in totals.items() if user_id != 1]
            spread_all = max(totals.values()) - min(totals.values())
            spread_others = max(others) - min(others)
            rows.append([name, spread_all, spread_others, totals.get(1), outcome.hit_budget, round(outcome.seconds, 1)])
            if outcome.hit_budget:
                continue
            if name.startswith("preferences") and spread_all > 1:
                problems.append(f"{name}: shift preferences moved totals apart by {spread_all}")
            if not name.startswith("preferences") and spread_others > 1:
                problems.append(f"{name}: the others' loads differ by {spread_others}")
            if name.startswith("capped-strict") and totals.get(1, 0) > 3:
                problems.append(f"{name}: strict cap 3 exceeded ({totals.get(1)})")
            if name.startswith("absent") or name.startswith("capped"):
                if totals.get(1, 0) > max(others):
                    problems.append(f"{name}: the limited person carries the most")
        _record("near_symmetric_rows", rows)
        self.assertFalse(problems, "\n".join(problems))


# --- (d) Spread -------------------------------------------------------------------------


def _max_spaced(dates: Iterable[date], recovery_of: Callable[[date], int]) -> int:
    """Most duties possible on these dates when each one claims its rest."""
    ordered = sorted(dates)
    best = [0] * (len(ordered) + 1)
    for position in range(len(ordered) - 1, -1, -1):
        resume = bisect_left(
            ordered, ordered[position] + timedelta(days=recovery_of(ordered[position]) + 1), position + 1
        )
        best[position] = max(best[position + 1], 1 + best[resume])
    return best[0]


class _SpreadModel:
    """The second pass's spread term, written independently from model doc 3.4/3.5.

    Per employee: candidate dates are the dates of their eligible slots and
    placements; ``shortest(d)`` is the least binding rest of a duty open to
    them on ``d`` (0 under a penalized rest); the unit is
    ``weight / (capacity * H7)``; every pair of worked dates ``d < d + g``
    with ``shortest(d) < g <= 7`` costs ``unit / g``.
    """

    def __init__(self, instance: Instance) -> None:
        """Precompute every employee's unit and candidate dates."""
        policy = instance.effective_policy
        weight = policy.weight(SPREAD)
        strict = policy.is_strict(REST)
        harmonic = sum(1.0 / gap for gap in range(1, SPREAD_HORIZON + 1))
        competences = instance.competence_map
        self.per_user: dict[int, tuple[float, dict[date, int]]] = {}
        for employee in instance.employees:
            slots = set(eligible_slots(instance, employee.id))
            slots |= {(k, d) for (u, k, d) in instance.fixed if u == employee.id and d in instance.day_set}
            by_day: dict[date, set[int]] = {}
            for competence_id, work_date in slots:
                by_day.setdefault(work_date, set()).add(competence_id)
            if not by_day or weight <= 0:
                continue

            def shortest(work_date: date, open_by_day: dict[date, set[int]] = by_day) -> int:
                return min(
                    competences[k].recovery_days_on(work_date) if strict and k in competences else 0
                    for k in open_by_day[work_date]
                )

            capacity = _max_spaced(by_day, shortest)
            if capacity <= 0:
                continue
            self.per_user[employee.id] = (
                weight / (capacity * harmonic),
                {work_date: shortest(work_date) for work_date in by_day},
            )

    def cost(self, duties: Iterable[Duty], users: Iterable[int] | None = None) -> float:
        """The spread cost of a roster (optionally of some employees only)."""
        worked: dict[int, Counter[date]] = {}
        for user_id, _competence_id, work_date in duties:
            worked.setdefault(user_id, Counter())[work_date] += 1
        total = 0.0
        for user_id in users if users is not None else self.per_user:
            if user_id not in self.per_user:
                continue
            unit, shortest = self.per_user[user_id]
            days = worked.get(user_id, Counter())
            for work_date in shortest:
                if not days[work_date]:
                    continue
                for gap in range(shortest[work_date] + 1, SPREAD_HORIZON + 1):
                    later = work_date + timedelta(days=gap)
                    if later in shortest and days[later]:
                        total += unit / gap * max(0, days[work_date] + days[later] - 1)
        return total


def _spread_instances() -> list[Instance]:
    """Wish-free months on which the second-pass objective is the spread alone."""
    combos = [(2, 1, 0), (3, 1, 0), (2, 1, 1), (4, 1, 1), (5, 2, 1), (6, 1, 1), (6, 2, 0), (7, 1, 2), (9, 2, 2), (10, 3, 2)]
    if STRESS:
        combos += [(3, 1, 1), (4, 2, 0), (5, 1, 0), (8, 2, 1), (8, 1, 3), (12, 3, 1), (12, 2, 3), (6, 3, 0), (14, 2, 1), (16, 4, 1)]
    instances = [symmetric_instance(n, k, recovery=r) for n, k, r in combos]
    instances += [symmetric_instance(n, k, month=2, year=2027, recovery=r, hours=12.0) for n, k, r in combos[:4]]
    return instances


def _spread_job(instance: Instance) -> dict[str, Any]:
    """Solve a wish-free month and measure its gaps (worker body)."""
    outcome = run_solver(instance, 20, observe=True)
    record: dict[str, Any] = {"label": instance.label, "status": outcome.status, "hit_budget": outcome.hit_budget}
    if outcome.status != "ok":
        return record
    model = _SpreadModel(instance)
    duties = sorted(outcome.assignments)
    measured = metrics(instance, duties)
    record.update(
        objective=outcome.second_pass.objective if outcome.second_pass else None,
        second_status=outcome.second_pass.sol_status if outcome.second_pass else None,
        spread=model.cost(duties),
        gap_histogram=dict(measured.gap_histogram),
        tightest=measured.tightest_gaps,
        gaps=sum(measured.gap_histogram.values()),
    )
    # For every duty at the tightest gap its rest allows: is there a swap with
    # another person's duty that keeps the first-pass cost and lowers the spread?
    base_cost = first_pass_cost(instance, duties)
    base_spread = record["spread"]
    rest_of = {
        (k.id, day): k.recovery_days_on(day) for k in instance.competences for day in instance.days
    }
    by_user: dict[int, list[Duty]] = {}
    for duty in duties:
        by_user.setdefault(duty[0], []).append(duty)
    tight_duties: set[Duty] = set()
    for own in by_user.values():
        own.sort(key=lambda duty: duty[2])
        for earlier, later in zip(own, own[1:]):
            if (later[2] - earlier[2]).days == rest_of[(earlier[1], earlier[2])] + 1:
                tight_duties.update((earlier, later))
    best_gain = 0.0
    improvable: set[Duty] = set()
    checked = 0
    for first in sorted(tight_duties):
        for second in duties:
            if first[0] == second[0] or first[2] == second[2]:
                continue
            new_first = (second[0], first[1], first[2])
            new_second = (first[0], second[1], second[2])
            rest = [d for d in duties if d not in (first, second)]
            if not eligible(instance, *new_first, rest) or not eligible(instance, *new_second, rest + [new_first]):
                continue
            checked += 1
            moved = rest + [new_first, new_second]
            if abs(first_pass_cost(instance, moved) - base_cost) > 1e-6:
                continue
            gain = base_spread - model.cost(moved)
            if gain > 1e-9:
                improvable.add(first)
                best_gain = max(best_gain, gain)
    record.update(
        tight_duties=len(tight_duties),
        improvable_tight_duties=len(improvable),
        neutral_swaps_checked=checked,
        improving_swaps=len(improvable),
        best_swap_gain=best_gain,
    )
    return record


class SpreadTests(unittest.TestCase):
    """(d) How far apart duties land when the balance leaves a choice."""

    def test_spread_model_matches_the_second_pass_and_gap_statistics(self) -> None:
        """The re-implemented spread equals the observed objective; no swap beats the tolerance."""
        records = _map(_spread_job, _spread_instances())
        problems: list[str] = []
        histogram: Counter[int] = Counter()
        tight = 0
        gaps = 0
        with_improving = 0
        tight_duties = 0
        improvable_duties = 0
        gains: list[float] = []
        relative: list[float] = []
        rows: list[list[Any]] = []
        for record in records:
            if record["status"] != "ok":
                problems.append(f"{record['label']}: {record['status']}")
                continue
            if record["objective"] is not None and record["second_status"] == 1:
                if abs(record["objective"] - record["spread"]) > 1e-6:
                    problems.append(
                        f"{record['label']}: spread model {record['spread']} vs objective {record['objective']}"
                    )
            for gap, number in record["gap_histogram"].items():
                histogram[int(gap)] += number
            tight += record["tightest"]
            gaps += record["gaps"]
            tight_duties += record["tight_duties"]
            improvable_duties += record["improvable_tight_duties"]
            if record["improving_swaps"]:
                with_improving += 1
                gains.append(record["best_swap_gain"])
                relative.append(record["best_swap_gain"] / max(1e-9, record["spread"]))
            # The documented tolerance is min(spread weight 1.0, 0.1 * 10) = 1.0.
            if not record["hit_budget"] and record["best_swap_gain"] > 1.0 + 1e-6:
                problems.append(f"{record['label']}: a balance-neutral swap saves {record['best_swap_gain']}")
            rows.append(
                [record["label"], round(record["spread"], 4), record["tightest"], record["gaps"],
                 record["tight_duties"], record["improvable_tight_duties"], round(record["best_swap_gain"], 4),
                 record["hit_budget"]]
            )
        _record("spread_gap_histogram", dict(sorted(histogram.items())))
        _record("spread_tight_share", round(tight / max(1, gaps), 3))
        _record("spread_runs_with_improving_swap", [with_improving, len(records)])
        _record("spread_tight_duties_improvable", [improvable_duties, tight_duties])
        _record("spread_best_gain", _quantiles(gains))
        _record("spread_best_gain_relative", _quantiles(relative))
        _record("spread_rows", rows)
        self.assertFalse(problems, "\n".join(problems))

    @unittest.expectedFailure
    def test_two_people_without_rest_alternate(self) -> None:
        """Suspected weakness: the spread is not optimized when it is worth less than the tolerance.

        Two identical people, one role, no rest, August 2026. Alternating
        days (every gap two days) is exactly as balanced as anything else --
        16/15 duties, 5/5 weekend duties -- and has the lowest spread, which
        is what model doc 3.4 and the module docstring promise ("duties end
        up further apart only where that is free"). The second pass stops
        within ``gapAbs = min(spread weight, 0.1 * day wish) = 1.0`` of its
        bound, and the whole roster's spread is about 0.35, so CBC may return
        the first feasible roster: it contains one-day gaps.
        """
        instance = symmetric_instance(2, 1, recovery=0)
        outcome = run_solver(instance, 20, observe=True)
        self.assertEqual(outcome.status, "ok")
        self.assertFalse(outcome.hit_budget)
        alternating = [(1 if day.day % 2 else 2, 1, day) for day in instance.days]
        self.assertEqual(validate(instance, alternating), [])
        self.assertAlmostEqual(
            first_pass_cost(instance, alternating), first_pass_cost(instance, outcome.assignments)
        )
        self.assertEqual(metrics(instance, outcome.assignments).gap_histogram.get(1, 0), 0)


if __name__ == "__main__":
    unittest.main()
