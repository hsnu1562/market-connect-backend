"""Require nickname and birthday in Google account profiles.

Revision ID: 20261002_03
Revises: 20261002_02
Create Date: 2026-10-02
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261002_03"
down_revision = "20261002_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    user_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("user")
    }
    if "nickname" not in user_columns or "birth_date" not in user_columns:
        with op.batch_alter_table("user") as batch_op:
            if "nickname" not in user_columns:
                batch_op.add_column(sa.Column("nickname", sa.String(length=50), nullable=True))
            if "birth_date" not in user_columns:
                batch_op.add_column(sa.Column("birth_date", sa.Date(), nullable=True))

    table_names = set(sa.inspect(bind).get_table_names())
    if "auth_identity" in table_names:
        bind.execute(
            sa.text(
                """
                UPDATE "user"
                SET profile_completed_at = NULL
                WHERE EXISTS (
                    SELECT 1
                    FROM auth_identity AS identity
                    WHERE identity.user_id = "user".id
                      AND identity.provider = 'google'
                )
                  AND (
                      nickname IS NULL OR TRIM(nickname) = ''
                      OR birth_date IS NULL
                      OR phone_number IS NULL OR TRIM(phone_number) = ''
                      OR first_name IS NULL OR TRIM(first_name) = ''
                      OR last_name IS NULL OR TRIM(last_name) = ''
                  )
                """
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    user_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("user")
    }
    with op.batch_alter_table("user") as batch_op:
        if "birth_date" in user_columns:
            batch_op.drop_column("birth_date")
        if "nickname" in user_columns:
            batch_op.drop_column("nickname")
