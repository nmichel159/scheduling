"""When employees may fill in their restrictions for a month.

One settings row holds the reminder and lock days the scheduler chose; one
row per month records a lock or unlock pressed by hand and the reminder the
server sent. With no rows the code defaults apply, so an existing database
starts on the 14th/15th without any backfill.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261016_02"
down_revision = "20261016_01"
branch_labels = None
depends_on = None

SETTINGS = "availability_settings"
PERIODS = "availability_periods"


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    tables = _tables()
    if SETTINGS not in tables:
        op.create_table(
            SETTINGS,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("reminder_day", sa.Integer(), nullable=False),
            sa.Column("lock_day", sa.Integer(), nullable=False),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
            ),
            sa.CheckConstraint(
                "reminder_day >= 1 AND reminder_day < lock_day AND lock_day <= 28",
                name="ck_availability_settings_days",
            ),
        )
    if PERIODS not in tables:
        op.create_table(
            PERIODS,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("year", sa.Integer(), nullable=False),
            sa.Column("month", sa.Integer(), nullable=False),
            sa.Column("is_locked", sa.Boolean(), nullable=True),
            sa.Column("reminder_sent_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("reminder_status", sa.String(32), nullable=True),
            sa.Column("reminder_recipients", sa.Integer(), nullable=True),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
            ),
            sa.UniqueConstraint("year", "month", name="uq_availability_periods_month"),
            sa.CheckConstraint(
                "month >= 1 AND month <= 12",
                name="ck_availability_periods_month",
            ),
        )


def downgrade() -> None:
    tables = _tables()
    if PERIODS in tables:
        op.drop_table(PERIODS)
    if SETTINGS in tables:
        op.drop_table(SETTINGS)
