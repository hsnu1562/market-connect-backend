"""Add required Google profile onboarding state.

Revision ID: 20261002_02
Revises: 20261002_01
Create Date: 2026-10-02
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261002_02"
down_revision = "20261002_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    user_columns = {column["name"] for column in inspector.get_columns("user")}

    if "profile_completed_at" not in user_columns:
        with op.batch_alter_table("user") as batch_op:
            batch_op.add_column(sa.Column("profile_completed_at", sa.DateTime(), nullable=True))

    table_names = set(sa.inspect(bind).get_table_names())
    if "auth_identity" in table_names:
        bind.execute(
            sa.text(
                """
                UPDATE "user"
                SET profile_completed_at = CURRENT_TIMESTAMP
                WHERE profile_completed_at IS NULL
                  AND NOT EXISTS (
                      SELECT 1
                      FROM auth_identity AS identity
                      WHERE identity.user_id = "user".id
                        AND identity.provider = 'google'
                  )
                """
            )
        )


def downgrade() -> None:
    user_columns = {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("user")
    }
    if "profile_completed_at" in user_columns:
        with op.batch_alter_table("user") as batch_op:
            batch_op.drop_column("profile_completed_at")
