"""Add indexes for high-volume endpoint access paths.

Revision ID: 20260813_01
Revises: 20260812_01
Create Date: 2026-08-13
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260813_01"
down_revision = "20260812_01"
branch_labels = None
depends_on = None


INDEX_DEFINITIONS = (
    (
        "ix_schedules_user_active_work_date",
        "schedules",
        ("user_id", "is_active", "work_date"),
    ),
    (
        "ix_schedules_ambulance_active_work_date",
        "schedules",
        ("ambulance_id", "is_active", "work_date"),
    ),
    (
        "ix_unavailabilities_user_active_date",
        "unavailabilities",
        ("user_id", "is_active", "date_absent", "id"),
    ),
    (
        "ix_user_roles_role_user",
        "user_roles",
        ("role_id", "user_id"),
    ),
    (
        "ix_user_ambulances_ambulance_active_user",
        "user_ambulances",
        ("ambulance_id", "is_active", "user_id"),
    ),
    (
        "ix_user_competences_competence_active_user",
        "user_competences",
        ("competence_id", "is_active", "user_id"),
    ),
    (
        "ix_competences_ambulance_active_name",
        "competences",
        ("ambulance_id", "is_active", "name"),
    ),
    (
        "ix_ambulances_manager_active_name",
        "ambulances",
        ("managed_by_user_id", "is_active", "name"),
    ),
    (
        "ix_ambulances_active_urgent_name",
        "ambulances",
        ("is_active", "isurgent", "name"),
    ),
    (
        "ix_users_active_full_name_email",
        "users",
        ("is_active", "full_name", "email"),
    ),
)


def _schema_state() -> tuple[set[str], dict[str, set[str]], dict[str, set[str]]]:
    """Return tables, columns, and index names visible to this migration."""
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    columns = {
        table: {column["name"] for column in inspector.get_columns(table)}
        for table in tables
    }
    indexes = {
        table: {index["name"] for index in inspector.get_indexes(table)}
        for table in tables
    }
    return tables, columns, indexes


def upgrade() -> None:
    """Create every applicable index without assuming a complete legacy schema."""
    tables, columns, indexes = _schema_state()
    for name, table, index_columns in INDEX_DEFINITIONS:
        if table not in tables:
            continue
        if not set(index_columns).issubset(columns[table]):
            continue
        if name in indexes[table]:
            continue
        op.create_index(name, table, list(index_columns), unique=False)
        indexes[table].add(name)


def downgrade() -> None:
    """Drop only indexes that are present in the current schema."""
    tables, _columns, indexes = _schema_state()
    for name, table, _index_columns in reversed(INDEX_DEFINITIONS):
        if table in tables and name in indexes[table]:
            op.drop_index(name, table_name=table)
            indexes[table].remove(name)
