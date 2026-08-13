"""Create and backfill weekday staffing requirements.

Revision ID: 20260812_01
Revises: 20260811_01
Create Date: 2026-08-12
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260812_01"
down_revision = "20260811_01"
branch_labels = None
depends_on = None


def _weekday_requirements_table() -> sa.TableClause:
    """Return a lightweight table definition used by the data migration."""
    return sa.table(
        "competence_weekday_requirements",
        sa.column("competence_id", sa.Integer()),
        sa.column("weekday", sa.Integer()),
        sa.column("required_count", sa.Integer()),
    )


def upgrade() -> None:
    """Create weekday requirements and backfill every missing weekday."""
    connection = op.get_bind()
    inspector = sa.inspect(connection)

    if not inspector.has_table("competence_weekday_requirements"):
        op.create_table(
            "competence_weekday_requirements",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("competence_id", sa.Integer(), nullable=False),
            sa.Column("weekday", sa.Integer(), nullable=False),
            sa.Column("required_count", sa.Integer(), nullable=False),
            sa.CheckConstraint(
                "required_count >= 0",
                name="ck_competence_weekday_requirement_count",
            ),
            sa.CheckConstraint(
                "weekday >= 0 AND weekday <= 6",
                name="ck_competence_weekday_requirement_weekday",
            ),
            sa.ForeignKeyConstraint(
                ["competence_id"],
                ["competences.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "competence_id",
                "weekday",
                name="uq_competence_weekday_requirement",
            ),
        )
        op.create_index(
            "ix_competence_weekday_requirements_id",
            "competence_weekday_requirements",
            ["id"],
        )
        op.create_index(
            "ix_competence_weekday_requirements_competence_id",
            "competence_weekday_requirements",
            ["competence_id"],
        )

    competences = sa.table(
        "competences",
        sa.column("id", sa.Integer()),
        sa.column("required_count", sa.Integer()),
    )
    weekday_requirements = _weekday_requirements_table()

    existing_rows = {
        (row.competence_id, row.weekday)
        for row in connection.execute(
            sa.select(
                weekday_requirements.c.competence_id,
                weekday_requirements.c.weekday,
            )
        )
    }
    missing_rows = [
        {
            "competence_id": row.id,
            "weekday": weekday,
            "required_count": max(row.required_count, 0),
        }
        for row in connection.execute(
            sa.select(competences.c.id, competences.c.required_count)
        )
        for weekday in range(7)
        if (row.id, weekday) not in existing_rows
    ]
    if missing_rows:
        op.bulk_insert(weekday_requirements, missing_rows)


def downgrade() -> None:
    """Remove weekday staffing requirements."""
    op.drop_index(
        "ix_competence_weekday_requirements_competence_id",
        table_name="competence_weekday_requirements",
    )
    op.drop_index(
        "ix_competence_weekday_requirements_id",
        table_name="competence_weekday_requirements",
    )
    op.drop_table("competence_weekday_requirements")
