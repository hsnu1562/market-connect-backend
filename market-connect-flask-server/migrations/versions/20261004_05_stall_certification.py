"""Add manual stall certification workflow.

Revision ID: 20261004_05
Revises: 20261002_04
Create Date: 2026-10-04
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261004_05"
down_revision = "20261002_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    table_names = set(sa.inspect(op.get_bind()).get_table_names())
    if "stall_certification" in table_names:
        return

    op.create_table(
        "stall_certification",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("stall_id", sa.Integer(), nullable=False),
        sa.Column("applicant_legal_name", sa.String(length=100), nullable=False),
        sa.Column("applicant_phone", sa.String(length=30), nullable=False),
        sa.Column("relationship_to_space", sa.String(length=40), nullable=False),
        sa.Column("proof_type", sa.String(length=40), nullable=False),
        sa.Column("proof_reference", sa.String(length=120), nullable=True),
        sa.Column("evidence_url", sa.Text(), nullable=False),
        sa.Column(
            "declaration_accepted",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="pending",
            nullable=False,
        ),
        sa.Column(
            "submitted_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("reviewer_reference", sa.String(length=100), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["stall_id"], ["stall.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stall_id", name="uq_stall_certification_stall_id"),
    )
    op.create_index(
        "ix_stall_certification_stall_id",
        "stall_certification",
        ["stall_id"],
    )
    op.create_index(
        "ix_stall_certification_status",
        "stall_certification",
        ["status"],
    )


def downgrade() -> None:
    table_names = set(sa.inspect(op.get_bind()).get_table_names())
    if "stall_certification" in table_names:
        op.drop_table("stall_certification")
