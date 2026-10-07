"""Add encrypted certification documents and admin review access.

Revision ID: 20261004_06
Revises: 20261004_05
Create Date: 2026-10-04
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261004_06"
down_revision = "20261004_05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    if "user" in table_names:
        user_columns = {column["name"] for column in inspector.get_columns("user")}
        if "is_admin" not in user_columns:
            op.add_column(
                "user",
                sa.Column(
                    "is_admin",
                    sa.Boolean(),
                    server_default=sa.false(),
                    nullable=False,
                ),
            )

    if "stall_certification" in table_names:
        certification_columns = {
            column["name"]: column
            for column in inspector.get_columns("stall_certification")
        }
        add_reviewer_column = "reviewed_by_user_id" not in certification_columns
        make_evidence_optional = (
            "evidence_url" in certification_columns
            and not certification_columns["evidence_url"]["nullable"]
        )
        if add_reviewer_column or make_evidence_optional:
            with op.batch_alter_table("stall_certification") as batch_op:
                if make_evidence_optional:
                    batch_op.alter_column(
                        "evidence_url",
                        existing_type=sa.Text(),
                        nullable=True,
                    )
                if add_reviewer_column:
                    batch_op.add_column(sa.Column("reviewed_by_user_id", sa.Integer()))
                    batch_op.create_foreign_key(
                        "fk_stall_certification_reviewed_by_user_id_user",
                        "user",
                        ["reviewed_by_user_id"],
                        ["id"],
                        ondelete="SET NULL",
                    )

        inspector = sa.inspect(bind)
        index_names = {
            index["name"] for index in inspector.get_indexes("stall_certification")
        }
        if "ix_stall_certification_reviewed_by_user_id" not in index_names:
            op.create_index(
                "ix_stall_certification_reviewed_by_user_id",
                "stall_certification",
                ["reviewed_by_user_id"],
            )

    inspector = sa.inspect(bind)
    if "stall_certification_document" not in inspector.get_table_names():
        op.create_table(
            "stall_certification_document",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("certification_id", sa.Integer(), nullable=False),
            sa.Column("original_filename", sa.String(length=255), nullable=False),
            sa.Column("content_type", sa.String(length=80), nullable=False),
            sa.Column("byte_size", sa.Integer(), nullable=False),
            sa.Column("sha256", sa.String(length=64), nullable=False),
            sa.Column("nonce", sa.LargeBinary(length=12), nullable=False),
            sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
            sa.Column(
                "uploaded_at",
                sa.DateTime(),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["certification_id"],
                ["stall_certification.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_stall_certification_document_certification_id",
            "stall_certification_document",
            ["certification_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())
    if "stall_certification_document" in table_names:
        op.drop_table("stall_certification_document")

    inspector = sa.inspect(bind)
    if "stall_certification" in inspector.get_table_names():
        certification_columns = {
            column["name"] for column in inspector.get_columns("stall_certification")
        }
        if "reviewed_by_user_id" in certification_columns:
            with op.batch_alter_table("stall_certification") as batch_op:
                batch_op.drop_column("reviewed_by_user_id")
        op.execute(
            sa.text(
                "UPDATE stall_certification "
                "SET evidence_url = 'https://invalid.local/evidence-removed-by-downgrade' "
                "WHERE evidence_url IS NULL"
            )
        )
        with op.batch_alter_table("stall_certification") as batch_op:
            batch_op.alter_column(
                "evidence_url",
                existing_type=sa.Text(),
                nullable=False,
            )

    inspector = sa.inspect(bind)
    if "user" in inspector.get_table_names():
        user_columns = {column["name"] for column in inspector.get_columns("user")}
        if "is_admin" in user_columns:
            with op.batch_alter_table("user") as batch_op:
                batch_op.drop_column("is_admin")
