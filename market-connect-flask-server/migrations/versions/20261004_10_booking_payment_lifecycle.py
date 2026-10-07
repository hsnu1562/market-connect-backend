"""Separate reservation holds from verified payment state.

Revision ID: 20261004_10
Revises: 20261004_09
Create Date: 2026-10-04
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261004_10"
down_revision = "20261004_09"
branch_labels = None
depends_on = None


ACTIVE_RESERVATION_PREDICATE = sa.text(
    "reservation_status IN ('HELD', 'CONFIRMED')"
)
SQLITE_NAMING_CONVENTION = {
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "payment_transaction" not in inspector.get_table_names():
        op.create_table(
            "payment_transaction",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("provider", sa.String(length=50)),
            sa.Column("merchant_order_id", sa.String(length=64), nullable=False),
            sa.Column("provider_transaction_id", sa.String(length=128)),
            sa.Column("amount", sa.Integer(), nullable=False),
            sa.Column(
                "currency",
                sa.String(length=3),
                server_default="TWD",
                nullable=False,
            ),
            sa.Column(
                "status",
                sa.String(length=20),
                server_default="PENDING",
                nullable=False,
            ),
            sa.Column("initiated_at", sa.DateTime(timezone=True)),
            sa.Column("verified_at", sa.DateTime(timezone=True)),
            sa.Column("provider_metadata", sa.JSON()),
            sa.Column("failure_reason", sa.String(length=255)),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "merchant_order_id",
                name="uq_payment_transaction_merchant_order_id",
            ),
            sa.UniqueConstraint(
                "provider_transaction_id",
                name="uq_payment_transaction_provider_transaction_id",
            ),
        )
        op.create_index(
            "ix_payment_transaction_status",
            "payment_transaction",
            ["status"],
        )

    inspector = sa.inspect(bind)
    if "booking" not in inspector.get_table_names():
        return
    booking_columns = {column["name"] for column in inspector.get_columns("booking")}
    slot_unique_constraints = [
        constraint
        for constraint in inspector.get_unique_constraints("booking")
        if constraint.get("column_names") == ["slot_id"]
    ]
    needs_batch_change = bool(slot_unique_constraints) or any(
        column not in booking_columns
        for column in (
            "payment_id",
            "reservation_status",
            "hold_expires_at",
            "confirmed_at",
        )
    )
    reservation_status_added = "reservation_status" not in booking_columns

    if needs_batch_change:
        with op.batch_alter_table(
            "booking",
            naming_convention=SQLITE_NAMING_CONVENTION,
        ) as batch_op:
            if "payment_id" not in booking_columns:
                batch_op.add_column(sa.Column("payment_id", sa.Integer()))
                batch_op.create_foreign_key(
                    "fk_booking_payment_id_payment_transaction",
                    "payment_transaction",
                    ["payment_id"],
                    ["id"],
                    ondelete="SET NULL",
                )
            if reservation_status_added:
                # Preserve occupied inventory without claiming historical payment
                # verification. Existing rows get CONFIRMED but no payment_id.
                batch_op.add_column(
                    sa.Column(
                        "reservation_status",
                        sa.String(length=20),
                        server_default="CONFIRMED",
                        nullable=False,
                    )
                )
            if "hold_expires_at" not in booking_columns:
                batch_op.add_column(
                    sa.Column("hold_expires_at", sa.DateTime(timezone=True))
                )
            if "confirmed_at" not in booking_columns:
                batch_op.add_column(
                    sa.Column("confirmed_at", sa.DateTime(timezone=True))
                )
            for constraint in slot_unique_constraints:
                batch_op.drop_constraint(
                    constraint.get("name") or "uq_booking_slot_id",
                    type_="unique",
                )

    # These legacy columns remain as untrusted historical evidence. Establish
    # database defaults for new rows without rewriting any existing value.
    booking_columns = {
        column["name"]: column
        for column in sa.inspect(bind).get_columns("booking")
    }
    with op.batch_alter_table("booking") as batch_op:
        if "payment_status" in booking_columns:
            batch_op.alter_column(
                "payment_status",
                existing_type=sa.String(length=20),
                existing_nullable=booking_columns["payment_status"]["nullable"],
                server_default="NotApplicable",
            )
        if "payment_method" in booking_columns:
            batch_op.alter_column(
                "payment_method",
                existing_type=sa.String(length=20),
                existing_nullable=booking_columns["payment_method"]["nullable"],
                server_default="",
            )

    if reservation_status_added:
        with op.batch_alter_table("booking") as batch_op:
            batch_op.alter_column(
                "reservation_status",
                existing_type=sa.String(length=20),
                server_default="HELD",
                existing_nullable=False,
            )

    inspector = sa.inspect(bind)
    booking_indexes = {index["name"] for index in inspector.get_indexes("booking")}
    if "ix_booking_payment_id" not in booking_indexes:
        op.create_index("ix_booking_payment_id", "booking", ["payment_id"])
    if "ix_booking_reservation_status" not in booking_indexes:
        op.create_index(
            "ix_booking_reservation_status",
            "booking",
            ["reservation_status"],
        )
    if "ix_booking_hold_expires_at" not in booking_indexes:
        op.create_index(
            "ix_booking_hold_expires_at",
            "booking",
            ["hold_expires_at"],
        )
    if "uq_booking_active_slot" not in booking_indexes:
        op.create_index(
            "uq_booking_active_slot",
            "booking",
            ["slot_id"],
            unique=True,
            postgresql_where=ACTIVE_RESERVATION_PREDICATE,
            sqlite_where=ACTIVE_RESERVATION_PREDICATE,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "booking" in inspector.get_table_names():
        # Check rollback feasibility before any DDL. Active and historical rows
        # may legitimately share a slot after migration 10.
        duplicate_slot = bind.execute(
            sa.text(
                "SELECT slot_id FROM booking GROUP BY slot_id "
                "HAVING COUNT(*) > 1 LIMIT 1"
            )
        ).first()
        if duplicate_slot is not None:
            raise RuntimeError(
                "Cannot downgrade while historical bookings share a slot_id."
            )

        indexes = {index["name"] for index in inspector.get_indexes("booking")}
        for index_name in (
            "uq_booking_active_slot",
            "ix_booking_hold_expires_at",
            "ix_booking_reservation_status",
            "ix_booking_payment_id",
        ):
            if index_name in indexes:
                op.drop_index(index_name, table_name="booking")

        column_details = {
            column["name"]: column
            for column in sa.inspect(bind).get_columns("booking")
        }
        columns = set(column_details)
        with op.batch_alter_table(
            "booking",
            naming_convention=SQLITE_NAMING_CONVENTION,
        ) as batch_op:
            if "payment_status" in columns:
                batch_op.alter_column(
                    "payment_status",
                    existing_type=sa.String(length=20),
                    existing_nullable=column_details["payment_status"]["nullable"],
                    server_default=None,
                )
            if "payment_method" in columns:
                batch_op.alter_column(
                    "payment_method",
                    existing_type=sa.String(length=20),
                    existing_nullable=column_details["payment_method"]["nullable"],
                    server_default=None,
                )
            if "confirmed_at" in columns:
                batch_op.drop_column("confirmed_at")
            if "hold_expires_at" in columns:
                batch_op.drop_column("hold_expires_at")
            if "reservation_status" in columns:
                batch_op.drop_column("reservation_status")
            if "payment_id" in columns:
                batch_op.drop_constraint(
                    "fk_booking_payment_id_payment_transaction",
                    type_="foreignkey",
                )
                batch_op.drop_column("payment_id")
            batch_op.create_unique_constraint("uq_booking_slot_id", ["slot_id"])

    if "payment_transaction" in sa.inspect(bind).get_table_names():
        op.drop_table("payment_transaction")
