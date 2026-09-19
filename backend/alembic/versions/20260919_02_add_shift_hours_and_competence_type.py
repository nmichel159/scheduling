"""Add per-weekday shift hours and a competence type.

Revision ID: 20260919_02
Revises: 20260919_01
Create Date: 2026-09-19

Two independent additions, both with a default that describes what the
application did before them:

- ``competence_weekday_requirements.shift_hours`` -- how many hours a duty
  of this competence lasts on that weekday, per scenario. Existing rows get
  the four-hour default the editor now offers.
- ``competences.competence_type`` -- what kind of duty the competence is
  ("standard" or "surcharge"). Everything that exists today is standard.

Both columns are added with server defaults, so a database that is mid
rollout answers the old queries unchanged.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260919_02"
down_revision = "20260919_01"
branch_labels = None
depends_on = None


DEFAULT_SHIFT_HOURS = 4
DEFAULT_COMPETENCE_TYPE = "standard"


def _column_names(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    """Add both columns and fill them with the pre-migration behaviour."""
    if "shift_hours" not in _column_names("competence_weekday_requirements"):
        op.add_column(
            "competence_weekday_requirements",
            sa.Column(
                "shift_hours",
                sa.Float(),
                nullable=False,
                server_default=str(DEFAULT_SHIFT_HOURS),
            ),
        )

    if "competence_type" not in _column_names("competences"):
        op.add_column(
            "competences",
            sa.Column(
                "competence_type",
                sa.String(),
                nullable=False,
                server_default=DEFAULT_COMPETENCE_TYPE,
            ),
        )


def downgrade() -> None:
    """Drop both columns; the values they hold have nowhere else to live."""
    if "competence_type" in _column_names("competences"):
        with op.batch_alter_table("competences") as batch:
            batch.drop_column("competence_type")
    if "shift_hours" in _column_names("competence_weekday_requirements"):
        with op.batch_alter_table("competence_weekday_requirements") as batch:
            batch.drop_column("shift_hours")
