"""Which duty limits hold for an employee in a month, and the weekday wishes.

The most duties a month an employee may be given is settled in three layers,
the stronger first:

1. ``User.scheduler_max_shifts_per_month`` -- the scheduler's cap. Hard.
2. ``MonthlyShiftWish`` -- what the employee wished for this month.
3. ``User.max_shifts_per_month`` -- what the employee wishes in general.

The employee's wish is the month's own when there is one, the standing one
otherwise, and never more than the cap: an employee who asks for ten duties
under a cap of four wishes, in effect, for four.
"""

from __future__ import annotations

from dataclasses import dataclass
from calendar import monthrange
from collections.abc import Iterable
from datetime import date

from sqlalchemy.orm import Session

from app.models.monthly_shift_wish import MonthlyShiftWish
from app.models.user import User


WANT = "want"
AVOID = "avoid"
ANY = "any"

_CODE_BY_VALUE = {WANT: "w", AVOID: "a", ANY: "-"}
_VALUE_BY_CODE = {code: value for value, code in _CODE_BY_VALUE.items()}


def decode_weekdays(stored: str | None) -> list[str]:
    """Seven weekday answers, Monday first, from their stored form."""
    stored = stored or ""
    return [_VALUE_BY_CODE.get(stored[index:index + 1], ANY) for index in range(7)]


def encode_weekdays(values: list[str]) -> str | None:
    """The stored form of seven answers; all of them "any" is NULL."""
    code = "".join(_CODE_BY_VALUE[value] for value in values)
    return None if code == "-------" else code


def weekday_preferences_of(user: User) -> list[str]:
    """The employee's own seven weekday answers."""
    return decode_weekdays(user.weekday_preferences)


def scheduler_weekday_preferences_of(user: User) -> list[str]:
    """The scheduler's seven weekday answers about the employee."""
    return decode_weekdays(user.scheduler_weekday_preferences)


def effective_weekday_preferences(user: User) -> list[str]:
    """Per weekday the scheduler's answer where they gave one, else the employee's."""
    return [
        scheduler if scheduler != ANY else own
        for scheduler, own in zip(
            scheduler_weekday_preferences_of(user), weekday_preferences_of(user)
        )
    ]


def weekday_dates(
    user: User, year: int, month: int
) -> tuple[frozenset[date], frozenset[date]]:
    """The month's days the user wants and avoids by their weekday."""
    preferences = effective_weekday_preferences(user)
    wanted: set[date] = set()
    avoided: set[date] = set()
    for day in range(1, monthrange(year, month)[1] + 1):
        current = date(year, month, day)
        answer = preferences[current.weekday()]
        if answer == WANT:
            wanted.add(current)
        elif answer == AVOID:
            avoided.add(current)
    return frozenset(wanted), frozenset(avoided)


@dataclass(frozen=True)
class ShiftLimits:
    """The duty limits one employee has in one month."""

    #: The scheduler's cap; None means none.
    cap: int | None
    #: The employee's wish for the month, already held under the cap.
    wish: int | None
    #: What the employee asked for this month in particular, if anything.
    month_wish: int | None


def month_wishes(
    db: Session, user_ids: Iterable[int], year: int, month: int
) -> dict[int, int]:
    """Each employee's wish for the month, for those who entered one."""
    ids = list(user_ids)
    if not ids:
        return {}
    rows = (
        db.query(MonthlyShiftWish.user_id, MonthlyShiftWish.max_shifts_per_month)
        .filter(
            MonthlyShiftWish.user_id.in_(ids),
            MonthlyShiftWish.year == year,
            MonthlyShiftWish.month == month,
        )
        .all()
    )
    return {user_id: value for user_id, value in rows}


def limits_for(user: User, month_wish: int | None) -> ShiftLimits:
    """Fold the three layers into the month's cap and wish."""
    cap = user.scheduler_max_shifts_per_month
    wish = month_wish if month_wish is not None else user.max_shifts_per_month
    if cap is not None and (wish is None or wish > cap):
        wish = cap
    return ShiftLimits(cap=cap, wish=wish, month_wish=month_wish)


def shift_limits(
    db: Session, users: Iterable[User], year: int, month: int
) -> dict[int, ShiftLimits]:
    """The month's limits of every user given, by user id."""
    users = list(users)
    wishes = month_wishes(db, (user.id for user in users), year, month)
    return {user.id: limits_for(user, wishes.get(user.id)) for user in users}


def get_month_wish(db: Session, user_id: int, year: int, month: int) -> int | None:
    return month_wishes(db, [user_id], year, month).get(user_id)


def set_month_wish(
    db: Session, user_id: int, year: int, month: int, value: int | None
) -> None:
    """Store or clear (None) the user's wish for one month; no commit."""
    row = (
        db.query(MonthlyShiftWish)
        .filter(
            MonthlyShiftWish.user_id == user_id,
            MonthlyShiftWish.year == year,
            MonthlyShiftWish.month == month,
        )
        .first()
    )
    if value is None:
        if row is not None:
            db.delete(row)
        return
    if row is None:
        db.add(
            MonthlyShiftWish(
                user_id=user_id, year=year, month=month, max_shifts_per_month=value
            )
        )
    else:
        row.max_shifts_per_month = value
