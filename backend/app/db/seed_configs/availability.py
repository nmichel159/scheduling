"""Deterministic absence and day-preference calendars for mock staff.

A generated schedule only demonstrates anything once the people in it have
opinions about the month. Two kinds of entry express those opinions, and both
live in the same table: a day somebody cannot work, which the solver treats as
a hard constraint, and a day somebody asked for, stored under the
``PREFERRED`` reason, which only orders schedules that are already equally
balanced.

Both calendars are derived from a hash of the person and the month rather than
from the clock, so rebuilding a database reproduces them exactly. They are
also drawn from a single sample per person-month, because the database allows
one active entry per person and day: a preferred day can therefore never
collide with an absence created next to it.
"""

from calendar import monthrange
from datetime import date
import hashlib
import random

#: Reason the scheduler reads as "this person asked to work this day".
PREFERRED_REASON = "PREFERRED"


def stable_random(*identity: object) -> random.Random:
    """Return a generator seeded only by `identity`, never by the clock."""
    digest = hashlib.sha256(
        "|".join(str(part) for part in identity).encode("utf-8")
    ).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def monthly_calendar(
    emails: list[str],
    year: int,
    months: tuple[int, ...],
    *,
    unavailable_reason: str,
    unavailable_days: tuple[int, int] = (8, 12),
    preferred_days: tuple[int, int] = (2, 4),
) -> list[dict]:
    """Build one year of absences and day requests for a group of people.

    Args:
        emails: People to build a calendar for.
        year: Calendar year the entries fall in.
        months: Months of that year to cover.
        unavailable_reason: Reason stored on the blocking entries. Seeding
            synchronizes absences per reason, so each staff group needs its own
            marker to stay inside its own scope.
        unavailable_days: Inclusive range of blocked days per person and month.
        preferred_days: Inclusive range of requested days per person and month.

    Returns:
        Seed entries ready for the profile's ``unavailabilities`` key.
    """
    entries: list[dict] = []
    for email in emails:
        for month in months:
            day_count = monthrange(year, month)[1]
            generator = stable_random(unavailable_reason, email, year, month)
            absent_count = generator.randint(*unavailable_days)
            preferred_count = generator.randint(*preferred_days)
            # One sample covers both kinds, so the two calendars are disjoint
            # by construction instead of by a later collision check.
            sampled = generator.sample(
                range(1, day_count + 1), absent_count + preferred_count
            )
            for day in sorted(sampled[:absent_count]):
                entries.append(
                    {
                        "user_email": email,
                        "date_absent": date(year, month, day),
                        "reason": unavailable_reason,
                    }
                )
            for day in sorted(sampled[absent_count:]):
                entries.append(
                    {
                        "user_email": email,
                        "date_absent": date(year, month, day),
                        "reason": PREFERRED_REASON,
                    }
                )
    return entries
