"""Add stall discovery fields and booking policies.

Revision ID: 20261002_04
Revises: 20261002_03
Create Date: 2026-10-02
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261002_04"
down_revision = "20261002_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    if "stall" in table_names:
        stall_columns = {column["name"] for column in inspector.get_columns("stall")}
        with op.batch_alter_table("stall") as batch_op:
            if "environment_type" not in stall_columns:
                batch_op.add_column(
                    sa.Column(
                        "environment_type",
                        sa.String(length=20),
                        server_default="unspecified",
                        nullable=False,
                    )
                )
            if "booking_mode" not in stall_columns:
                batch_op.add_column(
                    sa.Column(
                        "booking_mode",
                        sa.String(length=20),
                        server_default="hourly",
                        nullable=False,
                    )
                )
            if "minimum_booking_hours" not in stall_columns:
                batch_op.add_column(
                    sa.Column(
                        "minimum_booking_hours",
                        sa.Integer(),
                        server_default="1",
                        nullable=False,
                    )
                )

    if "slot" in table_names:
        slot_columns = {column["name"] for column in sa.inspect(bind).get_columns("slot")}
        if "duration_hours" not in slot_columns:
            with op.batch_alter_table("slot") as batch_op:
                batch_op.add_column(
                    sa.Column(
                        "duration_hours",
                        sa.Integer(),
                        server_default="1",
                        nullable=False,
                    )
                )


def downgrade() -> None:
    bind = op.get_bind()
    table_names = set(sa.inspect(bind).get_table_names())

    if "slot" in table_names:
        slot_columns = {column["name"] for column in sa.inspect(bind).get_columns("slot")}
        if "duration_hours" in slot_columns:
            with op.batch_alter_table("slot") as batch_op:
                batch_op.drop_column("duration_hours")

    if "stall" in table_names:
        stall_columns = {column["name"] for column in sa.inspect(bind).get_columns("stall")}
        with op.batch_alter_table("stall") as batch_op:
            for column_name in (
                "minimum_booking_hours",
                "booking_mode",
                "environment_type",
            ):
                if column_name in stall_columns:
                    batch_op.drop_column(column_name)
