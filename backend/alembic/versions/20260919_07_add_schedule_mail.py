"""Where a workplace's schedule is mailed, and what was mailed when.

A clinic reads the finished monthly schedule in a mailbox, not in this
application -- nobody there logs in. The addresses are therefore their own
per-workplace list rather than something derived from the employees, and
every send attempt is written down, the failed ones too: a schedule the
clinic plans around is worth being able to say when it left and to whom.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260919_07"
down_revision = "20260919_06"
branch_labels = None
depends_on = None

RECIPIENTS = "schedule_mail_recipients"
DISPATCHES = "schedule_mail_dispatches"


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    tables = _tables()

    if RECIPIENTS not in tables:
        op.create_table(
            RECIPIENTS,
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column(
                "ambulance_id",
                sa.Integer(),
                sa.ForeignKey("ambulances.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("email", sa.String(), nullable=False),
            sa.Column("label", sa.String(), nullable=True),
            sa.Column(
                "is_active",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
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
                "email",
                name="uq_schedule_mail_recipients_ambulance_email",
            ),
        )
        op.create_index(
            "ix_schedule_mail_recipients_ambulance_active",
            RECIPIENTS,
            ["ambulance_id", "is_active"],
        )

    if DISPATCHES not in tables:
        op.create_table(
            DISPATCHES,
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column(
                "ambulance_id",
                sa.Integer(),
                sa.ForeignKey("ambulances.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("month", sa.Integer(), nullable=False),
            sa.Column("year", sa.Integer(), nullable=False),
            sa.Column(
                "sent_by_user_id",
                sa.Integer(),
                sa.ForeignKey("users.id"),
                nullable=True,
            ),
            sa.Column("recipients", sa.Text(), nullable=False, server_default=""),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column(
                "entry_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
            ),
        )
        op.create_index(
            "ix_schedule_mail_dispatches_ambulance_period",
            DISPATCHES,
            ["ambulance_id", "year", "month"],
        )


def downgrade() -> None:
    tables = _tables()
    if DISPATCHES in tables:
        op.drop_index("ix_schedule_mail_dispatches_ambulance_period", table_name=DISPATCHES)
        op.drop_table(DISPATCHES)
    if RECIPIENTS in tables:
        op.drop_index("ix_schedule_mail_recipients_ambulance_active", table_name=RECIPIENTS)
        op.drop_table(RECIPIENTS)
