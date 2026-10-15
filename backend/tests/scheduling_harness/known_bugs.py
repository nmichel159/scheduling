"""Solver behaviour the self-check has found to disagree with the documentation.

Each entry has a minimal reproducing test in ``tests/test_harness_selfcheck.py``
(class ``KnownSolverBugTests``), marked ``unittest.expectedFailure``. When one
of those tests starts passing ("unexpected success"), the bug was fixed:
remove the marker and the entry here.

:func:`known_bug_triggers` tells a test whether an instance can run into one
of them, so a sweep can skip, ``expectedFailure`` or tally those instances
instead of reporting the same bug a hundred times.
"""

from __future__ import annotations

from dataclasses import dataclass

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
)

from tests.scheduling_harness.instances import Instance
from tests.scheduling_harness.semantics import (
    UNKNOWN_COMPETENCE_REST,
    fallback_external_rest,
    has_duplicate_external_dates,
)


@dataclass(frozen=True)
class KnownBug:
    """One documented disagreement between the solver and its documentation."""

    key: str
    title: str
    #: confirmed | unclear (behaviour is consistent but the intent is not)
    status: str
    #: in_memory | db | error_message | objective | docs
    surface: str
    test: str


KNOWN_BUGS: dict[str, KnownBug] = {
    bug.key: bug
    for bug in (
        KnownBug(
            "duplicate_external_dates",
            "Two duties elsewhere on one date: the solver keeps the last (date, rest) "
            "entry, not the longer rest, so strict rest can be broken depending on row order",
            "confirmed",
            "in_memory",
            "test_duplicate_external_dates_keep_the_longer_rest",
        ),
        KnownBug(
            "zero_balance_skips_wishes",
            "BALANCE weight 0 (with nothing else in the first pass) makes value(balance) "
            "None, so the second pass is silently skipped and day wishes are ignored",
            "confirmed",
            "in_memory",
            "test_zero_balance_weight_still_honours_day_wishes",
        ),
        KnownBug(
            "balance_lock_drift",
            "The balance lock's relative slack (1e-7 * |reached|) lets the second pass return "
            "a less balanced roster once the first pass pays large penalties",
            "confirmed",
            "objective",
            "test_second_pass_never_buys_a_less_balanced_roster",
        ),
        KnownBug(
            "penalized_rest_month_end",
            "Penalized rest between two duties of the model is charged only on the month's "
            "days; against duties outside the model every shared day is charged",
            "confirmed",
            "objective",
            "test_penalized_rest_is_charged_for_every_shared_day",
        ),
        KnownBug(
            "capacity_error_without_tightened_rules",
            "A capacity pre-check failure caused by a tightened rule does not name it in "
            "tightened_constraints (only constraint_conflict does)",
            "confirmed",
            "error_message",
            "test_capacity_failure_names_the_tightened_rule",
        ),
        KnownBug(
            "unconfigured_external_rest",
            "Database path: a duty at a workplace with no settings earns 1 day of rest, not "
            "the documented fallback (longest rest this workplace gives that day)",
            "confirmed",
            "db",
            "test_duty_at_an_unconfigured_workplace_earns_the_fallback_rest",
        ),
        KnownBug(
            "noncanonical_reason",
            "Database path: 'preferred' / 'soft_decline' / ' SOFT_DECLINE' are read as hard "
            "absences; only the exact upper-case spellings become wishes",
            "confirmed",
            "db",
            "test_wish_reasons_are_read_case_insensitively",
        ),
        KnownBug(
            "retired_competence_rest",
            "Database path: a duty just outside the month in a deactivated competence earns 1 "
            "day in the generator but its stored rest in the planner's conflict check",
            "unclear",
            "db",
            "test_deactivated_competence_keeps_its_stored_rest",
        ),
        KnownBug(
            "doc_coverage_equality",
            "Model doc 2.1 says coverage is an equality; by default it is '>= demand' "
            "(overstaffing penalized), equality only when overstaff is strict",
            "confirmed",
            "docs",
            "(documentation only)",
        ),
    )
}

#: First-pass rules whose weight, when large, makes the lock slack noticeable.
_FIRST_PASS_RULES = (UNAVAILABLE, VACATION, BUSINESS_TRIP, REST, MAX_SHIFTS, OVERSTAFF)


def known_bug_triggers(instance: Instance) -> set[str]:
    """Keys of :data:`KNOWN_BUGS` an in-memory solve of this instance may hit.

    Conservative: a key listed here means "may", not "will". DB-only bugs
    are reported by :func:`db_bug_triggers`.
    """
    policy = instance.effective_policy
    found: set[str] = set()
    if any(has_duplicate_external_dates(employee) for employee in instance.employees):
        found.add("duplicate_external_dates")
    soft_weight = 0.0 if policy.is_strict(SOFT_DECLINE) else policy.weight(SOFT_DECLINE)
    has_wishes = (
        (policy.weight(PREFERRED) > 0 and any(e.preferred_dates for e in instance.employees))
        or (soft_weight > 0 and any(e.soft_declined_dates for e in instance.employees))
        or policy.weight(SPREAD) > 0
    )
    if policy.weight(BALANCE) == 0 and has_wishes:
        found.add("zero_balance_skips_wishes")
    if any(
        not policy.is_strict(code) and policy.weight(code) >= 10_000 for code in _FIRST_PASS_RULES
    ):
        found.add("balance_lock_drift")
    if not policy.is_strict(REST) and policy.weight(REST) > 0:
        found.add("penalized_rest_month_end")
    return found


def db_bug_triggers(
    instance: Instance,
    external_fallback: str = "explicit",
    retired_recovery: int | None = None,
    **_other_options: object,
) -> set[str]:
    """Keys of :data:`KNOWN_BUGS` a database solve of this instance may hit.

    Takes the same keyword options as ``db_builder.materialize``.
    """
    found = known_bug_triggers(instance)
    if external_fallback == "unconfigured":
        explicit_dates = {
            (employee.id, day) for employee in instance.employees for day, _ in employee.external_commitments
        }
        for employee in instance.employees:
            for day in employee.externally_scheduled_dates:
                if (employee.id, day) not in explicit_dates and fallback_external_rest(
                    instance.competences, day
                ) != UNKNOWN_COMPETENCE_REST:
                    found.add("unconfigured_external_rest")
    if (
        retired_recovery is not None
        and retired_recovery != UNKNOWN_COMPETENCE_REST
        and any(duty[1] not in instance.competence_map for duty in instance.adjacent)
    ):
        found.add("retired_competence_rest")
    return found
