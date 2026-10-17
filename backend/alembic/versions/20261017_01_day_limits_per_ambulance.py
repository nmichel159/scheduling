"""Per-day absence limits belong to a workplace, not to the whole hospital.

The limits table gets the workplace into its key. Every hospital-wide limit
saved so far is copied to each workplace, so nothing that was limited before
stops being limited; each scheduler can change their own from there.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261017_01"
down_revision = "20261016_06"
branch_labels = None
depends_on = None

LIMITS = "availability_day_limits"


def _limit_columns() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if LIMITS not in set(inspector.get_table_names()):
        return set()
    return {column["name"] for column in inspector.get_columns(LIMITS)}


def _table(with_ambulance: bool) -> sa.Table:
    columns = [sa.column("reason"), sa.column("max_per_day")]
    if with_ambulance:
        columns.insert(0, sa.column("ambulance_id"))
    return sa.table(LIMITS, *columns)


def _create(with_ambulance: bool) -> None:
    columns = []
    if with_ambulance:
        columns.append(
            sa.Column(
                "ambulance_id",
                sa.Integer(),
                sa.ForeignKey("ambulances.id"),
                primary_key=True,
            )
        )
    columns += [
        sa.Column("reason", sa.String(32), primary_key=True),
        sa.Column("max_per_day", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("max_per_day >= 0", name="ck_availability_day_limits_max"),
    ]
    op.create_table(LIMITS, *columns)


def upgrade() -> None:
    columns = _limit_columns()
    if "ambulance_id" in columns:
        return
    if not columns:
        _create(with_ambulance=True)
        return
    # Read out and rebuilt rather than renamed: on PostgreSQL the renamed
    # table would keep its primary-key index name and block the new one.
    bind = op.get_bind()
    limits = bind.execute(sa.text(f"SELECT reason, max_per_day FROM {LIMITS}")).all()
    ambulance_ids = [row[0] for row in bind.execute(sa.text("SELECT id FROM ambulances"))]
    op.drop_table(LIMITS)
    _create(with_ambulance=True)
    rows = [
        {"ambulance_id": ambulance_id, "reason": reason, "max_per_day": max_per_day}
        for ambulance_id in ambulance_ids
        for reason, max_per_day in limits
    ]
    if rows:
        op.bulk_insert(_table(with_ambulance=True), rows)


def downgrade() -> None:
    if "ambulance_id" not in _limit_columns():
        return
    # The strictest workplace's limit stands for the whole hospital again.
    limits = op.get_bind().execute(
        sa.text(f"SELECT reason, MIN(max_per_day) FROM {LIMITS} GROUP BY reason")
    ).all()
    op.drop_table(LIMITS)
    _create(with_ambulance=False)
    if limits:
        op.bulk_insert(
            _table(with_ambulance=False),
            [{"reason": reason, "max_per_day": value} for reason, value in limits],
        )
