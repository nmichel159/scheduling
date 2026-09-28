"""The rules a workplace's schedule is generated under, and how hard each is.

Every rule the generator knows is listed once, in :data:`CONSTRAINTS`, and
falls into one of three kinds:

* **Fixed** rules are always strict. A role is staffed in full, a person
  works one role a day, only in a competence they hold, and never at two
  workplaces on the same day. No workplace setting moves them, because a
  roster that breaks them is not a roster.
* **Switchable** rules are strict or penalized, as the workplace decides.
  Strict means the generator never breaks them; penalized means it may, and
  pays the rule's weight for every breach, so it does so only where the
  month cannot be staffed otherwise.
* **Penalty-only** rules cannot be strict at all. There is no such thing as
  a strictly even load or strictly spread-out duties -- only more or less of
  it -- so all a workplace sets is how much they weigh.

A workplace stores only what it changed. A rule with no row of its own
follows the defaults below, which are the ones the generator used before the
rules could be set, so a workplace nobody configured is scheduled exactly as
it always was, and a default changed here reaches it without a migration.

The weights are only ever weighed against rules solved in the same pass. The
generator settles the absences, the rest, the monthly maximum, overstaffing
and the balance first, and the day wishes and the spread afterwards, under
the balance the first pass reached -- see ``schedule_generation_service``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from sqlalchemy.orm import Session

from app.models.constraint_setting import ConstraintSetting

#: Always strict; the workplace cannot change them.
MODE_FIXED = "fixed"
#: Strict or penalized, as the workplace decides.
MODE_SWITCHABLE = "switchable"
#: Always penalized; the workplace sets the weight.
MODE_PENALTY = "penalty"

GROUP_FIXED = "fixed"
GROUP_ABSENCE = "absence"
GROUP_LOAD = "load"
GROUP_WISH = "wish"

COVERAGE = "coverage"
ONE_ROLE_PER_DAY = "one_role_per_day"
QUALIFICATION = "qualification"
OTHER_WORKPLACE = "other_workplace"
UNAVAILABLE = "unavailable"
VACATION = "vacation"
BUSINESS_TRIP = "business_trip"
REST = "rest"
MAX_SHIFTS = "max_shifts"
OVERSTAFF = "overstaff"
BALANCE = "balance"
SOFT_DECLINE = "soft_decline"
PREFERRED = "preferred"
SPREAD = "spread"

#: The most a single weight may be set to. Far above any default, and far
#: below where the solver's arithmetic starts to lose the small terms.
MAX_WEIGHT = 100_000.0


@dataclass(frozen=True)
class ConstraintDefinition:
    """One rule the generator knows, with what a workplace starts from."""

    code: str
    group: str
    mode: str
    default_strict: bool
    #: What one breach costs when the rule is penalized. ``None`` for a
    #: fixed rule, which is never breached.
    default_weight: float | None


#: Every rule, in the order the settings screen lists them.
CONSTRAINTS: tuple[ConstraintDefinition, ...] = (
    ConstraintDefinition(COVERAGE, GROUP_FIXED, MODE_FIXED, True, None),
    ConstraintDefinition(ONE_ROLE_PER_DAY, GROUP_FIXED, MODE_FIXED, True, None),
    ConstraintDefinition(QUALIFICATION, GROUP_FIXED, MODE_FIXED, True, None),
    ConstraintDefinition(OTHER_WORKPLACE, GROUP_FIXED, MODE_FIXED, True, None),
    # An absence and a rest breach cost what a duty over the monthly wish
    # costs: far above any balance step, so they are broken only when the
    # month cannot be staffed otherwise.
    ConstraintDefinition(UNAVAILABLE, GROUP_ABSENCE, MODE_SWITCHABLE, True, 1000.0),
    ConstraintDefinition(VACATION, GROUP_ABSENCE, MODE_SWITCHABLE, True, 1000.0),
    ConstraintDefinition(BUSINESS_TRIP, GROUP_ABSENCE, MODE_SWITCHABLE, True, 1000.0),
    ConstraintDefinition(REST, GROUP_ABSENCE, MODE_SWITCHABLE, True, 1000.0),
    ConstraintDefinition(MAX_SHIFTS, GROUP_LOAD, MODE_SWITCHABLE, False, 1000.0),
    ConstraintDefinition(OVERSTAFF, GROUP_LOAD, MODE_SWITCHABLE, False, 1000.0),
    ConstraintDefinition(BALANCE, GROUP_LOAD, MODE_PENALTY, False, 4.0),
    ConstraintDefinition(SOFT_DECLINE, GROUP_WISH, MODE_SWITCHABLE, False, 10.0),
    ConstraintDefinition(PREFERRED, GROUP_WISH, MODE_PENALTY, False, 10.0),
    ConstraintDefinition(SPREAD, GROUP_WISH, MODE_PENALTY, False, 1.0),
)

DEFINITIONS: dict[str, ConstraintDefinition] = {
    definition.code: definition for definition in CONSTRAINTS
}


@dataclass(frozen=True)
class ConstraintRule:
    """How hard one rule is at one workplace."""

    strict: bool
    weight: float


@dataclass(frozen=True)
class ConstraintPolicy:
    """Every rule's setting at one workplace, as the generator reads them.

    A rule missing from ``rules`` follows its default, so the empty policy
    is the generator's behaviour before any of this could be set.
    """

    rules: Mapping[str, ConstraintRule]

    @classmethod
    def default(cls) -> ConstraintPolicy:
        """Every rule as it is out of the box."""
        return cls(rules={})

    def rule(self, code: str) -> ConstraintRule:
        """The setting of one rule, falling back to its default."""
        found = self.rules.get(code)
        if found is not None:
            return found
        definition = DEFINITIONS[code]
        return ConstraintRule(
            strict=definition.default_strict,
            weight=definition.default_weight or 0.0,
        )

    def is_strict(self, code: str) -> bool:
        """Whether the generator may never break this rule."""
        return self.rule(code).strict

    def weight(self, code: str) -> float:
        """What one breach of a penalized rule costs."""
        return self.rule(code).weight

    def tightened(self) -> list[str]:
        """Rules made strict here although they are only penalized by default."""
        return [
            definition.code
            for definition in CONSTRAINTS
            if definition.mode == MODE_SWITCHABLE
            and not definition.default_strict
            and self.is_strict(definition.code)
        ]


class ConstraintSettingError(ValueError):
    """A requested setting the rule it names does not allow."""


def _normalized(
    definition: ConstraintDefinition, strict: bool, weight: float | None
) -> ConstraintRule:
    """Check one requested setting against what its rule allows."""
    if definition.mode == MODE_FIXED:
        if not strict:
            raise ConstraintSettingError(
                f"Constraint '{definition.code}' is always strict."
            )
        return ConstraintRule(strict=True, weight=0.0)
    if definition.mode == MODE_PENALTY and strict:
        raise ConstraintSettingError(
            f"Constraint '{definition.code}' can only be penalized."
        )
    resolved = definition.default_weight if weight is None else float(weight)
    if resolved is None or not 0.0 <= resolved <= MAX_WEIGHT:
        raise ConstraintSettingError(
            f"The weight of '{definition.code}' must lie between 0 and {MAX_WEIGHT:g}."
        )
    return ConstraintRule(strict=strict, weight=resolved)


def _is_default(definition: ConstraintDefinition, rule: ConstraintRule) -> bool:
    """Whether a setting says nothing its rule would not say by itself."""
    if definition.mode == MODE_FIXED:
        return True
    return (
        rule.strict == definition.default_strict
        and rule.weight == definition.default_weight
    )


def load_constraint_policy(db: Session, ambulance_id: int) -> ConstraintPolicy:
    """Read one workplace's settings, ignoring rules the code no longer knows."""
    rows = (
        db.query(ConstraintSetting)
        .filter(ConstraintSetting.ambulance_id == ambulance_id)
        .all()
    )
    rules: dict[str, ConstraintRule] = {}
    for row in rows:
        definition = DEFINITIONS.get(row.code)
        if definition is None or definition.mode == MODE_FIXED:
            continue
        # A row written before a rule became penalty-only cannot keep it
        # strict; it keeps its weight and loses the rest.
        strict = bool(row.is_strict) and definition.mode == MODE_SWITCHABLE
        rules[row.code] = ConstraintRule(strict=strict, weight=float(row.weight))
    return ConstraintPolicy(rules=rules)


def constraint_entries(db: Session, ambulance_id: int) -> list[dict[str, object]]:
    """Every rule with its current and default setting, for the screen."""
    policy = load_constraint_policy(db, ambulance_id)
    entries: list[dict[str, object]] = []
    for definition in CONSTRAINTS:
        rule = policy.rule(definition.code)
        entries.append(
            {
                "code": definition.code,
                "group": definition.group,
                "mode": definition.mode,
                "is_strict": True if definition.mode == MODE_FIXED else rule.strict,
                "weight": definition.default_weight
                if definition.mode == MODE_FIXED
                else rule.weight,
                "default_is_strict": definition.default_strict,
                "default_weight": definition.default_weight,
                "is_default": definition.code not in policy.rules
                or _is_default(definition, rule),
            }
        )
    return entries


def save_constraint_settings(
    db: Session,
    ambulance_id: int,
    settings: list[tuple[str, bool, float | None]],
) -> None:
    """Store what a workplace set for the rules it names.

    ``settings`` is a list of ``(code, is_strict, weight)``. A rule set back
    to its default loses its row rather than keeping a copy of the default,
    so a default changed in code later still reaches it. Rules the list does
    not name are left as they are. Everything is checked before anything is
    written, so one refused setting leaves the workplace unchanged.
    """
    requested: dict[str, ConstraintRule] = {}
    for code, strict, weight in settings:
        definition = DEFINITIONS.get(code)
        if definition is None:
            raise ConstraintSettingError(f"Unknown constraint '{code}'.")
        if code in requested:
            raise ConstraintSettingError(f"Constraint '{code}' is listed twice.")
        requested[code] = _normalized(definition, strict, weight)

    existing = {
        row.code: row
        for row in db.query(ConstraintSetting)
        .filter(ConstraintSetting.ambulance_id == ambulance_id)
        .all()
    }
    for code, rule in requested.items():
        definition = DEFINITIONS[code]
        row = existing.get(code)
        if _is_default(definition, rule):
            if row is not None:
                db.delete(row)
            continue
        if row is None:
            db.add(
                ConstraintSetting(
                    ambulance_id=ambulance_id,
                    code=code,
                    is_strict=rule.strict,
                    weight=rule.weight,
                )
            )
        else:
            row.is_strict = rule.strict
            row.weight = rule.weight
    db.commit()


def reset_constraint_settings(db: Session, ambulance_id: int) -> None:
    """Hand every rule of a workplace back to its default."""
    db.query(ConstraintSetting).filter(
        ConstraintSetting.ambulance_id == ambulance_id
    ).delete(synchronize_session=False)
    db.commit()


def policy_from_settings(settings: Mapping[str, tuple[bool, float]]) -> ConstraintPolicy:
    """Build a policy from plain values, checked the way a save checks them."""
    rules: dict[str, ConstraintRule] = {}
    for code, (strict, weight) in settings.items():
        definition = DEFINITIONS.get(code)
        if definition is None:
            raise ConstraintSettingError(f"Unknown constraint '{code}'.")
        rules[code] = _normalized(definition, strict, weight)
    return ConstraintPolicy(rules=rules)
