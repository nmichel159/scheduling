"""The month's reminder, lock day and hand-set lock belong to a workplace.

Both window tables get the workplace into their key. The hospital-wide days
and every month's record so far (a hand-set lock, the reminder already sent)
are copied to each workplace, so nothing closes, opens or is mailed again
because of the move; each scheduler changes their own from there.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261017_02"
down_revision = "20261017_01"
branch_labels = None
depends_on = None

SETTINGS = "availability_settings"
PERIODS = "availability_periods"
PERIOD_FIELDS = (
    "year",
    "month",
    "is_locked",
    "reminder_sent_at",
    "reminder_status",
    "reminder_recipients",
)


def _columns(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if table not in set(inspector.get_table_names()):
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def _ambulance_column(with_ambulance: bool) -> list[sa.Column]:
    if not with_ambulance:
        return []
    return [
        sa.Column(
            "ambulance_id", sa.Integer(), sa.ForeignKey("ambulances.id"), nullable=False
        )
    ]


def _create_settings(with_ambulance: bool) -> None:
    extra = (
        [sa.UniqueConstraint("ambulance_id", name="uq_availability_settings_ambulance")]
        if with_ambulance
        else []
    )
    op.create_table(
        SETTINGS,
        sa.Column("id", sa.Integer(), primary_key=True),
        *_ambulance_column(with_ambulance),
        sa.Column("reminder_day", sa.Integer(), nullable=False),
        sa.Column("lock_day", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            "reminder_day >= 1 AND reminder_day < lock_day AND lock_day <= 28",
            name="ck_availability_settings_days",
        ),
        *extra,
    )


def _create_periods(with_ambulance: bool) -> None:
    unique = ("ambulance_id", "year", "month") if with_ambulance else ("year", "month")
    op.create_table(
        PERIODS,
        sa.Column("id", sa.Integer(), primary_key=True),
        *_ambulance_column(with_ambulance),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("is_locked", sa.Boolean(), nullable=True),
        sa.Column("reminder_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reminder_status", sa.String(32), nullable=True),
        sa.Column("reminder_recipients", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(*unique, name="uq_availability_periods_month"),
        sa.CheckConstraint("month >= 1 AND month <= 12", name="ck_availability_periods_month"),
    )


def _table(name: str, fields) -> sa.TableClause:
    return sa.table(name, *(sa.column(field) for field in fields))


def upgrade() -> None:
    bind = op.get_bind()
    ambulance_ids = [row[0] for row in bind.execute(sa.text("SELECT id FROM ambulances"))]

    columns = _columns(SETTINGS)
    if "ambulance_id" not in columns:
        days = None
        if columns:
            days = bind.execute(
                sa.text(f"SELECT reminder_day, lock_day FROM {SETTINGS} ORDER BY id")
            ).first()
            op.drop_table(SETTINGS)
        _create_settings(with_ambulance=True)
        if days is not None and ambulance_ids:
            op.bulk_insert(
                _table(SETTINGS, ("ambulance_id", "reminder_day", "lock_day")),
                [
                    {"ambulance_id": ambulance_id, "reminder_day": days[0], "lock_day": days[1]}
                    for ambulance_id in ambulance_ids
                ],
            )

    columns = _columns(PERIODS)
    if "ambulance_id" not in columns:
        periods = []
        if columns:
            periods = [
                dict(row._mapping)
                for row in bind.execute(
                    sa.text(f"SELECT {', '.join(PERIOD_FIELDS)} FROM {PERIODS}")
                )
            ]
            op.drop_table(PERIODS)
        _create_periods(with_ambulance=True)
        rows = [
            {"ambulance_id": ambulance_id, **period}
            for ambulance_id in ambulance_ids
            for period in periods
        ]
        if rows:
            op.bulk_insert(_table(PERIODS, ("ambulance_id", *PERIOD_FIELDS)), rows)


def downgrade() -> None:
    # The first workplace's window stands for the whole hospital again.
    bind = op.get_bind()
    if "ambulance_id" in _columns(SETTINGS):
        days = bind.execute(
            sa.text(f"SELECT reminder_day, lock_day FROM {SETTINGS} ORDER BY ambulance_id")
        ).first()
        op.drop_table(SETTINGS)
        _create_settings(with_ambulance=False)
        if days is not None:
            op.bulk_insert(
                _table(SETTINGS, ("id", "reminder_day", "lock_day")),
                [{"id": 1, "reminder_day": days[0], "lock_day": days[1]}],
            )
    if "ambulance_id" in _columns(PERIODS):
        first = bind.execute(sa.text(f"SELECT MIN(ambulance_id) FROM {PERIODS}")).scalar()
        periods = []
        if first is not None:
            periods = [
                dict(row._mapping)
                for row in bind.execute(
                    sa.text(
                        f"SELECT {', '.join(PERIOD_FIELDS)} FROM {PERIODS} "
                        "WHERE ambulance_id = :first"
                    ),
                    {"first": first},
                )
            ]
        op.drop_table(PERIODS)
        _create_periods(with_ambulance=False)
        if periods:
            op.bulk_insert(_table(PERIODS, PERIOD_FIELDS), periods)
