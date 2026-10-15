"""Deterministic problem instances for the schedule generator.

Two kinds of instance come out of :func:`make_instance`:

* **Random** instances draw every input independently. Nothing is promised
  about them -- they may well be infeasible -- which is what makes them good
  at testing the solver's infeasibility claims against a second opinion.
* **Planted** instances (``Knobs.planted``) are built backwards. The demand
  comes first, then a hidden roster (the *witness*) that keeps every hard rule
  of the chosen policy, and only then the absences, wishes, duties elsewhere,
  monthly maxima, duties around the month and manual placements -- each one
  added only where it cannot invalidate the witness. A planted instance is
  therefore feasible by construction, and a solver that calls one infeasible
  is wrong.

Every input the solver reads is drawn from :class:`Knobs`, and everything is
derived from ``random.Random`` streams seeded from the seed alone, so a seed
and a set of knobs name one instance exactly -- in every interpreter, whatever
``PYTHONHASHSEED`` is (no random draw ever depends on the iteration order of
a set). The structure of a workplace -- its roles, their eight day slots and
who holds which role -- comes from a stream of its own, so the same seed and
knobs in another month give the same workplace (see :func:`next_month_knobs`).
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import asdict, dataclass, field, fields, replace
from datetime import date, timedelta
from functools import cached_property
from math import ceil, floor
from typing import Any, Iterable

from app.models.competence_weekday_requirement import (
    DEFAULT_RECOVERY_DAYS,
    DEFAULT_SHIFT_HOURS,
    SPECIAL_DAY_SLOT,
    default_is_surcharge,
)
from app.services.constraint_setting_service import (
    BALANCE,
    BUSINESS_TRIP,
    CONSTRAINTS,
    MAX_SHIFTS,
    MODE_FIXED,
    MODE_PENALTY,
    PREFERRED,
    REST,
    SOFT_DECLINE,
    SPREAD,
    UNAVAILABLE,
    VACATION,
    ConstraintPolicy,
    policy_from_settings,
)
from app.services.schedule_generation_service import (
    SchedulingCompetence,
    SchedulingEmployee,
)
from app.services.special_day_service import library_rest_days

from tests.scheduling_harness.semantics import (
    MARGIN_DAYS,
    Duty,
    date_range,
    duty_rest,
    fallback_external_rest,
    month_days,
    touches,
)

#: Competence id used for duties around the month in a role the workplace
#: no longer has. The solver must credit such a duty with one day of rest.
RETIRED_COMPETENCE_ID = 900

#: The three absence rules, in the order ``absence_mix`` and ``block_mix``
#: weigh them.
ABSENCE_RULES = (UNAVAILABLE, VACATION, BUSINESS_TRIP)

#: Ready-made policies, by name, as ``code -> (strict, weight)``.
POLICY_PRESETS: dict[str, dict[str, tuple[bool, float]]] = {
    "default": {},
    "strict_load": {
        MAX_SHIFTS: (True, 1000.0),
        "overstaff": (True, 1000.0),
    },
    "strict_wishes": {SOFT_DECLINE: (True, 10.0)},
    "strict_everything": {
        MAX_SHIFTS: (True, 1000.0),
        "overstaff": (True, 1000.0),
        SOFT_DECLINE: (True, 10.0),
    },
    "penalized_absences": {
        UNAVAILABLE: (False, 1000.0),
        VACATION: (False, 500.0),
        BUSINESS_TRIP: (False, 2000.0),
    },
    "penalized_rest": {REST: (False, 1000.0)},
    "penalized_all": {
        UNAVAILABLE: (False, 1000.0),
        VACATION: (False, 1000.0),
        BUSINESS_TRIP: (False, 1000.0),
        REST: (False, 300.0),
    },
    "cheap_penalties": {
        MAX_SHIFTS: (False, 2.0),
        "overstaff": (False, 3.0),
        REST: (False, 5.0),
    },
    "heavy_balance": {"balance": (False, 40.0), "preferred": (False, 25.0)},
    "silent_wishes": {
        "preferred": (False, 0.0),
        SOFT_DECLINE: (False, 0.0),
        "spread": (False, 0.0),
    },
}

#: Weights :func:`random_policy` draws from, per kind of rule.
SWITCHABLE_WEIGHTS = (0.0, 0.5, 1.0, 10.0, 1000.0)
BALANCE_WEIGHTS = (0.0, 0.5, 1.0, 4.0, 40.0)
WISH_WEIGHTS = (0.0, 1.0, 10.0, 100.0)
SPREAD_WEIGHTS = (0.0, 0.5, 1.0, 5.0)


class PlantingFailed(RuntimeError):
    """A planted instance needed more spare employees than ``Knobs.max_spares``."""


@dataclass
class Instance:
    """One complete input of ``solve_monthly_schedule``, plus what it hides.

    ``adjacent`` are duties at this workplace within a week outside the
    month; ``fixed`` are manual placements inside it. ``witness`` is a roster
    known to keep every hard rule (planted instances only). ``knobs`` holds
    the knobs it was made from (as a dict), the ``seed`` and the number of
    ``spares`` the planter had to add.
    """

    employees: list[SchedulingEmployee]
    competences: list[SchedulingCompetence]
    month: int
    year: int
    adjacent: frozenset[Duty] = frozenset()
    fixed: frozenset[Duty] = frozenset()
    generate_from: date | None = None
    policy: ConstraintPolicy | None = None
    witness: frozenset[Duty] | None = None
    label: str = ""
    knobs: dict[str, Any] = field(default_factory=dict)

    @cached_property
    def days(self) -> list[date]:
        """Every date of the month."""
        return month_days(self.month, self.year)

    @cached_property
    def day_set(self) -> frozenset[date]:
        """The month's dates, as a set."""
        return frozenset(self.days)

    @cached_property
    def window_days(self) -> list[date]:
        """Dates the solver may fill."""
        return [
            day
            for day in self.days
            if self.generate_from is None or day >= self.generate_from
        ]

    @cached_property
    def history_days(self) -> list[date]:
        """Dates before ``generate_from``, which keep only their placements."""
        window = set(self.window_days)
        return [day for day in self.days if day not in window]

    @cached_property
    def employee_map(self) -> dict[int, SchedulingEmployee]:
        """Employees by id."""
        return {employee.id: employee for employee in self.employees}

    @cached_property
    def competence_map(self) -> dict[int, SchedulingCompetence]:
        """Competences by id."""
        return {competence.id: competence for competence in self.competences}

    @cached_property
    def special_dates(self) -> frozenset[date]:
        """Days of rest, as the competences carry them."""
        found: set[date] = set()
        for competence in self.competences:
            found |= set(competence.special_dates)
        return frozenset(found)

    @property
    def effective_policy(self) -> ConstraintPolicy:
        """The policy with defaults filled in."""
        return self.policy or ConstraintPolicy.default()

    @property
    def spares(self) -> int:
        """How many fully qualified spare employees the planter added."""
        return int(self.knobs.get("spares", 0))

    def solver_kwargs(self) -> dict[str, Any]:
        """Keyword arguments for ``solve_monthly_schedule``."""
        return {
            "employees": list(self.employees),
            "competences": list(self.competences),
            "month": self.month,
            "year": self.year,
            "adjacent_assignments": self.adjacent,
            "fixed_assignments": self.fixed,
            "generate_from": self.generate_from,
            "constraints": self.policy,
        }


@dataclass
class Knobs:
    """Everything :func:`make_instance` varies, with ordinary defaults.

    Profiles are short strings; the accepted values are listed beside each.
    Every knob added after the first version defaults to "off", so old knob
    sets keep their meaning.
    """

    n_employees: int = 8
    n_competences: int = 2
    month: int = 8
    year: int = 2026
    #: Chance an employee holds each competence (``iid`` structure).
    qualification_density: float = 0.75
    #: Chance an employee holds no competence at all.
    unqualified_employee_rate: float = 0.0
    #: iid | hierarchy (seniors hold all, juniors one) | rare (role 1 is held
    #: by one or two people only).
    qualification_structure: str = "iid"
    #: flat | weekday | sparse | heavy | mixed (per competence).
    demand_profile: str = "flat"
    #: None, or a share of the staff's rough capacity the demand should use
    #: (e.g. 0.5, 0.8, 0.95). Overrides the profile's non-zero counts.
    target_utilization: float | None = None
    #: The last this many competences ask for nobody all month.
    zero_demand_competences: int = 0
    #: none | library | random | mixed.
    special_days: str = "none"
    special_rate: float = 0.08
    #: Whether the special slot gets parameters of its own (otherwise it
    #: copies Sunday's).
    special_slot_differs: bool = True
    #: zero | one | mixed | long.
    recovery_profile: str = "one"
    #: uniform4 | uniform12 | mixed | fractional.
    hours_profile: str = "uniform4"
    #: weekend | random | none | all.
    surcharge_profile: str = "weekend"
    #: Chance per employee and day of a single absence.
    unavailability_rate: float = 0.0
    #: Shares of plain "cannot", vacation and business trip.
    absence_mix: tuple[float, float, float] = (1.0, 0.0, 0.0)
    #: Chance per employee of one contiguous absence of 3-14 days, drawn
    #: before the witness so the witness works around it.
    vacation_block_rate: float = 0.0
    #: Shares of "cannot", vacation and business trip among the blocks.
    block_mix: tuple[float, float, float] = (0.1, 0.6, 0.3)
    #: Whether every block starts within the same five days (holiday crowd).
    block_cluster: bool = False
    preferred_rate: float = 0.0
    soft_decline_rate: float = 0.0
    #: iid | weekday (each person likes some weekdays, dislikes one) | crowd
    #: (everyone wants, and avoids, the same few dates).
    wish_pattern: str = "iid"
    #: none | zero | loose | tight | below | hetero | starved | mixed.
    max_shifts_mode: str = "none"
    #: any | surcharge | standard | mixed.
    preference_mix: str = "any"
    #: Chance per employee and day (month +/- a week) of a duty elsewhere.
    external_rate: float = 0.0
    #: Share of those duties that carry their own rest.
    external_explicit_rest: float = 1.0
    #: Chance a duty elsewhere with its own rest gets a second duty elsewhere
    #: on the same date with another rest (entries in random order).
    external_duplicate_rate: float = 0.0
    #: Chance per needed person and day of a duty just outside the month.
    adjacent_rate: float = 0.0
    adjacent_retired_competence: bool = False
    #: None, a day of the month, or "mid" for a random mid-month day.
    generate_from: int | str | None = None
    #: Share of the history's duties kept as placements (planted/random).
    keep_history: float = 1.0
    #: Manual placements inside the window, taken from the witness.
    n_fixed: int = 0
    #: Share of the witness's window duties pinned as manual placements, on
    #: top of ``n_fixed`` (fill-in: the solver completes a partial roster).
    fixed_share: float = 0.0
    #: Whole window days whose every duty is pinned.
    fixed_full_days: int = 0
    #: Manual placements that break a rule on purpose.
    n_breaking_fixed: int = 0
    #: Kinds of rule-breaking placements to draw from.
    breaking_kinds: tuple[str, ...] = (
        "two_roles",
        "inside_rest",
        "unqualified",
        "absence",
        "above_demand",
    )
    #: ``code -> (strict, weight)`` passed through ``policy_from_settings``.
    policy: dict[str, tuple[bool, float]] | None = None
    planted: bool = False
    #: Planted only: whether the witness keeps rest even where it is penalized.
    #: When it does not, duties elsewhere may also collide with the witness's
    #: rest under a penalized rest rule.
    witness_keeps_rest: bool = True
    #: Planted only: the most fully qualified spare employees the planter may
    #: add when its greedy fill keeps failing; ``None`` means no limit.
    #: Exceeding it raises :class:`PlantingFailed`.
    max_spares: int | None = None


class _Draft:
    """An employee while the instance is still being drawn."""

    def __init__(self, user_id: int) -> None:
        """Start an employee with nothing."""
        self.id = user_id
        self.competence_ids: set[int] = set()
        self.absences: dict[date, str] = {}
        self.preferred: set[date] = set()
        self.soft_declined: set[date] = set()
        #: Day worked elsewhere -> the rests given for it, in entry order;
        #: ``None`` means "not known, use the fallback".
        self.externals: dict[date, list[int | None]] = {}
        self.max_shifts: int | None = None
        self.preference = "any"

    def taken(self, day: date) -> bool:
        """Whether the day already carries an absence or a day wish."""
        return day in self.absences or day in self.preferred or day in self.soft_declined

    def build(self) -> SchedulingEmployee:
        """Freeze the draft into the solver's input type."""
        return SchedulingEmployee(
            id=self.id,
            email=f"employee{self.id}@harness.test",
            full_name=f"Employee {self.id}",
            competence_ids=frozenset(self.competence_ids),
            unavailable_dates=frozenset(self.absences),
            externally_scheduled_dates=frozenset(self.externals),
            preferred_dates=frozenset(self.preferred),
            soft_declined_dates=frozenset(self.soft_declined),
            max_shifts_per_month=self.max_shifts,
            shift_preference=self.preference,
            external_commitments=tuple(
                (day, rest)
                for day in sorted(self.externals)
                for rest in self.externals[day]
                if rest is not None
            ),
            # A plain "cannot" may be listed or left out -- both mean the same
            # -- so about half of them are listed, to exercise both readings.
            absence_rules=tuple(
                sorted(
                    (day, rule) for day, rule in self.absences.items() if rule != UNAVAILABLE
                )
                + sorted(
                    (day, rule)
                    for day, rule in self.absences.items()
                    if rule == UNAVAILABLE and (day.day + self.id) % 2 == 0
                )
            ),
        )


def _stream(seed: int, purpose: int, month: int = 0, year: int = 0) -> random.Random:
    """An independent random stream for one purpose of one instance."""
    return random.Random(((seed * 1_000_003 + purpose) * 10_007 + year) * 13 + month)


# --- Structure ----------------------------------------------------------------


def _special_dates(rng: random.Random, knobs: Knobs, first: date, last: date) -> frozenset[date]:
    """Days of rest for the month and a week either side."""
    span = date_range(first, last)
    library: set[date] = set()
    for year in range(first.year, last.year + 1):
        library |= {day for day in library_rest_days(year) if first <= day <= last}
    if knobs.special_days == "none":
        return frozenset()
    if knobs.special_days == "library":
        return frozenset(library)
    extra = {day for day in span if rng.random() < knobs.special_rate}
    if knobs.special_days == "random":
        return frozenset(extra)
    removed = {day for day in sorted(library) if rng.random() < 0.4}
    return frozenset((library - removed) | extra)


def _demand_slots(rng: random.Random, profile: str) -> list[int]:
    """Eight required counts (Monday..Sunday, day of rest) for one profile."""
    if profile == "mixed":
        profile = rng.choice(["flat", "weekday", "sparse", "heavy"])
    if profile == "flat":
        return [1] * 8
    if profile == "weekday":
        return [rng.choice([1, 1, 2]) for _ in range(5)] + [
            rng.choice([0, 1, 1]) for _ in range(3)
        ]
    if profile == "sparse":
        slots = [rng.choice([0, 0, 1]) for _ in range(8)]
        if not any(slots):
            slots[rng.randrange(7)] = 1
        return slots
    if profile == "heavy":
        return [rng.choice([1, 2, 3]) for _ in range(8)]
    raise ValueError(f"unknown demand profile {profile!r}")


def _recovery_slots(rng: random.Random, profile: str) -> list[int]:
    """Eight recovery values for one profile."""
    if profile == "zero":
        return [0] * 8
    if profile == "one":
        return [1] * 8
    if profile == "mixed":
        return [rng.randint(0, 3) for _ in range(8)]
    if profile == "long":
        return [rng.randint(2, 6) for _ in range(8)]
    raise ValueError(f"unknown recovery profile {profile!r}")


def _hours_slots(rng: random.Random, profile: str) -> list[float]:
    """Eight shift lengths for one profile."""
    if profile == "uniform4":
        return [4.0] * 8
    if profile == "uniform12":
        return [12.0] * 8
    if profile == "mixed":
        return [float(rng.choice([4, 8, 12, 24])) for _ in range(8)]
    if profile == "fractional":
        return [rng.choice([4.5, 6.25, 7.5, 12.0]) for _ in range(8)]
    raise ValueError(f"unknown hours profile {profile!r}")


def _surcharge_slots(rng: random.Random, profile: str) -> list[bool]:
    """Eight surcharge flags for one profile."""
    if profile == "weekend":
        return [False] * 5 + [True] * 3
    if profile == "random":
        return [rng.random() < 0.4 for _ in range(8)]
    if profile == "none":
        return [False] * 8
    if profile == "all":
        return [True] * 8
    raise ValueError(f"unknown surcharge profile {profile!r}")


def _competence(
    rng: random.Random, knobs: Knobs, competence_id: int, special: frozenset[date]
) -> SchedulingCompetence:
    """One competence with all eight slots filled in."""
    counts = _demand_slots(rng, knobs.demand_profile)
    recovery = _recovery_slots(rng, knobs.recovery_profile)
    hours = _hours_slots(rng, knobs.hours_profile)
    surcharge = _surcharge_slots(rng, knobs.surcharge_profile)
    if competence_id > knobs.n_competences - knobs.zero_demand_competences:
        counts = [0] * 8
    if not knobs.special_slot_differs:
        counts[7], recovery[7], hours[7], surcharge[7] = (
            counts[6],
            recovery[6],
            hours[6],
            surcharge[6],
        )
    return _with_counts(
        SchedulingCompetence(
            id=competence_id,
            name=f"Role {competence_id}",
            required_count=1,
            special_dates=special,
            weekday_is_surcharge=tuple(surcharge[:7]),
            special_day_is_surcharge=surcharge[7],
            weekday_recovery_days=tuple(recovery[:7]),
            special_day_recovery_days=recovery[7],
            weekday_shift_hours=tuple(hours[:7]),
            special_day_shift_hours=hours[7],
        ),
        counts,
    )


def _with_counts(competence: SchedulingCompetence, counts: list[int]) -> SchedulingCompetence:
    """A competence with its eight required counts replaced."""
    return replace(
        competence,
        required_count=max(1, counts[0]),
        weekday_required_counts=tuple(counts[:7]),
        special_day_required_count=counts[7],
    )


def _slot_counts(competence: SchedulingCompetence) -> list[int]:
    """The eight required counts of a competence built by this module."""
    return list(competence.weekday_required_counts or ()) + [
        int(competence.special_day_required_count or 0)
    ]


def _qualify(
    rng: random.Random, knobs: Knobs, user_ids: list[int], competence_ids: list[int]
) -> dict[int, set[int]]:
    """Give every employee their competences, by the qualification structure."""
    held: dict[int, set[int]] = {}
    structure = knobs.qualification_structure
    for user_id in user_ids:
        if rng.random() < knobs.unqualified_employee_rate:
            held[user_id] = set()
            continue
        if structure == "hierarchy":
            if rng.random() < 0.35:
                held[user_id] = set(competence_ids)
            else:
                held[user_id] = {rng.choice(competence_ids)}
            continue
        if structure not in ("iid", "rare"):
            raise ValueError(f"unknown qualification structure {structure!r}")
        chosen = {
            competence_id
            for competence_id in competence_ids
            if rng.random() < knobs.qualification_density
        }
        held[user_id] = chosen or {rng.choice(competence_ids)}
    if structure == "rare" and competence_ids:
        rare = competence_ids[0]
        holders = [user_id for user_id in user_ids if rare in held[user_id]]
        keep = set(rng.sample(holders, min(len(holders), rng.randint(1, 2))))
        for user_id in holders:
            if user_id in keep:
                continue
            held[user_id].discard(rare)
            if not held[user_id] and len(competence_ids) > 1:
                held[user_id] = {rng.choice(competence_ids[1:])}
    return held


def _apply_utilization(
    rng: random.Random,
    knobs: Knobs,
    competences: list[SchedulingCompetence],
    held: dict[int, set[int]],
) -> list[SchedulingCompetence]:
    """Scale every non-zero count to a share of the staff's rough capacity.

    A person can start a duty on at most one day in ``1 + rest``, and their
    time is split evenly between the roles they hold. Summing that over the
    holders of a role gives its capacity in people per day; the counts become
    ``target_utilization`` times that, give or take 15 %.
    """
    if knobs.target_utilization is None:
        return competences
    scaled = []
    for competence in competences:
        counts = _slot_counts(competence)
        recovery = list(competence.weekday_recovery_days or ()) + [
            int(competence.special_day_recovery_days or 0)
        ]
        mean_rest = sum(recovery) / len(recovery)
        capacity = sum(
            1.0 / (len(roles) * (1.0 + mean_rest))
            for roles in held.values()
            if competence.id in roles
        )
        target = knobs.target_utilization * capacity
        counts = [
            0 if count == 0 else max(1, round(target * rng.uniform(0.85, 1.15)))
            for count in counts
        ]
        scaled.append(_with_counts(competence, counts))
    return scaled


def _generate_from(rng: random.Random, knobs: Knobs, days: list[date]) -> date | None:
    """Resolve the generate_from knob to a date of the month."""
    if knobs.generate_from is None:
        return None
    if knobs.generate_from == "mid":
        return days[rng.randint(7, len(days) - 6)]
    return days[int(knobs.generate_from) - 1]


def _blocks(
    rng: random.Random, knobs: Knobs, user_ids: list[int], days: list[date]
) -> dict[int, dict[date, str]]:
    """Contiguous absences (vacations, business trips) per employee."""
    blocks: dict[int, dict[date, str]] = {}
    if knobs.vacation_block_rate <= 0:
        return blocks
    cluster = rng.randrange(max(1, len(days) - 8))
    for user_id in user_ids:
        if rng.random() >= knobs.vacation_block_rate:
            continue
        length = min(len(days), rng.randint(3, 14))
        if knobs.block_cluster:
            start = min(len(days) - 1, cluster + rng.randint(0, 4))
        else:
            start = rng.randrange(len(days))
        rule = rng.choices(ABSENCE_RULES, weights=list(knobs.block_mix))[0]
        blocks[user_id] = {day: rule for day in days[start:start + length]}
    return blocks


# --- Rosters ------------------------------------------------------------------


class _Roster:
    """A roster under construction, with what it needs to check rest."""

    def __init__(
        self,
        competences: dict[int, SchedulingCompetence],
        keep_rest: bool,
    ) -> None:
        """Start an empty roster."""
        self.competences = competences
        self.keep_rest = keep_rest
        self.duties: set[Duty] = set()
        self.fixed: set[Duty] = set()
        self.by_user: dict[int, set[Duty]] = {}
        #: Duties outside the month the roster must respect: (date, rest).
        self.outside: dict[int, list[tuple[date, int]]] = {}

    def rest(self, duty: Duty) -> int:
        """Rest one duty earns."""
        return duty_rest(self.competences, duty[1], duty[2])

    def add(self, duty: Duty, fixed: bool = False) -> None:
        """Put a duty on the roster."""
        self.duties.add(duty)
        self.by_user.setdefault(duty[0], set()).add(duty)
        if fixed:
            self.fixed.add(duty)

    def remove(self, duty: Duty) -> None:
        """Take a duty off the roster."""
        self.duties.discard(duty)
        self.fixed.discard(duty)
        self.by_user.get(duty[0], set()).discard(duty)

    def works(self, user_id: int, day: date) -> bool:
        """Whether the user has any duty on the day."""
        return any(duty[2] == day for duty in self.by_user.get(user_id, ()))

    def generated_of(self, user_id: int) -> list[Duty]:
        """The user's duties that are not manual placements, in order."""
        return sorted(duty for duty in self.by_user.get(user_id, ()) if duty not in self.fixed)

    def fits(self, user_id: int, competence_id: int, day: date) -> bool:
        """Whether a new generated duty keeps one-a-day and the rest."""
        rest = duty_rest(self.competences, competence_id, day)
        for other in self.by_user.get(user_id, ()):
            if other[2] == day:
                return False
            if self.keep_rest and touches(day, rest, other[2], self.rest(other)):
                return False
        if self.keep_rest:
            for other_day, other_rest in self.outside.get(user_id, ()):
                if touches(day, rest, other_day, other_rest):
                    return False
        return True

    def clear_of_generated(self, user_id: int, day: date, rest: int, same_day_too: bool = True) -> bool:
        """Whether a commitment on ``day`` with ``rest`` leaves generated duties alone."""
        for other in self.generated_of(user_id):
            if other[2] == day and same_day_too:
                return False
            if other[2] != day and touches(day, rest, other[2], self.rest(other)):
                return False
        return True

    def pin_conflicts(self, placed: Duty) -> None:
        """Make every generated duty a new placement collides with a placement too.

        Manual placements may break the rules among themselves; turning the
        generated duties they collide with into placements is what keeps a
        planted witness valid after a rule-breaking placement is added.
        """
        rest = self.rest(placed)
        for other in self.generated_of(placed[0]):
            if other == placed:
                continue
            if touches(placed[2], rest, other[2], self.rest(other)):
                self.fixed.add(other)


def _fill(
    rng: random.Random,
    roster: _Roster,
    drafts: list[_Draft],
    competences: list[SchedulingCompetence],
    days: list[date],
    partial: bool,
) -> bool:
    """Staff every day greedily, the least loaded qualified person first.

    People on a block absence are never used. Returns ``False`` when a day
    cannot be staffed in full, unless ``partial`` asks for whatever fits.
    """
    load: Counter[int] = Counter()
    for day in days:
        order = list(competences)
        rng.shuffle(order)
        for competence in order:
            need = int(competence.required_on(day))
            if need <= 0:
                continue
            candidates = [
                draft
                for draft in drafts
                if competence.id in draft.competence_ids
                and day not in draft.absences
                and roster.fits(draft.id, competence.id, day)
            ]
            if len(candidates) < need and not partial:
                return False
            candidates.sort(key=lambda draft: load[draft.id] + 1.5 * rng.random())
            for draft in candidates[:need]:
                roster.add((draft.id, competence.id, day))
                load[draft.id] += 1
    return True


def _by_day(roster: _Roster) -> dict[date, list[Duty]]:
    """The roster's duties per date, each list in a fixed order."""
    by_day: dict[date, list[Duty]] = {}
    for duty in sorted(roster.duties):
        by_day.setdefault(duty[2], []).append(duty)
    return by_day


def _break_rules(
    rng: random.Random,
    roster: _Roster,
    drafts: list[_Draft],
    competence_ids: list[int],
    days: list[date],
    kind: str,
    forced_absences: list[Duty],
) -> bool:
    """Add one manual placement that breaks a rule on purpose.

    The placement replaces a duty already on the roster, so coverage is kept,
    and every generated duty it collides with becomes a placement too, so a
    planted witness stays valid. Returns whether a placement was found.
    """
    duties = sorted(roster.duties)
    if not duties:
        return False
    rng.shuffle(duties)
    by_day = _by_day(roster)
    ids = [draft.id for draft in drafts]

    def replace_duty(old: Duty, new: Duty) -> None:
        roster.remove(old)
        roster.add(new, fixed=True)
        roster.pin_conflicts(new)

    if kind == "two_roles":
        for duty in duties:
            others = [
                other
                for other in by_day[duty[2]]
                if other[0] != duty[0]
                and other[1] != duty[1]
                and (duty[0], other[1], duty[2]) not in roster.duties
            ]
            if others:
                other = rng.choice(others)
                roster.fixed.add(duty)
                replace_duty(other, (duty[0], other[1], duty[2]))
                return True
        return False
    if kind == "inside_rest":
        for duty in duties:
            rest = roster.rest(duty)
            later = [
                other
                for offset in range(1, rest + 1)
                for other in by_day.get(duty[2] + timedelta(days=offset), [])
                if other[0] != duty[0] and not roster.works(duty[0], other[2])
            ]
            if later:
                other = rng.choice(later)
                roster.fixed.add(duty)
                replace_duty(other, (duty[0], other[1], other[2]))
                return True
        return False
    if kind == "unqualified":
        for duty in duties:
            outsiders = [
                draft.id
                for draft in drafts
                if duty[1] not in draft.competence_ids and not roster.works(draft.id, duty[2])
            ]
            if outsiders:
                replace_duty(duty, (rng.choice(outsiders), duty[1], duty[2]))
                return True
        return False
    if kind == "above_demand":
        day = rng.choice(days)
        competence_id = rng.choice(competence_ids)
        free = [user_id for user_id in ids if not roster.works(user_id, day)]
        if not free:
            return False
        for duty in by_day.get(day, []):
            if duty[1] == competence_id:
                roster.fixed.add(duty)
        added = (rng.choice(free), competence_id, day)
        roster.add(added, fixed=True)
        roster.pin_conflicts(added)
        return True
    if kind == "absence":
        duty = duties[0]
        roster.fixed.add(duty)
        forced_absences.append(duty)
        return True
    raise ValueError(f"unknown breaking kind {kind!r}")


# --- Decorations ----------------------------------------------------------------


def _strict(policy: ConstraintPolicy, code: str) -> bool:
    """Whether a rule is strict under the instance's policy."""
    return policy.is_strict(code)


def _wish_chances(
    rng: random.Random, knobs: Knobs, drafts: list[_Draft], days: list[date], special: frozenset[date]
) -> dict[int, dict[date, tuple[float, float]]]:
    """Per employee and day, the chance of a "rather not" and of a "want to"."""
    chances: dict[int, dict[date, tuple[float, float]]] = {}
    pattern = knobs.wish_pattern
    soft, wish = knobs.soft_decline_rate, knobs.preferred_rate
    if pattern == "iid":
        for draft in drafts:
            chances[draft.id] = {day: (soft, wish) for day in days}
        return chances
    if pattern == "weekday":
        for draft in drafts:
            liked = set(rng.sample(range(7), rng.randint(1, 3)))
            disliked = rng.choice([weekday for weekday in range(7) if weekday not in liked])
            chances[draft.id] = {
                day: (
                    min(1.0, 4 * soft) if day.weekday() == disliked else 0.0,
                    min(1.0, 3 * wish) if day.weekday() in liked else 0.0,
                )
                for day in days
            }
        return chances
    if pattern == "crowd":
        popular = sorted(special & set(days)) or []
        pool = [day for day in days if day not in popular]
        wanted = set(popular[:2]) | set(rng.sample(pool, min(len(pool), 3)))
        pool = [day for day in pool if day not in wanted]
        avoided = set(rng.sample(pool, min(len(pool), 3)))
        for draft in drafts:
            chances[draft.id] = {
                day: (
                    0.7 if soft > 0 and day in avoided else soft / 4,
                    0.7 if wish > 0 and day in wanted else wish / 4,
                )
                for day in days
            }
        return chances
    raise ValueError(f"unknown wish pattern {pattern!r}")


def _decorate(
    rng: random.Random,
    knobs: Knobs,
    drafts: list[_Draft],
    competences: list[SchedulingCompetence],
    roster: _Roster,
    days: list[date],
    policy: ConstraintPolicy,
    planted: bool,
    forced_absences: list[Duty],
    carried: set[Duty],
) -> set[Duty]:
    """Add duties around the month, duties elsewhere, absences and wishes.

    In planted mode nothing is added that would break the roster: no
    commitment touches a generated duty (by rest only where rest matters),
    and no strict absence or strict "rather not" lands on one. Returns the
    duties around the month, the carried-in ones included.
    """
    first, last = days[0], days[-1]
    by_id = {competence.id: competence for competence in competences}
    rest_matters = _strict(policy, REST) or (planted and knobs.witness_keeps_rest)

    # Duties at this workplace just outside the month.
    adjacent: set[Duty] = set(carried)
    if knobs.adjacent_rate > 0:
        before = date_range(first - timedelta(days=MARGIN_DAYS), first - timedelta(days=1))
        after = date_range(last + timedelta(days=1), last + timedelta(days=MARGIN_DAYS))
        outside = (after if carried else before + after)
        for day in outside:
            busy: set[int] = {duty[0] for duty in carried if duty[2] == day}
            for competence in competences:
                for _ in range(int(competence.required_on(day))):
                    if rng.random() >= knobs.adjacent_rate:
                        continue
                    competence_id = competence.id
                    if knobs.adjacent_retired_competence and rng.random() < 0.25:
                        competence_id = RETIRED_COMPETENCE_ID
                    rest = duty_rest(by_id, competence_id, day)
                    options = [
                        draft.id
                        for draft in drafts
                        if draft.id not in busy
                        and (competence_id not in by_id or competence_id in draft.competence_ids)
                        and (
                            not (planted and rest_matters)
                            or roster.clear_of_generated(draft.id, day, rest)
                        )
                    ]
                    if options:
                        user_id = rng.choice(options)
                        busy.add(user_id)
                        adjacent.add((user_id, competence_id, day))

    # Duties at another workplace, inside the month and a week around it.
    if knobs.external_rate > 0:
        span = date_range(first - timedelta(days=MARGIN_DAYS), last + timedelta(days=MARGIN_DAYS))
        adjacent_days = {(duty[0], duty[2]) for duty in adjacent}
        for draft in drafts:
            for day in span:
                if rng.random() >= knobs.external_rate:
                    continue
                rest: int | None = (
                    rng.randint(0, 3) if rng.random() < knobs.external_explicit_rest else None
                )
                rests: list[int | None] = [rest]
                if rest is not None and rng.random() < knobs.external_duplicate_rate:
                    second = rng.choice([value for value in range(0, 5) if value != rest])
                    rests = [rest, second]
                    rng.shuffle(rests)
                explicit = [value for value in rests if value is not None]
                effective = max(explicit) if explicit else fallback_external_rest(competences, day)
                if (draft.id, day) in adjacent_days:
                    continue
                if planted and not roster.clear_of_generated(draft.id, day, effective if rest_matters else 0):
                    continue
                draft.externals[day] = rests

    # Absences, then "rather not", then "want to".
    weights = list(knobs.absence_mix)
    for user_id, _competence_id, day in forced_absences:
        draft = next(item for item in drafts if item.id == user_id)
        strict_rules = [rule for rule in ABSENCE_RULES if _strict(policy, rule)] or list(ABSENCE_RULES)
        draft.absences[day] = rng.choice(strict_rules)
        draft.preferred.discard(day)
        draft.soft_declined.discard(day)
    special = frozenset().union(*(competence.special_dates for competence in competences)) if competences else frozenset()
    chances = _wish_chances(rng, knobs, drafts, days, special)
    for draft in drafts:
        generated_days = {duty[2] for duty in roster.generated_of(draft.id)}
        for day in days:
            if draft.taken(day):
                continue
            if knobs.unavailability_rate > 0 and rng.random() < knobs.unavailability_rate:
                rule = rng.choices(ABSENCE_RULES, weights=weights)[0]
                if planted and _strict(policy, rule) and day in generated_days:
                    continue
                draft.absences[day] = rule
                continue
            soft_chance, wish_chance = chances[draft.id][day]
            if soft_chance > 0 and rng.random() < soft_chance:
                if planted and _strict(policy, SOFT_DECLINE) and day in generated_days:
                    continue
                draft.soft_declined.add(day)
                continue
            if wish_chance > 0 and rng.random() < wish_chance:
                draft.preferred.add(day)
    return adjacent


MAX_SHIFT_MODES = ("none", "zero", "loose", "tight", "below", "hetero", "starved")


def _max_shifts(
    rng: random.Random,
    knobs: Knobs,
    drafts: list[_Draft],
    roster: _Roster,
    days: list[date],
    window: list[date],
    competences: list[SchedulingCompetence],
    policy: ConstraintPolicy,
    planted: bool,
) -> None:
    """Set everyone's monthly maximum according to the knob.

    The base is what the witness gives each person (planted) or the window's
    average load plus the person's own placements in the history (random),
    since the maximum counts every duty of the month. A strict maximum on a
    planted instance never drops below what the witness gives.
    """
    month = set(days)
    window_set = set(window)
    totals = Counter(duty[0] for duty in roster.duties if duty[2] in month)
    history = Counter(
        duty[0] for duty in roster.fixed if duty[2] in month and duty[2] not in window_set
    )
    demanded = sum(int(competence.required_on(day)) for competence in competences for day in window)
    average = ceil(demanded / max(1, len(drafts)))
    strict = _strict(policy, MAX_SHIFTS)
    for draft in drafts:
        mode = knobs.max_shifts_mode
        if mode == "mixed":
            mode = rng.choice(list(MAX_SHIFT_MODES))
        base = totals[draft.id] if planted else average + history[draft.id]
        if mode == "none":
            cap: int | None = None
        elif mode == "zero":
            cap = 0
        elif mode == "loose":
            cap = base + rng.randint(1, 4)
        elif mode == "tight":
            cap = base if base > 0 else None
        elif mode == "below":
            cap = max(1, base - rng.randint(1, 3))
        elif mode == "hetero":
            share = 0.4 if rng.random() < 0.4 else 1.4
            cap = max(1, ceil(average * share)) + history[draft.id]
        elif mode == "starved":
            cap = max(1, floor(average * 0.6)) + history[draft.id]
        else:
            raise ValueError(f"unknown max_shifts mode {mode!r}")
        if planted and strict and cap is not None and cap != 0:
            cap = max(cap, totals[draft.id]) if totals[draft.id] > 0 else cap
        draft.max_shifts = cap


def _preferences(rng: random.Random, knobs: Knobs, drafts: list[_Draft]) -> None:
    """Set everyone's duty-kind preference."""
    for draft in drafts:
        if knobs.preference_mix == "mixed":
            draft.preference = rng.choice(["any", "surcharge", "standard"])
        else:
            draft.preference = knobs.preference_mix


# --- Entry point -----------------------------------------------------------------


def make_instance(
    seed: int, knobs: Knobs | None = None, carry_in: Iterable[Duty] = ()
) -> Instance:
    """Build one instance from a seed and a set of knobs, deterministically.

    ``carry_in`` are duties at this workplace from the neighbouring month
    (e.g. the last week of a solved previous month). Those within a week
    outside this month become ``adjacent`` duties, and a planted witness
    respects their rest; random adjacent duties are then drawn after the
    month only. Carried duties of people this instance does not have are
    dropped.

    Raises:
        PlantingFailed: If a planted instance needs more spare employees
            than ``knobs.max_spares`` allows.
    """
    knobs = knobs or Knobs()
    policy = policy_from_settings(knobs.policy) if knobs.policy is not None else None
    effective = policy or ConstraintPolicy.default()
    days = month_days(knobs.month, knobs.year)
    first, last = days[0], days[-1]

    structure_rng = _stream(seed, 1)
    calendar_rng = _stream(seed, 2, knobs.month, knobs.year)
    special = _special_dates(
        calendar_rng,
        knobs,
        first - timedelta(days=MARGIN_DAYS),
        last + timedelta(days=MARGIN_DAYS),
    )
    competences = [
        _competence(structure_rng, knobs, competence_id, special)
        for competence_id in range(1, knobs.n_competences + 1)
    ]
    competence_ids = [competence.id for competence in competences]
    user_ids = list(range(1, knobs.n_employees + 1))
    qualifications = _qualify(structure_rng, knobs, user_ids, competence_ids)
    competences = _apply_utilization(structure_rng, knobs, competences, qualifications)
    by_id = {competence.id: competence for competence in competences}
    generate_from = _generate_from(calendar_rng, knobs, days)
    window = [day for day in days if generate_from is None or day >= generate_from]
    window_set = set(window)
    history = {day for day in days if day not in window_set}
    blocks = _blocks(_stream(seed, 3, knobs.month, knobs.year), knobs, user_ids, days)

    margin = timedelta(days=MARGIN_DAYS)
    carried = {
        duty
        for duty in carry_in
        if duty[0] in qualifications
        and duty[2] not in set(days)
        and first - margin <= duty[2] <= last + margin
    }

    # Planting: retry the greedy fill with fresh sub-seeds, and add a fully
    # qualified spare employee every twenty failures until it goes through.
    spares = 0
    for attempt in range(4000):
        drafts = []
        for user_id in user_ids:
            draft = _Draft(user_id)
            draft.competence_ids = set(qualifications[user_id])
            draft.absences = dict(blocks.get(user_id, {}))
            drafts.append(draft)
        for offset in range(spares):
            spare = _Draft(knobs.n_employees + offset + 1)
            spare.competence_ids = set(competence_ids)
            drafts.append(spare)
        roster = _Roster(by_id, keep_rest=knobs.witness_keeps_rest or effective.is_strict(REST))
        for user_id, _competence_id, day in sorted(carried):
            roster.outside.setdefault(user_id, []).append(
                (day, duty_rest(by_id, _competence_id, day))
            )
        fill_rng = _stream(seed, 100 + attempt, knobs.month, knobs.year)
        if _fill(fill_rng, roster, drafts, competences, days, partial=not knobs.planted):
            break
        if attempt % 20 == 19:
            spares += 1
            if knobs.max_spares is not None and spares > knobs.max_spares:
                raise PlantingFailed(
                    f"seed {seed}: the greedy planter needs more than {knobs.max_spares} spares"
                )
    else:  # pragma: no cover - the spare employees always end the loop
        raise RuntimeError(f"could not plant a roster for seed {seed}")

    rng = _stream(seed, 4, knobs.month, knobs.year)
    # The history keeps a share of its duties, as placements.
    for duty in sorted(roster.duties):
        if duty[2] in history:
            if rng.random() < knobs.keep_history:
                roster.fixed.add(duty)
            else:
                roster.remove(duty)
    # Manual placements inside the window: single duties, a share, whole days.
    window_duties = sorted(duty for duty in roster.duties if duty[2] in window_set)
    for duty in rng.sample(window_duties, min(knobs.n_fixed, len(window_duties))):
        roster.fixed.add(duty)
    if knobs.fixed_share > 0:
        count = min(len(window_duties), round(knobs.fixed_share * len(window_duties)))
        for duty in rng.sample(window_duties, count):
            roster.fixed.add(duty)
    if knobs.fixed_full_days > 0:
        for day in rng.sample(window, min(len(window), knobs.fixed_full_days)):
            roster.fixed.update(duty for duty in window_duties if duty[2] == day)
    forced_absences: list[Duty] = []
    for _ in range(knobs.n_breaking_fixed):
        if knobs.breaking_kinds:
            _break_rules(
                rng,
                roster,
                drafts,
                competence_ids,
                days,
                rng.choice(list(knobs.breaking_kinds)),
                forced_absences,
            )
    adjacent = _decorate(
        rng,
        knobs,
        drafts,
        competences,
        roster,
        days,
        effective,
        knobs.planted,
        forced_absences,
        carried,
    )
    _max_shifts(rng, knobs, drafts, roster, days, window, competences, effective, knobs.planted)
    _preferences(rng, knobs, drafts)

    employees = [draft.build() for draft in drafts]
    fixed = frozenset(roster.fixed)
    instance = Instance(
        employees=employees,
        competences=competences,
        month=knobs.month,
        year=knobs.year,
        adjacent=frozenset(adjacent),
        fixed=fixed,
        generate_from=generate_from,
        policy=policy,
        witness=frozenset(roster.duties) if knobs.planted else None,
        label=_label(seed, knobs, len(drafts), spares),
        knobs={"seed": seed, "spares": spares, **asdict(knobs)},
    )
    if knobs.planted:
        _assert_witness(instance)
    return instance


def knobs_of(instance: Instance) -> Knobs:
    """The knobs an instance from :func:`make_instance` was made with."""
    names = {item.name for item in fields(Knobs)}
    values = {name: value for name, value in instance.knobs.items() if name in names}
    for name in ("absence_mix", "block_mix", "breaking_kinds"):
        if name in values:
            values[name] = tuple(values[name])
    return Knobs(**values)


def next_month_knobs(knobs: Knobs) -> Knobs:
    """The same knobs one month later (December rolls into January)."""
    if knobs.month == 12:
        return replace(knobs, month=1, year=knobs.year + 1)
    return replace(knobs, month=knobs.month + 1)


def _label(seed: int, knobs: Knobs, employees: int, spares: int) -> str:
    """A short readable name for an instance."""
    kind = "planted" if knobs.planted else "random"
    label = (
        f"{kind}-s{seed}-e{employees}-c{knobs.n_competences}-{knobs.year}-{knobs.month:02d}"
        f"-{knobs.demand_profile}-{knobs.recovery_profile}-{knobs.hours_profile}"
    )
    return f"{label}-sp{spares}" if spares else label


def _assert_witness(instance: Instance) -> None:
    """Refuse to hand out a planted instance whose witness breaks a rule."""
    from tests.scheduling_harness.oracle import validate

    violations = validate(instance, sorted(instance.witness or ()))
    if violations:
        raise AssertionError(
            f"harness bug: planted witness of {instance.label} breaks "
            f"{[violation.code for violation in violations[:5]]}"
        )


# --- Policies ------------------------------------------------------------------------


def random_policy(
    rng: random.Random, allow_zero_balance: bool = True, keep_default_share: float = 0.3
) -> dict[str, tuple[bool, float]]:
    """A random ``code -> (strict, weight)`` policy for ``Knobs.policy``.

    Every switchable rule is strict or penalized with a weight from
    :data:`SWITCHABLE_WEIGHTS` (zero included); balance, "want to" and
    spread get weights of their own kind. Each rule keeps its default with
    probability ``keep_default_share``. ``allow_zero_balance=False`` keeps
    the balance weight positive (a zero balance weight triggers a known
    solver bug, see ``known_bugs``).
    """
    policy: dict[str, tuple[bool, float]] = {}
    for definition in CONSTRAINTS:
        if definition.mode == MODE_FIXED or rng.random() < keep_default_share:
            continue
        if definition.mode == MODE_PENALTY:
            if definition.code == BALANCE:
                options = BALANCE_WEIGHTS if allow_zero_balance else BALANCE_WEIGHTS[1:]
            elif definition.code == PREFERRED:
                options = WISH_WEIGHTS
            elif definition.code == SPREAD:
                options = SPREAD_WEIGHTS
            else:  # pragma: no cover - a penalty-only rule this harness does not know
                options = SWITCHABLE_WEIGHTS
            policy[definition.code] = (False, rng.choice(options))
            continue
        policy[definition.code] = (rng.random() < 0.5, rng.choice(SWITCHABLE_WEIGHTS))
    return policy


# --- Ready-made instances and knob samplers ---------------------------------------


def symmetric_instance(
    n_employees: int,
    n_competences: int,
    month: int = 8,
    year: int = 2026,
    recovery: int = 1,
    hours: float = 4.0,
) -> Instance:
    """Identical employees, one person per role per day, nothing else.

    Every employee holds every competence and wishes for nothing, so a fair
    roster gives each of them the same number of duties, give or take one.
    """
    days = month_days(month, year)
    competences = [
        SchedulingCompetence(
            id=competence_id,
            name=f"Role {competence_id}",
            required_count=1,
            weekday_required_counts=(1,) * 7,
            special_day_required_count=1,
            special_dates=frozenset(),
            weekday_is_surcharge=(False,) * 5 + (True,) * 2,
            special_day_is_surcharge=True,
            weekday_recovery_days=(recovery,) * 7,
            special_day_recovery_days=recovery,
            weekday_shift_hours=(hours,) * 7,
            special_day_shift_hours=hours,
        )
        for competence_id in range(1, n_competences + 1)
    ]
    employees = []
    for user_id in range(1, n_employees + 1):
        draft = _Draft(user_id)
        draft.competence_ids = {competence.id for competence in competences}
        employees.append(draft.build())
    return Instance(
        employees=employees,
        competences=competences,
        month=month,
        year=year,
        label=f"symmetric-e{n_employees}-c{n_competences}-r{recovery}-{year}-{month:02d}",
        knobs={"days": len(days), "recovery": recovery},
    )


def pigeonhole_instance() -> Instance:
    """Two people a day in a role only one employee holds: plainly infeasible."""
    competence = SchedulingCompetence(
        id=1,
        name="Role 1",
        required_count=2,
        weekday_required_counts=(2,) * 7,
        special_day_required_count=2,
        weekday_recovery_days=(0,) * 7,
        special_day_recovery_days=0,
    )
    lonely = _Draft(1)
    lonely.competence_ids = {1}
    other = _Draft(2)
    return Instance(
        employees=[lonely.build(), other.build()],
        competences=[competence],
        month=8,
        year=2026,
        label="pigeonhole",
    )


def unconfigured_competence(
    competence_id: int, required_count: int, special: frozenset[date] = frozenset()
) -> SchedulingCompetence:
    """A competence exactly as the loader reads one with no scenario rows.

    Every slot asks for ``required_count``, earns the default rest and hours,
    and is surcharged on weekends and days of rest. Use it with
    ``materialize(..., scenario='none')``.
    """
    return SchedulingCompetence(
        id=competence_id,
        name=f"Role {competence_id}",
        required_count=required_count,
        weekday_required_counts=(required_count,) * 7,
        special_day_required_count=required_count,
        special_dates=special,
        weekday_is_surcharge=tuple(default_is_surcharge(weekday) for weekday in range(7)),
        special_day_is_surcharge=default_is_surcharge(SPECIAL_DAY_SLOT),
        weekday_recovery_days=(DEFAULT_RECOVERY_DAYS,) * 7,
        special_day_recovery_days=DEFAULT_RECOVERY_DAYS,
        weekday_shift_hours=(DEFAULT_SHIFT_HOURS,) * 7,
        special_day_shift_hours=DEFAULT_SHIFT_HOURS,
    )


def tiny_knobs(rng: random.Random, planted: bool) -> Knobs:
    """Knobs for an instance small enough to search exhaustively.

    At most five employees and two roles, and a window of the last four to
    seven days of a month. ``max_spares=0`` keeps planted ones at five
    people or fewer: a seed the greedy planter cannot plant raises
    :class:`PlantingFailed`, so callers should skip it.
    """
    month = rng.choice([2, 4, 8, 12])
    year = rng.choice([2026, 2028])
    days = len(month_days(month, year))
    return Knobs(
        n_employees=rng.randint(3, 5),
        n_competences=rng.choice([1, 1, 2]),
        month=month,
        year=year,
        qualification_density=rng.choice([0.6, 0.8, 1.0]),
        demand_profile=rng.choice(["flat", "weekday", "sparse"]),
        special_days=rng.choice(["none", "random"]),
        special_rate=0.2,
        recovery_profile=rng.choice(["zero", "one", "mixed"]),
        hours_profile=rng.choice(["uniform4", "mixed", "fractional"]),
        surcharge_profile=rng.choice(["weekend", "random"]),
        unavailability_rate=rng.choice([0.0, 0.1]),
        absence_mix=(0.6, 0.2, 0.2),
        preferred_rate=rng.choice([0.0, 0.2]),
        soft_decline_rate=rng.choice([0.0, 0.15]),
        max_shifts_mode=rng.choice(["none", "loose", "tight", "mixed"]),
        preference_mix=rng.choice(["any", "mixed", "standard"]),
        external_rate=rng.choice([0.0, 0.05]),
        external_explicit_rest=0.5,
        adjacent_rate=rng.choice([0.0, 0.5]),
        generate_from=days - rng.randint(3, 6),
        keep_history=0.9,
        n_fixed=rng.randint(0, 1),
        n_breaking_fixed=rng.choice([0, 0, 1]),
        policy=rng.choice(list(POLICY_PRESETS.values()))
        if rng.random() < 0.7
        else random_policy(rng),
        planted=planted,
        max_spares=0 if planted else None,
    )


def ultra_tiny_knobs(rng: random.Random, planted: bool) -> Knobs:
    """Two or three people, one or two roles, a window of two or three days.

    Small enough to enumerate every subset of possible duties without any
    pruning (see the self-check's naive enumerator).
    """
    knobs = tiny_knobs(rng, planted)
    days = len(month_days(knobs.month, knobs.year))
    return replace(
        knobs,
        n_employees=rng.randint(2, 3),
        generate_from=days - rng.randint(1, 2),
        demand_profile=rng.choice(["flat", "sparse"]),
        max_spares=None,
    )


def stress_knobs(rng: random.Random, planted: bool = True) -> Knobs:
    """Few people, many rule-breaking placements, tight maxima: the awkward corner.

    With two to five employees the planter usually has to add spare staff,
    so the month ends up staffed about as tightly as it can be, and up to
    eight placements break a rule on purpose. ``Instance.spares`` says how
    many people were added.
    """
    return Knobs(
        n_employees=rng.randint(2, 5),
        n_competences=rng.randint(1, 3),
        month=rng.choice([2, 8, 12]),
        year=rng.choice([2026, 2028]),
        qualification_density=rng.choice([0.5, 1.0]),
        demand_profile=rng.choice(["flat", "weekday", "heavy", "sparse"]),
        recovery_profile=rng.choice(["zero", "one", "mixed", "long"]),
        special_days=rng.choice(["none", "mixed"]),
        n_fixed=rng.randint(0, 6),
        n_breaking_fixed=rng.randint(1, 8),
        generate_from=rng.choice([None, "mid"]),
        adjacent_rate=rng.choice([0.0, 0.9]),
        external_rate=rng.choice([0.0, 0.05]),
        unavailability_rate=rng.choice([0.0, 0.1]),
        soft_decline_rate=0.1,
        max_shifts_mode=rng.choice(["tight", "mixed", "none"]),
        policy=rng.choice(list(POLICY_PRESETS.values())),
        witness_keeps_rest=rng.random() < 0.5,
        planted=planted,
    )


#: Employee and role ranges of :func:`sample_knobs`, per size.
SIZES: dict[str, tuple[tuple[int, int], tuple[int, int]]] = {
    "small": ((4, 10), (1, 2)),
    "medium": ((10, 25), (2, 4)),
    "large": ((25, 60), (3, 6)),
    "xl": ((60, 80), (6, 8)),
}


def sample_knobs(rng: random.Random, size: str = "small", planted: bool = True) -> Knobs:
    """Random knobs across every dimension, at one of four sizes.

    ``small`` is 4-10 employees and 1-2 roles, ``medium`` 10-25 and 2-4,
    ``large`` 25-60 and 3-6, ``xl`` 60-80 and 6-8. About a third of the
    instances get a demand tied to the staff's capacity
    (``target_utilization``), which is what makes the bigger sizes tight.
    Duplicate duties elsewhere on one date are left off (a known solver bug,
    see ``known_bugs``); turn ``external_duplicate_rate`` on to test them.
    """
    employees, roles = SIZES[size]
    month, year = rng.choice([(2, 2028), (2, 2027), (4, 2026), (8, 2026), (12, 2026), (1, 2027)])
    policy_draw = rng.random()
    if policy_draw < 0.75:
        policy = rng.choice(list(POLICY_PRESETS.values()))
    else:
        policy = random_policy(rng, allow_zero_balance=False)
    n_competences = rng.randint(*roles)
    return Knobs(
        n_employees=rng.randint(*employees),
        n_competences=n_competences,
        month=month,
        year=year,
        qualification_density=rng.choice([0.4, 0.6, 0.8, 1.0]),
        unqualified_employee_rate=rng.choice([0.0, 0.0, 0.1]),
        qualification_structure=rng.choice(["iid", "iid", "iid", "hierarchy", "rare"]),
        demand_profile=rng.choice(["flat", "weekday", "sparse", "heavy", "mixed"]),
        target_utilization=rng.choice([None, None, None, None, 0.5, 0.8]),
        zero_demand_competences=rng.choice([0, 0, 0, 0, 1]) if n_competences > 1 else 0,
        special_days=rng.choice(["none", "library", "random", "mixed"]),
        special_slot_differs=rng.random() < 0.7,
        recovery_profile=rng.choice(["zero", "one", "one", "mixed", "long"]),
        hours_profile=rng.choice(["uniform4", "uniform12", "mixed", "fractional"]),
        surcharge_profile=rng.choice(["weekend", "weekend", "random", "none", "all"]),
        unavailability_rate=rng.choice([0.0, 0.05, 0.15]),
        absence_mix=rng.choice([(1.0, 0.0, 0.0), (0.5, 0.3, 0.2)]),
        vacation_block_rate=rng.choice([0.0, 0.0, 0.2, 0.4]),
        block_cluster=rng.random() < 0.3,
        preferred_rate=rng.choice([0.0, 0.05, 0.15]),
        soft_decline_rate=rng.choice([0.0, 0.05, 0.15]),
        wish_pattern=rng.choice(["iid", "iid", "weekday", "crowd"]),
        max_shifts_mode=rng.choice(
            ["none", "zero", "loose", "tight", "below", "hetero", "starved", "mixed"]
        ),
        preference_mix=rng.choice(["any", "mixed", "surcharge", "standard"]),
        external_rate=rng.choice([0.0, 0.0, 0.03]),
        external_explicit_rest=rng.choice([1.0, 0.5, 0.0]),
        adjacent_rate=rng.choice([0.0, 0.5, 0.9]),
        adjacent_retired_competence=rng.random() < 0.2,
        generate_from=rng.choice([None, None, "mid"]),
        keep_history=rng.choice([1.0, 0.8]),
        n_fixed=rng.choice([0, 0, 2, 5]),
        fixed_share=rng.choice([0.0, 0.0, 0.0, 0.3, 0.6]),
        fixed_full_days=rng.choice([0, 0, 0, 2]),
        n_breaking_fixed=rng.choice([0, 0, 1, 2]),
        policy=policy,
        planted=planted,
        witness_keeps_rest=rng.random() < 0.7,
    )


def fill_in_knobs(rng: random.Random, share: float | None = None, size: str = "small") -> Knobs:
    """Planted knobs for "complete a partly filled roster" (dogenerovanie).

    A large share (30-90 %) of the witness is pinned as manual placements,
    sometimes with whole days pre-filled and a history before
    ``generate_from``, so the solver has to fill only the gaps.
    """
    knobs = sample_knobs(rng, size, planted=True)
    return replace(
        knobs,
        fixed_share=share if share is not None else rng.choice([0.3, 0.5, 0.7, 0.9]),
        fixed_full_days=rng.choice([0, 1, 3]),
        generate_from=rng.choice([None, "mid"]),
        n_breaking_fixed=rng.choice([0, 1, 2]),
    )
