"""How many duties a month an employee wants at most.

The restriction calendar says which days suit an employee; it never said
how many of them they are willing to take. The wish lives on the user
because it is the employee's own preference, not a property of any one
workplace, and it is nullable because "no opinion" is the default and is
different from wishing for zero duties.

It is a wish, not a cap: the solver pays a penalty for every duty above
it instead of refusing to staff the month.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260919_05"
down_revision = "20260919_04"
branch_labels = None
depends_on = None

COLUMN = "max_shifts_per_month"


def _has_column() -> bool:
    inspector = sa.inspect(op.get_bind())
    return COLUMN in {column["name"] for column in inspector.get_columns("users")}


def upgrade() -> None:
    if not _has_column():
        op.add_column("users", sa.Column(COLUMN, sa.Integer(), nullable=True))


def downgrade() -> None:
    if _has_column():
        op.drop_column("users", COLUMN)
