"""Add race-safe uniqueness indexes for endpoint writes.

Revision ID: 20260813_02
Revises: 20260813_01
Create Date: 2026-08-13

The migration never rewrites or deletes rows. If legacy duplicates exist, it
fails before creating the affected index and reports the first conflicting
key so the data can be reviewed explicitly.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260813_02"
down_revision = "20260813_01"
branch_labels = None
depends_on = None


UNIQUE_INDEX_DEFINITIONS = (
    (
        "uq_schedules_entry",
        "schedules",
        ("user_id", "ambulance_id", "competence_id", "work_date"),
        False,
    ),
    (
        "uq_unavailabilities_active_user_date",
        "unavailabilities",
        ("user_id", "date_absent"),
        True,
    ),
    (
        "uq_competences_active_ambulance_name",
        "competences",
        ("ambulance_id", "name"),
        True,
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


def _first_duplicate_key(
    table_name: str,
    key_columns: tuple[str, ...],
    active_only: bool,
) -> tuple[object, ...] | None:
    """Return the first duplicate natural key without changing any row."""
    bind = op.get_bind()
    table = sa.Table(table_name, sa.MetaData(), autoload_with=bind)
    selected_columns = [table.c[column] for column in key_columns]
    statement = (
        sa.select(*selected_columns)
        .group_by(*selected_columns)
        .having(sa.func.count() > 1)
        .limit(1)
    )
    if active_only:
        statement = statement.where(table.c.is_active.is_(True))
    row = bind.execute(statement).first()
    return tuple(row) if row is not None else None


def upgrade() -> None:
    """Preflight every key and create each applicable unique index."""
    tables, columns, indexes = _schema_state()
    for name, table, key_columns, active_only in UNIQUE_INDEX_DEFINITIONS:
        required_columns = set(key_columns)
        if active_only:
            required_columns.add("is_active")
        if table not in tables or not required_columns.issubset(columns[table]):
            continue
        if name in indexes[table]:
            continue

        duplicate_key = _first_duplicate_key(table, key_columns, active_only)
        if duplicate_key is not None:
            raise RuntimeError(
                f"Cannot create {name}: duplicate key {duplicate_key!r} "
                f"exists in {table}. No rows were changed."
            )

        options: dict[str, object] = {"unique": True}
        if active_only:
            options.update(
                postgresql_where=sa.text("is_active IS TRUE"),
                sqlite_where=sa.text("is_active = 1"),
            )
        op.create_index(name, table, list(key_columns), **options)
        indexes[table].add(name)


def downgrade() -> None:
    """Drop only uniqueness indexes that are present."""
    tables, _columns, indexes = _schema_state()
    for name, table, _key_columns, _active_only in reversed(
        UNIQUE_INDEX_DEFINITIONS
    ):
        if table in tables and name in indexes[table]:
            op.drop_index(name, table_name=table)
            indexes[table].remove(name)
