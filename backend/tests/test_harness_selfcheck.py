"""Self-checks of the scheduling test harness.

Before the harness is trusted to judge the solver, it has to be shown to be
right and to have teeth: the oracle must flag each kind of broken roster with
exactly the right code and stay silent on good ones, planted instances must
really be feasible, the independent feasibility judges must agree with each
other and with a pruning-free enumeration, the objective must match hand
computation, instances must be reproducible in any interpreter, and the
database writer must hand the loader exactly the problem the in-memory
instance describes.

The last class, :class:`KnownSolverBugTests`, holds one minimal reproduction
per solver bug the harness found, each marked ``expectedFailure`` (see
``tests/scheduling_harness/known_bugs.py``).
"""

from __future__ import annotations

import hashlib
import itertools
import os
import random
import subprocess
import sys
import unittest
from collections import Counter
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from typing import Callable
from unittest import mock

from app.models import Unavailability
from app.services import schedule_context_service
from app.services.constraint_setting_service import (
    BALANCE,
    CONSTRAINTS,
    MAX_SHIFTS,
    OVERSTAFF,
    REST,
    SOFT_DECLINE,
    VACATION,
    ConstraintPolicy,
    policy_from_settings,
)
from app.services.schedule_generation_service import (
    SchedulingCompetence,
    SchedulingEmployee,
    generate_ambulance_monthly_schedule,
)

from tests.scheduling_harness.db_builder import (
    InexpressibleInstance,
    calendar_span,
    fresh_session,
    materialize,
    run_db_solver,
)
from tests.scheduling_harness.instances import (
    POLICY_PRESETS,
    RETIRED_COMPETENCE_ID,
    Instance,
    Knobs,
    PlantingFailed,
    fill_in_knobs,
    knobs_of,
    make_instance,
    pigeonhole_instance,
    random_policy,
    sample_knobs,
    stress_knobs,
    symmetric_instance,
    tiny_knobs,
    ultra_tiny_knobs,
    unconfigured_competence,
)
from tests.scheduling_harness.known_bugs import KNOWN_BUGS, db_bug_triggers, known_bug_triggers
from tests.scheduling_harness.oracle import (
    day_wish_cost,
    eligible,
    find_improving_moves,
    first_pass_cost,
    metrics,
    validate,
    violation_codes,
)
from tests.scheduling_harness.reference import brute_force, reference_feasibility
from tests.scheduling_harness.runner import run_solver, solve_in_parallel
from tests.scheduling_harness.scenarios import (
    CHANGES,
    chain_months,
    regenerate,
    repair,
)
from tests.scheduling_harness.semantics import (
    Duty,
    absence_rule,
    duty_rest,
    external_duties,
    has_duplicate_external_dates,
    holds,
    ladder_cost,
)

Roster = list[Duty]
BACKEND = Path(__file__).resolve().parents[1]


# --- Helpers ----------------------------------------------------------------------------


def _competence(
    competence_id: int = 1,
    counts: tuple[int, ...] = (1,) * 8,
    recovery: tuple[int, ...] = (1,) * 8,
    hours: tuple[float, ...] = (4.0,) * 8,
    surcharge: tuple[bool, ...] = (False,) * 5 + (True,) * 3,
    special: frozenset[date] = frozenset(),
) -> SchedulingCompetence:
    """A competence with all eight slots given explicitly."""
    return SchedulingCompetence(
        id=competence_id,
        name=f"Role {competence_id}",
        required_count=max(1, counts[0]),
        weekday_required_counts=tuple(counts[:7]),
        special_day_required_count=counts[7],
        special_dates=special,
        weekday_is_surcharge=tuple(surcharge[:7]),
        special_day_is_surcharge=surcharge[7],
        weekday_recovery_days=tuple(recovery[:7]),
        special_day_recovery_days=recovery[7],
        weekday_shift_hours=tuple(hours[:7]),
        special_day_shift_hours=hours[7],
    )


def _employee(user_id: int, competence_ids: frozenset[int] = frozenset({1}), **extra) -> SchedulingEmployee:
    """An employee holding the given competences, with optional extras."""
    fields = {
        "id": user_id,
        "email": f"e{user_id}@harness.test",
        "full_name": f"E {user_id}",
        "competence_ids": competence_ids,
        "unavailable_dates": frozenset(),
        "externally_scheduled_dates": frozenset(),
    }
    fields.update(extra)
    return SchedulingEmployee(**fields)


def _with_employee(instance: Instance, user_id: int, **changes) -> Instance:
    """A copy of the instance with one employee's fields changed."""
    employees = [
        replace(employee, **changes) if employee.id == user_id else employee
        for employee in instance.employees
    ]
    return replace(instance, employees=employees)


def _with_policy(instance: Instance, **rules: tuple[bool, float]) -> Instance:
    """A copy of the instance with some rules overridden."""
    current = {
        code: (rule.strict, rule.weight)
        for code, rule in (instance.policy.rules if instance.policy else {}).items()
    }
    current.update(rules)
    return replace(instance, policy=policy_from_settings(current))


def _generated(instance: Instance, roster: Roster) -> list[Duty]:
    """The roster's duties that are not manual placements, in order."""
    return sorted(duty for duty in roster if duty not in instance.fixed)


def _codes(instance: Instance, roster: Roster) -> set[str]:
    """The violation codes of a roster."""
    return violation_codes(validate(instance, roster))


def _plant(seed: int, knobs: Knobs) -> Instance | None:
    """A planted instance, or ``None`` when the planter may not add spares."""
    try:
        return make_instance(seed, knobs)
    except PlantingFailed:
        return None


def _capture_solver_input(session, world, instance: Instance) -> dict[str, object]:
    """Run the database loader with the solver replaced by a recorder."""
    captured: dict[str, object] = {}
    names = [
        "employees",
        "competences",
        "month",
        "year",
        "adjacent_assignments",
        "fixed_assignments",
        "generate_from",
        "time_budget_seconds",
        "constraints",
    ]

    def capture(*args, **kwargs):
        captured.update(dict(zip(names, args)))
        captured.update(kwargs)
        return []

    with mock.patch(
        "app.services.schedule_generation_service.solve_monthly_schedule",
        side_effect=capture,
    ):
        generate_ambulance_monthly_schedule(
            session,
            world.ambulance_id,
            instance.month,
            instance.year,
            fixed_entries=world.fixed_entries_for_db(instance),
            generate_from=instance.generate_from,
            time_budget_seconds=5,
        )
    return captured


# --- Mutations: each returns (instance, roster) or None ------------------------------------

Mutation = Callable[[Instance, Roster], "tuple[Instance, Roster] | None"]


def mutate_duplicate(instance: Instance, roster: Roster):
    """List one duty twice."""
    if not roster:
        return None
    return instance, roster + [roster[0]]


def mutate_outside_month(instance: Instance, roster: Roster):
    """Add a duty the day after the month ends."""
    if not roster:
        return None
    user_id, competence_id, _day = roster[0]
    return instance, roster + [(user_id, competence_id, instance.days[-1] + timedelta(days=1))]


def mutate_unknown_user(instance: Instance, roster: Roster):
    """Add a duty for somebody who does not work here."""
    if not roster:
        return None
    _user, competence_id, day = roster[0]
    return instance, roster + [(9999, competence_id, day)]


def mutate_unknown_competence(instance: Instance, roster: Roster):
    """Add a duty in a role the workplace does not have."""
    if not roster:
        return None
    user_id, _competence, day = roster[0]
    return instance, roster + [(user_id, 9999, day)]


def mutate_fixed_missing(instance: Instance, roster: Roster):
    """Hand a manual placement to somebody else who may legally take it."""
    history = set(instance.history_days)
    for duty in sorted(instance.fixed):
        if duty[2] in history:
            return instance, [item for item in roster if item != duty]
    for duty in sorted(instance.fixed):
        if duty[2] not in instance.day_set:
            continue
        rest = [item for item in roster if item != duty]
        for employee in instance.employees:
            if employee.id != duty[0] and eligible(instance, employee.id, duty[1], duty[2], rest):
                return instance, rest + [(employee.id, duty[1], duty[2])]
    return None


def mutate_history_changed(instance: Instance, roster: Roster):
    """Add a legal-looking duty on a day before ``generate_from``."""
    if instance.generate_from is None:
        return None
    open_month = replace(instance, generate_from=None)
    for day in instance.history_days:
        for competence in instance.competences:
            for employee in instance.employees:
                if eligible(open_month, employee.id, competence.id, day, roster):
                    return instance, roster + [(employee.id, competence.id, day)]
    return None


def mutate_coverage_short(instance: Instance, roster: Roster):
    """Drop one generated duty."""
    generated = _generated(instance, roster)
    if not generated:
        return None
    return instance, [duty for duty in roster if duty != generated[len(generated) // 2]]


def mutate_coverage_over(instance: Instance, roster: Roster):
    """Add one legal extra person to a role, under a strict overstaff rule."""
    strict = _with_policy(instance, overstaff=(True, 1000.0))
    for day in instance.window_days:
        for competence in instance.competences:
            for employee in instance.employees:
                if eligible(strict, employee.id, competence.id, day, roster):
                    return strict, roster + [(employee.id, competence.id, day)]
    return None


def mutate_coverage_zero_day(instance: Instance, roster: Roster):
    """Make a role ask for nobody on a weekday somebody was generated for."""
    for duty in _generated(instance, roster):
        competence = instance.competence_map[duty[1]]
        if duty[2] in competence.special_dates:
            continue
        counts = list(competence.weekday_required_counts)
        counts[duty[2].weekday()] = 0
        changed = replace(competence, weekday_required_counts=tuple(counts))
        competences = [changed if item.id == competence.id else item for item in instance.competences]
        return replace(instance, competences=competences), roster
    return None


def mutate_unqualified_output(instance: Instance, roster: Roster):
    """Hand a generated duty to someone who lacks the competence but is otherwise free."""
    for duty in _generated(instance, roster):
        rest = [item for item in roster if item != duty]
        for employee in instance.employees:
            if duty[1] in employee.competence_ids:
                continue
            widened = _with_employee(
                instance, employee.id, competence_ids=employee.competence_ids | {duty[1]}
            )
            if eligible(widened, employee.id, duty[1], duty[2], rest):
                return instance, rest + [(employee.id, duty[1], duty[2])]
    return None


def mutate_unqualified_instance(instance: Instance, roster: Roster):
    """Take a competence away from someone generated in it."""
    for duty in _generated(instance, roster):
        employee = instance.employee_map[duty[0]]
        return _with_employee(
            instance, duty[0], competence_ids=employee.competence_ids - {duty[1]}
        ), roster
    return None


def mutate_double_role(instance: Instance, roster: Roster):
    """Give someone a second role on a day they already work, taking it from another."""
    by_user_day = {(duty[0], duty[2]): duty for duty in _generated(instance, roster)}
    for duty in _generated(instance, roster):
        for (user_id, day), own in sorted(by_user_day.items()):
            if day != duty[2] or user_id == duty[0] or own[1] == duty[1]:
                continue
            rest = [item for item in roster if item != duty]
            own_others = [item for item in rest if item != own]
            employee = instance.employee_map[user_id]
            limit = employee.max_shifts_per_month
            if (
                instance.effective_policy.is_strict(MAX_SHIFTS)
                and limit
                and sum(1 for item in rest if item[0] == user_id) + 1 > limit
            ):
                continue
            if eligible(instance, user_id, duty[1], day, own_others):
                return instance, rest + [(user_id, duty[1], day)]
    return None


def mutate_other_workplace(instance: Instance, roster: Roster):
    """Book someone elsewhere on a day they were generated, earning no rest."""
    for duty in _generated(instance, roster):
        employee = instance.employee_map[duty[0]]
        return _with_employee(
            instance,
            duty[0],
            externally_scheduled_dates=employee.externally_scheduled_dates | {duty[2]},
            external_commitments=tuple(
                item for item in employee.external_commitments if item[0] != duty[2]
            )
            + ((duty[2], 0),),
        ), roster
    return None


def mutate_rest_instance(instance: Instance, roster: Roster):
    """Book someone elsewhere the day before a generated duty, with a day of rest."""
    if not instance.effective_policy.is_strict(REST):
        return None
    worked = {(duty[0], duty[2]) for duty in roster}
    for duty in _generated(instance, roster):
        employee = instance.employee_map[duty[0]]
        before = duty[2] - timedelta(days=1)
        if (duty[0], before) in worked or before in employee.externally_scheduled_dates:
            continue
        return _with_employee(
            instance,
            duty[0],
            externally_scheduled_dates=employee.externally_scheduled_dates | {before},
            external_commitments=employee.external_commitments + ((before, 1),),
        ), roster
    return None


def mutate_rest_duplicate_external(instance: Instance, roster: Roster):
    """A second duty elsewhere on a day already worked elsewhere, with a longer rest.

    The entry is put *first*, so a reader keeping only the last entry per
    date (the solver's bug) would miss it; the oracle must not.
    """
    if not instance.effective_policy.is_strict(REST):
        return None
    worked = {(duty[0], duty[2]) for duty in roster}
    for duty in _generated(instance, roster):
        employee = instance.employee_map[duty[0]]
        before = duty[2] - timedelta(days=1)
        if (duty[0], before) in worked or before in employee.externally_scheduled_dates:
            continue
        return _with_employee(
            instance,
            duty[0],
            externally_scheduled_dates=employee.externally_scheduled_dates | {before},
            external_commitments=((before, 1), (before, 0)) + employee.external_commitments,
        ), roster
    return None


def mutate_rest_output(instance: Instance, roster: Roster):
    """Hand someone the duty right after their own, inside its rest."""
    if not instance.effective_policy.is_strict(REST):
        return None
    relaxed = _with_policy(instance, rest=(False, 1000.0))
    generated = _generated(instance, roster)
    for duty in generated:
        reach = duty_rest(instance.competence_map, duty[1], duty[2])
        for later in generated:
            if later[0] == duty[0] or not duty[2] < later[2] <= duty[2] + timedelta(days=reach):
                continue
            rest = [item for item in roster if item != later]
            if eligible(relaxed, duty[0], later[1], later[2], rest):
                return instance, rest + [(duty[0], later[1], later[2])]
    return None


def mutate_absence(instance: Instance, roster: Roster):
    """Record a strict absence on a generated duty's day."""
    strict_rules = [rule for rule in ("unavailable", "vacation", "business_trip") if instance.effective_policy.is_strict(rule)]
    if not strict_rules:
        return None
    for duty in _generated(instance, roster):
        employee = instance.employee_map[duty[0]]
        rule = strict_rules[duty[2].day % len(strict_rules)]
        return _with_employee(
            instance,
            duty[0],
            unavailable_dates=employee.unavailable_dates | {duty[2]},
            absence_rules=tuple(item for item in employee.absence_rules if item[0] != duty[2])
            + ((duty[2], rule),),
        ), roster
    return None


def mutate_soft_decline(instance: Instance, roster: Roster):
    """Mark a generated duty's day as "rather not" under a strict rule."""
    strict = _with_policy(instance, soft_decline=(True, 10.0))
    for duty in _generated(instance, roster):
        employee = instance.employee_map[duty[0]]
        return _with_employee(
            strict, duty[0], soft_declined_dates=employee.soft_declined_dates | {duty[2]}
        ), roster
    return None


def mutate_max_shifts(instance: Instance, roster: Roster):
    """Set a strict monthly maximum one below what someone was given."""
    strict = _with_policy(instance, max_shifts=(True, 1000.0))
    totals = Counter(duty[0] for duty in roster)
    placed = Counter(duty[0] for duty in instance.fixed)
    for user_id, total in sorted(totals.items()):
        if total >= 2 and placed[user_id] < total:
            return _with_employee(strict, user_id, max_shifts_per_month=total - 1), roster
    return None


MUTATIONS: list[tuple[str, Mutation]] = [
    ("malformed", mutate_duplicate),
    ("malformed", mutate_outside_month),
    ("malformed", mutate_unknown_user),
    ("malformed", mutate_unknown_competence),
    ("fixed_missing", mutate_fixed_missing),
    ("history_changed", mutate_history_changed),
    ("coverage", mutate_coverage_short),
    ("coverage", mutate_coverage_over),
    ("coverage", mutate_coverage_zero_day),
    ("unqualified", mutate_unqualified_output),
    ("unqualified", mutate_unqualified_instance),
    ("double_role", mutate_double_role),
    ("other_workplace", mutate_other_workplace),
    ("rest", mutate_rest_instance),
    ("rest", mutate_rest_duplicate_external),
    ("rest", mutate_rest_output),
    ("absence", mutate_absence),
    ("soft_decline", mutate_soft_decline),
    ("max_shifts", mutate_max_shifts),
]

#: Knobs of the instances the solver is run on before mutating its output.
SOLVED_KNOBS: dict[str, Knobs] = {
    "everything_default_policy": Knobs(
        n_employees=9,
        n_competences=2,
        demand_profile="weekday",
        recovery_profile="mixed",
        hours_profile="mixed",
        special_days="mixed",
        unavailability_rate=0.1,
        absence_mix=(0.5, 0.3, 0.2),
        preferred_rate=0.1,
        soft_decline_rate=0.1,
        max_shifts_mode="mixed",
        preference_mix="mixed",
        external_rate=0.04,
        external_explicit_rest=0.5,
        adjacent_rate=0.6,
        adjacent_retired_competence=True,
        generate_from="mid",
        n_fixed=3,
        planted=True,
    ),
    "strict_overstaff_and_max": Knobs(
        n_employees=8,
        n_competences=2,
        month=2,
        year=2028,
        demand_profile="flat",
        max_shifts_mode="tight",
        soft_decline_rate=0.1,
        n_fixed=2,
        adjacent_rate=0.5,
        policy=POLICY_PRESETS["strict_everything"],
        planted=True,
    ),
    "rule_breaking_placements": Knobs(
        n_employees=8,
        n_competences=2,
        month=12,
        year=2026,
        special_days="library",
        recovery_profile="mixed",
        n_fixed=2,
        n_breaking_fixed=4,
        external_rate=0.03,
        unavailability_rate=0.05,
        planted=True,
    ),
    "penalized_rest_and_absences": Knobs(
        n_employees=7,
        n_competences=2,
        month=4,
        year=2026,
        recovery_profile="long",
        unavailability_rate=0.15,
        absence_mix=(0.4, 0.3, 0.3),
        external_rate=0.03,
        adjacent_rate=0.5,
        policy=POLICY_PRESETS["penalized_all"],
        witness_keeps_rest=False,
        planted=True,
    ),
    "fill_in_with_blocks_and_patterns": Knobs(
        n_employees=10,
        n_competences=3,
        qualification_structure="hierarchy",
        demand_profile="mixed",
        target_utilization=0.6,
        vacation_block_rate=0.4,
        block_cluster=True,
        preferred_rate=0.1,
        soft_decline_rate=0.1,
        wish_pattern="weekday",
        max_shifts_mode="hetero",
        fixed_share=0.5,
        fixed_full_days=2,
        generate_from="mid",
        planted=True,
    ),
}


class ValidateMutationTests(unittest.TestCase):
    """The oracle accepts good rosters and flags each breach with exactly its code."""

    solved: dict[str, tuple[Instance, Roster]] = {}

    @classmethod
    def setUpClass(cls) -> None:
        """Solve a handful of feature-rich planted instances once, in parallel."""
        instances = [make_instance(100 + index, knobs) for index, knobs in enumerate(SOLVED_KNOBS.values())]
        outcomes = solve_in_parallel(instances, time_budget_seconds=15, workers=len(instances))
        cls.solved = {}
        cls.outcomes = {}
        for name, instance, outcome in zip(SOLVED_KNOBS, instances, outcomes):
            cls.outcomes[name] = outcome
            if outcome.status == "ok":
                cls.solved[name] = (instance, sorted(outcome.assignments))

    def _sources(self) -> list[tuple[str, Instance, Roster]]:
        """Solver outputs plus planted witnesses, all of them valid rosters."""
        sources = [(name, instance, roster) for name, (instance, roster) in self.solved.items()]
        rng = random.Random(7)
        for seed in range(8):
            knobs = sample_knobs(rng, "small", planted=True)
            instance = make_instance(500 + seed, knobs)
            sources.append((f"witness-{seed}", instance, sorted(instance.witness or ())))
        return sources

    def test_the_solver_answers_every_planted_instance(self) -> None:
        """Planted instances are feasible, so the solver must return a roster."""
        for name, outcome in self.outcomes.items():
            with self.subTest(name=name):
                self.assertEqual(outcome.status, "ok", outcome.issues)

    def test_valid_rosters_pass(self) -> None:
        """Unmutated solver outputs and witnesses break no rule."""
        for name, instance, roster in self._sources():
            with self.subTest(name=name):
                self.assertEqual(validate(instance, roster), [])

    def test_every_mutation_is_flagged_with_exactly_its_code(self) -> None:
        """Each injected breach yields its own code and no other."""
        exercised: Counter[str] = Counter()
        for name, instance, roster in self._sources():
            for expected, mutation in MUTATIONS:
                mutated = mutation(instance, roster)
                if mutated is None:
                    continue
                changed_instance, changed_roster = mutated
                with self.subTest(source=name, mutation=mutation.__name__):
                    self.assertEqual(_codes(changed_instance, changed_roster), {expected})
                    exercised[mutation.__name__] += 1
        for _expected, mutation in MUTATIONS:
            with self.subTest(mutation=mutation.__name__):
                self.assertGreater(exercised[mutation.__name__], 0, "mutation never applied")

    def test_penalized_rules_are_not_violations(self) -> None:
        """Breaches of penalized rules cost money but are not hard violations."""
        name, instance, roster = self._sources()[0]
        duty = _generated(instance, roster)[0]
        employee = instance.employee_map[duty[0]]
        on_vacation = _with_employee(
            _with_policy(instance, vacation=(False, 500.0)),
            duty[0],
            unavailable_dates=employee.unavailable_dates | {duty[2]},
            absence_rules=tuple(item for item in employee.absence_rules if item[0] != duty[2])
            + ((duty[2], VACATION),),
        )
        self.assertEqual(validate(on_vacation, roster), [], name)
        reluctant = _with_employee(
            _with_policy(instance, soft_decline=(False, 10.0)),
            duty[0],
            soft_declined_dates=employee.soft_declined_dates | {duty[2]},
        )
        self.assertEqual(validate(reluctant, roster), [])
        strict_cap = _with_policy(instance, max_shifts=(True, 1000.0))
        no_limit = replace(
            strict_cap,
            employees=[replace(item, max_shifts_per_month=0) for item in instance.employees],
        )
        self.assertEqual(validate(no_limit, roster), [])
        overfull = _with_policy(instance, overstaff=(False, 1000.0))
        extra = mutate_coverage_over(overfull, roster)
        if extra is not None:
            self.assertEqual(validate(overfull, extra[1]), [])

    def test_manual_placements_may_break_rules_among_themselves(self) -> None:
        """Placements on an absence, unqualified, in two roles or inside rest are kept legal."""
        instance = make_instance(
            31,
            Knobs(
                n_employees=6,
                n_competences=2,
                recovery_profile="long",
                n_breaking_fixed=6,
                planted=True,
            ),
        )
        self.assertEqual(validate(instance, sorted(instance.witness or ())), [])
        rule_breaking = Counter()
        for user_id, competence_id, day in instance.fixed:
            employee = instance.employee_map[user_id]
            if competence_id not in employee.competence_ids:
                rule_breaking["unqualified"] += 1
            if absence_rule(employee, day) is not None:
                rule_breaking["absence"] += 1
        same_day = Counter((duty[0], duty[2]) for duty in instance.fixed)
        if any(count > 1 for count in same_day.values()):
            rule_breaking["two_roles"] += 1
        self.assertTrue(rule_breaking, "no rule-breaking placement was planted")

    def test_external_rest_ignores_entry_order(self) -> None:
        """Two rests for one day elsewhere hold the person for the longer one, in either order."""
        day = date(2026, 8, 10)
        for order in (((day, 3), (day, 0)), ((day, 0), (day, 3))):
            employee = _employee(
                1, externally_scheduled_dates=frozenset({day}), external_commitments=order
            )
            with self.subTest(order=order):
                self.assertTrue(has_duplicate_external_dates(employee))
                self.assertEqual(external_duties(employee, [_competence()]), [(day, 3)])
        stray = _employee(1, external_commitments=((day, 3),))
        self.assertEqual(external_duties(stray, [_competence()]), [])


class PlantedWitnessTests(unittest.TestCase):
    """Planted witnesses keep every hard rule, across many seeds and knobs."""

    def test_witnesses_validate_across_sizes_and_knobs(self) -> None:
        """Every planted witness passes the oracle, and its history equals the placements."""
        rng = random.Random(2024)
        for seed in range(140):
            size = ("small", "medium", "large", "xl")[seed % 4]
            knobs = sample_knobs(rng, size, planted=True)
            instance = make_instance(seed, knobs)
            witness = sorted(instance.witness or ())
            with self.subTest(label=instance.label):
                self.assertEqual(validate(instance, witness), [])
                self.assertTrue(instance.fixed <= frozenset(witness))
                history = set(instance.history_days)
                self.assertEqual(
                    {duty for duty in witness if duty[2] in history},
                    {duty for duty in instance.fixed if duty[2] in history},
                )

    def test_witnesses_survive_many_rule_breaking_placements(self) -> None:
        """Tight months with up to eight rule-breaking placements still plant cleanly."""
        rng = random.Random(4242)
        for seed in range(150):
            instance = make_instance(seed, stress_knobs(rng))
            with self.subTest(label=instance.label):
                self.assertEqual(validate(instance, sorted(instance.witness or ())), [])

    def test_every_policy_preset_plants(self) -> None:
        """Each policy preset, and random policies, yield a valid witness with every feature on."""
        policies = list(POLICY_PRESETS.items()) + [
            (f"random-{seed}", random_policy(random.Random(seed))) for seed in range(12)
        ]
        for index, (name, policy) in enumerate(policies):
            knobs = Knobs(
                n_employees=10,
                n_competences=3,
                demand_profile="mixed",
                recovery_profile="mixed",
                special_days="mixed",
                unavailability_rate=0.1,
                absence_mix=(0.4, 0.3, 0.3),
                vacation_block_rate=0.3,
                preferred_rate=0.1,
                soft_decline_rate=0.1,
                wish_pattern=("iid", "weekday", "crowd")[index % 3],
                max_shifts_mode="mixed",
                external_rate=0.03,
                external_explicit_rest=0.5,
                external_duplicate_rate=0.5,
                adjacent_rate=0.7,
                adjacent_retired_competence=True,
                generate_from="mid",
                n_fixed=4,
                n_breaking_fixed=2,
                policy=policy,
                planted=True,
                witness_keeps_rest=index % 2 == 0,
            )
            instance = make_instance(index, knobs)
            with self.subTest(policy=name):
                self.assertEqual(validate(instance, sorted(instance.witness or ())), [])

    def test_generation_is_deterministic(self) -> None:
        """The same seed and knobs give the same instance."""
        knobs = sample_knobs(random.Random(5), "medium", planted=True)
        first = make_instance(77, knobs)
        second = make_instance(77, knobs)
        self.assertEqual(first.employees, second.employees)
        self.assertEqual(first.competences, second.competences)
        self.assertEqual(first.witness, second.witness)
        self.assertEqual(first.fixed, second.fixed)
        self.assertEqual(first.adjacent, second.adjacent)

    def test_generation_does_not_depend_on_the_hash_seed(self) -> None:
        """Two interpreters with different PYTHONHASHSEED build identical instances."""
        script = (
            "import hashlib, random\n"
            "from tests.scheduling_harness.instances import make_instance, stress_knobs, sample_knobs, fill_in_knobs\n"
            "h = hashlib.sha256()\n"
            "for seed in range(12):\n"
            "    for knobs in (stress_knobs(random.Random(seed)), sample_knobs(random.Random(seed), 'small'),\n"
            "                  fill_in_knobs(random.Random(seed))):\n"
            "        i = make_instance(seed, knobs)\n"
            "        h.update(repr((sorted(i.fixed), sorted(i.witness), sorted(i.adjacent), i.generate_from,\n"
            "            [(e.id, sorted(e.competence_ids), sorted(e.unavailable_dates), e.absence_rules,\n"
            "              sorted(e.externally_scheduled_dates), e.external_commitments, sorted(e.preferred_dates),\n"
            "              sorted(e.soft_declined_dates), e.max_shifts_per_month, e.shift_preference) for e in i.employees],\n"
            "            [(c.id, sorted(c.special_dates), c.weekday_required_counts) for c in i.competences])).encode())\n"
            "print(h.hexdigest())\n"
        )
        digests = []
        for hash_seed in ("1", "2"):
            environment = {**os.environ, "PYTHONHASHSEED": hash_seed}
            result = subprocess.run(
                [sys.executable, "-c", script],
                cwd=BACKEND,
                env=environment,
                capture_output=True,
                text=True,
                timeout=120,
                check=True,
            )
            digests.append(result.stdout.strip())
        self.assertEqual(digests[0], digests[1])

    def test_knobs_reach_the_instance(self) -> None:
        """Calendar, special days, rests, hours and the features land where asked."""
        leap = make_instance(1, Knobs(month=2, year=2028, special_days="library", planted=True))
        self.assertEqual(len(leap.days), 29)
        december = make_instance(
            2,
            Knobs(
                month=12,
                year=2026,
                special_days="library",
                recovery_profile="long",
                hours_profile="mixed",
                external_rate=0.05,
                external_explicit_rest=0.0,
                adjacent_rate=0.8,
                adjacent_retired_competence=True,
                planted=True,
            ),
        )
        self.assertEqual(len(december.days), 31)
        self.assertIn(date(2026, 12, 25), december.special_dates)
        self.assertIn(date(2027, 1, 1), december.special_dates)
        self.assertTrue(
            all(
                2 <= competence.recovery_days_on(day) <= 6
                for competence in december.competences
                for day in december.days
            )
        )
        self.assertTrue(any(employee.externally_scheduled_dates for employee in december.employees))
        self.assertTrue(all(not employee.external_commitments for employee in december.employees))
        self.assertTrue(any(duty[1] == RETIRED_COMPETENCE_ID for duty in december.adjacent))
        self.assertTrue(any(duty[2] < december.days[0] for duty in december.adjacent))
        self.assertTrue(any(duty[2] > december.days[-1] for duty in december.adjacent))

    def test_new_knobs_reach_the_instance(self) -> None:
        """Blocks, wish patterns, structures, utilization, fill-in and duplicates all land."""
        base = Knobs(n_employees=16, n_competences=3, planted=True, recovery_profile="one")
        hierarchy = make_instance(3, replace(base, qualification_structure="hierarchy"))
        juniors = [e for e in hierarchy.employees[:16] if len(e.competence_ids) == 1]
        seniors = [e for e in hierarchy.employees[:16] if len(e.competence_ids) == 3]
        self.assertTrue(juniors and seniors)
        rare = make_instance(4, replace(base, qualification_structure="rare"))
        self.assertLessEqual(sum(1 in e.competence_ids for e in rare.employees[:16]), 2)

        busy = make_instance(5, replace(base, target_utilization=0.9, demand_profile="flat"))
        calm = make_instance(5, replace(base, target_utilization=0.3, demand_profile="flat"))
        self.assertGreater(
            sum(c.required_on(day) for c in busy.competences for day in busy.days),
            sum(c.required_on(day) for c in calm.competences for day in calm.days),
        )
        idle = make_instance(6, replace(base, zero_demand_competences=1))
        self.assertTrue(all(idle.competences[-1].required_on(day) == 0 for day in idle.days))

        blocks = make_instance(7, replace(base, vacation_block_rate=1.0, block_cluster=True))
        runs = [sorted(e.unavailable_dates) for e in blocks.employees[:16]]
        self.assertTrue(all(len(run) >= 3 for run in runs))
        self.assertTrue(all((run[-1] - run[0]).days == len(run) - 1 for run in runs))
        self.assertLessEqual(max(run[0] for run in runs) - min(run[0] for run in runs), timedelta(days=4))

        crowd = make_instance(8, replace(base, preferred_rate=0.1, wish_pattern="crowd"))
        wanted = Counter(day for e in crowd.employees for day in e.preferred_dates)
        self.assertGreaterEqual(max(wanted.values()), 6)
        weekly = make_instance(9, replace(base, soft_decline_rate=0.2, wish_pattern="weekday"))
        for employee in weekly.employees[:16]:
            self.assertLessEqual(len({day.weekday() for day in employee.soft_declined_dates}), 1)

        fill = make_instance(10, replace(base, fixed_share=0.6, fixed_full_days=2, generate_from="mid"))
        window = set(fill.window_days)
        pinned = [duty for duty in fill.fixed if duty[2] in window]
        planted = [duty for duty in fill.witness if duty[2] in window]
        self.assertGreaterEqual(len(pinned), 0.6 * len(planted) - 1)

        doubled = make_instance(11, replace(base, external_rate=0.1, external_duplicate_rate=1.0))
        self.assertTrue(any(has_duplicate_external_dates(e) for e in doubled.employees))
        self.assertIn("duplicate_external_dates", known_bug_triggers(doubled))

        hetero = make_instance(12, replace(base, max_shifts_mode="hetero", planted=False))
        caps = {e.max_shifts_per_month for e in hetero.employees}
        self.assertGreater(len(caps), 1)

        self.assertEqual(knobs_of(fill), replace(base, fixed_share=0.6, fixed_full_days=2, generate_from="mid"))

    def test_spares_are_recorded_and_can_be_forbidden(self) -> None:
        """A planter that must add staff says so, and refuses when told not to."""
        knobs = Knobs(n_employees=2, n_competences=1, demand_profile="heavy", recovery_profile="one", planted=True)
        instance = make_instance(1, knobs)
        self.assertGreater(instance.spares, 0)
        self.assertEqual(len(instance.employees), 2 + instance.spares)
        self.assertIn(f"-sp{instance.spares}", instance.label)
        with self.assertRaises(PlantingFailed):
            make_instance(1, replace(knobs, max_spares=0))


class FirstPassCostTests(unittest.TestCase):
    """The documented objective, checked against hand computation."""

    def _instance(self, employees, competences, policy=None, **extra) -> Instance:
        """A plain August 2026 instance."""
        return Instance(employees=employees, competences=competences, month=8, year=2026, policy=policy, **extra)

    def test_ladder_cost_matches_the_sum_of_odd_numbers(self) -> None:
        """Whole steps cost unit * q^2; a fraction pays its share of the next odd number."""
        self.assertEqual(ladder_cost(3, 4.0), 4.0 * (1 + 3 + 5))
        self.assertAlmostEqual(ladder_cost(2.5, 4.0), 4.0 * (1 + 3 + 0.5 * 5))
        self.assertAlmostEqual(ladder_cost(10.0, 4.0, step=4.0), 4.0 * (1 + 3 + 0.5 * 5))
        self.assertEqual(ladder_cost(0, 4.0), 0.0)

    def test_uniform_duties_cost_three_equal_ladders(self) -> None:
        """Ordinary 4-hour duties: total, standard and hours ladders agree."""
        instance = self._instance(
            [_employee(1), _employee(2)],
            [_competence(recovery=(0,) * 8, surcharge=(False,) * 8)],
        )
        roster = [(1, 1, date(2026, 8, 3)), (1, 1, date(2026, 8, 4)), (1, 1, date(2026, 8, 5)), (2, 1, date(2026, 8, 6))]
        self.assertAlmostEqual(first_pass_cost(instance, roster), 3 * 4 * 9 + 3 * 4 * 1)

    def test_fractional_hours_ladder(self) -> None:
        """Mixed lengths step the hour ladder in the month's mean demanded duty."""
        hours = (12.0,) + (4.0,) * 7  # Mondays are twelve hours long
        instance = self._instance(
            [_employee(1)],
            [_competence(recovery=(0,) * 8, hours=hours, surcharge=(False,) * 8)],
        )
        # August 2026 has five Mondays: (5 * 12 + 26 * 4) / 31 hours per duty.
        step = (5 * 12 + 26 * 4) / 31
        roster = [(1, 1, date(2026, 8, 3)), (1, 1, date(2026, 8, 4))]
        q = 16 / step
        expected = 4 * 4 + 4 * 4 + 4 * (3 ** 2 + 7 * (q - 3))
        self.assertAlmostEqual(first_pass_cost(instance, roster), expected)

    def test_shift_preference_tilts_the_kind_ladders(self) -> None:
        """Surcharge-minded pay 3 for surcharged and 5 for ordinary duties, and vice versa."""
        roster = [(1, 1, date(2026, 8, 1)), (1, 1, date(2026, 8, 2)), (1, 1, date(2026, 8, 4))]
        expected = {"surcharge": 3 * 4 + 5 * 1, "standard": 5 * 4 + 3 * 1, "any": 4 * 4 + 4 * 1}
        for preference, kinds in expected.items():
            instance = self._instance(
                [_employee(1, shift_preference=preference)],
                [_competence(recovery=(0,) * 8)],
            )
            with self.subTest(preference=preference):
                self.assertAlmostEqual(first_pass_cost(instance, roster), 4 * 9 + 4 * 9 + kinds)

    def test_balance_weight_scales_every_ladder(self) -> None:
        """Doubling the balance weight doubles the ladders."""
        roster = [(1, 1, date(2026, 8, 3)), (1, 1, date(2026, 8, 5))]
        base = self._instance([_employee(1)], [_competence()])
        heavy = replace(base, policy=policy_from_settings({BALANCE: (False, 8.0)}))
        self.assertAlmostEqual(first_pass_cost(heavy, roster), 2 * first_pass_cost(base, roster))
        silent = replace(base, policy=policy_from_settings({BALANCE: (False, 0.0)}))
        self.assertEqual(first_pass_cost(silent, roster), 0.0)

    def test_penalties_of_the_first_pass(self) -> None:
        """Monthly excess, overstaffing, penalized absences and rest are charged per breach."""
        days = [date(2026, 8, day) for day in (3, 5, 7)]
        roster = [(1, 1, day) for day in days]
        ladders = 3 * 4 * 9
        capped = self._instance([_employee(1, max_shifts_per_month=2)], [_competence()])
        self.assertAlmostEqual(first_pass_cost(capped, roster), ladders + 1000)
        strict_cap = replace(capped, policy=policy_from_settings({MAX_SHIFTS: (True, 1000.0)}))
        self.assertAlmostEqual(first_pass_cost(strict_cap, roster), ladders)

        crowd = self._instance([_employee(1), _employee(2)], [_competence()])
        crowded = roster + [(2, 1, days[0])]
        self.assertAlmostEqual(first_pass_cost(crowd, crowded), ladders + 3 * 4 + 1000)
        strict_crowd = replace(crowd, policy=policy_from_settings({OVERSTAFF: (True, 1000.0)}))
        self.assertAlmostEqual(first_pass_cost(strict_crowd, crowded), ladders + 3 * 4)

        vacation = self._instance(
            [_employee(1, unavailable_dates=frozenset({days[0]}), absence_rules=((days[0], VACATION),))],
            [_competence()],
            policy=policy_from_settings({VACATION: (False, 500.0)}),
        )
        self.assertAlmostEqual(first_pass_cost(vacation, roster), ladders + 500)
        placed = replace(vacation, fixed=frozenset({roster[0]}))
        self.assertAlmostEqual(first_pass_cost(placed, roster), ladders)

    def test_penalized_rest_is_charged_per_shared_day(self) -> None:
        """Each day two rests overlap costs the rest weight, also against duties outside."""
        policy = policy_from_settings({REST: (False, 1000.0)})
        instance = self._instance([_employee(1)], [_competence(recovery=(2,) * 8)], policy=policy)
        close = [(1, 1, date(2026, 8, 3)), (1, 1, date(2026, 8, 5))]
        ladders = 3 * 4 * 4
        self.assertAlmostEqual(first_pass_cost(instance, close), ladders + 1000)
        tight = [(1, 1, date(2026, 8, 3)), (1, 1, date(2026, 8, 4))]
        self.assertAlmostEqual(first_pass_cost(instance, tight), ladders + 2000)
        both_placed = replace(instance, fixed=frozenset(tight))
        self.assertAlmostEqual(first_pass_cost(both_placed, tight), ladders)
        around = replace(instance, adjacent=frozenset({(1, 1, date(2026, 7, 31))}))
        first = [(1, 1, date(2026, 8, 1))]
        # 31 July holds 31 July - 2 August; 1 August holds 1-3 August.
        self.assertAlmostEqual(first_pass_cost(around, first), 3 * 4 + 2000)

    def test_rest_metrics_match_what_is_charged(self) -> None:
        """metrics.rest_breach_days is the charged quantity; pair overlaps are kept apart."""
        policy = policy_from_settings({REST: (False, 1000.0)})
        instance = self._instance(
            [_employee(1)],
            [_competence(recovery=(5,) * 8)],
            policy=policy,
            generate_from=date(2026, 8, 29),
        )
        roster = [(1, 1, date(2026, 8, day)) for day in (29, 30, 31)]
        measured = metrics(instance, roster)
        self.assertEqual(measured.rest_breach_days, 3)
        self.assertEqual(measured.rest_breach_pairs, 3)
        self.assertEqual(measured.rest_overlap_pair_days, 5 + 4 + 5)
        ladders = first_pass_cost(replace(instance, policy=policy_from_settings({REST: (False, 0.0)})), roster)
        self.assertAlmostEqual(first_pass_cost(instance, roster), ladders + 1000 * measured.rest_breach_days)

    def test_day_wishes(self) -> None:
        """A requested day earns its weight, a reluctant one costs it unless strict."""
        employee = _employee(
            1,
            preferred_dates=frozenset({date(2026, 8, 3)}),
            soft_declined_dates=frozenset({date(2026, 8, 5)}),
        )
        instance = self._instance([employee], [_competence()])
        roster = [(1, 1, date(2026, 8, 3)), (1, 1, date(2026, 8, 5))]
        self.assertEqual(day_wish_cost(instance, roster), -10 + 10)
        strict = replace(instance, policy=policy_from_settings({SOFT_DECLINE: (True, 10.0)}))
        self.assertEqual(day_wish_cost(strict, roster), -10)

    def test_metrics(self) -> None:
        """Gaps, tightest gaps, wishes and spread are measured as defined."""
        employee = _employee(1, preferred_dates=frozenset({date(2026, 8, 3), date(2026, 8, 20)}))
        instance = self._instance([employee, _employee(2)], [_competence()])
        roster = [(1, 1, date(2026, 8, day)) for day in (3, 5, 10)] + [(2, 1, date(2026, 8, 4))]
        measured = metrics(instance, roster)
        self.assertEqual(measured.gap_histogram, {2: 1, 5: 1})
        self.assertEqual(measured.min_gap, 2)
        self.assertEqual(measured.tightest_gaps, 1)
        self.assertEqual(measured.load_spread, 2)
        self.assertEqual(measured.preferred_honored, 1)
        self.assertEqual(measured.preferred_opportunities, 2)
        self.assertEqual(measured.loads[1].surcharge, 0)


class ImprovingMoveTests(unittest.TestCase):
    """The local search finds what a careless roster leaves behind."""

    def test_finds_a_fairer_reassignment(self) -> None:
        """Piling everything on three people while a fourth is idle is improvable."""
        instance = symmetric_instance(4, 1, recovery=0)
        roster = [(1 + min(2, (day.day - 1) // 11), 1, day) for day in instance.days]
        self.assertEqual(validate(instance, roster), [])
        moves = find_improving_moves(instance, roster)
        self.assertTrue(any(move.reason == "first_pass" and move.kind == "reassign" for move in moves))

    def test_finds_a_missed_day_wish(self) -> None:
        """Swapping two weekdays to honor a request costs no balance and is found."""
        base = symmetric_instance(2, 1, recovery=0)
        instance = _with_employee(base, 2, preferred_dates=frozenset({date(2026, 8, 3)}))
        roster = [(1 if day.day % 2 else 2, 1, day) for day in instance.days]
        self.assertEqual(validate(instance, roster), [])
        moves = find_improving_moves(instance, roster)
        self.assertTrue(any(move.reason == "day_wish" for move in moves))
        self.assertFalse(any(move.reason == "first_pass" for move in moves))

    def test_finds_a_needless_extra_duty(self) -> None:
        """A generated duty above demand under a penalized overstaff rule is a drop move."""
        instance = symmetric_instance(3, 1, recovery=0)
        roster = [(1 + day.day % 3, 1, day) for day in instance.days]
        extra = roster + [(1 + (instance.days[0].day + 1) % 3, 1, instance.days[0])]
        self.assertEqual(validate(instance, extra), [])
        moves = find_improving_moves(instance, extra)
        drops = [move for move in moves if move.kind == "drop"]
        self.assertTrue(drops)
        self.assertTrue(all(move.reason == "first_pass" for move in drops))
        self.assertFalse([move for move in find_improving_moves(instance, roster) if move.kind == "drop"])

    def test_eligibility(self) -> None:
        """eligible() refuses double roles, rest, absences, elsewhere and the unqualified."""
        employee = _employee(
            1,
            unavailable_dates=frozenset({date(2026, 8, 10)}),
            externally_scheduled_dates=frozenset({date(2026, 8, 12)}),
        )
        instance = Instance([employee], [_competence(), _competence(2)], 8, 2026)
        roster = [(1, 1, date(2026, 8, 5))]
        self.assertTrue(eligible(instance, 1, 1, date(2026, 8, 7), roster))
        self.assertFalse(eligible(instance, 1, 1, date(2026, 8, 6), roster))  # rest
        self.assertFalse(eligible(instance, 1, 1, date(2026, 8, 4), roster))  # rest reaches 5th
        self.assertFalse(eligible(instance, 1, 2, date(2026, 8, 7), roster))  # unqualified
        self.assertFalse(eligible(instance, 1, 1, date(2026, 8, 10), roster))  # absent
        self.assertFalse(eligible(instance, 1, 1, date(2026, 8, 12), roster))  # elsewhere
        self.assertFalse(eligible(instance, 1, 1, date(2026, 8, 13), roster))  # elsewhere's rest
        relaxed = replace(instance, policy=policy_from_settings({REST: (False, 1000.0)}))
        self.assertTrue(eligible(relaxed, 1, 1, date(2026, 8, 6), roster))
        self.assertFalse(eligible(relaxed, 1, 1, date(2026, 8, 5), roster))  # same day


def _naive_optimum(instance: Instance) -> tuple[bool, float | None, float | None]:
    """Enumerate every set of generated duties, judge each roster by validate() alone.

    No pruning and no eligibility filter: every subset of every employee
    (qualified or not) on every window slot is tried. Returns (feasible,
    min first-pass cost, min day-wish cost among those at the minimum).
    """
    slots = [(competence.id, day) for day in instance.window_days for competence in instance.competences]
    fixed = sorted(instance.fixed)
    choices = [
        [
            [(user_id, competence_id, day) for user_id in subset]
            for size in range(len(instance.employees) + 1)
            for subset in itertools.combinations([e.id for e in instance.employees], size)
        ]
        for competence_id, day in slots
    ]
    best: tuple[float, float] | None = None
    for picked in itertools.product(*choices):
        roster = list(fixed)
        for duties in picked:
            roster.extend(duty for duty in duties if duty not in instance.fixed)
        if validate(instance, roster):
            continue
        key = (first_pass_cost(instance, roster), day_wish_cost(instance, roster))
        if best is None or key[0] < best[0] - 1e-9 or (abs(key[0] - best[0]) <= 1e-9 and key[1] < best[1] - 1e-9):
            best = key
    if best is None:
        return False, None, None
    return True, best[0], best[1]


class ReferenceAgreementTests(unittest.TestCase):
    """Brute force, the reference MILP and a naive enumeration agree."""

    def test_brute_force_and_reference_agree(self) -> None:
        """Both judges reach the same verdict on planted and random tiny instances."""
        verdicts: Counter[str] = Counter()
        complete = 0
        for seed in range(48):
            rng = random.Random(seed)
            planted = seed % 2 == 0
            instance = _plant(seed, tiny_knobs(rng, planted))
            if instance is None:
                continue
            self.assertLessEqual(len(instance.employees), 5)
            exhaustive = brute_force(instance, node_limit=20_000)
            status, roster = reference_feasibility(instance, time_limit=20)
            with self.subTest(label=instance.label):
                self.assertNotEqual(status, "unknown")
                if planted:
                    self.assertEqual(status, "feasible")
                if roster is not None:
                    self.assertEqual(validate(instance, roster), [])
                if exhaustive.complete:
                    complete += 1
                    self.assertEqual(exhaustive.feasible, status == "feasible")
                    if exhaustive.feasible:
                        self.assertLessEqual(
                            exhaustive.best_cost, first_pass_cost(instance, roster) + 1e-6
                        )
                elif exhaustive.feasible:
                    self.assertEqual(status, "feasible")
            verdicts[status] += 1
        self.assertGreaterEqual(complete, 24)
        self.assertGreater(verdicts["infeasible"], 0, "no infeasible instance in the batch")
        self.assertGreater(verdicts["feasible"], 0)

    def test_naive_enumeration_matches_brute_force_and_reference(self) -> None:
        """validate() over every subset agrees with the pruned search and the MILP."""
        checked = Counter()
        for seed in range(80):
            instance = make_instance(seed, ultra_tiny_knobs(random.Random(seed), seed % 3 != 0))
            slots = len(instance.window_days) * len(instance.competences)
            if len(instance.employees) * slots > 12:
                continue
            feasible, cost, wish = _naive_optimum(instance)
            exhaustive = brute_force(instance)
            status, _roster = reference_feasibility(instance, time_limit=10)
            with self.subTest(label=instance.label):
                self.assertTrue(exhaustive.complete)
                self.assertEqual(exhaustive.feasible, feasible)
                self.assertEqual(status, "feasible" if feasible else "infeasible")
                if feasible:
                    self.assertAlmostEqual(exhaustive.best_cost, cost, places=6)
                    self.assertAlmostEqual(exhaustive.best_wish, wish, places=6)
            checked["feasible" if feasible else "infeasible"] += 1
        self.assertGreaterEqual(checked["feasible"], 20)
        self.assertGreaterEqual(checked["infeasible"], 3)

    def test_brute_force_completes_at_exactly_its_node_count(self) -> None:
        """A search that needs N nodes is complete with a limit of N, not with N - 1."""
        tested = 0
        for seed in range(30):
            instance = _plant(seed, tiny_knobs(random.Random(seed), True))
            if instance is None:
                continue
            full = brute_force(instance, node_limit=20_000)
            if not full.complete or full.nodes < 3:
                continue
            tested += 1
            with self.subTest(label=instance.label):
                self.assertTrue(brute_force(instance, node_limit=full.nodes).complete)
                self.assertFalse(brute_force(instance, node_limit=full.nodes - 1).complete)
        self.assertGreater(tested, 5)

    def test_clique_cuts_change_no_verdict(self) -> None:
        """Pairwise rest rows alone and with clique cuts give the same answers."""
        for seed in range(10):
            knobs = replace(sample_knobs(random.Random(seed), "small", seed % 2 == 0), recovery_profile="mixed")
            instance = make_instance(seed, knobs)
            with self.subTest(label=instance.label):
                with_cuts, _ = reference_feasibility(instance, time_limit=30)
                without, _ = reference_feasibility(instance, time_limit=30, clique_cuts=False)
                self.assertNotEqual(with_cuts, "unknown")
                if without != "unknown":
                    self.assertEqual(with_cuts, without)

    def test_pigeonhole_is_infeasible_everywhere(self) -> None:
        """An obviously impossible month is impossible for every judge, the solver included."""
        instance = pigeonhole_instance()
        self.assertEqual(reference_feasibility(instance)[0], "infeasible")
        self.assertFalse(brute_force(instance).feasible)
        self.assertEqual(run_solver(instance, time_budget_seconds=5).status, "infeasible")

    def test_reference_confirms_medium_planted_instances(self) -> None:
        """The reference model finds planted medium instances feasible, long rests included."""
        rng = random.Random(99)
        for seed in range(6):
            knobs = sample_knobs(rng, "medium", planted=True)
            if seed % 2:
                knobs = replace(knobs, recovery_profile="long")
            instance = make_instance(900 + seed, knobs)
            with self.subTest(label=instance.label):
                status, roster = reference_feasibility(instance, time_limit=30)
                self.assertEqual(status, "feasible")
                self.assertEqual(validate(instance, roster), [])


class RunnerAndScenarioTests(unittest.TestCase):
    """Observed runs, parallel runs, fill-in, regeneration and month chains."""

    def test_observed_run_records_both_passes(self) -> None:
        """An observed run sees the first-pass value, which equals the harness's cost model."""
        instance = make_instance(3, Knobs(n_employees=5, preferred_rate=0.2, planted=True))
        outcome = run_solver(instance, time_budget_seconds=10, observe=True)
        self.assertEqual(outcome.status, "ok")
        self.assertEqual([record.kind for record in outcome.passes], ["balance", "wishes"])
        self.assertTrue(outcome.first_pass.optimal)
        self.assertLessEqual(first_pass_cost(instance, outcome.assignments), outcome.balance_cap)
        self.assertFalse(outcome.hit_budget)

    def test_cost_model_matches_the_solvers_objective(self) -> None:
        """On every observed run the final roster's cost lies in [reached, reached + lock slack].

        The final roster obeys the solver's lock, so a cost model that
        disagreed with the solver's objective would land outside the band
        (below it only when the first pass was proved optimal).
        """
        instances = []
        for seed in range(24):
            rng = random.Random(seed)
            if seed % 3 == 0:
                knobs = replace(tiny_knobs(rng, True), max_spares=None)
            elif seed % 3 == 1:
                knobs = stress_knobs(rng)
            else:
                knobs = sample_knobs(rng, "small", planted=True)
            instances.append(make_instance(seed, knobs))
        outcomes = solve_in_parallel(instances, time_budget_seconds=10, workers=16, observe=True)
        compared = 0
        for instance, outcome in zip(instances, outcomes):
            with self.subTest(label=instance.label):
                self.assertEqual(outcome.status, "ok", outcome.issues)
                cost = first_pass_cost(instance, outcome.assignments)
                self.assertLessEqual(cost, outcome.balance_cap + 1e-6)
                if outcome.first_pass.optimal:
                    compared += 1
                    self.assertGreaterEqual(cost, outcome.first_pass_objective - 1e-6)
        self.assertGreaterEqual(compared, 18)

    def test_solve_in_parallel_keeps_the_input_order(self) -> None:
        """Parallel outcomes come back in order and match the instances they solve."""
        instances = [make_instance(seed, Knobs(n_employees=4 + seed, planted=True)) for seed in range(3)]
        outcomes = solve_in_parallel(instances, time_budget_seconds=10, workers=3)
        for instance, outcome in zip(instances, outcomes):
            with self.subTest(label=instance.label):
                self.assertEqual(outcome.status, "ok")
                self.assertEqual(validate(instance, outcome.assignments), [])

    def test_repair_completes_partial_rosters(self) -> None:
        """repair() fills a fill-in instance from its placements alone, validly."""
        repaired = 0
        for seed in range(20):
            instance = make_instance(seed, fill_in_knobs(random.Random(seed)))
            roster = repair(instance, seed=seed)
            if roster is not None:
                repaired += 1
                self.assertEqual(validate(instance, roster), [], instance.label)
                self.assertTrue(instance.fixed <= roster)
        self.assertGreaterEqual(repaired, 12)

    def test_regeneration_keeps_the_history_and_plants_valid_witnesses(self) -> None:
        """Every change yields an instance whose witness (when found) is valid and keeps history."""
        instance = make_instance(
            21,
            Knobs(n_employees=10, n_competences=2, recovery_profile="mixed", unavailability_rate=0.05,
                  preferred_rate=0.05, max_shifts_mode="loose", planted=True),
        )
        roster = sorted(instance.witness)
        cut = instance.days[12]
        planted = 0
        for index, change in enumerate(CHANGES):
            changed = regenerate(instance, roster, cut, change, seed=index)
            with self.subTest(change=change):
                self.assertEqual(changed.generate_from, cut)
                self.assertEqual(
                    {duty for duty in changed.fixed if duty[2] < cut},
                    {duty for duty in roster if duty[2] < cut},
                )
                if changed.witness is not None:
                    planted += 1
                    self.assertEqual(validate(changed, changed.witness), [])
        self.assertGreaterEqual(planted, 4)
        with fresh_session() as session:
            materialize(regenerate(instance, roster, cut, "vacation_block", seed=1), session)

    def test_regenerated_months_are_solved(self) -> None:
        """The solver re-generates a changed month without touching its history."""
        instance = make_instance(22, Knobs(n_employees=8, n_competences=2, planted=True))
        roster = sorted(instance.witness)
        changed = [regenerate(instance, roster, instance.days[10], change, seed=3) for change in ("absence", "leave", "demand_up")]
        changed = [item for item in changed if item.witness is not None]
        outcomes = solve_in_parallel(changed, time_budget_seconds=10, workers=len(changed))
        for item, outcome in zip(changed, outcomes):
            with self.subTest(label=item.label):
                self.assertEqual(outcome.status, "ok", outcome.issues)
                self.assertEqual(validate(item, outcome.assignments), [])

    def test_month_chain_across_the_year_end(self) -> None:
        """December, January and a leap February solved in a row, each fed by the last."""
        knobs = Knobs(n_employees=12, n_competences=2, month=12, year=2027, recovery_profile="long",
                      special_days="library", planted=True)

        def solve(instance: Instance) -> list[Duty] | None:
            outcome = run_solver(instance, time_budget_seconds=10)
            return outcome.assignments if outcome.status == "ok" else None

        chain = chain_months(5, knobs, 3, solve)
        self.assertEqual([(item.month, item.year) for item, _ in chain], [(12, 2027), (1, 2028), (2, 2028)])
        for (previous, roster), (following, _next) in zip(chain, chain[1:]):
            carried = {
                duty
                for duty in roster
                if duty[2] >= previous.days[-1] - timedelta(days=6) and duty[0] in following.employee_map
            }
            self.assertTrue(carried)
            self.assertTrue(carried <= following.adjacent)
            self.assertEqual(following.competences[0].weekday_recovery_days, previous.competences[0].weekday_recovery_days)
        for instance, roster in chain:
            with self.subTest(label=instance.label):
                self.assertIsNotNone(roster)
                self.assertEqual(validate(instance, roster), [])
        self.assertEqual(len(chain[-1][0].days), 29)


class DbRoundTripTests(unittest.TestCase):
    """The database writer hands the loader exactly the instance's problem."""

    def _round_trip(self, instance: Instance, **options: object) -> None:
        """Materialize, capture what the loader passes to the solver, compare."""
        with fresh_session() as session:
            world = materialize(instance, session, **options)
            captured = _capture_solver_input(session, world, instance)
            self._compare(instance, world, captured)

    def _compare(self, instance: Instance, world, captured: dict) -> None:
        """Every field the solver reads must match after id translation."""
        self.assertEqual((captured["month"], captured["year"]), (instance.month, instance.year))
        self.assertEqual(captured["generate_from"], instance.generate_from)
        self.assertEqual(
            sorted(world.to_instance_tuples(list(captured["fixed_assignments"]))), sorted(instance.fixed)
        )
        self.assertEqual(
            sorted(world.to_instance_tuples(list(captured["adjacent_assignments"]))),
            sorted(instance.adjacent),
        )
        loaded_policy: ConstraintPolicy = captured["constraints"]
        for definition in CONSTRAINTS:
            self.assertEqual(
                loaded_policy.rule(definition.code),
                instance.effective_policy.rule(definition.code),
                definition.code,
            )

        span = calendar_span(instance)
        self.assertEqual(len(captured["competences"]), len(instance.competences))
        loaded_competences = {world.competence_back[item.id]: item for item in captured["competences"]}
        self.assertEqual(set(loaded_competences), set(instance.competence_map))
        for competence_id, loaded in loaded_competences.items():
            original = instance.competence_map[competence_id]
            self.assertEqual(
                set(loaded.special_dates) & set(span), set(original.special_dates) & set(span)
            )
            for day in span:
                self.assertEqual(
                    (
                        loaded.required_on(day),
                        loaded.is_surcharge_on(day),
                        loaded.recovery_days_on(day),
                        loaded.shift_hours_on(day),
                    ),
                    (
                        original.required_on(day),
                        original.is_surcharge_on(day),
                        original.recovery_days_on(day),
                        original.shift_hours_on(day),
                    ),
                    f"competence {competence_id} on {day}",
                )

        self.assertEqual(len(captured["employees"]), len(instance.employees))
        loaded_employees = {world.user_back[item.id]: item for item in captured["employees"]}
        self.assertEqual(set(loaded_employees), set(instance.employee_map))
        for user_id, loaded in loaded_employees.items():
            original = instance.employee_map[user_id]
            with self.subTest(user_id=user_id):
                self.assertEqual(
                    {world.competence_back[item] for item in loaded.competence_ids},
                    set(original.competence_ids),
                )
                self.assertEqual(loaded.unavailable_dates, original.unavailable_dates)
                for day in original.unavailable_dates:
                    self.assertEqual(absence_rule(loaded, day), absence_rule(original, day))
                self.assertEqual(loaded.preferred_dates, original.preferred_dates)
                self.assertEqual(loaded.soft_declined_dates, original.soft_declined_dates)
                self.assertEqual(loaded.max_shifts_per_month, original.max_shifts_per_month)
                self.assertEqual(loaded.shift_preference, original.shift_preference)
                self.assertEqual(
                    loaded.externally_scheduled_dates, original.externally_scheduled_dates
                )
                self.assertEqual(
                    sorted(external_duties(loaded, captured["competences"])),
                    sorted(external_duties(original, instance.competences)),
                )
                explicit_dates = {day for day, _rest in original.external_commitments}
                self.assertEqual(
                    Counter(item for item in loaded.external_commitments if item[0] in explicit_dates),
                    Counter(original.external_commitments),
                )

    def test_round_trip_preserves_every_solver_input(self) -> None:
        """Feature-rich instances survive the trip through the database unchanged."""
        variants = [
            Knobs(
                month=12,
                year=2026,
                n_employees=9,
                n_competences=3,
                special_days="mixed",
                special_rate=0.1,
                demand_profile="mixed",
                recovery_profile="mixed",
                hours_profile="fractional",
                surcharge_profile="random",
                unavailability_rate=0.12,
                absence_mix=(0.4, 0.3, 0.3),
                vacation_block_rate=0.3,
                preferred_rate=0.1,
                soft_decline_rate=0.1,
                wish_pattern="crowd",
                max_shifts_mode="mixed",
                preference_mix="mixed",
                external_rate=0.05,
                external_explicit_rest=0.5,
                external_duplicate_rate=0.5,
                adjacent_rate=0.8,
                adjacent_retired_competence=True,
                generate_from="mid",
                n_fixed=4,
                n_breaking_fixed=2,
                policy=POLICY_PRESETS["penalized_all"],
                planted=True,
            ),
            Knobs(
                month=2,
                year=2028,
                n_employees=6,
                special_days="library",
                special_slot_differs=False,
                max_shifts_mode="zero",
                policy=POLICY_PRESETS["strict_everything"],
                external_rate=0.04,
                external_explicit_rest=0.0,
                planted=False,
            ),
            Knobs(
                month=1,
                year=2027,
                special_days="random",
                special_rate=0.2,
                recovery_profile="long",
                hours_profile="mixed",
                preference_mix="surcharge",
                adjacent_rate=0.5,
                policy=POLICY_PRESETS["silent_wishes"],
                planted=True,
            ),
        ]
        for seed, knobs in enumerate(variants):
            instance = make_instance(40 + seed, knobs)
            for options in ({}, {"noise": True}, {"foreign_calendar": True}):
                with self.subTest(label=instance.label, options=options):
                    self._round_trip(instance, **options)

    def test_round_trip_over_many_random_instances(self) -> None:
        """Forty instances from every sampler, a quarter with the default policy, round-trip exactly."""
        for seed in range(40):
            rng = random.Random(seed)
            sampler = seed % 4
            if sampler == 0:
                knobs = tiny_knobs(rng, False)
            elif sampler == 1:
                knobs = stress_knobs(rng, seed % 8 == 1)
            else:
                knobs = sample_knobs(rng, ("small", "medium")[sampler - 2], seed % 3 == 0)
            if seed % 4 == 3:
                knobs = replace(knobs, policy=None)
            knobs = replace(knobs, external_duplicate_rate=0.3 if seed % 5 == 0 else 0.0)
            instance = make_instance(seed, knobs)
            with self.subTest(label=instance.label):
                self._round_trip(instance, noise=seed % 2 == 0, foreign_calendar=seed % 3 == 0)

    def test_round_trip_through_the_loaders_fallbacks(self) -> None:
        """A scenario without the special slot, and no scenario at all, read as expected."""
        sunday_like = make_instance(
            8,
            Knobs(month=5, year=2026, n_employees=5, special_days="library", special_slot_differs=False,
                  recovery_profile="mixed", hours_profile="mixed", planted=True),
        )
        self._round_trip(sunday_like, scenario="no_special_slot")
        with self.assertRaises(InexpressibleInstance):
            different = make_instance(8, replace(knobs_of(sunday_like), special_slot_differs=True, demand_profile="heavy"))
            with fresh_session() as session:
                materialize(different, session, scenario="no_special_slot")

        holidays = frozenset({date(2026, 5, 1), date(2026, 5, 8)})
        plain = Instance(
            [_employee(user_id, frozenset({1, 2})) for user_id in range(1, 5)],
            [unconfigured_competence(1, 1, holidays), unconfigured_competence(2, 2, holidays)],
            5,
            2026,
        )
        self._round_trip(plain, scenario="none")
        with self.assertRaises(InexpressibleInstance):
            with fresh_session() as session:
                materialize(sunday_like, session, scenario="none")

    def test_overlapping_day_records_are_refused(self) -> None:
        """The application keeps one record per person and day; the writer says so."""
        instance = Instance(
            [_employee(1, preferred_dates=frozenset({date(2026, 8, 3)}), soft_declined_dates=frozenset({date(2026, 8, 3)}))],
            [_competence()],
            8,
            2026,
        )
        with fresh_session() as session, self.assertRaises(InexpressibleInstance):
            materialize(instance, session)
        far = Instance([_employee(1)], [_competence()], 8, 2026, adjacent=frozenset({(1, 1, date(2026, 7, 20))}))
        with fresh_session() as session, self.assertRaises(InexpressibleInstance):
            materialize(far, session)

    def test_database_path_solves_like_the_in_memory_one(self) -> None:
        """The loader path returns a valid roster as cheap as the direct call."""
        instance = make_instance(
            61,
            Knobs(
                n_employees=7,
                n_competences=2,
                special_days="library",
                month=12,
                year=2026,
                unavailability_rate=0.08,
                external_rate=0.03,
                adjacent_rate=0.6,
                n_fixed=2,
                generate_from=10,
                planted=True,
            ),
        )
        through_db = run_db_solver(instance, time_budget_seconds=15, noise=True, foreign_calendar=True)
        direct = run_solver(instance, time_budget_seconds=15)
        self.assertEqual(through_db.status, "ok", through_db.issues)
        self.assertEqual(direct.status, "ok", direct.issues)
        self.assertEqual(validate(instance, through_db.assignments), [])
        if through_db.seconds < 10 and direct.seconds < 10:
            self.assertAlmostEqual(
                first_pass_cost(instance, through_db.assignments),
                first_pass_cost(instance, direct.assignments),
                places=4,
            )


# --- Known solver bugs -----------------------------------------------------------------------


def _lock_drift_instance() -> Instance:
    """Five people, two roles at one a day, fractional hours, everybody "cannot" (penalized).

    The first pass pays 62 absences at 100 000 each, so the lock's relative
    slack (1e-7 * 6.2e6, about 0.62) is wider than the smallest fractional
    step of the hours ladder, and "want to" at 100 000 buys that drift.
    """
    rng = random.Random(2)
    days = [date(2026, 8, day) for day in range(1, 32)]
    competences = [
        SchedulingCompetence(
            id=competence_id,
            name=f"c{competence_id}",
            required_count=1,
            weekday_required_counts=(1,) * 7,
            weekday_recovery_days=(0,) * 7,
            weekday_shift_hours=tuple(rng.choice([4.5, 6.25, 7.5, 12.0]) for _ in range(7)),
            weekday_is_surcharge=tuple(rng.random() < 0.4 for _ in range(7)),
        )
        for competence_id in (1, 2)
    ]
    employees = [
        SchedulingEmployee(
            id=user_id,
            email=f"{user_id}@harness.test",
            full_name=None,
            competence_ids=frozenset({1, 2}),
            unavailable_dates=frozenset(days),
            externally_scheduled_dates=frozenset(),
            preferred_dates=frozenset(day for day in days if rng.random() < 0.3),
            shift_preference=rng.choice(["any", "surcharge", "standard"]),
        )
        for user_id in range(1, 6)
    ]
    return Instance(
        employees,
        competences,
        8,
        2026,
        policy=policy_from_settings({"unavailable": (False, 100000.0), "preferred": (False, 100000.0)}),
        label="lock-drift",
    )


def _duplicate_external_instance(order: tuple[tuple[date, int], ...]) -> Instance:
    """A works elsewhere on 25 August with rests 3 and 0; B cannot on the 26th."""
    a = _employee(1, externally_scheduled_dates=frozenset({date(2026, 8, 25)}), external_commitments=order)
    b = _employee(2, unavailable_dates=frozenset({date(2026, 8, 26)}))
    return Instance([a, b], [_competence(recovery=(0,) * 8)], 8, 2026, generate_from=date(2026, 8, 25))


def _penalized_rest_instance() -> Instance:
    """One person, five days of rest, penalized rest, the last three days to fill."""
    return Instance(
        [_employee(1)],
        [_competence(recovery=(5,) * 8)],
        8,
        2026,
        generate_from=date(2026, 8, 29),
        policy=policy_from_settings({REST: (False, 1000.0)}),
    )


class KnownSolverBugTests(unittest.TestCase):
    """One minimal reproduction per solver bug the harness found (see known_bugs.py).

    The ``expectedFailure`` tests assert the documented behaviour; each has a
    passing companion that pins the harness's own view of the same case.
    """

    def test_every_known_bug_has_a_test(self) -> None:
        """The registry and this class name the same tests."""
        names = set(dir(self))
        for bug in KNOWN_BUGS.values():
            if bug.surface != "docs":
                with self.subTest(bug=bug.key):
                    self.assertIn(bug.test, names)

    # Two duties elsewhere on one date --------------------------------------------------

    def test_duplicate_external_dates_harness_view(self) -> None:
        """The harness holds A for three days in either order; the month is then impossible."""
        for order in (
            ((date(2026, 8, 25), 3), (date(2026, 8, 25), 0)),
            ((date(2026, 8, 25), 0), (date(2026, 8, 25), 3)),
        ):
            instance = _duplicate_external_instance(order)
            with self.subTest(order=order):
                self.assertEqual(reference_feasibility(instance)[0], "infeasible")
                self.assertIn("duplicate_external_dates", known_bug_triggers(instance))
        reversed_order = _duplicate_external_instance(((date(2026, 8, 25), 0), (date(2026, 8, 25), 3)))
        self.assertEqual(run_solver(reversed_order, 5).status, "infeasible")

    @unittest.expectedFailure
    def test_duplicate_external_dates_keep_the_longer_rest(self) -> None:
        """Suspected bug: with the longer rest listed first, the solver keeps only the last entry.

        ``elsewhere = dict(employee.external_commitments)`` in
        ``solve_monthly_schedule`` keeps the last (date, rest) pair, so A gets
        0 days of rest after 25 August and is put on the 26th, inside the
        3-day rest of the other duty that day. Through the database the
        order is the Schedule rows' order (no ORDER BY).
        """
        instance = _duplicate_external_instance(((date(2026, 8, 25), 3), (date(2026, 8, 25), 0)))
        outcome = run_solver(instance, 5)
        self.assertEqual(outcome.status, "infeasible", validate(instance, outcome.assignments))

    @unittest.expectedFailure
    def test_db_duplicate_external_rows_keep_the_longer_rest(self) -> None:
        """Suspected bug, database path: two duties elsewhere on Tuesday, rests 4 and 0.

        The only employee must not take Wednesday's duty inside the 4-day
        rest; with the long-rest row stored first, the generator does.
        """
        tuesday = date(2026, 5, 12)
        employee = _employee(
            1, externally_scheduled_dates=frozenset({tuesday}), external_commitments=((tuesday, 4), (tuesday, 0))
        )
        wednesdays_only = _competence(counts=(0, 0, 1, 0, 0, 0, 0, 0), recovery=(1,) * 8)
        instance = Instance([employee], [wednesdays_only], 5, 2026)
        outcome = run_db_solver(instance, time_budget_seconds=5)
        self.assertEqual(outcome.status, "infeasible", validate(instance, outcome.assignments))

    # Zero balance weight -----------------------------------------------------------------

    @unittest.expectedFailure
    def test_zero_balance_weight_still_honours_day_wishes(self) -> None:
        """Suspected bug: balance weight 0 with strict overstaff skips the second pass.

        ``value(balance)`` is ``None`` when the first-pass objective has no
        live term, and ``if wishes and reached is not None`` then skips the
        wishes silently. Employee 1 declined every day, employee 2 nothing,
        rest is 0: the documented answer gives employee 1 no duty.
        """
        days = frozenset(date(2026, 8, day) for day in range(1, 32))
        instance = Instance(
            [_employee(1, soft_declined_dates=days), _employee(2)],
            [_competence(recovery=(0,) * 8)],
            8,
            2026,
            policy=policy_from_settings({BALANCE: (False, 0.0), OVERSTAFF: (True, 1.0)}),
        )
        self.assertIn("zero_balance_skips_wishes", known_bug_triggers(instance))
        outcome = run_solver(instance, 10, observe=True)
        self.assertEqual(outcome.status, "ok")
        self.assertIsNotNone(outcome.second_pass, "the second pass never ran")
        self.assertEqual(sum(duty[0] == 1 for duty in outcome.assignments), 0)

    def test_zero_balance_weight_with_penalized_overstaff_works(self) -> None:
        """Companion: with overstaff penalized the first pass has a live term and wishes are kept."""
        days = frozenset(date(2026, 8, day) for day in range(1, 32))
        instance = Instance(
            [_employee(1, soft_declined_dates=days), _employee(2)],
            [_competence(recovery=(0,) * 8)],
            8,
            2026,
            policy=policy_from_settings({BALANCE: (False, 0.0)}),
        )
        outcome = run_solver(instance, 10)
        self.assertEqual(sum(duty[0] == 1 for duty in outcome.assignments), 0)

    # Balance lock slack ------------------------------------------------------------------

    @unittest.expectedFailure
    def test_second_pass_never_buys_a_less_balanced_roster(self) -> None:
        """Suspected bug: the lock's 1e-7 * |reached| slack lets wishes buy imbalance.

        README: wishes "never buy a less balanced roster"; model doc 3.2
        claims every balance difference is a whole number. Here the first
        pass reaches an integer, both passes are proved optimal, and the
        final roster's first-pass cost is about 0.48 higher.
        """
        instance = _lock_drift_instance()
        outcome = run_solver(instance, 10, observe=True)
        self.assertEqual(outcome.status, "ok")
        self.assertLessEqual(first_pass_cost(instance, outcome.assignments), outcome.first_pass_objective + 1e-3)

    def test_lock_drift_is_reported_as_lock_drift(self) -> None:
        """Companion: the drift stays within the lock, and the local search names it so."""
        instance = _lock_drift_instance()
        self.assertIn("balance_lock_drift", known_bug_triggers(instance))
        outcome = run_solver(instance, 10, observe=True)
        self.assertEqual(outcome.status, "ok")
        self.assertTrue(outcome.first_pass.optimal)
        final = first_pass_cost(instance, outcome.assignments)
        self.assertLessEqual(final, outcome.balance_cap + 1e-6)
        moves = find_improving_moves(instance, outcome.assignments, balance_cap=outcome.balance_cap)
        self.assertFalse([move for move in moves if move.reason == "first_pass"])

    # Penalized rest at the month's end ---------------------------------------------------

    def test_penalized_rest_harness_matches_the_solver(self) -> None:
        """Companion: the harness's cost equals the solver's first-pass value (3 days charged)."""
        instance = _penalized_rest_instance()
        outcome = run_solver(instance, 5, observe=True)
        self.assertEqual(sorted(day for _u, _k, day in outcome.assignments), [date(2026, 8, d) for d in (29, 30, 31)])
        self.assertAlmostEqual(first_pass_cost(instance, outcome.assignments), outcome.first_pass_objective)
        self.assertEqual(metrics(instance, outcome.assignments).rest_breach_days, 3)

    @unittest.expectedFailure
    def test_penalized_rest_is_charged_for_every_shared_day(self) -> None:
        """Suspected bug: overlap past the month's end is free between duties of the model.

        Model doc 6: one pays "for every day on which the rests of two duties
        overlap". Duties on 29, 30 and 31 August with five days of rest
        overlap on 30 August - 4 September: 10 breach-days by that reading
        (sum over days of holders - 1). The solver charges only 3, the
        in-month ones, while a duty against one just outside the month is
        charged every shared day.
        """
        instance = _penalized_rest_instance()
        outcome = run_solver(instance, 5, observe=True)
        duties = outcome.assignments
        rest = 5
        charged = sum(
            max(0, sum(holds(duty[2], rest, day) for duty in duties) - 1)
            for day in (date(2026, 8, 29) + timedelta(days=offset) for offset in range(12))
        )
        self.assertEqual(charged, 10)
        ladders = first_pass_cost(replace(instance, policy=policy_from_settings({REST: (False, 0.0)})), duties)
        self.assertAlmostEqual(outcome.first_pass_objective, ladders + 1000 * charged)

    # Error message --------------------------------------------------------------------------

    @unittest.expectedFailure
    def test_capacity_failure_names_the_tightened_rule(self) -> None:
        """Suspected bug: a capacity pre-check failure omits ``tightened_constraints``.

        README: a failure under a rule the workplace made strict names it.
        A strict "rather not" removes the only candidate on 30 August, which
        the capacity pre-check reports without naming ``soft_decline``.
        """
        instance = Instance(
            [_employee(1, soft_declined_dates=frozenset({date(2026, 8, 30)}))],
            [_competence(recovery=(0,) * 8)],
            8,
            2026,
            generate_from=date(2026, 8, 28),
            policy=policy_from_settings({SOFT_DECLINE: (True, 10.0)}),
        )
        outcome = run_solver(instance, 5)
        self.assertEqual(outcome.status, "infeasible")
        named = [issue.get("tightened_constraints") or [] for issue in outcome.issues]
        self.assertTrue(any(SOFT_DECLINE in item for item in named), outcome.issues)

    def test_constraint_conflict_names_the_tightened_rule(self) -> None:
        """Companion: a conflict found by CBC does name the tightened rule."""
        instance = Instance(
            [_employee(1, max_shifts_per_month=2)],
            [_competence(recovery=(0,) * 8)],
            8,
            2026,
            generate_from=date(2026, 8, 28),
            policy=policy_from_settings({MAX_SHIFTS: (True, 1000.0)}),
        )
        outcome = run_solver(instance, 5)
        self.assertEqual(outcome.issue_codes, {"constraint_conflict"})
        self.assertIn(MAX_SHIFTS, outcome.issues[0]["tightened_constraints"])

    # Database-only -----------------------------------------------------------------------

    @unittest.expectedFailure
    def test_duty_at_an_unconfigured_workplace_earns_the_fallback_rest(self) -> None:
        """Suspected bug: a duty at a workplace with no scenario earns 1 day, not the fallback.

        Model doc 2.2 and the SchedulingEmployee docstring: with nothing
        configured there, the duty earns the longest rest this workplace
        gives that day (3 here). ``foreign_recovery_reader`` answers
        DEFAULT_RECOVERY_DAYS (1) and always fills external_commitments, so
        the solver's own fallback is never reached from the database.
        """
        day = date(2026, 8, 10)
        instance = Instance(
            [_employee(1, externally_scheduled_dates=frozenset({day})), _employee(2)],
            [_competence(recovery=(3,) * 8)],
            8,
            2026,
        )
        self.assertIn("unconfigured_external_rest", db_bug_triggers(instance, external_fallback="unconfigured"))
        with fresh_session() as session:
            world = materialize(instance, session, external_fallback="unconfigured")
            captured = _capture_solver_input(session, world, instance)
        loaded = next(item for item in captured["employees"] if world.user_back[item.id] == 1)
        self.assertEqual(external_duties(loaded, captured["competences"]), [(day, 3)])

    @unittest.expectedFailure
    def test_wish_reasons_are_read_case_insensitively(self) -> None:
        """Suspected bug: 'preferred', 'soft_decline' and ' SOFT_DECLINE' become hard absences.

        ``_is_hard_unavailability`` compares the raw reason while
        ``_absence_rule``, schedule_context_service and schedule_service
        normalize with strip().upper(); the API stores free text.
        """
        instance = Instance([_employee(1)], [_competence()], 8, 2026)
        spellings = {date(2026, 8, 5): "preferred", date(2026, 8, 6): "soft_decline", date(2026, 8, 7): " SOFT_DECLINE"}
        with fresh_session() as session:
            world = materialize(instance, session)
            for day, reason in spellings.items():
                session.add(Unavailability(user_id=world.user_ids[1], date_absent=day, reason=reason, is_active=True))
            session.commit()
            captured = _capture_solver_input(session, world, instance)
        loaded = captured["employees"][0]
        self.assertEqual(loaded.unavailable_dates, frozenset())
        self.assertEqual(loaded.preferred_dates, {date(2026, 8, 5)})
        self.assertEqual(loaded.soft_declined_dates, {date(2026, 8, 6), date(2026, 8, 7)})

    def _retired_world(self, session):
        """June 2026: one person, a role needed on Tuesdays, a 31 May duty in a retired role (rest 4)."""
        live = _competence(counts=(0, 1, 0, 0, 0, 0, 0, 0), recovery=(1,) * 8)
        instance = Instance(
            [_employee(1)],
            [live],
            6,
            2026,
            adjacent=frozenset({(1, RETIRED_COMPETENCE_ID, date(2026, 5, 31))}),
        )
        world = materialize(instance, session, retired_recovery=4)
        return instance, world

    def test_deactivated_competence_planner_view(self) -> None:
        """Companion: the planner's context credits the 31 May duty with its stored 4 days."""
        with fresh_session() as session:
            instance, world = self._retired_world(session)
            self.assertIn("retired_competence_rest", db_bug_triggers(instance, retired_recovery=4))
            context = schedule_context_service.get_schedule_context(session, world.ambulance_id, 6, 2026)
            duties = [duty for employee in context.employees for duty in employee.duties]
            self.assertEqual([(duty.work_date, duty.recovery_days) for duty in duties], [(date(2026, 5, 31), 4)])

    @unittest.expectedFailure
    def test_deactivated_competence_keeps_its_stored_rest(self) -> None:
        """Unclear: the generator gives a duty in a deactivated competence 1 day of rest.

        The planner (get_schedule_context) reads the stored 4 days, so the
        generated 2 June duty shows up as a rest conflict in the editor.
        Either the generator should read the stored rest, or the planner
        should agree on 1 day; today they disagree.
        """
        with fresh_session() as session:
            instance, world = self._retired_world(session)
            response = generate_ambulance_monthly_schedule(session, world.ambulance_id, 6, 2026, time_budget_seconds=5)
        self.assertNotIn(date(2026, 6, 2), [entry.work_date for entry in response.entries])


if __name__ == "__main__":
    unittest.main()
