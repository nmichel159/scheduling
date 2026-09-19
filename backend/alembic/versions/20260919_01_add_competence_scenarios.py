"""Introduce competence scenarios and per-weekday recovery days.

Revision ID: 20260919_01
Revises: 20260813_03
Create Date: 2026-09-19

A workplace's competences keep one set of weekday parameters per scenario.
Every workplace that already has competences gets one scenario, named
"Scenár 1" and selected, and its existing weekday rows are adopted by that
scenario unchanged -- so the numbers a manager configured before this
migration are exactly what their first scenario contains.

The migration never deletes a weekday row. It only adds the two columns,
fills them in, and widens the natural key to include the scenario.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260919_01"
down_revision = "20260813_03"
branch_labels = None
depends_on = None


DEFAULT_SCENARIO_NAME = "Scenár 1"
DEFAULT_RECOVERY_DAYS = 1


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _column_names(table: str) -> set[str]:
    return {column["name"] for column in _inspector().get_columns(table)}


def _constraint_names(table: str) -> set[str]:
    inspector = _inspector()
    names = {index["name"] for index in inspector.get_indexes(table)}
    names.update(
        constraint["name"]
        for constraint in inspector.get_unique_constraints(table)
    )
    return {name for name in names if name}


def _scenarios_table() -> sa.TableClause:
    """Lightweight definition used by this migration's data statements."""
    return sa.table(
        "competence_scenarios",
        sa.column("id", sa.Integer()),
        sa.column("name", sa.String()),
        sa.column("ambulance_id", sa.Integer()),
        sa.column("is_selected", sa.Boolean()),
        sa.column("is_active", sa.Boolean()),
    )


def _requirements_table() -> sa.TableClause:
    """Lightweight definition used by this migration's data statements."""
    return sa.table(
        "competence_weekday_requirements",
        sa.column("id", sa.Integer()),
        sa.column("competence_id", sa.Integer()),
        sa.column("scenario_id", sa.Integer()),
    )


def _competences_table() -> sa.TableClause:
    """Lightweight definition used by this migration's data statements."""
    return sa.table(
        "competences",
        sa.column("id", sa.Integer()),
        sa.column("ambulance_id", sa.Integer()),
    )


def _selected_scenario_ids() -> sa.Select:
    """One scenario id per workplace: the oldest active one."""
    scenarios = _scenarios_table()
    return (
        sa.select(sa.func.min(scenarios.c.id))
        .where(scenarios.c.is_active.is_(True))
        .group_by(scenarios.c.ambulance_id)
    )


def upgrade() -> None:
    """Create scenarios, give every weekday row one, and add recovery days."""
    connection = op.get_bind()
    inspector = _inspector()

    if not inspector.has_table("competence_scenarios"):
        op.create_table(
            "competence_scenarios",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("ambulance_id", sa.Integer(), nullable=False),
            sa.Column(
                "is_selected",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=True),
            sa.ForeignKeyConstraint(["ambulance_id"], ["ambulances.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_competence_scenarios_id", "competence_scenarios", ["id"]
        )
        op.create_index(
            "ix_competence_scenarios_ambulance_active",
            "competence_scenarios",
            ["ambulance_id", "is_active"],
        )
        op.create_index(
            "uq_competence_scenarios_active_ambulance_name",
            "competence_scenarios",
            ["ambulance_id", "name"],
            unique=True,
            postgresql_where=sa.text("is_active IS TRUE"),
            sqlite_where=sa.text("is_active = 1"),
        )

    requirement_columns = _column_names("competence_weekday_requirements")
    if "recovery_days" not in requirement_columns:
        op.add_column(
            "competence_weekday_requirements",
            sa.Column(
                "recovery_days",
                sa.Integer(),
                nullable=False,
                server_default=str(DEFAULT_RECOVERY_DAYS),
            ),
        )
    if "scenario_id" not in requirement_columns:
        op.add_column(
            "competence_weekday_requirements",
            sa.Column("scenario_id", sa.Integer(), nullable=True),
        )

    _create_default_scenarios(connection)
    _attach_requirements_to_scenarios(connection)

    had_old_key = (
        "uq_competence_weekday_requirement"
        in _constraint_names("competence_weekday_requirements")
    )
    with op.batch_alter_table("competence_weekday_requirements") as batch:
        if had_old_key:
            batch.drop_constraint(
                "uq_competence_weekday_requirement", type_="unique"
            )
        batch.alter_column(
            "scenario_id", existing_type=sa.Integer(), nullable=False
        )
        batch.create_foreign_key(
            "fk_competence_weekday_requirements_scenario",
            "competence_scenarios",
            ["scenario_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_unique_constraint(
            "uq_competence_weekday_requirement",
            ["scenario_id", "competence_id", "weekday"],
        )
    if "ix_competence_weekday_requirements_scenario_id" not in _constraint_names(
        "competence_weekday_requirements"
    ):
        op.create_index(
            "ix_competence_weekday_requirements_scenario_id",
            "competence_weekday_requirements",
            ["scenario_id"],
        )


def _create_default_scenarios(connection: sa.engine.Connection) -> None:
    """Give every workplace that lacks one a selected default scenario."""
    scenarios = _scenarios_table()
    ambulances = sa.table(
        "ambulances",
        sa.column("id", sa.Integer()),
    )

    covered = {
        row.ambulance_id
        for row in connection.execute(sa.select(scenarios.c.ambulance_id))
    }
    missing = [
        {
            "name": DEFAULT_SCENARIO_NAME,
            "ambulance_id": row.id,
            "is_selected": True,
            "is_active": True,
        }
        for row in connection.execute(sa.select(ambulances.c.id))
        if row.id not in covered
    ]
    if missing:
        op.bulk_insert(scenarios, missing)


def _attach_requirements_to_scenarios(connection: sa.engine.Connection) -> None:
    """Point every weekday row at its workplace's selected scenario.

    Rows are matched through their competence's ambulance, which is the only
    link they had before scenarios existed. Any row left unattached is
    reported by name instead of surfacing later as an opaque NOT NULL
    violation; nothing has been deleted when that happens.
    """
    scenarios = _scenarios_table()
    competences = _competences_table()
    requirements = _requirements_table()

    selected = connection.execute(
        sa.select(scenarios.c.ambulance_id, sa.func.min(scenarios.c.id))
        .where(scenarios.c.is_active.is_(True))
        .group_by(scenarios.c.ambulance_id)
    ).all()
    for ambulance_id, scenario_id in selected:
        connection.execute(
            requirements.update()
            .where(
                requirements.c.scenario_id.is_(None),
                requirements.c.competence_id.in_(
                    sa.select(competences.c.id).where(
                        competences.c.ambulance_id == ambulance_id
                    )
                ),
            )
            .values(scenario_id=scenario_id)
        )

    orphan = connection.execute(
        sa.select(requirements.c.id).where(
            requirements.c.scenario_id.is_(None)
        ).limit(1)
    ).scalar()
    if orphan is not None:
        raise RuntimeError(
            f"Cannot attach weekday requirement {orphan} to a scenario: its "
            "competence belongs to no workplace. No rows were changed."
        )


def downgrade() -> None:
    """Collapse back to one weekly definition per competence.

    Only the selected scenario's rows survive -- the alternatives have
    nowhere to live once the scenario column is gone.
    """
    connection = op.get_bind()
    requirements = _requirements_table()
    connection.execute(
        requirements.delete().where(
            requirements.c.scenario_id.notin_(_selected_scenario_ids())
        )
    )

    existing = _constraint_names("competence_weekday_requirements")
    if "ix_competence_weekday_requirements_scenario_id" in existing:
        op.drop_index(
            "ix_competence_weekday_requirements_scenario_id",
            table_name="competence_weekday_requirements",
        )
    with op.batch_alter_table("competence_weekday_requirements") as batch:
        batch.drop_constraint("uq_competence_weekday_requirement", type_="unique")
        batch.drop_constraint(
            "fk_competence_weekday_requirements_scenario", type_="foreignkey"
        )
        batch.drop_column("scenario_id")
        batch.drop_column("recovery_days")
        batch.create_unique_constraint(
            "uq_competence_weekday_requirement", ["competence_id", "weekday"]
        )

    op.drop_index(
        "uq_competence_scenarios_active_ambulance_name",
        table_name="competence_scenarios",
    )
    op.drop_index(
        "ix_competence_scenarios_ambulance_active",
        table_name="competence_scenarios",
    )
    op.drop_index("ix_competence_scenarios_id", table_name="competence_scenarios")
    op.drop_table("competence_scenarios")
