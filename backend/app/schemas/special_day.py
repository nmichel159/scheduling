"""Pydantic schemas for the special-day (day of rest) calendar."""

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


class SpecialDayEntry(BaseModel):
    """One date in a workplace's special-day calendar.

    The verdict a schedule is built from is ``is_rest_day``. The three
    fields around it say where that verdict came from, which is what lets
    the screen distinguish a day inherited from the library from one this
    workplace decided itself:

    * ``in_library`` -- the holiday library knows this date at all.
    * ``library_rest_day`` -- the library calls it a day of rest. A date
      that is ``in_library`` but not a rest day is a state holiday that is
      worked (8 May, 1 and 15 September, 28 October, 17 November).
    * ``is_overridden`` -- this workplace disagrees with the library, so
      resetting the date would change it back.
    """

    day: date
    name: Optional[str] = None
    in_library: bool
    library_rest_day: bool
    is_rest_day: bool
    is_overridden: bool


class SpecialDayYear(BaseModel):
    """A whole year of one workplace's special days."""

    ambulance_id: int
    year: int
    entries: list[SpecialDayEntry]


class SpecialDayWrite(BaseModel):
    """Set what one workplace makes of one date."""

    day: date
    is_rest_day: bool = Field(
        ...,
        description="True marks the date a day of rest, False marks it worked.",
    )
    name: Optional[str] = Field(
        None,
        max_length=200,
        description="What the workplace calls the day; only used for added days.",
    )


class SpecialDayCopy(BaseModel):
    """Copy one year of another workplace's special days onto this one."""

    source_ambulance_id: int
    year: int
