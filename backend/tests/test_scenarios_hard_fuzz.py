"""Hard-constraint fuzzing of the monthly schedule generator.

Planted and random instances are swept over every size (tiny, small,
medium, large, xl) and every knob profile the harness offers: recovery,
duty length, demand shape, days of rest, duties elsewhere, duties around
the month, absences, qualification structure, unqualified staff, roles
asking for nobody, history before ``generate_from`` and rule-breaking
manual placements. Every solve is judged by the same checks:

1. a returned roster keeps every hard rule (``oracle.validate``);
2. a planted instance is never called infeasible (a timeout with no
   roster at all is tallied separately);
3. an ``infeasible`` verdict on a random instance is confirmed by the
   independent reference model (``'unknown'`` is tallied as unconfirmed);
4. every capacity pre-check issue the solver gives as its reason
   (``insufficient_daily_capacity``, ``insufficient_qualified_staff``,
   ``insufficient_consecutive_day_rotation``,
   ``insufficient_consecutive_day_capacity``) is recomputed from the
   instance alone: the claimed ``required_count`` and ``available_count``
   must be the true ones, and the claim must really prove the shortage;
5. where the run did not hit its budget, the roster is no worse than the
   witness in first-pass cost, and the oracle's local search finds no
   ``first_pass`` or ``day_wish`` improvement (small instances only).

Default mode runs a deterministic sweep in a few minutes; the heavier sweep
runs only with ``SCHEDULING_STRESS=1``. ``HARD_FUZZ_METRICS=<path>`` writes
every per-solve record as JSON for reporting.
"""

from __future__ import annotations

import json
import os
import random
import statistics
import unittest
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, field, replace
from datetime import date, timedelta
from typing import Any, Iterable

from app.services.constraint_setting_service import (
    REST,
    SOFT_DECLINE,
    UNAVAILABLE,
    policy_from_settings,
)
from app.services.schedule_generation_service import SchedulingCompetence, SchedulingEmployee

from tests.scheduling_harness.instances import (
    Instance,
    Knobs,
    PlantingFailed,
    make_instance,
    sample_knobs,
    stress_knobs,
    tiny_knobs,
)
from tests.scheduling_harness.known_bugs import known_bug_triggers
from tests.scheduling_harness.oracle import (
    find_improving_moves,
    first_pass_cost,
    validate,
    violation_codes,
)
from tests.scheduling_harness.reference import reference_feasibility
from tests.scheduling_harness.runner import run_solver
from tests.scheduling_harness.semantics import (
    Duty,
    absence_rule,
    balance_lock_slack,
    collide,
    demand,
    duty_rest,
    external_duties,
    fixed_counts,
)

STRESS = os.environ.get("SCHEDULING_STRESS") == "1"
#: One other agent shares the machine: never more than six CBC processes.
#: Each worker runs the solver and then, if needed, the reference model, so
#: one worker never has two CBC processes at once.
WORKERS = 6

CAPACITY_CODES = (
    "insufficient_daily_capacity",
    "insufficient_qualified_staff",
    "insufficient_consecutive_day_rotation",
    "insufficient_consecutive_day_capacity",
)

#: Solver budget per size, in seconds.
BUDGETS: dict[str, float] = {
    "tiny": 5,
    "small": 10,
    "stress": 10,
    "capacity": 10,
    "medium": 20,
    "large": 30,
    "xl": 30,
}
#: Reference-model time limit per size, in seconds.
REFERENCE_LIMITS: dict[str, float] = {
    "tiny": 30,
    "small": 30,
    "stress": 30,
    "capacity": 30,
    "medium": 60,
    "large": 120,
    "xl": 120,
}
#: Sizes on which the local-search optimality probe runs.
MOVE_SIZES = frozenset({"tiny", "small", "stress"})

#: One override set per knob profile, applied on top of ``sample_knobs``.
PROFILES: dict[str, dict[str, Any]] = {
    "recovery_zero": {"recovery_profile": "zero"},
    "recovery_one": {"recovery_profile": "one"},
    "recovery_mixed": {"recovery_profile": "mixed"},
    "recovery_long": {"recovery_profile": "long"},
    "hours_uniform4": {"hours_profile": "uniform4"},
    "hours_uniform12": {"hours_profile": "uniform12"},
    "hours_mixed": {"hours_profile": "mixed"},
    "hours_fractional": {"hours_profile": "fractional"},
    "demand_flat": {"demand_profile": "flat"},
    "demand_weekday": {"demand_profile": "weekday"},
    "demand_sparse": {"demand_profile": "sparse"},
    "demand_heavy": {"demand_profile": "heavy"},
    "demand_mixed": {"demand_profile": "mixed"},
    "special_none": {"special_days": "none"},
    "special_library": {"special_days": "library"},
    "special_random": {"special_days": "random", "special_rate": 0.15},
    "special_mixed": {"special_days": "mixed"},
    "externals_explicit": {"external_rate": 0.06, "external_explicit_rest": 1.0},
    "externals_fallback": {"external_rate": 0.06, "external_explicit_rest": 0.0},
    "adjacent": {"adjacent_rate": 0.9, "adjacent_retired_competence": False},
    "adjacent_retired": {"adjacent_rate": 0.9, "adjacent_retired_competence": True},
    "absences_single": {"unavailability_rate": 0.15, "absence_mix": (0.5, 0.3, 0.2)},
    "absences_blocks": {"vacation_block_rate": 0.4, "block_cluster": False},
    "absences_clustered": {"vacation_block_rate": 0.4, "block_cluster": True},
    "qualification_iid": {"qualification_structure": "iid"},
    "qualification_hierarchy": {"qualification_structure": "hierarchy"},
    "qualification_rare": {"qualification_structure": "rare"},
    "unqualified_staff": {"unqualified_employee_rate": 0.3},
    "zero_demand_role": {"zero_demand_competences": 1},
    "history_mid": {"generate_from": "mid", "keep_history": 0.8},
    "breaking_placements": {"n_breaking_fixed": 3, "n_fixed": 2},
    "pinned_share": {"fixed_share": 0.5, "fixed_full_days": 2},
}
#: Profiles that need at least two roles to mean anything.
TWO_ROLE_PROFILES = frozenset({"zero_demand_role", "qualification_rare"})


# --- Jobs and records -------------------------------------------------------------------


@dataclass(frozen=True)
class Job:
    """One instance to build and judge inside a worker process."""

    family: str
    size: str
    seed: int
    knobs: Knobs
    moves: bool = False


@dataclass
class Record:
    """What one solve of one instance showed, as plain data."""

    family: str
    size: str
    seed: int
    planted: bool
    label: str = ""
    built: bool = True
    status: str = ""
    seconds: float = 0.0
    hit_budget: bool = False
    #: The wish pass ended with no roster (status 0): a budget hit too.
    wish_pass_empty: bool = False
    n_employees: int = 0
    n_competences: int = 0
    spares: int = 0
    triggers: list[str] = field(default_factory=list)
    issue_codes: list[str] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)
    reference: str | None = None
    reference_seconds: float = 0.0
    claims_checked: int = 0
    claim_errors: list[str] = field(default_factory=list)
    completeness_errors: list[str] = field(default_factory=list)
    independent_shortfalls: int = 0
    witness_gap: float | None = None
    cost_checked: bool = False
    cost_excess: float | None = None
    moves_checked: bool = False
    bad_moves: list[str] = field(default_factory=list)
    error: str | None = None
    first_pass_status: int | None = None
    duties: int = 0
    fixed: int = 0


# --- Independent capacity bookkeeping ------------------------------------------------------


@dataclass
class _Capacity:
    """Who could hold which slot, recomputed from the documented rules only."""

    candidates: dict[tuple[int, date], set[int]]
    daily: dict[date, set[int]]
    fixed_by_date: dict[date, list[tuple[int, int]]]
    demand: dict[tuple[int, date], int]
    rest_strict: bool


def _capacity(instance: Instance) -> _Capacity:
    """Recompute every window slot's possible holders from the instance alone.

    A person may hold slot ``(k, d)`` when it is one of their manual
    placements, or when they hold ``k``, the role asks for somebody on
    ``d``, the day is no strict absence or strict "rather not", and no
    commitment they already owe (placements anywhere in the month, duties
    around the month, duties elsewhere) falls on ``d`` or, while rest is
    strict, collides with a duty on ``d``. The monthly maximum is ignored,
    which only makes the count larger.
    """
    policy = instance.effective_policy
    rest_strict = policy.is_strict(REST)
    soft_strict = policy.is_strict(SOFT_DECLINE)
    competences = instance.competence_map
    month = instance.day_set
    fixed = frozenset(duty for duty in instance.fixed if duty[2] in month)
    owed: dict[int, list[tuple[date, int]]] = defaultdict(list)
    for user_id, competence_id, work_date in fixed:
        owed[user_id].append((work_date, duty_rest(competences, competence_id, work_date)))
    for user_id, competence_id, work_date in instance.adjacent:
        owed[user_id].append((work_date, duty_rest(competences, competence_id, work_date)))
    for employee in instance.employees:
        owed[employee.id].extend(external_duties(employee, instance.competences))

    candidates: dict[tuple[int, date], set[int]] = defaultdict(set)
    daily: dict[date, set[int]] = defaultdict(set)
    window = set(instance.window_days)
    for user_id, competence_id, work_date in fixed:
        if work_date in window:
            candidates[(competence_id, work_date)].add(user_id)
            daily[work_date].add(user_id)
    for employee in instance.employees:
        for competence in instance.competences:
            if competence.id not in employee.competence_ids:
                continue
            for work_date in instance.window_days:
                if competence.required_on(work_date) == 0:
                    continue
                rule = absence_rule(employee, work_date)
                if rule is not None and policy.is_strict(rule):
                    continue
                if soft_strict and work_date in employee.soft_declined_dates:
                    continue
                rest = int(competence.recovery_days_on(work_date))
                if any(
                    other == work_date
                    or (rest_strict and collide(work_date, rest, other, other_rest))
                    for other, other_rest in owed[employee.id]
                ):
                    continue
                candidates[(competence.id, work_date)].add(employee.id)
                daily[work_date].add(employee.id)
    fixed_by_date: dict[date, list[tuple[int, int]]] = defaultdict(list)
    for user_id, competence_id, work_date in fixed:
        fixed_by_date[work_date].append((user_id, competence_id))
    placed = fixed_counts(fixed)
    needed = {
        (competence.id, work_date): demand(competence, work_date, placed)
        for competence in instance.competences
        for work_date in instance.window_days
    }
    return _Capacity(candidates, daily, fixed_by_date, needed, rest_strict)


def _extra_placed(
    capacity: _Capacity, days: Iterable[date], competence_id: int | None = None
) -> int:
    """Duties beyond one per person among the placements of some days.

    Each such duty is one more slot its holder covers than the head count
    says (two roles on a day, or two days inside one rest).
    """
    per_user = Counter(
        user_id
        for day in days
        for user_id, placed_competence in capacity.fixed_by_date.get(day, ())
        if competence_id is None or placed_competence == competence_id
    )
    return sum(count - 1 for count in per_user.values() if count > 1)


def _true_shortfalls(instance: Instance, capacity: _Capacity) -> dict[tuple, tuple[int, int]]:
    """Every capacity shortage the documented pre-check should find.

    Keys are ``(code, work_date, next_work_date, competence_id)`` and values
    ``(required, available)``. The two-day checks run only while rest is
    strict and only when no single-day shortage was found, as the model
    doc describes; each of them is a proof of infeasibility on its own.
    """
    found: dict[tuple, tuple[int, int]] = {}
    days = instance.window_days
    for day in days:
        required = sum(capacity.demand[(competence.id, day)] for competence in instance.competences)
        available = len(capacity.daily.get(day, set())) + _extra_placed(capacity, (day,))
        if available < required:
            found[("insufficient_daily_capacity", day, None, None)] = (required, available)
        for competence in instance.competences:
            required = capacity.demand[(competence.id, day)]
            available = len(capacity.candidates.get((competence.id, day), set()))
            if available < required:
                found[("insufficient_qualified_staff", day, None, competence.id)] = (
                    required,
                    available,
                )
    if found or not capacity.rest_strict:
        return found
    for day, following in zip(days, days[1:]):
        for competence in instance.competences:
            if competence.recovery_days_on(day) < 1:
                continue
            people = capacity.candidates.get((competence.id, day), set()) | capacity.candidates.get(
                (competence.id, following), set()
            )
            available = len(people) + _extra_placed(capacity, (day, following), competence.id)
            required = capacity.demand[(competence.id, day)] + capacity.demand[
                (competence.id, following)
            ]
            if available < required:
                found[("insufficient_consecutive_day_rotation", day, following, competence.id)] = (
                    required,
                    available,
                )
        if any(competence.recovery_days_on(day) < 1 for competence in instance.competences):
            continue
        people = capacity.daily.get(day, set()) | capacity.daily.get(following, set())
        available = len(people) + _extra_placed(capacity, (day, following))
        required = sum(
            capacity.demand[(competence.id, day)] + capacity.demand[(competence.id, following)]
            for competence in instance.competences
        )
        if available < required:
            found[("insufficient_consecutive_day_capacity", day, following, None)] = (
                required,
                available,
            )
    return found


def _issue_key(issue: dict) -> tuple:
    """The identity of one capacity issue, in the shape of :func:`_true_shortfalls`."""
    following = issue.get("next_work_date")
    return (
        issue["code"],
        date.fromisoformat(issue["work_date"]),
        date.fromisoformat(following) if following else None,
        issue.get("competence_id"),
    )


def _upper_bound(instance: Instance, capacity: _Capacity, key: tuple) -> tuple[int, int]:
    """``(required, available)`` for any claimed issue, shortage or not."""
    code, day, following, competence_id = key
    if code == "insufficient_daily_capacity":
        required = sum(capacity.demand[(k.id, day)] for k in instance.competences)
        return required, len(capacity.daily.get(day, set())) + _extra_placed(capacity, (day,))
    if code == "insufficient_qualified_staff":
        return capacity.demand[(competence_id, day)], len(
            capacity.candidates.get((competence_id, day), set())
        )
    if code == "insufficient_consecutive_day_rotation":
        people = capacity.candidates.get((competence_id, day), set()) | capacity.candidates.get(
            (competence_id, following), set()
        )
        return (
            capacity.demand[(competence_id, day)] + capacity.demand[(competence_id, following)],
            len(people) + _extra_placed(capacity, (day, following), competence_id),
        )
    people = capacity.daily.get(day, set()) | capacity.daily.get(following, set())
    required = sum(
        capacity.demand[(k.id, day)] + capacity.demand[(k.id, following)]
        for k in instance.competences
    )
    return required, len(people) + _extra_placed(capacity, (day, following))


def _check_claims(instance: Instance, issues: list[dict], record: Record) -> None:
    """Recompute every capacity issue the solver reported and compare."""
    capacity = _capacity(instance)
    truth = _true_shortfalls(instance, capacity)
    record.independent_shortfalls = len(truth)
    claimed = [issue for issue in issues if issue.get("code") in CAPACITY_CODES]
    window = set(instance.window_days)
    for issue in claimed:
        record.claims_checked += 1
        key = _issue_key(issue)
        if key[1] not in window or (key[2] is not None and key[2] not in window):
            record.claim_errors.append(f"{key}: date outside the window")
            continue
        if key[3] is not None and key[3] not in instance.competence_map:
            record.claim_errors.append(f"{key}: unknown competence")
            continue
        required, available = _upper_bound(instance, capacity, key)
        if available >= required:
            record.claim_errors.append(
                f"{key}: claimed {issue['available_count']}<{issue['required_count']}, "
                f"true capacity {available} for {required}"
            )
        elif (issue["required_count"], issue["available_count"]) != (required, available):
            record.claim_errors.append(
                f"{key}: claimed {issue['available_count']}/{issue['required_count']}, "
                f"recomputed {available}/{required}"
            )
    if claimed:
        reported = {_issue_key(issue) for issue in claimed}
        for key in sorted(set(truth) - reported, key=str):
            record.completeness_errors.append(f"missed {key} {truth[key]}")
        for key in sorted(reported - set(truth), key=str):
            record.completeness_errors.append(f"extra {key}")
    elif truth and record.status in ("ok", "infeasible", "timeout"):
        # A shortage the pre-check should have reported but did not.
        record.completeness_errors.append(
            f"unreported {sorted(truth, key=str)[0]} (+{len(truth) - 1} more)"
        )


# --- The worker ---------------------------------------------------------------------------


def judge(job: Job) -> Record:
    """Build, solve and judge one instance; runs in a worker process."""
    record = Record(job.family, job.size, job.seed, job.knobs.planted)
    try:
        instance = make_instance(job.seed, job.knobs)
    except PlantingFailed:
        record.built = False
        return record
    record.label = instance.label
    record.n_employees = len(instance.employees)
    record.n_competences = len(instance.competences)
    record.spares = instance.spares
    record.fixed = len(instance.fixed)
    record.triggers = sorted(known_bug_triggers(instance))
    outcome = run_solver(instance, BUDGETS[job.size], observe=True)
    record.status = outcome.status
    record.seconds = round(outcome.seconds, 3)
    second = outcome.second_pass
    record.wish_pass_empty = second is not None and second.sol_status == 0
    record.hit_budget = (
        outcome.hit_budget
        or record.wish_pass_empty
        or outcome.seconds >= 0.9 * BUDGETS[job.size]
    )
    record.issue_codes = sorted(outcome.issue_codes)
    record.error = outcome.error if outcome.status == "error" else None
    record.duties = len(outcome.assignments)
    if outcome.first_pass is not None:
        record.first_pass_status = outcome.first_pass.sol_status

    if outcome.status == "ok":
        record.violations = sorted(violation_codes(validate(instance, outcome.assignments)))
    _check_claims(instance, outcome.issues, record)

    needs_reference = (outcome.status == "infeasible" and not job.knobs.planted) or (
        outcome.status == "timeout"
    )
    if needs_reference:
        from time import perf_counter

        started = perf_counter()
        status, _roster = reference_feasibility(instance, time_limit=REFERENCE_LIMITS[job.size])
        record.reference = status
        record.reference_seconds = round(perf_counter() - started, 3)

    if outcome.status == "ok" and not record.violations and not record.hit_budget:
        if instance.witness is not None and "balance_lock_drift" not in record.triggers:
            record.cost_checked = True
            reached = first_pass_cost(instance, outcome.assignments)
            witness = first_pass_cost(instance, instance.witness)
            record.witness_gap = round(reached - witness, 6)
            excess = reached - witness - balance_lock_slack(witness)
            if excess > 0:
                record.cost_excess = excess
        if job.moves:
            record.moves_checked = True
            moves = find_improving_moves(
                instance, outcome.assignments, max_checks=6000, balance_cap=outcome.balance_cap
            )
            for move in moves:
                if move.reason == "first_pass":
                    record.bad_moves.append(f"first_pass {move.kind} {move.first_pass_delta:.4g}")
                elif move.reason == "day_wish" and "zero_balance_skips_wishes" not in record.triggers:
                    record.bad_moves.append(f"day_wish {move.kind} {move.day_wish_delta:.4g}")
    return record


def run_jobs(jobs: list[Job]) -> list[Record]:
    """Judge jobs in at most :data:`WORKERS` processes, records in job order."""
    if len(jobs) <= 1:
        return [judge(job) for job in jobs]
    with ProcessPoolExecutor(max_workers=WORKERS) as pool:
        return list(pool.map(judge, jobs, chunksize=1))


# --- Job builders --------------------------------------------------------------------------


def _profile_knobs(rng: random.Random, profile: str, size: str, planted: bool) -> Knobs:
    """Sampled knobs of one size with one profile forced on."""
    knobs = sample_knobs(rng, size, planted)
    overrides = dict(PROFILES[profile])
    if profile in TWO_ROLE_PROFILES and knobs.n_competences < 2:
        overrides["n_competences"] = 2
    if planted:
        overrides.setdefault("max_spares", 12)
    return replace(knobs, **overrides)


def profile_jobs(sizes: dict[str, int], seed_base: int) -> list[Job]:
    """For every profile and size: that many planted and random instances."""
    jobs: list[Job] = []
    for index, profile in enumerate(sorted(PROFILES)):
        for size, count in sizes.items():
            for repeat in range(count):
                for planted in (True, False):
                    seed = seed_base + 1000 * index + 10 * repeat + (0 if planted else 5)
                    rng = random.Random(f"{profile}-{size}-{seed}")
                    jobs.append(
                        Job(
                            profile,
                            size,
                            seed,
                            _profile_knobs(rng, profile, size, planted),
                            moves=size in MOVE_SIZES,
                        )
                    )
    return jobs


def size_jobs(counts: dict[str, int], seed_base: int) -> list[Job]:
    """Plain ``sample_knobs`` / ``tiny_knobs`` / ``stress_knobs`` instances per size."""
    jobs: list[Job] = []
    for size, count in counts.items():
        for repeat in range(count):
            for planted in (True, False):
                seed = seed_base + 37 * repeat + (0 if planted else 17)
                rng = random.Random(f"size-{size}-{seed}")
                if size == "tiny":
                    knobs = tiny_knobs(rng, planted)
                elif size == "stress":
                    knobs = stress_knobs(rng, planted)
                else:
                    knobs = sample_knobs(rng, size, planted)
                    if planted:
                        knobs = replace(knobs, max_spares=20)
                jobs.append(Job(f"size_{size}", size, seed, knobs, moves=size in MOVE_SIZES))
    return jobs


def capacity_jobs(count: int, seed_base: int) -> list[Job]:
    """Random instances tuned to sit right at the capacity edge.

    High utilization, long rests, absences and strict rules make every one
    of the four pre-check codes fire now and then, so their content can be
    recomputed; some of them stay feasible, which checks the other side.
    """
    jobs: list[Job] = []
    for repeat in range(count):
        seed = seed_base + repeat
        rng = random.Random(f"capacity-{seed}")
        knobs = sample_knobs(rng, rng.choice(["small", "small", "medium"]), planted=False)
        knobs = replace(
            knobs,
            target_utilization=rng.choice([0.8, 0.95, 1.05, 1.2]),
            recovery_profile=rng.choice(["one", "mixed", "long"]),
            unavailability_rate=rng.choice([0.0, 0.1, 0.25]),
            vacation_block_rate=rng.choice([0.0, 0.3]),
            n_breaking_fixed=rng.choice([0, 0, 2]),
            n_fixed=rng.choice([0, 3]),
            policy=rng.choice(
                [None, {"rest": (True, 1000.0)}, {"soft_decline": (True, 10.0)}, {"rest": (False, 5.0)}]
            ),
            generate_from=rng.choice([None, None, "mid"]),
        )
        size = "capacity"
        jobs.append(Job("capacity_edge", size, seed, knobs, moves=False))
    return jobs


# --- Reporting -----------------------------------------------------------------------------

_ALL_RECORDS: list[Record] = []


def failures_of(record: Record) -> list[str]:
    """The hard-check failures one record shows (empty when it passed)."""
    found: list[str] = []
    if not record.built:
        return found
    if record.status == "error":
        found.append(f"solver error: {record.error}")
    if record.violations and "duplicate_external_dates" not in record.triggers:
        found.append(f"invalid roster: {record.violations}")
    if record.planted and record.status == "infeasible":
        found.append(f"planted instance called infeasible: {record.issue_codes}")
    if record.reference == "feasible" and record.status == "infeasible":
        found.append(f"feasible instance called infeasible: {record.issue_codes}")
    if record.claim_errors and "duplicate_external_dates" not in record.triggers:
        found.append(f"wrong capacity claims: {record.claim_errors[:3]}")
    if record.cost_excess is not None:
        found.append(f"worse than witness by {record.cost_excess:.4g}")
    if record.bad_moves:
        found.append(f"improving moves: {record.bad_moves[:3]}")
    return found


def summarize(records: list[Record], by: str) -> list[dict[str, Any]]:
    """Counts and timings per value of one record attribute."""
    groups: dict[str, list[Record]] = defaultdict(list)
    for record in records:
        groups[str(getattr(record, by))].append(record)
    rows = []
    for key in sorted(groups):
        group = [record for record in groups[key] if record.built]
        seconds = sorted(record.seconds for record in group)
        rows.append(
            {
                by: key,
                "solves": len(group),
                "unbuilt": len(groups[key]) - len(group),
                "planted": sum(record.planted for record in group),
                "ok": sum(record.status == "ok" for record in group),
                "infeasible": sum(record.status == "infeasible" for record in group),
                "inf_confirmed": sum(
                    record.status == "infeasible" and record.reference == "infeasible"
                    for record in group
                ),
                "inf_unknown": sum(
                    record.status == "infeasible" and record.reference == "unknown"
                    for record in group
                ),
                "timeouts": sum(record.status == "timeout" for record in group),
                "errors": sum(record.status == "error" for record in group),
                "invalid": sum(bool(record.violations) for record in group),
                "hit_budget": sum(record.hit_budget for record in group),
                "wish_pass_empty": sum(record.wish_pass_empty for record in group),
                "claims": sum(record.claims_checked for record in group),
                "claim_errors": sum(len(record.claim_errors) for record in group),
                "incomplete": sum(bool(record.completeness_errors) for record in group),
                "cost_checked": sum(record.cost_checked for record in group),
                "moves_checked": sum(record.moves_checked for record in group),
                "failures": sum(bool(failures_of(record)) for record in group),
                "median_s": round(statistics.median(seconds), 2) if seconds else None,
                "max_s": round(seconds[-1], 2) if seconds else None,
            }
        )
    return rows


def tearDownModule() -> None:  # noqa: N802 - unittest hook
    """Print the sweep's tallies and optionally write every record as JSON."""
    if not _ALL_RECORDS:
        return
    for by in ("size", "family"):
        print(f"\n=== hard_fuzz by {by} ===")
        for row in summarize(_ALL_RECORDS, by):
            print(row)
    path = os.environ.get("HARD_FUZZ_METRICS")
    if path:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump([asdict(record) for record in _ALL_RECORDS], handle, default=str, indent=1)


# --- Tests ---------------------------------------------------------------------------------


class HardFuzzBase(unittest.TestCase):
    """Shared assertion over a batch of records."""

    def assert_clean(self, records: list[Record]) -> None:
        """Every record passes every hard check; the failures are listed."""
        _ALL_RECORDS.extend(records)
        failed = {
            f"{record.family}/{record.size}/{record.label or record.seed}": failures_of(record)
            for record in records
            if failures_of(record)
        }
        self.assertEqual(failed, {}, f"{len(failed)} of {len(records)} instances failed")
        built = [record for record in records if record.built]
        self.assertGreater(len(built), 0)


class DefaultSweepTests(HardFuzzBase):
    """The deterministic default sweep: every profile once, every size a few times."""

    def test_every_profile_small_planted_and_random(self) -> None:
        """Each knob profile on two planted and two random small instances."""
        self.assert_clean(run_jobs(profile_jobs({"small": 2}, seed_base=100)))

    def test_every_size(self) -> None:
        """Tiny, rule-breaking stress, medium, large and xl instances, planted and random."""
        self.assert_clean(
            run_jobs(
                size_jobs({"xl": 1, "large": 1, "medium": 3, "stress": 12, "tiny": 24}, seed_base=7)
            )
        )

    def test_capacity_edge_claims_are_true(self) -> None:
        """Random instances at the capacity edge: every pre-check claim is recomputed."""
        records = run_jobs(capacity_jobs(48, seed_base=500))
        self.assert_clean(records)
        self.assertGreater(sum(record.claims_checked for record in records), 0)


def _role(competence_id: int, rest: int, required: int = 1) -> SchedulingCompetence:
    """A role asking for ``required`` people every day, each duty earning ``rest`` days."""
    return SchedulingCompetence(
        id=competence_id,
        name=f"Role {competence_id}",
        required_count=required,
        weekday_required_counts=(required,) * 7,
        weekday_recovery_days=(rest,) * 7,
    )


def _person(user_id: int, roles: Iterable[int], **fields: Any) -> SchedulingEmployee:
    """An employee holding ``roles`` with nothing else unless given."""
    return SchedulingEmployee(
        id=user_id,
        email=f"p{user_id}@example.test",
        full_name=None,
        competence_ids=frozenset(roles),
        unavailable_dates=fields.pop("unavailable_dates", frozenset()),
        externally_scheduled_dates=frozenset(),
        **fields,
    )


def _handmade_record(name: str, instance: Instance) -> Record:
    """Solve a hand-built instance and judge it like a random one."""
    record = Record("handmade", "handmade", 0, False, label=name)
    outcome = run_solver(instance, 10, observe=True)
    record.status = outcome.status
    record.issue_codes = sorted(outcome.issue_codes)
    if outcome.status == "ok":
        record.violations = sorted(violation_codes(validate(instance, outcome.assignments)))
    _check_claims(instance, outcome.issues, record)
    if outcome.status in ("infeasible", "timeout"):
        record.reference = reference_feasibility(instance, time_limit=30)[0]
    return record


class HandmadePreCheckTests(HardFuzzBase):
    """Corners of the capacity pre-check, each built by hand with a known answer."""

    AUGUST = (8, 2026)

    def _instance(self, employees, competences, **fields: Any) -> Instance:
        month, year = self.AUGUST
        return Instance(employees=employees, competences=competences, month=month, year=year, **fields)

    def test_corners(self) -> None:
        """Every corner: the verdict, the issue codes and their counts are as derived by hand."""
        last = date(2026, 8, 31)
        away = frozenset(date(2026, 8, day) for day in range(1, 32))
        cases: list[tuple[str, Instance, str, set[str]]] = [
            # One person, one role with a day of rest: every pair of days needs two
            # (in that role, and over all roles).
            ("rotation", self._instance([_person(1, [1])], [_role(1, 1)]), "infeasible",
             {"insufficient_consecutive_day_rotation", "insufficient_consecutive_day_capacity"}),
            # Two people, two roles every day, rest 1: both days together need four.
            ("consecutive", self._instance([_person(1, [1, 2]), _person(2, [1, 2])], [_role(1, 1), _role(2, 1)]),
             "infeasible", {"insufficient_consecutive_day_capacity"}),
            # Role 1 earns no rest, so the two-day capacity check must not fire,
            # but role 2's rest still makes the month infeasible (the MILP finds it).
            ("mixed_rest", self._instance([_person(1, [1, 2]), _person(2, [1, 2])], [_role(1, 0), _role(2, 1)]),
             "infeasible", {"constraint_conflict"}),
            # No rest anywhere: two people cover two roles every day.
            ("no_rest", self._instance([_person(1, [1, 2]), _person(2, [1, 2])], [_role(1, 0), _role(2, 0)]),
             "ok", set()),
            # One person placed in both roles on the only window day: the
            # doubled placement covers two slots.
            ("doubled_placement", self._instance(
                [_person(1, [1, 2])], [_role(1, 0), _role(2, 0)],
                fixed=frozenset({(1, 1, last), (1, 2, last)}), generate_from=last), "ok", set()),
            # A penalized rest lets one person work every day.
            ("penalized_rest", self._instance([_person(1, [1])], [_role(1, 1)],
                                              policy=policy_from_settings({REST: (False, 10.0)})), "ok", set()),
            # Absent all month: strict refuses with a per-role shortage, penalized works.
            ("strict_absence", self._instance([_person(1, [1], unavailable_dates=away)], [_role(1, 0)]),
             "infeasible", {"insufficient_qualified_staff", "insufficient_daily_capacity"}),
            ("penalized_absence", self._instance(
                [_person(1, [1], unavailable_dates=away)], [_role(1, 0)],
                policy=policy_from_settings({UNAVAILABLE: (False, 1000.0)})), "ok", set()),
        ]
        records = []
        for name, instance, expected, codes in cases:
            record = _handmade_record(name, instance)
            records.append(record)
            with self.subTest(name):
                self.assertEqual(record.status, expected, record.issue_codes)
                self.assertEqual(set(record.issue_codes), codes)
                self.assertEqual(record.claim_errors, [])
                self.assertEqual(record.completeness_errors, [])
                if expected == "infeasible":
                    self.assertEqual(record.reference, "infeasible")
        self.assert_clean(records)


@unittest.skipUnless(STRESS, "set SCHEDULING_STRESS=1 for the heavy sweep")
class StressSweepTests(HardFuzzBase):
    """The heavy sweep: every profile at several sizes, many more seeds."""

    def test_stress_profiles_small_and_medium(self) -> None:
        """Every profile: six small, two medium and one large instance, planted and random."""
        self.assert_clean(run_jobs(profile_jobs({"small": 6, "medium": 2, "large": 1}, seed_base=20_000)))

    def test_stress_sizes(self) -> None:
        """Many tiny and stress instances, several large and xl ones."""
        self.assert_clean(
            run_jobs(
                size_jobs(
                    {"xl": 6, "large": 6, "medium": 8, "small": 30, "stress": 60, "tiny": 100},
                    seed_base=30_000,
                )
            )
        )

    def test_stress_capacity_edge(self) -> None:
        """Many random capacity-edge instances."""
        self.assert_clean(run_jobs(capacity_jobs(250, seed_base=40_000)))


if __name__ == "__main__":
    unittest.main()
