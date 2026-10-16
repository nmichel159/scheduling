"""How many people may be away on one day, and when a restriction was entered.

A new table holds the hospital-wide limit per kind of absence; without rows
nothing is limited. Each restriction gets the moment its reason was set and
who set it, so the days can be shown in the order people filled them in.
Existing records take their creation time; who entered them is unknown.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261016_04"
down_revision = "20261016_03"
branch_labels = None
depends_on = None

LIMITS = "availability_day_limits"
RECORDS = "unavailabilities"


def _columns() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns(RECORDS)}


def upgrade() -> None:
    if LIMITS not in set(sa.inspect(op.get_bind()).get_table_names()):
        op.create_table(
            LIMITS,
            sa.Column("reason", sa.String(32), primary_key=True),
            sa.Column("max_per_day", sa.Integer(), nullable=False),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
            ),
            sa.CheckConstraint(
                "max_per_day >= 0", name="ck_availability_day_limits_max"
            ),
        )
    columns = _columns()
    # In a batch: SQLite cannot ALTER in a column whose default is now().
    with op.batch_alter_table(RECORDS) as batch:
        if "entered_at" not in columns:
            batch.add_column(
                sa.Column(
                    "entered_at",
                    sa.DateTime(timezone=True),
                    server_default=sa.func.now(),
                )
            )
        if "entered_by_user_id" not in columns:
            batch.add_column(sa.Column("entered_by_user_id", sa.Integer(), nullable=True))
            batch.create_foreign_key(
                "fk_unavailabilities_entered_by_user_id_users",
                "users",
                ["entered_by_user_id"],
                ["id"],
            )
    if "entered_at" not in columns and "created_at" in columns:
        op.execute(sa.text(f"UPDATE {RECORDS} SET entered_at = created_at"))


def downgrade() -> None:
    columns = _columns()
    if "entered_by_user_id" in columns:
        with op.batch_alter_table(RECORDS) as batch:
            batch.drop_constraint(
                "fk_unavailabilities_entered_by_user_id_users", type_="foreignkey"
            )
            batch.drop_column("entered_by_user_id")
    if "entered_at" in columns:
        op.drop_column(RECORDS, "entered_at")
    if LIMITS in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table(LIMITS)
