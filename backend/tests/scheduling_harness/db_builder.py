"""Write an instance into a database the way the application stores it.

:func:`materialize` turns an :class:`~.instances.Instance` into rows -- a
workplace, its people, competences, a selected scenario with all eight day
slots, absences and wishes, duties around the month, duties at a second
workplace that earn exactly the instance's rest, constraint settings and
special-day overrides -- so that ``generate_ambulance_monthly_schedule`` can
be tested end to end on the very same problem the in-memory solver gets.

Options reach the loader's other paths: a scenario without the special slot
or with no scenario at all, a duty elsewhere at a workplace with no settings
(the documented fallback rest), a second workplace with its own calendar and
per-slot rest, scenario rows for a deactivated competence, and inactive
"noise" rows the loader must ignore.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, timedelta
from time import perf_counter
from typing import Callable

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.session import Base
from app.models import (
    Ambulance,
    Competence,
    CompetenceScenario,
    CompetenceWeekdayRequirement,
    ConstraintSetting,
    Schedule,
    SpecialDay,
    Unavailability,
    User,
)
from app.models.associations import UserAmbulance, UserCompetence
from app.models.competence_weekday_requirement import (
    DEFAULT_RECOVERY_DAYS,
    DEFAULT_SHIFT_HOURS,
    SPECIAL_DAY_SLOT,
    default_is_surcharge,
)
from app.services.constraint_setting_service import (
    BUSINESS_TRIP,
    DEFINITIONS,
    MODE_FIXED,
    UNAVAILABLE,
    VACATION,
)
from app.services.schedule_generation_service import (
    ScheduleGenerationError,
    SchedulingCompetence,
    generate_ambulance_monthly_schedule,
)
from app.services.special_day_service import library_rest_days, rest_days_between

from tests.scheduling_harness.instances import Instance
from tests.scheduling_harness.runner import SolveOutcome
from tests.scheduling_harness.semantics import (
    MARGIN_DAYS,
    Duty,
    date_range,
    fallback_external_rest,
)

#: How each absence rule is recorded in the unavailability table.
REASON_BY_RULE = {
    UNAVAILABLE: "UNAVAILABLE",
    VACATION: "VACATION",
    BUSINESS_TRIP: "BUSINESS_TRIP",
}

#: Accepted values of ``materialize(scenario=...)``.
SCENARIO_MODES = ("full", "no_special_slot", "none")
#: Accepted values of ``materialize(external_fallback=...)``.
EXTERNAL_FALLBACK_MODES = ("explicit", "unconfigured")


class InexpressibleInstance(ValueError):
    """The instance says something the database cannot store."""


@dataclass
class DbWorld:
    """Where an instance landed in the database, and how to translate ids.

    ``external_ambulance_id`` is the second workplace holding the duties
    elsewhere; ``unconfigured_ambulance_id`` the third one, with no scenario,
    used by ``external_fallback='unconfigured'`` (``None`` otherwise).
    """

    ambulance_id: int
    external_ambulance_id: int
    unconfigured_ambulance_id: int | None = None
    user_ids: dict[int, int] = field(default_factory=dict)
    user_back: dict[int, int] = field(default_factory=dict)
    competence_ids: dict[int, int] = field(default_factory=dict)
    competence_back: dict[int, int] = field(default_factory=dict)

    def to_instance_tuples(self, entries: list) -> list[Duty]:
        """Translate response entries (or db-id tuples) back to instance ids.

        Raises:
            KeyError: If an entry names a user or competence the instance
                does not have.
        """
        found: list[Duty] = []
        for entry in entries:
            if isinstance(entry, tuple):
                user_id, competence_id, work_date = entry
            else:
                user_id, competence_id, work_date = (
                    entry.user_id,
                    entry.competence_id,
                    entry.work_date,
                )
            found.append(
                (self.user_back[user_id], self.competence_back[competence_id], work_date)
            )
        return found

    def fixed_entries_for_db(self, instance: Instance) -> list[tuple[int, int, date]]:
        """The instance's manual placements, in database ids."""
        return [
            (self.user_ids[user_id], self.competence_ids[competence_id], work_date)
            for user_id, competence_id, work_date in sorted(instance.fixed)
        ]


@contextmanager
def fresh_session() -> Iterator[Session]:
    """An empty in-memory SQLite database with every table created."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _one_value(values: set, what: str) -> object:
    """The single value a slot must take, or an error if the dates disagree."""
    if len(values) > 1:
        raise InexpressibleInstance(f"{what} differs between dates of one slot: {values}")
    return next(iter(values))


def slot_values(
    competence: SchedulingCompetence, span: list[date]
) -> dict[int, tuple[int, bool, int, float]]:
    """The eight slots ``(count, surcharge, recovery, hours)`` of one competence.

    Read through the competence's own per-date contract over ``span`` --
    weekday slots from ordinary dates, the special slot from the days of
    rest -- so whatever fields the instance left unset, the stored slots
    answer every date of the span the same way.
    """

    def answer(day: date) -> tuple[int, bool, int, float]:
        return (
            int(competence.required_on(day)),
            bool(competence.is_surcharge_on(day)),
            int(competence.recovery_days_on(day)),
            float(competence.shift_hours_on(day)),
        )

    special = set(competence.special_dates)
    slots: dict[int, tuple[int, bool, int, float]] = {}
    for weekday in range(7):
        ordinary = {answer(day) for day in span if day.weekday() == weekday and day not in special}
        if not ordinary:
            raise InexpressibleInstance(f"every weekday {weekday} of the span is a day of rest")
        slots[weekday] = _one_value(ordinary, f"weekday {weekday} of {competence.name}")
    rest_days = {answer(day) for day in span if day in special}
    if rest_days:
        slots[7] = _one_value(rest_days, f"day of rest of {competence.name}")
    else:
        slots[7] = (
            competence.special_day_required_count
            if competence.special_day_required_count is not None
            else slots[6][0],
            competence.special_day_is_surcharge
            if competence.special_day_is_surcharge is not None
            else True,
            competence.special_day_recovery_days
            if competence.special_day_recovery_days is not None
            else slots[6][2],
            competence.special_day_shift_hours
            if competence.special_day_shift_hours is not None
            else slots[6][3],
        )
    return slots


def unconfigured_slots(required_count: int) -> dict[int, tuple[int, bool, int, float]]:
    """The slots the loader answers for a competence with no scenario rows."""
    return {
        slot: (
            required_count,
            default_is_surcharge(slot),
            DEFAULT_RECOVERY_DAYS,
            float(DEFAULT_SHIFT_HOURS),
        )
        for slot in range(SPECIAL_DAY_SLOT + 1)
    }


def calendar_span(instance: Instance) -> list[date]:
    """The month and a week either side: everything the loader reads."""
    margin = timedelta(days=MARGIN_DAYS)
    return date_range(instance.days[0] - margin, instance.days[-1] + margin)


def _library_between(first: date, last: date) -> set[date]:
    """Slovak public holidays that are days of rest, between two dates."""
    found: set[date] = set()
    for year in range(first.year, last.year + 1):
        found |= {day for day in library_rest_days(year) if first <= day <= last}
    return found


def _external_rows(
    instance: Instance, external_fallback: str
) -> list[tuple[int, date, int | None]]:
    """One ``(user, date, rest)`` per duty elsewhere, in the instance's entry order.

    A date with two explicit rests gives two rows (two duties elsewhere that
    day). A date with none gives one row whose rest is the documented
    fallback (``explicit``) or ``None``, meaning "at a workplace with no
    settings" (``unconfigured``).
    """
    rows: list[tuple[int, date, int | None]] = []
    for employee in instance.employees:
        for day in sorted(employee.externally_scheduled_dates):
            given = [int(rest) for when, rest in employee.external_commitments if when == day]
            if given:
                rows.extend((employee.id, day, rest) for rest in given)
            elif external_fallback == "explicit":
                rows.append(
                    (employee.id, day, fallback_external_rest(instance.competences, day))
                )
            else:
                rows.append((employee.id, day, None))
    return rows


def materialize(
    instance: Instance,
    session: Session,
    ambulance_name: str = "Target",
    *,
    scenario: str = "full",
    external_fallback: str = "explicit",
    foreign_calendar: bool = False,
    retired_recovery: int | None = None,
    noise: bool = False,
) -> DbWorld:
    """Write an instance into an empty session and commit it.

    Args:
        instance: What to write.
        session: An empty session (see :func:`fresh_session`).
        ambulance_name: Name of the target workplace.
        scenario: ``'full'`` writes all eight slots of every competence;
            ``'no_special_slot'`` leaves out slot 7, which the loader then
            answers like Sunday (the instance's special slot must equal its
            Sunday slot); ``'none'`` writes no scenario at all (every
            competence must equal :func:`.instances.unconfigured_competence`).
        external_fallback: How a day worked elsewhere with no rest of its own
            is written. ``'explicit'`` puts it at the second workplace in a
            competence earning exactly the documented fallback (longest rest
            here that day); ``'unconfigured'`` puts it at a third workplace
            with no scenario, so the loader has to apply the fallback itself.
        foreign_calendar: Give the second workplace days of rest of its own
            and competences whose rest differs by slot, so the loader must
            read the right slot of the right calendar.
        retired_recovery: If set, the deactivated competence used by duties
            around the month keeps scenario rows with this rest (as real
            data does after a competence is switched off).
        noise: Add inactive rows (users, memberships, qualifications,
            absences, duties, an unselected scenario, an unknown rule) that
            the loader must ignore.

    Raises:
        InexpressibleInstance: If the instance carries something the
            application cannot store (overlapping day records, a record
            outside the month, an adjacent duty inside the month or more
            than a week outside it, slot values that differ between dates of
            one slot, competences disagreeing on the days of rest, or values
            the chosen ``scenario`` mode cannot express).
    """
    if scenario not in SCENARIO_MODES:
        raise ValueError(f"unknown scenario mode {scenario!r}")
    if external_fallback not in EXTERNAL_FALLBACK_MODES:
        raise ValueError(f"unknown external_fallback mode {external_fallback!r}")
    span = calendar_span(instance)
    first, last = span[0], span[-1]
    special_sets = {frozenset(c.special_dates & set(span)) for c in instance.competences}
    if len(special_sets) > 1:
        raise InexpressibleInstance("competences disagree on the days of rest")
    wanted_rest_days = next(iter(special_sets), frozenset())

    target = Ambulance(name=ambulance_name, is_active=True)
    elsewhere = Ambulance(name=f"{ambulance_name} elsewhere", is_active=True)
    session.add_all([target, elsewhere])
    unconfigured: Ambulance | None = None
    if external_fallback == "unconfigured":
        unconfigured = Ambulance(name=f"{ambulance_name} unconfigured", is_active=True)
        session.add(unconfigured)
    session.flush()
    world = DbWorld(
        ambulance_id=target.id,
        external_ambulance_id=elsewhere.id,
        unconfigured_ambulance_id=unconfigured.id if unconfigured else None,
    )

    users: dict[int, User] = {}
    for employee in instance.employees:
        users[employee.id] = User(
            email=employee.email,
            full_name=employee.full_name,
            max_shifts_per_month=employee.max_shifts_per_month,
            shift_preference=employee.shift_preference,
            is_active=True,
        )
    session.add_all(users.values())
    session.flush()
    for instance_id, user in users.items():
        world.user_ids[instance_id] = user.id
        world.user_back[user.id] = instance_id
        session.add(UserAmbulance(user_id=user.id, ambulance_id=target.id, is_active=True))

    competences: dict[int, Competence] = {}
    for competence in instance.competences:
        competences[competence.id] = Competence(
            name=competence.name,
            required_count=competence.required_count,
            ambulance_id=target.id,
            is_active=True,
        )
    known = {competence.id for competence in instance.competences}
    retired_ids = sorted({duty[1] for duty in instance.adjacent} - known)
    for retired_id in retired_ids:
        competences[retired_id] = Competence(
            name=f"Retired {retired_id}",
            required_count=1,
            ambulance_id=target.id,
            is_active=False,
        )
    session.add_all(competences.values())
    session.flush()
    for instance_id, row in competences.items():
        world.competence_ids[instance_id] = row.id
        world.competence_back[row.id] = instance_id

    selected: CompetenceScenario | None = None
    if scenario != "none":
        selected = CompetenceScenario(
            name="Harness", ambulance_id=target.id, is_selected=True, is_active=True
        )
        session.add(selected)
        session.flush()
    for competence in instance.competences:
        slots = slot_values(competence, span)
        if scenario == "none":
            if slots != unconfigured_slots(competence.required_count):
                raise InexpressibleInstance(
                    f"{competence.name} differs from what a competence with no scenario reads"
                )
            continue
        if scenario == "no_special_slot":
            if slots[SPECIAL_DAY_SLOT] != slots[6]:
                raise InexpressibleInstance(
                    f"{competence.name}: the special slot differs from Sunday's"
                )
            del slots[SPECIAL_DAY_SLOT]
        for slot, (count, surcharge, recovery, hours) in slots.items():
            session.add(
                CompetenceWeekdayRequirement(
                    competence_id=world.competence_ids[competence.id],
                    scenario_id=selected.id,
                    weekday=slot,
                    required_count=count,
                    is_surcharge=surcharge,
                    recovery_days=recovery,
                    shift_hours=hours,
                )
            )
    if retired_recovery is not None and selected is not None:
        for retired_id in retired_ids:
            for slot in range(SPECIAL_DAY_SLOT + 1):
                session.add(
                    CompetenceWeekdayRequirement(
                        competence_id=world.competence_ids[retired_id],
                        scenario_id=selected.id,
                        weekday=slot,
                        required_count=1,
                        is_surcharge=default_is_surcharge(slot),
                        recovery_days=retired_recovery,
                        shift_hours=4.0,
                    )
                )

    library = _library_between(first, last)
    for day in sorted(wanted_rest_days - library):
        session.add(SpecialDay(ambulance_id=target.id, day=day, is_rest_day=True, name="Harness"))
    for day in sorted(library - wanted_rest_days):
        session.add(SpecialDay(ambulance_id=target.id, day=day, is_rest_day=False))

    month = instance.day_set
    for employee in instance.employees:
        user_id = world.user_ids[employee.id]
        for competence_id in sorted(employee.competence_ids):
            if competence_id in world.competence_ids:
                session.add(
                    UserCompetence(
                        user_id=user_id,
                        competence_id=world.competence_ids[competence_id],
                        is_active=True,
                    )
                )
        reasons: dict[date, str] = {}
        rules = dict(employee.absence_rules)
        for day in employee.unavailable_dates:
            reasons[day] = REASON_BY_RULE[rules.get(day, UNAVAILABLE)]
        for wish_dates, reason in (
            (employee.preferred_dates, "PREFERRED"),
            (employee.soft_declined_dates, "SOFT_DECLINE"),
        ):
            for day in wish_dates:
                if day in reasons:
                    raise InexpressibleInstance(f"two day records for {employee.id} on {day}")
                reasons[day] = reason
        for day, reason in sorted(reasons.items()):
            if day not in month:
                raise InexpressibleInstance(f"day record outside the month: {day}")
            session.add(
                Unavailability(user_id=user_id, date_absent=day, reason=reason, is_active=True)
            )

    for user_id, competence_id, day in sorted(instance.adjacent):
        if day in month:
            raise InexpressibleInstance(f"adjacent duty inside the month: {day}")
        if not first <= day <= last:
            raise InexpressibleInstance(f"adjacent duty more than a week outside the month: {day}")
        session.add(
            Schedule(
                user_id=world.user_ids[user_id],
                ambulance_id=target.id,
                competence_id=world.competence_ids[competence_id],
                work_date=day,
                is_active=True,
            )
        )

    _write_externals(instance, session, world, elsewhere, unconfigured, external_fallback, foreign_calendar)

    if instance.policy is not None:
        for code, rule in instance.policy.rules.items():
            if DEFINITIONS[code].mode == MODE_FIXED:
                continue
            session.add(
                ConstraintSetting(
                    ambulance_id=target.id,
                    code=code,
                    is_strict=rule.strict,
                    weight=rule.weight,
                )
            )
    if noise:
        _write_noise(instance, session, world, target, elsewhere, selected)
    session.commit()

    stored = rest_days_between(session, target.id, first, last)
    if stored != set(wanted_rest_days):
        raise InexpressibleInstance(
            f"days of rest came out as {sorted(stored)}, wanted {sorted(wanted_rest_days)}"
        )
    return world


def _write_externals(
    instance: Instance,
    session: Session,
    world: DbWorld,
    elsewhere: Ambulance,
    unconfigured: Ambulance | None,
    external_fallback: str,
    foreign_calendar: bool,
) -> None:
    """Write the duties elsewhere, each in a competence earning exactly its rest.

    Plain mode: one competence per rest length, every slot of it earning that
    rest. With ``foreign_calendar`` the second workplace adds and removes days
    of rest of its own, and every competence earns the wanted rest on one
    slot only (a weekday, or the special slot), something else on the rest,
    so the loader has to pick the slot from the second workplace's calendar.
    """
    span = calendar_span(instance)
    first, last = span[0], span[-1]
    rows = _external_rows(instance, external_fallback)
    for _user, day, _rest in rows:
        if not first <= day <= last:
            raise InexpressibleInstance(f"duty elsewhere too far from the month: {day}")
    if not rows:
        return

    foreign_rest_days: set[date] = set()
    if foreign_calendar:
        library = _library_between(first, last)
        added = {day for day in span if day.toordinal() % 9 == 4} - library
        removed = {day for day in sorted(library) if day.toordinal() % 2 == 0}
        for day in sorted(added):
            session.add(SpecialDay(ambulance_id=elsewhere.id, day=day, is_rest_day=True, name="Own"))
        for day in sorted(removed):
            session.add(SpecialDay(ambulance_id=elsewhere.id, day=day, is_rest_day=False))
        session.flush()
        foreign_rest_days = rest_days_between(session, elsewhere.id, first, last)

    foreign = CompetenceScenario(
        name="Elsewhere", ambulance_id=elsewhere.id, is_selected=True, is_active=True
    )
    session.add(foreign)
    session.flush()
    rest_competences: dict[tuple, Competence] = {}
    unconfigured_competences: dict[int, Competence] = {}

    def slot_of(day: date) -> int:
        return SPECIAL_DAY_SLOT if day in foreign_rest_days else day.weekday()

    def competence_for(rest: int, day: date, copy: int) -> Competence:
        key = (rest, slot_of(day) if foreign_calendar else None, copy)
        if key not in rest_competences:
            row = Competence(
                name=f"Rest {rest} slot {key[1]} copy {copy}",
                required_count=1,
                ambulance_id=elsewhere.id,
                is_active=True,
            )
            session.add(row)
            session.flush()
            for slot in range(SPECIAL_DAY_SLOT + 1):
                # Any other slot earns a different rest (1 + slot % 6 is never 0 mod 7).
                earned = rest if key[1] is None or slot == key[1] else (rest + 1 + slot % 6) % 7
                session.add(
                    CompetenceWeekdayRequirement(
                        competence_id=row.id,
                        scenario_id=foreign.id,
                        weekday=slot,
                        required_count=1,
                        is_surcharge=False,
                        recovery_days=earned,
                        shift_hours=4.0,
                    )
                )
            rest_competences[key] = row
        return rest_competences[key]

    used: set[tuple[int, int, date]] = set()
    for user_id, day, rest in rows:
        if rest is None:
            assert unconfigured is not None
            if 0 not in unconfigured_competences:
                unconfigured_competences[0] = Competence(
                    name="Anything", required_count=1, ambulance_id=unconfigured.id, is_active=True
                )
                session.add(unconfigured_competences[0])
                session.flush()
            row = unconfigured_competences[0]
            ambulance_id = unconfigured.id
        else:
            copy = 0
            row = competence_for(rest, day, copy)
            while (user_id, row.id, day) in used:
                copy += 1
                row = competence_for(rest, day, copy)
            ambulance_id = elsewhere.id
        used.add((user_id, row.id, day))
        session.add(
            Schedule(
                user_id=world.user_ids[user_id],
                ambulance_id=ambulance_id,
                competence_id=row.id,
                work_date=day,
                is_active=True,
            )
        )
        session.flush()


def _write_noise(
    instance: Instance,
    session: Session,
    world: DbWorld,
    target: Ambulance,
    elsewhere: Ambulance,
    selected: CompetenceScenario | None,
) -> None:
    """Rows the loader must ignore: inactive people, links, records and duties."""
    competence_rows = [world.competence_ids[competence.id] for competence in instance.competences]
    if not competence_rows:
        return
    month = instance.days
    ghost = User(email="noise-inactive@harness.test", full_name="Gone", is_active=False)
    leaver = User(email="noise-leaver@harness.test", full_name="Left", is_active=True)
    session.add_all([ghost, leaver])
    session.flush()
    session.add_all(
        [
            UserAmbulance(user_id=ghost.id, ambulance_id=target.id, is_active=True),
            UserAmbulance(user_id=leaver.id, ambulance_id=target.id, is_active=False),
            UserCompetence(user_id=ghost.id, competence_id=competence_rows[0], is_active=True),
            UserCompetence(user_id=leaver.id, competence_id=competence_rows[0], is_active=True),
            Unavailability(user_id=ghost.id, date_absent=month[0], reason="VACATION", is_active=True),
        ]
    )
    for employee in instance.employees:
        user_id = world.user_ids[employee.id]
        missing = [
            world.competence_ids[competence.id]
            for competence in instance.competences
            if competence.id not in employee.competence_ids
        ]
        if missing:
            session.add(UserCompetence(user_id=user_id, competence_id=missing[0], is_active=False))
        day = month[(employee.id * 7) % len(month)]
        session.add(
            Unavailability(user_id=user_id, date_absent=day, reason="UNAVAILABLE", is_active=False)
        )
        before = month[0] - timedelta(days=1 + employee.id % 7)
        if not any(duty[0] == employee.id and duty[2] == before for duty in instance.adjacent):
            session.add(
                Schedule(
                    user_id=user_id,
                    ambulance_id=target.id,
                    competence_id=competence_rows[0],
                    work_date=before,
                    is_active=False,
                )
            )
    garbage = CompetenceScenario(
        name="Unselected", ambulance_id=target.id, is_selected=False, is_active=True
    )
    session.add(garbage)
    session.flush()
    for competence_id in competence_rows:
        for slot in range(SPECIAL_DAY_SLOT + 1):
            session.add(
                CompetenceWeekdayRequirement(
                    competence_id=competence_id,
                    scenario_id=garbage.id,
                    weekday=slot,
                    required_count=9,
                    is_surcharge=slot % 2 == 0,
                    recovery_days=6,
                    shift_hours=23.5,
                )
            )
    session.add(ConstraintSetting(ambulance_id=target.id, code="legacy_rule", is_strict=True, weight=5.0))


def run_db_solver(
    instance: Instance,
    time_budget_seconds: float = 30,
    session_factory: Callable[[], object] = fresh_session,
    **materialize_options: object,
) -> SolveOutcome:
    """Materialize an instance and solve it through the database loader.

    ``materialize_options`` are passed on to :func:`materialize`. A response
    naming an unknown user or competence is reported as ``status='error'``.
    """
    with session_factory() as session:
        world = materialize(instance, session, **materialize_options)
        started = perf_counter()
        try:
            response = generate_ambulance_monthly_schedule(
                session,
                world.ambulance_id,
                instance.month,
                instance.year,
                fixed_entries=world.fixed_entries_for_db(instance),
                generate_from=instance.generate_from,
                time_budget_seconds=time_budget_seconds,
            )
            assignments = world.to_instance_tuples(response.entries)
        except ScheduleGenerationError as error:
            issues = list(error.issues)
            status = (
                "timeout"
                if any(issue.get("code") == "solver_timeout" for issue in issues)
                else "infeasible"
            )
            return SolveOutcome(
                status, [], issues, perf_counter() - started, error.message, time_budget_seconds
            )
        except Exception as error:  # noqa: BLE001 - every other failure is a finding
            return SolveOutcome(
                "error",
                [],
                [],
                perf_counter() - started,
                f"{type(error).__name__}: {error}",
                time_budget_seconds,
            )
        return SolveOutcome(
            "ok", assignments, [], perf_counter() - started, None, time_budget_seconds
        )
