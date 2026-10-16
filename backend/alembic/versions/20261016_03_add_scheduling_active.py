"""Whether the generator may give an employee duties.

An employee on long leave stays in the workplace with their competences
and wishes, but is switched off for scheduling. Every existing employee
starts switched on, so a database upgraded with this column plans exactly
as it did before.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261016_03"
down_revision = "20261016_02"
branch_labels = None
depends_on = None

COLUMN = "scheduling_active"


def _has_column() -> bool:
    inspector = sa.inspect(op.get_bind())
    return COLUMN in {column["name"] for column in inspector.get_columns("users")}


def upgrade() -> None:
    if not _has_column():
        op.add_column(
            "users",
            sa.Column(COLUMN, sa.Boolean(), nullable=False, server_default=sa.true()),
        )


def downgrade() -> None:
    if _has_column():
        op.drop_column("users", COLUMN)
