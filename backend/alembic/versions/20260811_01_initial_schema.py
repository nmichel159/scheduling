"""Create the baseline scheduling schema.

Revision ID: 20260811_01
Revises:
Create Date: 2026-08-13

Existing installations originally created these tables through SQLAlchemy.
The table guards let an unversioned legacy database adopt Alembic without
rewriting any rows, while new installations are migration-only.
"""

from __future__ import annotations

from collections.abc import Callable

from alembic import op
import sqlalchemy as sa


revision = "20260811_01"
down_revision = None
branch_labels = None
depends_on = None


def _create_if_missing(table_name: str, create_table: Callable[[], None]) -> None:
    """Create one legacy baseline table only when it is absent."""
    if not sa.inspect(op.get_bind()).has_table(table_name):
        create_table()


def _create_users() -> None:
    """Create the users table and its original lookup indexes."""
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("full_name", sa.String(), nullable=True),
        sa.Column("auth_token", sa.String(length=64), nullable=True),
        sa.Column("auth_token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("login_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_id", "users", ["id"])
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_auth_token", "users", ["auth_token"])


def _create_roles() -> None:
    """Create the role codebook table."""
    op.create_table(
        "roles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index("ix_roles_id", "roles", ["id"])


def _create_ambulances() -> None:
    """Create the ambulance table."""
    op.create_table(
        "ambulances",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("managed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("isurgent", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(["managed_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ambulances_id", "ambulances", ["id"])


def _create_competences() -> None:
    """Create the competence table."""
    op.create_table(
        "competences",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("required_count", sa.Integer(), nullable=False),
        sa.Column("ambulance_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(["ambulance_id"], ["ambulances.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_competences_id", "competences", ["id"])


def _create_audit_logs() -> None:
    """Create the audit log table."""
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("entity_id", sa.String(), nullable=False),
        sa.Column("changes", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_logs_id", "audit_logs", ["id"])


def _create_seed_versions() -> None:
    """Create deterministic demo seed version tracking."""
    op.create_table(
        "seed_versions",
        sa.Column("profile", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("profile"),
    )


def _create_user_roles() -> None:
    """Create the user-to-role association table."""
    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id", "role_id"),
    )


def _create_user_ambulances() -> None:
    """Create the user-to-ambulance association table."""
    op.create_table(
        "user_ambulances",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("ambulance_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(["ambulance_id"], ["ambulances.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id", "ambulance_id"),
    )


def _create_user_competences() -> None:
    """Create the user-to-competence association table."""
    op.create_table(
        "user_competences",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("competence_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(["competence_id"], ["competences.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id", "competence_id"),
    )


def _create_unavailabilities() -> None:
    """Create employee unavailability records."""
    op.create_table(
        "unavailabilities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("date_absent", sa.Date(), nullable=False),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_unavailabilities_id", "unavailabilities", ["id"])


def _create_schedules() -> None:
    """Create persisted schedule entries."""
    op.create_table(
        "schedules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("ambulance_id", sa.Integer(), nullable=False),
        sa.Column("competence_id", sa.Integer(), nullable=False),
        sa.Column("work_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(["ambulance_id"], ["ambulances.id"]),
        sa.ForeignKeyConstraint(["competence_id"], ["competences.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_schedules_id", "schedules", ["id"])


def upgrade() -> None:
    """Create missing baseline tables without touching existing data."""
    for table_name, create_table in (
        ("users", _create_users),
        ("roles", _create_roles),
        ("ambulances", _create_ambulances),
        ("competences", _create_competences),
        ("audit_logs", _create_audit_logs),
        ("seed_versions", _create_seed_versions),
        ("user_roles", _create_user_roles),
        ("user_ambulances", _create_user_ambulances),
        ("user_competences", _create_user_competences),
        ("unavailabilities", _create_unavailabilities),
        ("schedules", _create_schedules),
    ):
        _create_if_missing(table_name, create_table)


def downgrade() -> None:
    """Drop the complete baseline schema in reverse dependency order."""
    for table_name in (
        "schedules",
        "unavailabilities",
        "user_competences",
        "user_ambulances",
        "user_roles",
        "seed_versions",
        "audit_logs",
        "competences",
        "ambulances",
        "roles",
        "users",
    ):
        if sa.inspect(op.get_bind()).has_table(table_name):
            op.drop_table(table_name)
