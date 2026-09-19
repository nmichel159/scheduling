"""Move the standard/surcharge distinction onto the weekday.

Whether a duty is paid with a surcharge is a property of the day it is
worked, not of the competence: the same competence is standard on a
Tuesday and surcharged on a Sunday. So the flag moves from
``competences.competence_type`` to
``competence_weekday_requirements.is_surcharge``, where it sits beside the
hours of that day.

Existing data has no per-day answer to migrate, so the backfill states the
rule the application defaults to: weekends (Saturday and Sunday) are
surcharged, the rest of the week is not. A competence that was marked
"surcharge" workplace-wide gets every one of its days flagged, which is
the reading closest to what it used to mean.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260919_03"
down_revision = "20260919_02"
branch_labels = None
depends_on = None


#: Weekdays a duty is surcharged on unless said otherwise (Monday is 0).
DEFAULT_SURCHARGE_WEEKDAYS = (5, 6)


def _column_names(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    """Add the per-weekday flag, seed it, and retire the old column."""
    bind = op.get_bind()

    if "is_surcharge" not in _column_names("competence_weekday_requirements"):
        op.add_column(
            "competence_weekday_requirements",
            sa.Column(
                "is_surcharge",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )
        weekdays = ", ".join(str(day) for day in DEFAULT_SURCHARGE_WEEKDAYS)
        bind.execute(
            sa.text(
                "UPDATE competence_weekday_requirements SET is_surcharge = true "
                f"WHERE weekday IN ({weekdays})"
            )
        )

    if "competence_type" in _column_names("competences"):
        bind.execute(
            sa.text(
                "UPDATE competence_weekday_requirements SET is_surcharge = true "
                "WHERE competence_id IN ("
                "  SELECT id FROM competences WHERE competence_type = 'surcharge'"
                ")"
            )
        )
        with op.batch_alter_table("competences") as batch:
            batch.drop_column("competence_type")


def downgrade() -> None:
    """Put the workplace-wide column back and drop the per-day flag.

    A competence counts as a surcharge one again when every staffed day of
    it was flagged, which is the only shape the old column could express.
    """
    bind = op.get_bind()

    if "competence_type" not in _column_names("competences"):
        op.add_column(
            "competences",
            sa.Column(
                "competence_type",
                sa.String(),
                nullable=False,
                server_default="standard",
            ),
        )
        bind.execute(
            sa.text(
                "UPDATE competences SET competence_type = 'surcharge' WHERE id IN ("
                "  SELECT competence_id FROM competence_weekday_requirements"
                "  GROUP BY competence_id"
                "  HAVING MIN(CASE WHEN is_surcharge THEN 1 ELSE 0 END) = 1"
                ")"
            )
        )

    if "is_surcharge" in _column_names("competence_weekday_requirements"):
        with op.batch_alter_table("competence_weekday_requirements") as batch:
            batch.drop_column("is_surcharge")
