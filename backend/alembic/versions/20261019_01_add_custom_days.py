"""Custom days: a workplace's own kinds of day, placed on chosen dates.

``custom_days`` names one kind of day of one workplace,
``custom_day_requirements`` says what each competence needs on it and
``custom_day_dates`` places it on a date, which is then staffed from it
instead of from its weekday or the day of rest.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261019_01"
down_revision = "20261017_03"
branch_labels = None
depends_on = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    ]


def upgrade() -> None:
    tables = _table_names()
    if "custom_days" not in tables:
        op.create_table(
            "custom_days",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "ambulance_id",
                sa.Integer(),
                sa.ForeignKey("ambulances.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("name", sa.String(), nullable=False),
            *_timestamps(),
        )
        op.create_index("ix_custom_days_id", "custom_days", ["id"])
        op.create_index("ix_custom_days_ambulance", "custom_days", ["ambulance_id"])

    if "custom_day_requirements" not in tables:
        op.create_table(
            "custom_day_requirements",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "custom_day_id",
                sa.Integer(),
                sa.ForeignKey("custom_days.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "competence_id",
                sa.Integer(),
                sa.ForeignKey("competences.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("required_count", sa.Integer(), nullable=False),
            sa.Column(
                "recovery_days", sa.Integer(), nullable=False, server_default="1"
            ),
            sa.Column("shift_hours", sa.Float(), nullable=False, server_default="4"),
            sa.Column(
                "is_surcharge", sa.Boolean(), nullable=False, server_default=sa.false()
            ),
            sa.UniqueConstraint(
                "custom_day_id", "competence_id", name="uq_custom_day_requirement"
            ),
            sa.CheckConstraint(
                "required_count >= 0", name="ck_custom_day_requirement_count"
            ),
            sa.CheckConstraint(
                "recovery_days >= 0 AND recovery_days <= 6",
                name="ck_custom_day_requirement_recovery",
            ),
            sa.CheckConstraint(
                "shift_hours >= 0 AND shift_hours <= 24",
                name="ck_custom_day_requirement_shift_hours",
            ),
        )
        op.create_index(
            "ix_custom_day_requirements_id", "custom_day_requirements", ["id"]
        )
        op.create_index(
            "ix_custom_day_requirements_custom_day_id",
            "custom_day_requirements",
            ["custom_day_id"],
        )
        op.create_index(
            "ix_custom_day_requirements_competence_id",
            "custom_day_requirements",
            ["competence_id"],
        )

    if "custom_day_dates" not in tables:
        op.create_table(
            "custom_day_dates",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "ambulance_id",
                sa.Integer(),
                sa.ForeignKey("ambulances.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("day", sa.Date(), nullable=False),
            sa.Column(
                "custom_day_id",
                sa.Integer(),
                sa.ForeignKey("custom_days.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.UniqueConstraint(
                "ambulance_id", "day", name="uq_custom_day_dates_ambulance_day"
            ),
        )
        op.create_index("ix_custom_day_dates_id", "custom_day_dates", ["id"])
        op.create_index(
            "ix_custom_day_dates_ambulance_day",
            "custom_day_dates",
            ["ambulance_id", "day"],
        )
        op.create_index(
            "ix_custom_day_dates_custom_day_id", "custom_day_dates", ["custom_day_id"]
        )


def downgrade() -> None:
    tables = _table_names()
    if "custom_day_dates" in tables:
        op.drop_table("custom_day_dates")
    if "custom_day_requirements" in tables:
        op.drop_table("custom_day_requirements")
    if "custom_days" in tables:
        op.drop_table("custom_days")
