"""Which kind of duty an employee would rather be given.

The monthly wish says *how many* duties an employee wants; it never said
*which kind*. Surcharged duties (weekends, days of rest) are the ones people
actually have an opinion about -- some chase them, some avoid them -- so the
preference is stored beside the wish, on the user, because it follows the
person and not the workplace.

Three values: ``surcharge``, ``standard`` and ``any``. ``any`` is the
default and means no opinion, which is why the column is not nullable: an
employee always has one of the three, even if it is "I do not mind".
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260919_06"
down_revision = "20260919_05"
branch_labels = None
depends_on = None

COLUMN = "shift_preference"


def _has_column() -> bool:
    inspector = sa.inspect(op.get_bind())
    return COLUMN in {column["name"] for column in inspector.get_columns("users")}


def upgrade() -> None:
    if not _has_column():
        op.add_column(
            "users",
            sa.Column(
                COLUMN,
                sa.String(length=16),
                nullable=False,
                server_default="any",
            ),
        )


def downgrade() -> None:
    if _has_column():
        op.drop_column("users", COLUMN)
