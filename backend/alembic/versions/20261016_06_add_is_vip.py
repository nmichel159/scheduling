"""Whether an employee is marked as a VIP.

Every existing employee starts unmarked.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261016_06"
down_revision = "20261016_05"
branch_labels = None
depends_on = None

COLUMN = "is_vip"


def _has_column() -> bool:
    inspector = sa.inspect(op.get_bind())
    return COLUMN in {column["name"] for column in inspector.get_columns("users")}


def upgrade() -> None:
    if not _has_column():
        op.add_column(
            "users",
            sa.Column(COLUMN, sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade() -> None:
    if _has_column():
        op.drop_column("users", COLUMN)
