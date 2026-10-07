"""Disable URL evidence and require uploaded certification files.

Revision ID: 20261004_07
Revises: 20261004_06
Create Date: 2026-10-04
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261004_07"
down_revision = "20261004_06"
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
    if "evidence_url" not in certification_columns:
        return

    op.execute(
        sa.text(
            """
            UPDATE stall_certification
            SET status = 'rejected',
                reviewed_at = NULL,
                reviewed_by_user_id = NULL,
                reviewer_reference = 'system-migration',
                review_note = 'Link evidence is no longer accepted. Upload files and resubmit.'
            WHERE status IN ('approved', 'pending')
              AND NOT EXISTS (
                  SELECT 1
                  FROM stall_certification_document AS document
                  WHERE document.certification_id = stall_certification.id
              )
            """
        )
    )
    op.execute(sa.text("UPDATE stall_certification SET evidence_url = NULL"))


def downgrade() -> None:
    # Cleared external URLs cannot be reconstructed safely.
    pass
