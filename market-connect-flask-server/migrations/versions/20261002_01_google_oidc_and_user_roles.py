"""Add Google identities and multi-role account memberships.

Revision ID: 20261002_01
Revises:
Create Date: 2026-10-02
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261002_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())
    if "user" not in table_names:
        raise RuntimeError("Run `flask --app app init-db` before applying the initial migration.")

    user_columns = {column["name"]: column for column in inspector.get_columns("user")}
    needs_user_changes = (
        any(column not in user_columns for column in ("status", "created_at", "updated_at"))
        or not user_columns["password_hash"]["nullable"]
    )
    if needs_user_changes:
        with op.batch_alter_table("user") as batch_op:
            if "status" not in user_columns:
                batch_op.add_column(
                    sa.Column(
                        "status",
                        sa.String(length=20),
                        server_default="active",
                        nullable=False,
                    )
                )
            if "created_at" not in user_columns:
                batch_op.add_column(
                    sa.Column(
                        "created_at",
                        sa.DateTime(),
                        server_default=sa.func.now(),
                        nullable=False,
                    )
                )
            if "updated_at" not in user_columns:
                batch_op.add_column(
                    sa.Column(
                        "updated_at",
                        sa.DateTime(),
                        server_default=sa.func.now(),
                        nullable=False,
                    )
                )
            if not user_columns["password_hash"]["nullable"]:
                batch_op.alter_column(
                    "password_hash",
                    existing_type=sa.String(length=255),
                    nullable=True,
                )

    if "user_role" not in table_names:
        op.create_table(
            "user_role",
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("role", sa.String(length=20), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("user_id", "role"),
        )

    if "auth_identity" not in table_names:
        op.create_table(
            "auth_identity",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("provider", sa.String(length=30), nullable=False),
            sa.Column("provider_subject", sa.String(length=255), nullable=False),
            sa.Column("email", sa.String(length=320), nullable=True),
            sa.Column("email_verified", sa.Boolean(), nullable=False),
            sa.Column("display_name", sa.String(length=255), nullable=True),
            sa.Column("picture_url", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("last_login_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "provider",
                "provider_subject",
                name="uq_auth_identity_provider_subject",
            ),
        )
        op.create_index("ix_auth_identity_user_id", "auth_identity", ["user_id"])

    bind.execute(
        sa.text(
            """
            INSERT INTO user_role (user_id, role, created_at)
            SELECT u.id, u.role, CURRENT_TIMESTAMP
            FROM "user" AS u
            WHERE u.role IN ('Tenant', 'Landlord')
              AND NOT EXISTS (
                  SELECT 1
                  FROM user_role AS ur
                  WHERE ur.user_id = u.id AND ur.role = u.role
              )
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    if "auth_identity" in table_names:
        index_names = {index["name"] for index in inspector.get_indexes("auth_identity")}
        if "ix_auth_identity_user_id" in index_names:
            op.drop_index("ix_auth_identity_user_id", table_name="auth_identity")
        op.drop_table("auth_identity")
    if "user_role" in table_names:
        op.drop_table("user_role")

    bind.execute(
        sa.text(
            "UPDATE \"user\" SET password_hash = '!oauth-only-account' "
            "WHERE password_hash IS NULL"
        )
    )
    user_columns = {column["name"]: column for column in sa.inspect(bind).get_columns("user")}
    with op.batch_alter_table("user") as batch_op:
        batch_op.alter_column(
            "password_hash",
            existing_type=sa.String(length=255),
            nullable=False,
        )
        for column_name in ("updated_at", "created_at", "status"):
            if column_name in user_columns:
                batch_op.drop_column(column_name)
