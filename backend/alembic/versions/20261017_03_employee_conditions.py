"""An employee's standing conditions and the scheduler's duty cap.

Three things arrive together:

* ``users.weekday_preferences`` -- for each weekday, Monday first, whether
  the employee wants it, would rather not work it, or does not mind. NULL
  is "does not mind" every day.
* ``users.scheduler_weekday_preferences`` -- the same seven answers set by
  the scheduler; where the scheduler answered, it outranks the employee.
* ``users.scheduler_max_shifts_per_month`` -- the most duties a month the
  scheduler allows. It outranks whatever the employee wished for.
* ``monthly_shift_wishes`` -- the employee's duty wish for one month, which
  outranks their standing wish in ``users.max_shifts_per_month``.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261017_03"
down_revision = "20261017_02"
branch_labels = None
depends_on = None

TABLE = "monthly_shift_wishes"


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _user_columns() -> set[str]:
    return {column["name"] for column in _inspector().get_columns("users")}


def upgrade() -> None:
    columns = _user_columns()
    if "weekday_preferences" not in columns:
        op.add_column("users", sa.Column("weekday_preferences", sa.String(7), nullable=True))
    if "scheduler_weekday_preferences" not in columns:
        op.add_column(
            "users", sa.Column("scheduler_weekday_preferences", sa.String(7), nullable=True)
        )
    if "scheduler_max_shifts_per_month" not in columns:
        op.add_column(
            "users",
            sa.Column("scheduler_max_shifts_per_month", sa.Integer(), nullable=True),
        )
    if TABLE not in set(_inspector().get_table_names()):
        op.create_table(
            TABLE,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("year", sa.Integer(), nullable=False),
            sa.Column("month", sa.Integer(), nullable=False),
            sa.Column("max_shifts_per_month", sa.Integer(), nullable=False),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
            ),
            sa.UniqueConstraint("user_id", "year", "month", name="uq_monthly_shift_wishes_month"),
            sa.CheckConstraint("month >= 1 AND month <= 12", name="ck_monthly_shift_wishes_month"),
        )


def downgrade() -> None:
    if TABLE in set(_inspector().get_table_names()):
        op.drop_table(TABLE)
    columns = _user_columns()
    for column in ("scheduler_max_shifts_per_month", "scheduler_weekday_preferences", "weekday_preferences"):
        if column in columns:
            op.drop_column("users", column)
