"""Pydantic schemas for a workplace's scheduling rules."""

from typing import Literal, Optional

from pydantic import BaseModel, Field


class ConstraintSettingEntry(BaseModel):
    """One rule as a workplace has it, next to what it would be by default.

    ``mode`` says what may be changed: ``fixed`` rules are always strict,
    ``switchable`` ones may be strict or penalized, and ``penalty`` ones are
    always penalized. ``weight`` is what one breach costs while the rule is
    penalized; a fixed rule has none.
    """

    code: str
    group: Literal["fixed", "absence", "load", "wish"]
    mode: Literal["fixed", "switchable", "penalty"]
    is_strict: bool
    weight: Optional[float] = None
    default_is_strict: bool
    default_weight: Optional[float] = None
    is_default: bool


class ConstraintSettingList(BaseModel):
    """Every rule of one workplace."""

    ambulance_id: int
    entries: list[ConstraintSettingEntry]


class ConstraintSettingWrite(BaseModel):
    """What a workplace sets for one rule."""

    code: str = Field(..., max_length=64)
    is_strict: bool
    weight: Optional[float] = Field(
        None,
        ge=0,
        description="Cost of one breach while penalized; the default when omitted.",
    )


class ConstraintSettingUpdate(BaseModel):
    """A batch of rule settings, applied together or not at all."""

    entries: list[ConstraintSettingWrite]
