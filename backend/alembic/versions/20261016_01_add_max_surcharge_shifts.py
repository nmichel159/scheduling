"""How many surcharged duties a month an employee wants at most.

It sits beside ``max_shifts_per_month`` and follows the same rules: it is
the employee's own wish, nullable because "no opinion" is the default, and
the solver applies it as strictly as the workplace applies the duty wish.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261016_01"
down_revision = "20260928_01"
branch_labels = None
depends_on = None

COLUMN = "max_surcharge_shifts_per_month"


def _has_column() -> bool:
    inspector = sa.inspect(op.get_bind())
    return COLUMN in {column["name"] for column in inspector.get_columns("users")}


def upgrade() -> None:
    if not _has_column():
        op.add_column("users", sa.Column(COLUMN, sa.Integer(), nullable=True))


def downgrade() -> None:
    if _has_column():
        op.drop_column("users", COLUMN)
