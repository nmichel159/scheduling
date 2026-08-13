"""Add schedule approval and automatic monthly generation run tracking.

Revision ID: 20260813_03
Revises: 20260813_02
Create Date: 2026-08-13
"""

from alembic import op
import sqlalchemy as sa


revision = "20260813_03"
down_revision = "20260813_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add approval state while preserving visibility of existing schedules."""
    op.add_column(
        "schedules",
        sa.Column(
            "is_approved",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.execute(sa.text("UPDATE schedules SET is_approved = true"))

    op.create_table(
        "automatic_schedule_generation_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("target_year", sa.Integer(), nullable=False),
        sa.Column("target_month", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "target_month >= 1 AND target_month <= 12",
            name="ck_auto_schedule_runs_target_month",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "target_year",
            "target_month",
            name="uq_auto_schedule_runs_target_period",
        ),
    )
    op.create_index(
        op.f("ix_automatic_schedule_generation_runs_id"),
        "automatic_schedule_generation_runs",
        ["id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove automatic run tracking and schedule approval state."""
    op.drop_index(
        op.f("ix_automatic_schedule_generation_runs_id"),
        table_name="automatic_schedule_generation_runs",
    )
    op.drop_table("automatic_schedule_generation_runs")
    op.drop_column("schedules", "is_approved")
