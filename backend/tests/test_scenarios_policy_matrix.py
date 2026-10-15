"""Workplace rule settings: every rule in every mode, judged with the harness.

What is checked:

* **Matrix.** Every switchable rule (unavailable, vacation, business trip,
  rest, monthly maximum, overstaff, "rather not") strict and penalized with
  weights 0 / 0.5 / default / 1000 / 100000, and every penalty-only rule
  (balance, "want to", spread) with weights 0 / 0.5 / default / 1000 /
  100000, on planted instances that stimulate that rule. Each solve must be
  ``ok`` (planted), keep every hard rule (``validate``), cost no more than
  the witness when it finished in time, end within the balance lock of its
  own first pass (wishes never buy a less balanced roster), and leave no
  ``first_pass`` / ``day_wish`` improving move.
* **Weight 0 removes the term.** A weight of zero must give the same first
  pass as an instance without the thing it prices.
* **Order of strength.** Penalized absences, rest and monthly maximum at
  1000 (and 100000) beat every balance step; at 0 / 0.5 they lose to it.
  Day wishes at 100000 still cannot buy a less balanced roster.
* **Presets and random policies.** Every ``POLICY_PRESETS`` entry and many
  ``random_policy`` draws on planted small instances.
* **Settings service.** Save / load / reset round trips and validation.
* **Conflict message.** ``constraint_conflict`` lists exactly
  ``policy.tightened()`` (a capacity pre-check failure omitting it is the
  known bug ``capacity_error_without_tightened_rules``; tallied only).

``SCHEDULING_STRESS=1`` widens every sweep. ``POLICY_MATRIX_METRICS=<path>``
writes the measured numbers as JSON.
"""

from __future__ import annotations

import json
import math
import os
import random
import statistics
import unittest
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from datetime import date, timedelta
from typing import Any, Callable

from app.models import Ambulance, ConstraintSetting
from app.services.constraint_setting_service import (
    BALANCE,
    BUSINESS_TRIP,
    CONSTRAINTS,
    DEFINITIONS,
    MAX_SHIFTS,
    MAX_WEIGHT,
    MODE_FIXED,
    MODE_PENALTY,
    MODE_SWITCHABLE,
    OVERSTAFF,
    PREFERRED,
    REST,
    SOFT_DECLINE,
    SPREAD,
    UNAVAILABLE,
    VACATION,
    ConstraintPolicy,
    ConstraintRule,
    ConstraintSettingError,
    constraint_entries,
    load_constraint_policy,
    policy_from_settings,
    reset_constraint_settings,
    save_constraint_settings,
)
from app.services.schedule_generation_service import SchedulingCompetence, SchedulingEmployee

from tests.scheduling_harness.db_builder import fresh_session
from tests.scheduling_harness.instances import (
    POLICY_PRESETS,
    Instance,
    Knobs,
    PlantingFailed,
    make_instance,
    random_policy,
    sample_knobs,
)
from tests.scheduling_harness.known_bugs import known_bug_triggers
from tests.scheduling_harness.oracle import (
    find_improving_moves,
    first_pass_cost,
    metrics,
    validate,
    violation_codes,
)
from tests.scheduling_harness.reference import reference_feasibility
from tests.scheduling_harness.runner import SolveOutcome, run_solver, solve_in_parallel
from tests.scheduling_harness.semantics import balance_lock_slack

STRESS = os.environ.get("SCHEDULING_STRESS") == "1"
#: One other agent shares the machine: never more than six CBC processes.
WORKERS = 6
#: Solver budget per solve; the wish pass usually uses all of it (see optimality_1).
BUDGET = 8.0 if STRESS else 5.0

SWITCHABLE = (UNAVAILABLE, VACATION, BUSINESS_TRIP, REST, MAX_SHIFTS, OVERSTAFF, SOFT_DECLINE)
PENALTY_ONLY = (BALANCE, PREFERRED, SPREAD)
WEIGHTS = (0.0, 0.5, "default", 1000.0, 100000.0)

#: Knobs that make each rule matter, on top of a small planted workplace.
STIMULI: dict[str, dict[str, Any]] = {
    UNAVAILABLE: dict(unavailability_rate=0.15, absence_mix=(1.0, 0.0, 0.0), vacation_block_rate=0.3, block_mix=(1.0, 0.0, 0.0)),
    VACATION: dict(unavailability_rate=0.08, absence_mix=(0.0, 1.0, 0.0), vacation_block_rate=0.5, block_mix=(0.0, 1.0, 0.0)),
    BUSINESS_TRIP: dict(unavailability_rate=0.08, absence_mix=(0.0, 0.0, 1.0), vacation_block_rate=0.5, block_mix=(0.0, 0.0, 1.0)),
    REST: dict(recovery_profile="mixed", external_rate=0.05, adjacent_rate=0.4, n_breaking_fixed=1, breaking_kinds=("inside_rest",)),
    MAX_SHIFTS: dict(max_shifts_mode="below"),
    OVERSTAFF: dict(n_breaking_fixed=2, breaking_kinds=("above_demand",), demand_profile="sparse"),
    SOFT_DECLINE: dict(soft_decline_rate=0.25, wish_pattern="weekday"),
    BALANCE: dict(max_shifts_mode="hetero", preference_mix="mixed", hours_profile="mixed"),
    PREFERRED: dict(preferred_rate=0.2, wish_pattern="crowd"),
    SPREAD: dict(recovery_profile="zero", preferred_rate=0.05),
}

_METRICS: dict[str, Any] = {}


def _record(key: str, value: Any) -> None:
    """Keep one measured number (or table) for the JSON report."""
    _METRICS[key] = value


def tearDownModule() -> None:
    """Write the measured numbers when ``POLICY_MATRIX_METRICS`` names a file."""
    path = os.environ.get("POLICY_MATRIX_METRICS")
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
        return list(pool.map(function, jobs, chunksize=2))


def _weight(code: str, weight: Any) -> float:
    """A weight of the matrix, with ``'default'`` resolved."""
    return float(DEFINITIONS[code].default_weight or 0.0) if weight == "default" else float(weight)


def _mode_label(strict: bool, weight: float) -> str:
    """A matrix column name."""
    return "strict" if strict else f"w{weight:g}"


# --- The judge every policy solve goes through ---------------------------------------


def _judge(job: tuple[str, Instance, float]) -> dict[str, Any]:
    """Solve, validate and measure one instance (worker body)."""
    tag, instance, budget = job
    outcome = run_solver(instance, budget, observe=True)
    record: dict[str, Any] = {
        "tag": tag,
        "label": instance.label,
        "planted": instance.witness is not None,
        "status": outcome.status,
        "error": outcome.error,
        "issues": outcome.issues,
        "seconds": round(outcome.seconds, 2),
        "hit_budget": outcome.hit_budget,
        "second_pass": outcome.second_pass is not None,
        # The wish pass ran out of time with no roster at all (CBC status 0);
        # the solver then keeps the first-pass roster (optimality_1).
        "second_pass_empty": outcome.second_pass is not None and outcome.second_pass.sol_status == 0,
        "first_optimal": outcome.first_pass is not None and outcome.first_pass.optimal,
        "second_optimal": outcome.second_pass is None or outcome.second_pass.optimal,
        "triggers": sorted(known_bug_triggers(instance)),
        "tightened": instance.effective_policy.tightened(),
    }
    if instance.witness is not None:
        record["witness_cost"] = first_pass_cost(instance, instance.witness)
    if outcome.status != "ok":
        if outcome.status == "infeasible" and instance.witness is None:
            record["reference"] = reference_feasibility(instance, time_limit=30)[0]
        return record
    violations = validate(instance, outcome.assignments)
    record["violations"] = sorted(violation_codes(violations))
    if violations:
        return record
    measured = metrics(instance, outcome.assignments)
    record.update(
        cost=first_pass_cost(instance, outcome.assignments),
        reached=outcome.first_pass_objective,
        cap=outcome.balance_cap,
        absence_breaches=dict(measured.absence_breaches),
        rest_breach_days=measured.rest_breach_days,
        over_max=sum(measured.over_max.values()),
        overstaff=measured.overstaff,
        soft_declined_worked=measured.soft_declined_worked,
        preferred_honored=measured.preferred_honored,
        load_spread=measured.load_spread,
        loads={user_id: load.total for user_id, load in measured.loads.items()},
        assignments=sorted(outcome.assignments),
    )
    if record["first_optimal"]:
        moves = find_improving_moves(
            instance, outcome.assignments, max_checks=8000, balance_cap=outcome.balance_cap
        )
        record["moves"] = dict(Counter(move.reason for move in moves))
    return record


def _problems(record: dict[str, Any]) -> list[str]:
    """Every generic check a judged record fails, as messages."""
    where = f"{record['tag']} {record['label']}"
    if record["status"] == "error":
        return [f"{where}: solver error {record['error']}"]
    if record["status"] == "timeout":
        return []
    if record["status"] == "infeasible":
        if record["planted"]:
            return [f"{where}: planted instance reported infeasible {record['issues'][:2]}"]
        if record.get("reference") == "feasible":
            return [f"{where}: infeasible but the reference model found a roster"]
        return []
    if record["violations"]:
        return [f"{where}: roster breaks {record['violations']}"]
    found: list[str] = []
    # Wishes never buy a less balanced roster: the final roster's first-pass
    # cost stays within the lock of what the first pass reached.
    if record["reached"] is not None and record["cost"] > record["reached"] + balance_lock_slack(record["reached"]) + 1e-6:
        found.append(f"{where}: final first-pass cost {record['cost']} beyond the lock of {record['reached']}")
    # A first pass proved optimal is no worse than the witness; the final
    # roster may sit up to the lock above it.
    if record["planted"] and record["first_optimal"] and record["reached"] is not None:
        if record["reached"] > record["witness_cost"] + balance_lock_slack(record["witness_cost"]):
            found.append(f"{where}: first pass {record['reached']} above the witness {record['witness_cost']}")
    # day_wish moves only prove a miss when the wish pass itself was proved optimal.
    judged = ("first_pass", "day_wish") if record["second_optimal"] else ("first_pass",)
    bad = {k: v for k, v in record.get("moves", {}).items() if k in judged}
    if bad and "zero_balance_skips_wishes" not in record["triggers"]:
        found.append(f"{where}: improving moves {bad}")
    return found


def _stimulated(rule: str, seed: int, policy: dict[str, tuple[bool, float]]) -> Instance | None:
    """A small planted workplace that makes ``rule`` matter, planted under ``policy``."""
    knobs = Knobs(
        n_employees=7,
        n_competences=2,
        month=(2, 8, 12)[seed % 3],
        year=2027,
        qualification_density=0.8,
        hours_profile="mixed",
        special_days="random",
        planted=True,
        policy=policy,
        max_spares=3,
    )
    knobs = replace(knobs, **STIMULI[rule])
    try:
        return make_instance(seed, knobs)
    except PlantingFailed:
        return None


def _matrix_jobs(seeds: range) -> list[tuple[str, Instance, float]]:
    """Every rule in every mode on stimulated instances."""
    jobs: list[tuple[str, Instance, float]] = []
    for rule in SWITCHABLE:
        default = float(DEFINITIONS[rule].default_weight or 0.0)
        for seed in seeds:
            strict_base = _stimulated(rule, seed, {rule: (True, default)})
            loose_base = _stimulated(rule, seed, {rule: (False, default)})
            if strict_base is not None:
                jobs.append((f"{rule}|strict|strict-planted", replace(strict_base, policy=policy_from_settings({rule: (True, default)})), BUDGET))
            for weight in WEIGHTS:
                value = _weight(rule, weight)
                policy = policy_from_settings({rule: (False, value)})
                for base_name, base in (("strict-planted", strict_base), ("loose-planted", loose_base)):
                    if base is not None:
                        jobs.append((f"{rule}|w{value:g}|{base_name}", replace(base, policy=policy), BUDGET))
    for rule in PENALTY_ONLY:
        for seed in seeds:
            base = _stimulated(rule, seed, {})
            if base is None:
                continue
            for weight in WEIGHTS:
                value = _weight(rule, weight)
                jobs.append((f"{rule}|w{value:g}|planted", replace(base, policy=policy_from_settings({rule: (False, value)})), BUDGET))
    return jobs


def _breaches(rule: str, record: dict[str, Any]) -> int:
    """How often the record's roster broke (or paid for) ``rule``."""
    if rule in (UNAVAILABLE, VACATION, BUSINESS_TRIP):
        return int(record["absence_breaches"].get(rule, 0))
    return int(
        {
            REST: record["rest_breach_days"],
            MAX_SHIFTS: record["over_max"],
            OVERSTAFF: record["overstaff"],
            SOFT_DECLINE: record["soft_declined_worked"],
            PREFERRED: record["preferred_honored"],
            BALANCE: record["load_spread"],
            SPREAD: 0,
        }[rule]
    )


class PolicyMatrixTests(unittest.TestCase):
    """Rule x mode: solves, valid, breaches."""

    def test_every_rule_in_every_mode(self) -> None:
        """The generic checks hold for every cell of the matrix."""
        seeds = range(4) if STRESS else range(1)
        jobs = _matrix_jobs(seeds)
        records = _map(_judge, jobs)
        problems: list[str] = []
        table: dict[tuple[str, str, str], Counter[str]] = {}
        for record in records:
            rule, mode, base = record["tag"].split("|")
            cell = table.setdefault((rule, mode, base), Counter())
            cell["solves"] += 1
            cell[f"status_{record['status']}"] += 1
            problems += _problems(record)
            for trigger in record["triggers"]:
                cell[f"trigger_{trigger}"] += 1
            if record["status"] != "ok" or record.get("violations"):
                continue
            cell["valid"] += 1
            cell["breaches"] += _breaches(rule, record)
            cell["hit_budget"] += int(record["hit_budget"])
            cell["second_pass"] += int(record["second_pass"])
            cell["second_pass_empty"] += int(record["second_pass_empty"])
            cell["first_optimal"] += int(record["first_optimal"])
            cell["empty_after_optimal_first"] += int(record["second_pass_empty"] and record["first_optimal"])
            cell["lock_drift"] += int(record.get("moves", {}).get("lock_drift", 0) > 0)
            if record["cost"] > (record["reached"] or 0) + 1e-6:
                cell["drift_runs"] += 1
            # Order of strength on stimulated instances planted under the
            # strict rule: the witness never breaks it, so at 100000 a breach
            # would have to save 100000 in balance steps.
            if mode == "w100000" and base == "strict-planted" and rule in (UNAVAILABLE, VACATION, BUSINESS_TRIP, REST, MAX_SHIFTS, OVERSTAFF) and record["first_optimal"]:
                if _breaches(rule, record) and record["witness_cost"] < 100000:
                    problems.append(f"{record['tag']} {record['label']}: {rule} broken at weight 100000")
        rows = [
            [rule, mode, base, cell["solves"], cell["valid"], cell["breaches"], cell["hit_budget"],
             cell["second_pass"], cell["second_pass_empty"], cell["first_optimal"], cell["empty_after_optimal_first"],
             cell["lock_drift"], cell["status_timeout"],
             ",".join(sorted(k[8:] for k in cell if k.startswith("trigger_")))]
            for (rule, mode, base), cell in sorted(table.items())
        ]
        _record("matrix_rows", rows)
        _record("matrix_seconds", _quantiles([record["seconds"] for record in records]))
        _record("matrix_solves", len(records))
        _record("matrix_final_above_reached", sum(cell["drift_runs"] for cell in table.values()))
        _record("matrix_empty_wish_pass", [sum(cell["empty_after_optimal_first"] for cell in table.values()), sum(cell["first_optimal"] for cell in table.values())])
        self.assertFalse(problems, "\n".join(problems[:25]))


def _quantiles(values: list[float]) -> dict[str, float]:
    """Median, p90 and max of a list."""
    if not values:
        return {"n": 0}
    ordered = sorted(values)
    return {
        "n": len(ordered),
        "median": round(statistics.median(ordered), 3),
        "p90": round(ordered[min(len(ordered) - 1, int(0.9 * len(ordered)))], 3),
        "max": round(ordered[-1], 3),
    }


# --- Weight 0 removes the term --------------------------------------------------------


def _without(instance: Instance, **changes: Callable[[SchedulingEmployee], SchedulingEmployee]) -> Instance:
    """The instance with every employee passed through one transformation."""
    (transform,) = changes.values()
    return replace(instance, employees=[transform(employee) for employee in instance.employees])


def _no_rest(instance: Instance) -> Instance:
    """The instance with every rest at zero (here and elsewhere)."""
    competences = [
        replace(
            competence,
            weekday_recovery_days=(0,) * 7,
            special_day_recovery_days=0,
        )
        for competence in instance.competences
    ]
    employees = [
        replace(
            employee,
            external_commitments=tuple((day, 0) for day, _rest in employee.external_commitments),
        )
        for employee in instance.employees
    ]
    return replace(instance, competences=competences, employees=employees)


def _zero_weight_pairs(seed: int) -> list[tuple[str, Instance, Instance, str]]:
    """``(name, weight-0 instance, instance without the term, comparison)`` pairs."""
    pairs: list[tuple[str, Instance, Instance, str]] = []
    for rule in (UNAVAILABLE, VACATION, BUSINESS_TRIP):
        base = _stimulated(rule, seed, {rule: (False, 1000.0)})
        if base is None:
            continue
        zero = replace(base, policy=policy_from_settings({rule: (False, 0.0)}))
        dropped = _without(
            replace(base, policy=None),
            transform=lambda e, rule=rule: replace(
                e,
                unavailable_dates=frozenset(
                    day for day in e.unavailable_dates if dict(e.absence_rules).get(day, UNAVAILABLE) != rule
                ),
                absence_rules=tuple(item for item in e.absence_rules if item[1] != rule),
            ),
        )
        pairs.append((f"{rule}=0 vs no {rule}", zero, dropped, "identical"))
    base = _stimulated(MAX_SHIFTS, seed, {MAX_SHIFTS: (False, 1000.0)})
    if base is not None:
        pairs.append(
            (
                "max_shifts=0 vs no caps",
                replace(base, policy=policy_from_settings({MAX_SHIFTS: (False, 0.0)})),
                _without(replace(base, policy=None), transform=lambda e: replace(e, max_shifts_per_month=None)),
                "identical",
            )
        )
    base = _stimulated(SOFT_DECLINE, seed, {})
    if base is not None:
        pairs.append(
            (
                "soft_decline=0 vs no rather-not days",
                replace(base, policy=policy_from_settings({SOFT_DECLINE: (False, 0.0)})),
                _without(replace(base, policy=None), transform=lambda e: replace(e, soft_declined_dates=frozenset())),
                "identical",
            )
        )
    base = _stimulated(PREFERRED, seed, {})
    if base is not None:
        pairs.append(
            (
                "preferred=0 vs no want-to days",
                replace(base, policy=policy_from_settings({PREFERRED: (False, 0.0)})),
                _without(replace(base, policy=None), transform=lambda e: replace(e, preferred_dates=frozenset())),
                "identical",
            )
        )
    base = _stimulated(REST, seed, {REST: (False, 1000.0)})
    if base is not None:
        pairs.append(
            (
                "rest=0 vs every rest zero",
                replace(base, policy=policy_from_settings({REST: (False, 0.0)})),
                _no_rest(replace(base, policy=None)),
                "objective",
            )
        )
    base = _stimulated(OVERSTAFF, seed, {OVERSTAFF: (True, 1000.0)})
    if base is not None:
        pairs.append(
            (
                "overstaff=0 vs strict overstaff",
                replace(base, policy=policy_from_settings({OVERSTAFF: (False, 0.0)})),
                replace(base, policy=policy_from_settings({OVERSTAFF: (True, 1000.0)})),
                "objective",
            )
        )
    return pairs


class ZeroWeightTests(unittest.TestCase):
    """Model doc 6: a weight of 0 leaves its term out of the model altogether."""

    def test_weight_zero_equals_the_instance_without_the_term(self) -> None:
        """Same first-pass value; where the model is literally the same, the same roster."""
        seeds = range(3) if STRESS else range(1)
        pairs = [pair for seed in seeds for pair in _zero_weight_pairs(seed)]
        jobs: list[tuple[str, Instance, float]] = []
        for name, zero, dropped, _how in pairs:
            jobs += [(name + "|zero", zero, BUDGET), (name + "|dropped", dropped, BUDGET)]
        records = _map(_judge, jobs)
        problems: list[str] = []
        table: dict[str, Counter[str]] = {}
        for (name, _zero, _dropped, how), first, second in zip(pairs, records[::2], records[1::2]):
            cell = table.setdefault(name, Counter())
            cell["pairs"] += 1
            problems += _problems(first) + _problems(second)
            if first["status"] != second["status"]:
                problems.append(f"{name} {first['label']}: status {first['status']} vs {second['status']}")
                continue
            if first["status"] != "ok" or first.get("violations") or second.get("violations"):
                continue
            if not (first["first_optimal"] and second["first_optimal"]):
                cell["hit_budget"] += 1
                continue
            cell["compared"] += 1
            if abs(first["reached"] - second["reached"]) > balance_lock_slack(second["reached"]):
                problems.append(f"{name} {first['label']}: first pass {first['reached']} vs {second['reached']}")
            if first["hit_budget"] or second["hit_budget"]:
                cell["wish_pass_cut"] += 1
                continue
            same = first["assignments"] == second["assignments"]
            cell["identical_roster"] += int(same)
            if how == "identical" and not same:
                cell["roster_differs"] += 1
        _record("zero_weight_rows", [[name, *[cell[k] for k in ("pairs", "compared", "identical_roster", "roster_differs", "wish_pass_cut", "hit_budget")]] for name, cell in table.items()])
        self.assertFalse(problems, "\n".join(problems[:20]))

    def test_silenced_wishes_and_spread_skip_the_second_pass(self) -> None:
        """Doc 6: a workplace that silenced every wish and the spread has no second pass."""
        policy = policy_from_settings({PREFERRED: (False, 0.0), SOFT_DECLINE: (False, 0.0), SPREAD: (False, 0.0)})
        base = _stimulated(PREFERRED, 3, {})
        assert base is not None
        outcome = run_solver(replace(base, policy=policy), BUDGET, observe=True)
        self.assertEqual(outcome.status, "ok")
        self.assertIsNone(outcome.second_pass)
        strict_soft = policy_from_settings({PREFERRED: (False, 0.0), SOFT_DECLINE: (True, 10.0), SPREAD: (False, 0.0)})
        outcome = run_solver(replace(base, policy=strict_soft), BUDGET, observe=True)
        self.assertEqual(outcome.status, "ok")
        self.assertIsNone(outcome.second_pass)

    def test_zero_balance_without_wishes_prices_only_the_penalties(self) -> None:
        """Balance 0: the first-pass value is the penalties alone, and it matches the oracle."""
        base = _stimulated(UNAVAILABLE, 4, {UNAVAILABLE: (False, 1000.0)})
        assert base is not None
        policy = policy_from_settings(
            {BALANCE: (False, 0.0), UNAVAILABLE: (False, 7.0), PREFERRED: (False, 0.0), SOFT_DECLINE: (False, 0.0), SPREAD: (False, 0.0)}
        )
        instance = replace(base, policy=policy)
        self.assertNotIn("zero_balance_skips_wishes", known_bug_triggers(instance))
        outcome = run_solver(instance, BUDGET, observe=True)
        self.assertEqual(outcome.status, "ok")
        self.assertEqual(validate(instance, outcome.assignments), [])
        cost = first_pass_cost(instance, outcome.assignments)
        self.assertAlmostEqual(cost, outcome.first_pass_objective or 0.0, places=6)
        breaches = sum(metrics(instance, outcome.assignments).absence_breaches.values())
        self.assertAlmostEqual(cost, 7.0 * breaches + 1000.0 * metrics(instance, outcome.assignments).overstaff, places=6)
        self.assertEqual(breaches, 0, "a free roster without absences exists (the witness)")


# --- Order of strength -------------------------------------------------------------------


def _role(recovery: int = 0) -> SchedulingCompetence:
    """One role, one person a day, every day, the given rest."""
    return SchedulingCompetence(
        id=1,
        name="Role 1",
        required_count=1,
        weekday_required_counts=(1,) * 7,
        weekday_recovery_days=(recovery,) * 7,
    )


def _person(user_id: int, **fields: Any) -> SchedulingEmployee:
    """A one-role employee."""
    values: dict[str, Any] = {
        "id": user_id,
        "email": f"p{user_id}@harness.test",
        "full_name": None,
        "competence_ids": frozenset({1}),
        "unavailable_dates": frozenset(),
        "externally_scheduled_dates": frozenset(),
    }
    values.update(fields)
    return SchedulingEmployee(**values)


FEB = [date(2027, 2, day) for day in range(1, 29)]


def _absence_duel(rule: str, weight: float) -> Instance:
    """A and B, no rest; B is away (``rule``) on 1-20 Feb: 20/8 without breaches, 14/14 balanced."""
    away = frozenset(FEB[:20])
    people = [
        _person(1),
        _person(2, unavailable_dates=away, absence_rules=tuple((day, rule) for day in sorted(away))),
    ]
    return Instance(people, [_role(0)], 2, 2027, policy=policy_from_settings({rule: (False, weight)}), label=f"duel-{rule}-{weight:g}")


def _rest_duel(weight: float) -> Instance:
    """A, B, C with one day of rest; C cannot work 1-20 Feb (strict): C works 4 of 21-28 unless rest is broken."""
    people = [_person(1), _person(2), _person(3, unavailable_dates=frozenset(FEB[:20]))]
    return Instance(people, [_role(1)], 2, 2027, policy=policy_from_settings({REST: (False, weight)}), label=f"duel-rest-{weight:g}")


def _max_duel(weight: float) -> Instance:
    """A wants at most 5 duties, B has no opinion; no rest: 5/23 kept, 14/14 balanced."""
    people = [_person(1, max_shifts_per_month=5), _person(2)]
    return Instance(people, [_role(0)], 2, 2027, policy=policy_from_settings({MAX_SHIFTS: (False, weight)}), label=f"duel-max-{weight:g}")


def _wish_duel(code: str, weight: float) -> Instance:
    """A wants every day (or would rather not work any); no rest: balance must still be 14/14."""
    days = frozenset(FEB)
    first = _person(1, preferred_dates=days) if code == PREFERRED else _person(1, soft_declined_dates=days)
    return Instance([first, _person(2)], [_role(0)], 2, 2027, policy=policy_from_settings({code: (False, weight)}), label=f"duel-{code}-{weight:g}")


class StrengthOrderTests(unittest.TestCase):
    """Penalties of the first pass beat the balance at 1000; wishes never buy imbalance."""

    @classmethod
    def setUpClass(cls) -> None:
        """Solve every duel once."""
        cls.cases: list[tuple[str, float, Instance]] = []
        for weight in (0.0, 0.5, 4.0, 40.0, 1000.0, 100000.0):
            for rule in (UNAVAILABLE, VACATION, BUSINESS_TRIP):
                cls.cases.append((rule, weight, _absence_duel(rule, weight)))
            cls.cases.append((REST, weight, _rest_duel(weight)))
            cls.cases.append((MAX_SHIFTS, weight, _max_duel(weight)))
        for weight in (0.0, 10.0, 100000.0):
            cls.cases.append((PREFERRED, weight, _wish_duel(PREFERRED, weight)))
            cls.cases.append((SOFT_DECLINE, weight, _wish_duel(SOFT_DECLINE, weight)))
        cls.outcomes = solve_in_parallel([case[2] for case in cls.cases], BUDGET, workers=WORKERS, observe=True)
        rows = []
        for (rule, weight, instance), outcome in zip(cls.cases, cls.outcomes):
            measured = metrics(instance, outcome.assignments) if outcome.status == "ok" else None
            rows.append(
                [rule, weight, outcome.status, measured and sorted((u, l.total) for u, l in measured.loads.items()),
                 measured and (sum(measured.absence_breaches.values()), measured.rest_breach_days, sum(measured.over_max.values()),
                               measured.preferred_honored, measured.soft_declined_worked),
                 outcome.hit_budget]
            )
        _record("strength_rows", rows)

    def _each(self, rules: tuple[str, ...], allow_budget: bool = False):
        """The solved duels of some rules, checked for validity on the way.

        ``allow_budget`` admits runs whose wish pass hit the budget: the
        balance lock binds whatever the wish pass found.
        """
        for (rule, weight, instance), outcome in zip(self.cases, self.outcomes):
            if rule not in rules:
                continue
            self.assertEqual(outcome.status, "ok", instance.label)
            self.assertEqual(validate(instance, outcome.assignments), [], instance.label)
            if not allow_budget:
                self.assertFalse(outcome.hit_budget, instance.label)
            else:
                self.assertTrue(outcome.first_pass.optimal, instance.label)
            yield rule, weight, instance, outcome, metrics(instance, outcome.assignments)

    def test_penalized_absences_at_1000_beat_the_balance(self) -> None:
        """No breach at 1000 / 100000; full balance at 0 / 0.5; fewer breaches as the weight rises."""
        previous: dict[str, int] = {}
        for rule, weight, instance, outcome, measured in self._each((UNAVAILABLE, VACATION, BUSINESS_TRIP)):
            breaches = measured.absence_breaches.get(rule, 0)
            if weight >= 1000:
                self.assertEqual(breaches, 0, instance.label)
                self.assertEqual(measured.loads[2].total, 8, instance.label)
            if weight <= 0.5:
                self.assertLessEqual(measured.load_spread, 1, instance.label)
            if rule in previous:
                self.assertLessEqual(breaches, previous[rule], instance.label)
            previous[rule] = breaches

    def test_penalized_rest_at_1000_beats_the_balance(self) -> None:
        """No rest breach at 1000; at 0 C fills all of 21-28 Feb."""
        previous = None
        for _rule, weight, instance, outcome, measured in self._each((REST,)):
            if weight >= 1000:
                self.assertEqual(measured.rest_breach_days, 0, instance.label)
                self.assertEqual(measured.loads[3].total, 4, instance.label)
            if weight == 0.0:
                self.assertEqual(measured.loads[3].total, 8, instance.label)
            if previous is not None:
                self.assertLessEqual(measured.rest_breach_days, previous, instance.label)
            previous = measured.rest_breach_days

    def test_penalized_monthly_maximum_at_1000_beats_the_balance(self) -> None:
        """5/23 at 1000 / 100000; 14/14 at 0 / 0.5."""
        for _rule, weight, instance, outcome, measured in self._each((MAX_SHIFTS,)):
            if weight >= 1000:
                self.assertEqual(sum(measured.over_max.values()), 0, instance.label)
                self.assertEqual(measured.loads[1].total, 5, instance.label)
            if weight <= 0.5:
                self.assertLessEqual(measured.load_spread, 1, instance.label)

    def test_day_wishes_never_buy_a_less_balanced_roster(self) -> None:
        """Even at 100000, A keeps 14 of 28 duties and the first pass is unchanged."""
        reached: dict[str, float] = {}
        for rule, _weight, instance, outcome, measured in self._each((PREFERRED, SOFT_DECLINE), allow_budget=True):
            self.assertLessEqual(measured.load_spread, 1, instance.label)
            final = first_pass_cost(instance, outcome.assignments)
            self.assertLessEqual(final, outcome.first_pass_objective + balance_lock_slack(outcome.first_pass_objective), instance.label)
            if rule in reached:
                self.assertAlmostEqual(outcome.first_pass_objective, reached[rule], places=6)
            reached[rule] = outcome.first_pass_objective


# --- Presets and random policies ---------------------------------------------------------


def _preset_jobs() -> list[tuple[str, Instance, float]]:
    """Every preset and many random policies on planted small instances."""
    jobs: list[tuple[str, Instance, float]] = []
    per_preset = range(6) if STRESS else range(2)
    for name, settings in POLICY_PRESETS.items():
        for seed in per_preset:
            knobs = replace(sample_knobs(random.Random(7000 + seed), "small", planted=True), policy=dict(settings))
            jobs.append((f"preset:{name}", make_instance(7000 + seed, knobs), BUDGET))
    draws = range(80) if STRESS else range(20)
    for seed in draws:
        rng = random.Random(9000 + seed)
        settings = random_policy(rng, allow_zero_balance=False)
        knobs = replace(sample_knobs(rng, "small", planted=True), policy=settings)
        jobs.append(("random_policy", make_instance(9000 + seed, knobs), BUDGET))
    return jobs


class PresetAndRandomPolicyTests(unittest.TestCase):
    """Every preset and many random policies keep the generic checks."""

    def test_presets_and_random_policies(self) -> None:
        """Planted, valid, no worse than the witness, within the lock, no improving move."""
        records = _map(_judge, _preset_jobs())
        problems: list[str] = []
        table: dict[str, Counter[str]] = {}
        for record in records:
            cell = table.setdefault(record["tag"], Counter())
            cell["solves"] += 1
            cell[f"status_{record['status']}"] += 1
            problems += _problems(record)
            for trigger in record["triggers"]:
                cell[f"trigger_{trigger}"] += 1
            if record["status"] == "ok" and not record.get("violations"):
                cell["valid"] += 1
                cell["hit_budget"] += int(record["hit_budget"])
                cell["lock_drift_runs"] += int(record.get("moves", {}).get("lock_drift", 0) > 0)
                cell["second_pass_empty"] += int(record["second_pass_empty"])
                cell["final_above_reached"] += int(record["cost"] > (record["reached"] or 0) + 1e-6)
        _record("preset_rows", [[tag, *[cell[k] for k in ("solves", "valid", "status_timeout", "hit_budget", "second_pass_empty", "lock_drift_runs", "final_above_reached")], ",".join(sorted(k[8:] for k in cell if k.startswith("trigger_")))] for tag, cell in sorted(table.items())])
        self.assertFalse(problems, "\n".join(problems[:25]))

    def test_zero_balance_draws_are_tallied(self) -> None:
        """``random_policy(allow_zero_balance=True)``: tally the known bug, check everything else."""
        draws = range(40) if STRESS else range(12)
        jobs = []
        for seed in draws:
            rng = random.Random(11000 + seed)
            settings = random_policy(rng, allow_zero_balance=True)
            settings[BALANCE] = (False, 0.0)
            knobs = replace(sample_knobs(rng, "small", planted=True), policy=settings, preferred_rate=0.1, soft_decline_rate=0.1)
            jobs.append(("zero_balance", make_instance(11000 + seed, knobs), BUDGET))
        records = _map(_judge, jobs)
        problems: list[str] = []
        tally: Counter[str] = Counter()
        for record in records:
            tally["solves"] += 1
            tally[f"status_{record['status']}"] += 1
            problems += _problems(record)
            known = "zero_balance_skips_wishes" in record["triggers"]
            tally["triggers_known_bug"] += int(known)
            if record["status"] == "ok":
                tally["second_pass_skipped_with_trigger"] += int(known and not record["second_pass"])
        _record("zero_balance_tally", dict(tally))
        self.assertFalse(problems, "\n".join(problems[:20]))


# --- The conflict message -------------------------------------------------------------------


class ConflictMessageTests(unittest.TestCase):
    """A failed generation names the rules the workplace tightened."""

    def test_constraint_conflict_lists_exactly_the_tightened_rules(self) -> None:
        """Random instances under random policies: every constraint_conflict carries policy.tightened()."""
        draws = range(200) if STRESS else range(50)
        jobs = []
        for seed in draws:
            rng = random.Random(13000 + seed)
            settings = random_policy(rng, allow_zero_balance=False)
            knobs = replace(
                sample_knobs(rng, "small", planted=False),
                policy=settings,
                max_shifts_mode=rng.choice(["tight", "below", "starved"]),
                soft_decline_rate=0.2,
            )
            jobs.append(("conflict", make_instance(13000 + seed, knobs), BUDGET))
        records = _map(_judge, jobs)
        problems: list[str] = []
        tally: Counter[str] = Counter()
        for record in records:
            tally["solves"] += 1
            tally[f"status_{record['status']}"] += 1
            problems += _problems(record)
            if record["status"] != "infeasible":
                continue
            codes = {issue.get("code") for issue in record["issues"]}
            if "constraint_conflict" in codes:
                tally["constraint_conflict"] += 1
                tally[f"reference_{record.get('reference')}"] += 1
                for issue in record["issues"]:
                    if issue.get("code") == "constraint_conflict" and issue.get("tightened_constraints") != record["tightened"]:
                        problems.append(f"{record['label']}: lists {issue.get('tightened_constraints')} not {record['tightened']}")
                tally["conflict_with_tightened"] += int(bool(record["tightened"]))
            else:
                tally["capacity_precheck"] += 1
                tally[f"reference_{record.get('reference')}"] += 1
                if record["tightened"]:
                    tally["capacity_with_tightened_rules_unnamed_known_bug"] += 1
        _record("conflict_tally", dict(tally))
        self.assertFalse(problems, "\n".join(problems[:20]))

    def test_named_rules_follow_the_settings_order(self) -> None:
        """Strict maximum, overstaff and "rather not" together are named in CONSTRAINTS order."""
        people = [_person(1, max_shifts_per_month=2, soft_declined_dates=frozenset({FEB[0]})), _person(2, max_shifts_per_month=2)]
        policy = policy_from_settings({SOFT_DECLINE: (True, 10.0), OVERSTAFF: (True, 1.0), MAX_SHIFTS: (True, 1.0)})
        instance = Instance(people, [_role(0)], 2, 2027, policy=policy)
        outcome = run_solver(instance, BUDGET)
        self.assertEqual(outcome.status, "infeasible")
        conflict = [issue for issue in outcome.issues if issue.get("code") == "constraint_conflict"]
        self.assertEqual(len(conflict), 1, outcome.issues)
        self.assertEqual(conflict[0]["tightened_constraints"], [MAX_SHIFTS, OVERSTAFF, SOFT_DECLINE])

    def test_default_policy_conflict_names_nothing(self) -> None:
        """Nothing tightened: the list is empty, not missing.

        Three people with two days of rest must rotate A, B, C; A cannot
        work 1-3 Feb, which no pair of neighbouring days reveals, so the
        conflict is CBC's.
        """
        people = [_person(1, unavailable_dates=frozenset(FEB[:3])), _person(2), _person(3)]
        instance = Instance(people, [_role(2)], 2, 2027)
        outcome = run_solver(instance, BUDGET)
        self.assertEqual(outcome.status, "infeasible")
        self.assertEqual([issue.get("code") for issue in outcome.issues], ["constraint_conflict"])
        self.assertEqual(outcome.issues[0]["tightened_constraints"], [])


# --- The settings service --------------------------------------------------------------------


def _random_settings(rng: random.Random) -> list[tuple[str, bool, float | None]]:
    """A valid batch of settings for some rules (fixed ones included, as strict)."""
    batch: list[tuple[str, bool, float | None]] = []
    for definition in CONSTRAINTS:
        if rng.random() < 0.4:
            continue
        if definition.mode == MODE_FIXED:
            batch.append((definition.code, True, rng.choice([None, 0.0, 5.0])))
            continue
        strict = definition.mode == MODE_SWITCHABLE and rng.random() < 0.5
        weight = rng.choice([None, 0.0, 0.5, definition.default_weight, 1000.0, MAX_WEIGHT, round(rng.uniform(0, MAX_WEIGHT), 3)])
        batch.append((definition.code, strict, weight))
    rng.shuffle(batch)
    return batch


def _expected_rule(code: str, strict: bool, weight: float | None) -> ConstraintRule:
    """What the policy should say for a saved setting, by the documented rules."""
    definition = DEFINITIONS[code]
    if definition.mode == MODE_FIXED:
        return ConstraintRule(strict=True, weight=0.0)
    return ConstraintRule(strict=strict, weight=float(definition.default_weight if weight is None else weight))


class SettingsServiceTests(unittest.TestCase):
    """Save / load / reset and what a setting may say."""

    def setUp(self) -> None:
        """A fresh database with two workplaces."""
        self._context = fresh_session()
        self.db = self._context.__enter__()
        self.first = Ambulance(name="First", is_active=True)
        self.second = Ambulance(name="Second", is_active=True)
        self.db.add_all([self.first, self.second])
        self.db.commit()

    def tearDown(self) -> None:
        """Close the database."""
        self._context.__exit__(None, None, None)

    def _rows(self, ambulance_id: int) -> dict[str, ConstraintSetting]:
        return {
            row.code: row
            for row in self.db.query(ConstraintSetting).filter(ConstraintSetting.ambulance_id == ambulance_id)
        }

    def test_random_batches_round_trip(self) -> None:
        """Whatever is saved is read back; defaults keep no row; the other workplace is untouched."""
        rng = random.Random(5)
        rounds = 400 if STRESS else 120
        expected: dict[str, ConstraintRule] = {}
        save_constraint_settings(self.db, self.second.id, [(VACATION, False, 3.0)])
        for _ in range(rounds):
            batch = _random_settings(rng)
            save_constraint_settings(self.db, self.first.id, batch)
            for code, strict, weight in batch:
                expected[code] = _expected_rule(code, strict, weight)
            policy = load_constraint_policy(self.db, self.first.id)
            rows = self._rows(self.first.id)
            for definition in CONSTRAINTS:
                code = definition.code
                rule = expected.get(code)
                if definition.mode == MODE_FIXED:
                    self.assertNotIn(code, rows)
                    self.assertTrue(policy.is_strict(code))
                    continue
                if rule is None:
                    self.assertEqual(policy.rule(code), ConstraintPolicy.default().rule(code))
                    continue
                self.assertEqual(policy.rule(code), rule, code)
                is_default = rule.strict == definition.default_strict and rule.weight == definition.default_weight
                self.assertEqual(code not in rows, is_default, code)
            entries = {entry["code"]: entry for entry in constraint_entries(self.db, self.first.id)}
            for code, entry in entries.items():
                rule = policy.rule(code)
                if DEFINITIONS[code].mode == MODE_FIXED:
                    self.assertTrue(entry["is_strict"])
                    self.assertTrue(entry["is_default"])
                    continue
                self.assertEqual(entry["is_strict"], rule.strict)
                self.assertEqual(entry["weight"], rule.weight)
                definition = DEFINITIONS[code]
                self.assertEqual(entry["is_default"], rule.strict == definition.default_strict and rule.weight == definition.default_weight)
        self.assertEqual(load_constraint_policy(self.db, self.second.id).rule(VACATION), ConstraintRule(False, 3.0))
        _record("settings_round_trips", rounds)

    def test_refused_settings_change_nothing(self) -> None:
        """Every invalid setting is refused and leaves the workplace exactly as it was."""
        save_constraint_settings(self.db, self.first.id, [(REST, False, 77.0), (BALANCE, False, 2.0)])
        before = {code: (row.is_strict, row.weight) for code, row in self._rows(self.first.id).items()}
        invalid: list[list[tuple[str, bool, float | None]]] = []
        for definition in CONSTRAINTS:
            if definition.mode == MODE_FIXED:
                invalid.append([(definition.code, False, None)])
            if definition.mode == MODE_PENALTY:
                invalid.append([(definition.code, True, 1.0)])
            if definition.mode != MODE_FIXED:
                for weight in (-0.001, -1.0, MAX_WEIGHT + 0.001, 1e9, math.inf, -math.inf, math.nan):
                    invalid.append([(definition.code, False, weight)])
        invalid.append([(VACATION, False, 5.0), (VACATION, True, 5.0)])
        invalid.append([("no_such_rule", False, 1.0)])
        invalid.append([("", False, 1.0)])
        invalid.append([("Vacation", False, 1.0)])
        refused = 0
        for batch in invalid:
            with self.subTest(batch=batch):
                with self.assertRaises(ConstraintSettingError):
                    save_constraint_settings(self.db, self.first.id, [(VACATION, False, 4.0)] + batch)
                if len(batch) == 1:
                    code, strict, weight = batch[0]
                    with self.assertRaises(ConstraintSettingError):
                        policy_from_settings({code: (strict, weight)})  # type: ignore[dict-item]
                refused += 1
            after = {code: (row.is_strict, row.weight) for code, row in self._rows(self.first.id).items()}
            self.assertEqual(after, before)
        _record("settings_refused_batches", refused)

    def test_edge_weights_are_accepted(self) -> None:
        """0 and the maximum are valid weights; fixed rules accept strict with any weight and store nothing."""
        batch = [(code, False, 0.0) for code in SWITCHABLE + PENALTY_ONLY]
        save_constraint_settings(self.db, self.first.id, batch)
        policy = load_constraint_policy(self.db, self.first.id)
        for code in SWITCHABLE + PENALTY_ONLY:
            self.assertEqual(policy.rule(code), ConstraintRule(False, 0.0))
        save_constraint_settings(self.db, self.first.id, [(code, False, MAX_WEIGHT) for code in SWITCHABLE + PENALTY_ONLY])
        policy = load_constraint_policy(self.db, self.first.id)
        for code in SWITCHABLE + PENALTY_ONLY:
            self.assertEqual(policy.weight(code), MAX_WEIGHT)
        fixed = [definition.code for definition in CONSTRAINTS if definition.mode == MODE_FIXED]
        save_constraint_settings(self.db, self.first.id, [(code, True, 123.0) for code in fixed])
        rows = self._rows(self.first.id)
        self.assertFalse(set(fixed) & set(rows))

    def test_reset_hands_every_rule_back_for_one_workplace_only(self) -> None:
        """Reset removes every row of one workplace and nothing else."""
        rng = random.Random(9)
        save_constraint_settings(self.db, self.first.id, _random_settings(rng))
        save_constraint_settings(self.db, self.second.id, [(REST, False, 9.0)])
        reset_constraint_settings(self.db, self.first.id)
        self.assertEqual(self._rows(self.first.id), {})
        self.assertEqual(load_constraint_policy(self.db, self.first.id).rules, {})
        self.assertTrue(all(entry["is_default"] for entry in constraint_entries(self.db, self.first.id)))
        self.assertEqual(load_constraint_policy(self.db, self.second.id).rule(REST), ConstraintRule(False, 9.0))

    def test_loader_ignores_what_the_code_no_longer_allows(self) -> None:
        """Unknown codes and fixed rules are skipped; a strict penalty-only row keeps only its weight."""
        self.db.add_all(
            [
                ConstraintSetting(ambulance_id=self.first.id, code="retired_rule", is_strict=True, weight=5.0),
                ConstraintSetting(ambulance_id=self.first.id, code="coverage", is_strict=False, weight=1.0),
                ConstraintSetting(ambulance_id=self.first.id, code=BALANCE, is_strict=True, weight=8.0),
                ConstraintSetting(ambulance_id=self.first.id, code=REST, is_strict=False, weight=12.0),
            ]
        )
        self.db.commit()
        policy = load_constraint_policy(self.db, self.first.id)
        self.assertEqual(set(policy.rules), {BALANCE, REST})
        self.assertEqual(policy.rule(BALANCE), ConstraintRule(False, 8.0))
        self.assertTrue(policy.is_strict("coverage"))
        self.assertEqual(policy.rule(REST), ConstraintRule(False, 12.0))

    def test_tightened_lists_switchable_rules_stricter_than_their_default(self) -> None:
        """For many random policies, tightened() is exactly the definition-based list, in order."""
        rng = random.Random(3)
        for _ in range(500):
            settings = random_policy(rng)
            policy = policy_from_settings(settings)
            expected = [
                definition.code
                for definition in CONSTRAINTS
                if definition.mode == MODE_SWITCHABLE and not definition.default_strict and settings.get(definition.code, (False,))[0]
            ]
            self.assertEqual(policy.tightened(), expected)
            self.assertTrue(set(expected) <= {MAX_SHIFTS, OVERSTAFF, SOFT_DECLINE})


if __name__ == "__main__":
    unittest.main()
