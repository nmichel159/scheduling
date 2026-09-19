"""Days of rest: the special-day calendar and the eighth day slot.

Two changes that only make sense together.

``special_days`` holds one workplace's *exceptions* to the public-holiday
calendar. The calendar itself is not stored: the ``holidays`` library
computes Slovakia's public holidays, including the 2024 split between the
days of rest and the state holidays that are worked, so there is nothing to
migrate and nothing to maintain per year. A row here says a workplace
closes on a day the library works, or staffs a day the library rests.

``competence_weekday_requirements`` gains an eighth slot for those days.
Weekday 7 is not a weekday: a date the calendar calls a day of rest is
staffed from that slot whatever weekday it falls on, so a holiday on a
Tuesday is staffed like a holiday. Existing scenarios have no answer for
it, so the backfill states the reading closest to what they meant --
whatever they staff on a Sunday, surcharged, a day of rest being surcharged
by definition.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260919_04"
down_revision = "20260919_03"
branch_labels = None
depends_on = None

#: The slot a day of rest is staffed from.
SPECIAL_DAY_SLOT = 7

WEEKDAY_CHECK = "ck_competence_weekday_requirement_weekday"


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _check_constraint_names(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {
        constraint["name"]
        for constraint in inspector.get_check_constraints(table)
    }


def _set_weekday_bound(condition: str) -> None:
    """Rewrite the weekday range check to ``condition``."""
    had_check = WEEKDAY_CHECK in _check_constraint_names(
        "competence_weekday_requirements"
    )
    with op.batch_alter_table("competence_weekday_requirements") as batch:
        if had_check:
            batch.drop_constraint(WEEKDAY_CHECK, type_="check")
        batch.create_check_constraint(WEEKDAY_CHECK, condition)


def upgrade() -> None:
    """Create the override table and open the eighth requirement slot."""
    bind = op.get_bind()

    if "special_days" not in _table_names():
        op.create_table(
            "special_days",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "ambulance_id",
                sa.Integer(),
                sa.ForeignKey("ambulances.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("day", sa.Date(), nullable=False),
            sa.Column(
                "is_rest_day",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
            sa.Column("name", sa.String(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
            ),
            sa.UniqueConstraint(
                "ambulance_id", "day", name="uq_special_days_ambulance_day"
            ),
        )
        op.create_index(
            "ix_special_days_ambulance_day", "special_days", ["ambulance_id", "day"]
        )
        op.create_index("ix_special_days_id", "special_days", ["id"])

    # The slot has to be allowed before any row can carry it. Batch mode
    # because SQLite cannot alter a constraint in place.
    _set_weekday_bound("weekday >= 0 AND weekday <= 7")

    # Every (scenario, competence) pair that has a Sunday but no special day
    # gets Sunday's parameters, surcharged.
    bind.execute(
        sa.text(
            "INSERT INTO competence_weekday_requirements "
            "(competence_id, scenario_id, weekday, required_count, "
            " recovery_days, shift_hours, is_surcharge) "
            "SELECT sunday.competence_id, sunday.scenario_id, :slot, "
            "       sunday.required_count, sunday.recovery_days, "
            "       sunday.shift_hours, true "
            "FROM competence_weekday_requirements AS sunday "
            "WHERE sunday.weekday = 6 "
            "  AND NOT EXISTS ("
            "    SELECT 1 FROM competence_weekday_requirements AS special "
            "    WHERE special.competence_id = sunday.competence_id "
            "      AND special.scenario_id = sunday.scenario_id "
            "      AND special.weekday = :slot"
            "  )"
        ),
        {"slot": SPECIAL_DAY_SLOT},
    )


def downgrade() -> None:
    """Drop the special-day rows, the table, and close the slot again."""
    bind = op.get_bind()

    bind.execute(
        sa.text(
            "DELETE FROM competence_weekday_requirements WHERE weekday = :slot"
        ),
        {"slot": SPECIAL_DAY_SLOT},
    )

    _set_weekday_bound("weekday >= 0 AND weekday <= 6")

    if "special_days" in _table_names():
        op.drop_index("ix_special_days_id", table_name="special_days")
        op.drop_index("ix_special_days_ambulance_day", table_name="special_days")
        op.drop_table("special_days")
