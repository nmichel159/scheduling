"""Custom days of a workplace and the dates they are placed on.

See :mod:`app.models.custom_day` for what a custom day is. This module
keeps them and answers the one question the rest of the application asks:
for a date of this workplace, which parameters staff it -- a custom day's,
the day of rest's or the weekday's.
"""

from calendar import monthrange
from datetime import date
from typing import NamedTuple

from fastapi import HTTPException, status
from sqlalchemy.orm import Session, selectinload

from app.models.competence import Competence
from app.models.competence_weekday_requirement import (
    DEFAULT_RECOVERY_DAYS,
    DEFAULT_SHIFT_HOURS,
    SPECIAL_DAY_SLOT,
)
from app.models.custom_day import CustomDay, CustomDayDate, CustomDayRequirement
from app.schemas.custom_day import (
    CustomDayCreate,
    CustomDayRequirementData,
    CustomDayResponse,
    CustomDayUpdate,
    DayNeed,
    MonthDay,
    MonthNeeds,
)
from app.services.competence_service import (
    list_competences,
    resolve_scenario,
    weekly_parameters,
)
from app.services.special_day_service import rest_days_between


class DayParameters(NamedTuple):
    """Everything a date's duty is built from, for one competence."""

    required_count: int
    is_surcharge: bool
    recovery_days: int
    shift_hours: float


#: What a competence a custom day has no row for gets: nobody.
UNSTAFFED = DayParameters(0, False, DEFAULT_RECOVERY_DAYS, DEFAULT_SHIFT_HOURS)


def _active_competence_ids(db: Session, ambulance_id: int) -> list[int]:
    return [
        row_id
        for (row_id,) in db.query(Competence.id)
        .filter(
            Competence.ambulance_id == ambulance_id,
            Competence.is_active.is_(True),
        )
        .order_by(Competence.name)
    ]


def _date_counts(db: Session, ambulance_id: int) -> dict[int, int]:
    counts: dict[int, int] = {}
    for (custom_day_id,) in db.query(CustomDayDate.custom_day_id).filter(
        CustomDayDate.ambulance_id == ambulance_id
    ):
        counts[custom_day_id] = counts.get(custom_day_id, 0) + 1
    return counts


def to_response(
    custom_day: CustomDay, competence_ids: list[int], date_count: int = 0
) -> CustomDayResponse:
    """Serialize a custom day with a row for every active competence."""
    rows = {row.competence_id: row for row in custom_day.requirements}
    requirements = []
    for competence_id in competence_ids:
        row = rows.get(competence_id)
        requirements.append(
            CustomDayRequirementData(
                competence_id=competence_id,
                required_count=row.required_count if row else 0,
                recovery_days=row.recovery_days if row else DEFAULT_RECOVERY_DAYS,
                shift_hours=row.shift_hours if row else DEFAULT_SHIFT_HOURS,
                is_surcharge=bool(row.is_surcharge) if row else False,
            )
        )
    return CustomDayResponse(
        id=custom_day.id,
        ambulance_id=custom_day.ambulance_id,
        name=custom_day.name,
        requirements=requirements,
        date_count=date_count,
    )


def list_custom_days(db: Session, ambulance_id: int) -> list[CustomDayResponse]:
    competence_ids = _active_competence_ids(db, ambulance_id)
    counts = _date_counts(db, ambulance_id)
    rows = (
        db.query(CustomDay)
        .options(selectinload(CustomDay.requirements))
        .filter(CustomDay.ambulance_id == ambulance_id)
        .order_by(CustomDay.name, CustomDay.id)
        .all()
    )
    return [to_response(row, competence_ids, counts.get(row.id, 0)) for row in rows]


def get_custom_day(db: Session, ambulance_id: int, custom_day_id: int) -> CustomDay:
    row = (
        db.query(CustomDay)
        .options(selectinload(CustomDay.requirements))
        .filter(
            CustomDay.id == custom_day_id,
            CustomDay.ambulance_id == ambulance_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Custom day not found in this workplace.",
        )
    return row


def _replace_requirements(
    db: Session,
    ambulance_id: int,
    custom_day: CustomDay,
    requirements: list[CustomDayRequirementData],
) -> None:
    """Write the submitted competences' rows, leaving the others alone."""
    allowed = set(_active_competence_ids(db, ambulance_id))
    existing = {row.competence_id: row for row in custom_day.requirements}
    for item in requirements:
        if item.competence_id not in allowed:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Competence {item.competence_id} is not part of this workplace.",
            )
        row = existing.get(item.competence_id)
        if row is None:
            row = CustomDayRequirement(competence_id=item.competence_id)
            custom_day.requirements.append(row)
            existing[item.competence_id] = row
        row.required_count = item.required_count
        row.recovery_days = item.recovery_days
        row.shift_hours = item.shift_hours
        row.is_surcharge = item.is_surcharge


def create_custom_day(
    db: Session, ambulance_id: int, data: CustomDayCreate
) -> CustomDayResponse:
    custom_day = CustomDay(ambulance_id=ambulance_id, name=data.name.strip())
    db.add(custom_day)
    _replace_requirements(db, ambulance_id, custom_day, data.requirements or [])
    db.commit()
    db.refresh(custom_day)
    return to_response(custom_day, _active_competence_ids(db, ambulance_id))


def update_custom_day(
    db: Session, ambulance_id: int, custom_day_id: int, data: CustomDayUpdate
) -> CustomDayResponse:
    custom_day = get_custom_day(db, ambulance_id, custom_day_id)
    if data.name is not None:
        custom_day.name = data.name.strip()
    if data.requirements is not None:
        _replace_requirements(db, ambulance_id, custom_day, data.requirements)
    db.commit()
    db.refresh(custom_day)
    return to_response(
        custom_day,
        _active_competence_ids(db, ambulance_id),
        _date_counts(db, ambulance_id).get(custom_day.id, 0),
    )


def delete_custom_day(db: Session, ambulance_id: int, custom_day_id: int) -> None:
    """Remove a custom day; its dates go back to the calendar."""
    custom_day = get_custom_day(db, ambulance_id, custom_day_id)
    db.delete(custom_day)
    db.commit()


def set_custom_date(
    db: Session, ambulance_id: int, day: date, custom_day_id: int | None
) -> None:
    """Staff ``day`` as a custom day, or hand it back to the calendar."""
    existing = (
        db.query(CustomDayDate)
        .filter(CustomDayDate.ambulance_id == ambulance_id, CustomDayDate.day == day)
        .first()
    )
    if custom_day_id is None:
        if existing is not None:
            db.delete(existing)
            db.commit()
        return
    get_custom_day(db, ambulance_id, custom_day_id)
    if existing is None:
        existing = CustomDayDate(ambulance_id=ambulance_id, day=day)
        db.add(existing)
    existing.custom_day_id = custom_day_id
    db.commit()


def custom_dates_between(
    db: Session, ambulance_id: int, first: date, last: date
) -> dict[date, int]:
    """Which dates of a range are custom days, date -> custom day id."""
    return dict(
        db.query(CustomDayDate.day, CustomDayDate.custom_day_id)
        .filter(
            CustomDayDate.ambulance_id == ambulance_id,
            CustomDayDate.day >= first,
            CustomDayDate.day <= last,
        )
        .all()
    )


def custom_parameters_between(
    db: Session, ambulance_id: int, first: date, last: date
) -> dict[date, dict[int, DayParameters]]:
    """The parameters of every custom date in a range, per competence.

    A competence missing from a date's map is not staffed that day; callers
    read it as :data:`UNSTAFFED`.
    """
    dates = custom_dates_between(db, ambulance_id, first, last)
    if not dates:
        return {}
    by_day: dict[int, dict[int, DayParameters]] = {}
    for row in db.query(CustomDayRequirement).filter(
        CustomDayRequirement.custom_day_id.in_(set(dates.values()))
    ):
        by_day.setdefault(row.custom_day_id, {})[row.competence_id] = DayParameters(
            int(row.required_count),
            bool(row.is_surcharge),
            int(row.recovery_days),
            float(row.shift_hours),
        )
    return {day: by_day.get(custom_day_id, {}) for day, custom_day_id in dates.items()}


def month_needs(
    db: Session,
    ambulance_id: int,
    year: int,
    month: int,
    scenario_id: int | None = None,
) -> MonthNeeds:
    """What every competence needs on every date of a month.

    This is the same reading the schedule generator makes: a custom date
    first, then a day of rest, then the weekday, all from ``scenario_id``
    (the selected scenario when none is given).
    """
    scenario = resolve_scenario(db, ambulance_id, scenario_id)
    first = date(year, month, 1)
    last = date(year, month, monthrange(year, month)[1])
    rest_days = rest_days_between(db, ambulance_id, first, last)
    custom_ids = custom_dates_between(db, ambulance_id, first, last)
    custom = custom_parameters_between(db, ambulance_id, first, last)
    competences = list_competences(db, ambulance_id)
    weeks = {
        competence.id: weekly_parameters(competence, scenario.id)
        for competence in competences
    }

    days: list[MonthDay] = []
    for offset in range(last.day):
        current = date(year, month, offset + 1)
        is_rest = current in rest_days
        if current in custom:
            kind = "custom"
        elif is_rest:
            kind = "rest"
        else:
            kind = "weekday"
        slot = SPECIAL_DAY_SLOT if is_rest else current.weekday()
        needs = []
        for competence in competences:
            if kind == "custom":
                parameters = custom[current].get(competence.id, UNSTAFFED)
                needs.append(
                    DayNeed(
                        competence_id=competence.id,
                        required_count=parameters.required_count,
                        shift_hours=parameters.shift_hours,
                        recovery_days=parameters.recovery_days,
                        is_surcharge=parameters.is_surcharge,
                    )
                )
            else:
                row = weeks[competence.id][slot]
                needs.append(
                    DayNeed(
                        competence_id=competence.id,
                        required_count=row.required_count,
                        shift_hours=row.shift_hours,
                        recovery_days=row.recovery_days,
                        is_surcharge=row.is_surcharge,
                    )
                )
        days.append(
            MonthDay(
                day=current,
                kind=kind,
                is_rest_day=is_rest,
                custom_day_id=custom_ids.get(current),
                needs=needs,
            )
        )
    return MonthNeeds(
        ambulance_id=ambulance_id,
        scenario_id=scenario.id,
        year=year,
        month=month,
        days=days,
    )
