"""How strictly, or at what price, each workplace applies each scheduling rule.

The rules and their defaults are code. What a workplace can change is
whether a switchable rule is strict or only penalized, and what a breach of
a penalized one costs; a row exists only where it chose something other
than the default, so a workplace with no rows is scheduled exactly as before.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260928_01"
down_revision = "20260919_07"
branch_labels = None
depends_on = None

TABLE = "constraint_settings"


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if TABLE in _tables():
        return
    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column(
            "ambulance_id",
            sa.Integer(),
            sa.ForeignKey("ambulances.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("is_strict", sa.Boolean(), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
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
            "ambulance_id",
            "code",
            name="uq_constraint_settings_ambulance_code",
        ),
    )


def downgrade() -> None:
    if TABLE in _tables():
        op.drop_table(TABLE)
