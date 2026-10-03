"""Drop the deprecated certification evidence URL column.

Revision ID: 20261004_08
Revises: 20261004_07
Create Date: 2026-10-04
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261004_08"
down_revision = "20261004_07"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "stall_certification" not in inspector.get_table_names():
        return

    certification_columns = {
        column["name"] for column in inspector.get_columns("stall_certification")
    }
    if "evidence_url" in certification_columns:
        with op.batch_alter_table("stall_certification") as batch_op:
            batch_op.drop_column("evidence_url")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "stall_certification" not in inspector.get_table_names():
        return

    certification_columns = {
        column["name"] for column in inspector.get_columns("stall_certification")
    }
    if "evidence_url" not in certification_columns:
        with op.batch_alter_table("stall_certification") as batch_op:
            batch_op.add_column(sa.Column("evidence_url", sa.Text(), nullable=True))
