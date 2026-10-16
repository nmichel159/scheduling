"""Sign-in with an e-mail and a password.

The hash stays NULL until the employee chooses a password; until then the
account's e-mail is the password. A reset link is kept as a digest with its
expiry next to it.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261016_05"
down_revision = "20261016_04"
branch_labels = None
depends_on = None

TABLE = "users"
INDEX = "ix_users_password_reset_token"


def _columns() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns(TABLE)}


def upgrade() -> None:
    columns = _columns()
    if "password_hash" not in columns:
        op.add_column(TABLE, sa.Column("password_hash", sa.String(255), nullable=True))
    if "password_reset_token" not in columns:
        op.add_column(TABLE, sa.Column("password_reset_token", sa.String(64), nullable=True))
        op.create_index(INDEX, TABLE, ["password_reset_token"])
    if "password_reset_expires_at" not in columns:
        op.add_column(
            TABLE,
            sa.Column("password_reset_expires_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    columns = _columns()
    if "password_reset_expires_at" in columns:
        op.drop_column(TABLE, "password_reset_expires_at")
    if "password_reset_token" in columns:
        op.drop_index(INDEX, table_name=TABLE)
        op.drop_column(TABLE, "password_reset_token")
    if "password_hash" in columns:
        op.drop_column(TABLE, "password_hash")
