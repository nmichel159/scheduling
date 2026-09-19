"""Which calendar dates are days of rest, and who gets to say so.

The answer comes from two layers, in this order:

1. **The library.** ``holidays`` ships Slovakia's public holidays, and it
   distinguishes the two kinds the law distinguishes: its ``public``
   category is the days of rest ("dni pracovneho pokoja"), while its
   ``workday`` category holds the state holidays that are *not* days of
   rest -- since the 2024 amendment, 8 May, 1 and 15 September, 28 October
   and 17 November are commemorated but worked. Nobody types this in and
   nobody has to maintain it per year.
2. **The workplace's own overrides.** A clinic may close on a day the
   library works, or staff a day the library rests. One
   :class:`~app.models.special_day.SpecialDay` row is one such exception;
   removing the row hands the date back to the library.

Sundays are days of rest by law as well, but they need no library: they are
a weekday, and the competence editor already staffs weekdays one by one.
This module is about the dates that move from year to year.
"""

from datetime import date

import holidays
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.special_day import SpecialDay
from app.services.database_conflict import commit_or_conflict

#: The country whose public-holiday calendar the library is asked for.
HOLIDAY_COUNTRY = "SK"

#: Language the library names the days in. The screen that shows them is
#: Slovak-first, and the names are proper nouns rather than UI strings.
HOLIDAY_LANGUAGE = "sk"

#: Years the library is willing to answer for. ``holidays`` computes rather
#: than tabulates, so the bound is only there to keep a mistyped year from
#: building a calendar nobody asked for.
MIN_YEAR = 2000
MAX_YEAR = 2100

DUPLICATE_DETAIL = "This workplace already has an entry for that day."


def _library(year: int, category: str) -> dict[date, str]:
    """One category of the Slovak holiday calendar for one year."""
    return dict(
        holidays.country_holidays(
            HOLIDAY_COUNTRY,
            years=year,
            language=HOLIDAY_LANGUAGE,
            categories=(category,),
        )
    )


def library_rest_days(year: int) -> dict[date, str]:
    """The year's public holidays that are days of rest, date -> name."""
    return _library(year, "public")


def library_state_workdays(year: int) -> dict[date, str]:
    """The year's state holidays that are ordinary working days.

    They are listed beside the days of rest on the library screen because
    they are exactly the dates a workplace is most likely to want to
    override: commemorated, widely known, and worked by default.
    """
    return _library(year, "workday")


def _library_rest_days_between(start: date, end: date) -> dict[date, str]:
    """Days of rest the library knows in a closed date range."""
    found: dict[date, str] = {}
    for year in range(start.year, end.year + 1):
        for day, name in library_rest_days(year).items():
            if start <= day <= end:
                found[day] = name
    return found


def validate_year(year: int) -> int:
    """Reject a year the library is not asked to compute."""
    if not MIN_YEAR <= year <= MAX_YEAR:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"year must be between {MIN_YEAR} and {MAX_YEAR}.",
        )
    return year


def overrides_between(
    db: Session, ambulance_id: int, start: date, end: date
) -> dict[date, SpecialDay]:
    """A workplace's overrides in a closed date range, keyed by date."""
    rows = (
        db.query(SpecialDay)
        .filter(
            SpecialDay.ambulance_id == ambulance_id,
            SpecialDay.day >= start,
            SpecialDay.day <= end,
        )
        .order_by(SpecialDay.day)
        .all()
    )
    return {row.day: row for row in rows}


def rest_days_between(
    db: Session, ambulance_id: int, start: date, end: date
) -> set[date]:
    """Every date this workplace treats as a day of rest in a range.

    This is the function the schedule generator asks: the library's days of
    rest, plus the ones the workplace added, minus the ones it took away.
    """
    days = set(_library_rest_days_between(start, end))
    for day, override in overrides_between(db, ambulance_id, start, end).items():
        if override.is_rest_day:
            days.add(day)
        else:
            days.discard(day)
    return days


def year_entries(db: Session, ambulance_id: int, year: int) -> list[dict]:
    """The workplace's whole special-day calendar for one year.

    Every date worth showing is in the list -- the library's days of rest,
    the state holidays it works, and anything the workplace added of its
    own -- each one carrying where its verdict came from, so the screen can
    show a day as inherited, added here or taken away here rather than just
    as a checkbox.
    """
    validate_year(year)
    start = date(year, 1, 1)
    end = date(year, 12, 31)

    entries: dict[date, dict] = {}
    for day, name in library_rest_days(year).items():
        entries[day] = {
            "day": day,
            "name": name,
            "in_library": True,
            "library_rest_day": True,
            "is_rest_day": True,
            "is_overridden": False,
        }
    for day, name in library_state_workdays(year).items():
        entries[day] = {
            "day": day,
            "name": name,
            "in_library": True,
            "library_rest_day": False,
            "is_rest_day": False,
            "is_overridden": False,
        }
    for day, override in overrides_between(db, ambulance_id, start, end).items():
        entry = entries.get(day)
        if entry is None:
            entry = {
                "day": day,
                "name": override.name,
                "in_library": False,
                "library_rest_day": False,
            }
            entries[day] = entry
        entry["is_rest_day"] = bool(override.is_rest_day)
        entry["is_overridden"] = bool(override.is_rest_day) != entry["library_rest_day"]
        if override.name:
            entry["name"] = override.name

    return [entries[day] for day in sorted(entries)]


def set_special_day(
    db: Session,
    ambulance_id: int,
    day: date,
    is_rest_day: bool,
    name: str | None = None,
) -> SpecialDay | None:
    """Record what this workplace makes of one date.

    An override that merely repeats the library is not stored: saying
    "1 January rests" changes nothing, and keeping a row for it would make
    the screen claim the workplace had decided something it inherited. Such
    a call deletes any existing override instead and returns ``None``,
    which is the same state a reset leaves behind.
    """
    library_says_rest = day in library_rest_days(day.year)
    existing = (
        db.query(SpecialDay)
        .filter(SpecialDay.ambulance_id == ambulance_id, SpecialDay.day == day)
        .first()
    )

    if is_rest_day == library_says_rest:
        if existing is not None:
            db.delete(existing)
            db.commit()
        return None

    if existing is None:
        existing = SpecialDay(ambulance_id=ambulance_id, day=day)
        db.add(existing)
    existing.is_rest_day = is_rest_day
    existing.name = (name or "").strip() or existing.name
    commit_or_conflict(db, DUPLICATE_DETAIL)
    db.refresh(existing)
    return existing


def clear_special_day(db: Session, ambulance_id: int, day: date) -> None:
    """Hand one date back to the library, whichever way it was overridden."""
    existing = (
        db.query(SpecialDay)
        .filter(SpecialDay.ambulance_id == ambulance_id, SpecialDay.day == day)
        .first()
    )
    if existing is None:
        return
    db.delete(existing)
    db.commit()


def copy_special_days(
    db: Session, source_ambulance_id: int, target_ambulance_id: int, year: int
) -> int:
    """Copy one year of overrides from one workplace onto another.

    The target's own overrides for that year are replaced, because the
    point of the action is "make this workplace's year look like that
    one's". Returns how many overrides were copied.
    """
    validate_year(year)
    start = date(year, 1, 1)
    end = date(year, 12, 31)
    for row in overrides_between(db, target_ambulance_id, start, end).values():
        db.delete(row)
    db.flush()
    sources = overrides_between(db, source_ambulance_id, start, end)
    for day, row in sources.items():
        db.add(
            SpecialDay(
                ambulance_id=target_ambulance_id,
                day=day,
                is_rest_day=row.is_rest_day,
                name=row.name,
            )
        )
    commit_or_conflict(db, DUPLICATE_DETAIL)
    return len(sources)
