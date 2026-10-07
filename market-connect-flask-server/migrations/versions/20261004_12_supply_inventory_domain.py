"""Add the verified supply and allocated inventory domain.

Revision ID: 20261004_12
Revises: 20261004_11
Create Date: 2026-10-07
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261004_12"
down_revision = "20261004_11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    table_names = set(sa.inspect(bind).get_table_names())

    if "provider" not in table_names:
        op.create_table(
            "provider",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("managing_user_id", sa.Integer(), nullable=False),
            sa.Column("display_name", sa.String(length=120), nullable=False),
            sa.Column("legal_name", sa.String(length=160)),
            sa.Column("description", sa.Text()),
            sa.Column("contact_name", sa.String(length=100), nullable=False),
            sa.Column("contact_phone", sa.String(length=30), nullable=False),
            sa.Column("contact_email", sa.String(length=320)),
            sa.Column(
                "verification_status",
                sa.String(length=20),
                server_default="PENDING",
                nullable=False,
            ),
            sa.Column("verified_at", sa.DateTime(timezone=True)),
            sa.Column("verification_expires_at", sa.DateTime(timezone=True)),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.CheckConstraint(
                "verification_status IN ('PENDING', 'VERIFIED', 'SUSPENDED', 'REVOKED')",
                name="ck_provider_verification_status",
            ),
            sa.ForeignKeyConstraint(
                ["managing_user_id"], ["user.id"], ondelete="RESTRICT"
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_provider_managing_user_id", "provider", ["managing_user_id"])
        op.create_index(
            "ix_provider_verification_status", "provider", ["verification_status"]
        )

    table_names = set(sa.inspect(bind).get_table_names())
    if "venue" not in table_names:
        op.create_table(
            "venue",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("provider_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=140), nullable=False),
            sa.Column(
                "country_code",
                sa.String(length=2),
                server_default="TW",
                nullable=False,
            ),
            sa.Column("city", sa.String(length=80), nullable=False),
            sa.Column("district", sa.String(length=80)),
            sa.Column("address_line", sa.String(length=255), nullable=False),
            sa.Column("postal_code", sa.String(length=20)),
            sa.Column("business_description", sa.Text()),
            sa.Column(
                "verification_status",
                sa.String(length=20),
                server_default="PENDING",
                nullable=False,
            ),
            sa.Column("verified_at", sa.DateTime(timezone=True)),
            sa.Column("verification_expires_at", sa.DateTime(timezone=True)),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.CheckConstraint(
                "verification_status IN ('PENDING', 'VERIFIED', 'SUSPENDED', 'REVOKED')",
                name="ck_venue_verification_status",
            ),
            sa.ForeignKeyConstraint(["provider_id"], ["provider.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_venue_provider_id", "venue", ["provider_id"])
        op.create_index(
            "ix_venue_verification_status", "venue", ["verification_status"]
        )

    table_names = set(sa.inspect(bind).get_table_names())
    if "opportunity" not in table_names:
        op.create_table(
            "opportunity",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("provider_id", sa.Integer(), nullable=False),
            sa.Column("venue_id", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(length=180), nullable=False),
            sa.Column("description", sa.Text()),
            sa.Column("opportunity_type", sa.String(length=20), nullable=False),
            sa.Column(
                "visibility",
                sa.String(length=20),
                server_default="PUBLIC",
                nullable=False,
            ),
            sa.Column(
                "publication_status",
                sa.String(length=20),
                server_default="DRAFT",
                nullable=False,
            ),
            sa.Column(
                "booking_policy",
                sa.String(length=30),
                server_default="INSTANT",
                nullable=False,
            ),
            sa.Column("pricing_context", sa.Text()),
            sa.Column("requirements_summary", sa.Text()),
            sa.Column("required_requirement_types", sa.JSON(), nullable=False),
            sa.Column("cancellation_policy", sa.Text()),
            sa.Column("published_at", sa.DateTime(timezone=True)),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.CheckConstraint(
                "opportunity_type IN ('EVENT', 'LONG_TERM', 'RECURRING')",
                name="ck_opportunity_type",
            ),
            sa.CheckConstraint(
                "visibility IN ('PUBLIC', 'PRIVATE')",
                name="ck_opportunity_visibility",
            ),
            sa.CheckConstraint(
                "publication_status IN ('DRAFT', 'PUBLISHED', 'PAUSED', 'ARCHIVED')",
                name="ck_opportunity_publication_status",
            ),
            sa.CheckConstraint(
                "booking_policy = 'INSTANT'", name="ck_opportunity_booking_policy"
            ),
            sa.ForeignKeyConstraint(["provider_id"], ["provider.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["venue_id"], ["venue.id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_opportunity_provider_id", "opportunity", ["provider_id"])
        op.create_index("ix_opportunity_venue_id", "opportunity", ["venue_id"])
        op.create_index(
            "ix_opportunity_publication_status",
            "opportunity",
            ["publication_status"],
        )

    table_names = set(sa.inspect(bind).get_table_names())
    if "inventory_group" not in table_names:
        op.create_table(
            "inventory_group",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("opportunity_id", sa.Integer(), nullable=False),
            sa.Column("service_period_start", sa.DateTime(timezone=True), nullable=False),
            sa.Column("service_period_end", sa.DateTime(timezone=True), nullable=False),
            sa.Column("allocated_capacity", sa.Integer(), nullable=False),
            sa.Column("price_amount", sa.Integer(), nullable=False),
            sa.Column(
                "currency",
                sa.String(length=3),
                server_default="TWD",
                nullable=False,
            ),
            sa.Column(
                "status",
                sa.String(length=20),
                server_default="DRAFT",
                nullable=False,
            ),
            sa.Column("required_requirement_types", sa.JSON(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.CheckConstraint(
                "allocated_capacity >= 0", name="ck_inventory_group_capacity"
            ),
            sa.CheckConstraint("price_amount >= 0", name="ck_inventory_group_price"),
            sa.CheckConstraint(
                "service_period_end > service_period_start",
                name="ck_inventory_group_service_period",
            ),
            sa.CheckConstraint(
                "status IN ('DRAFT', 'ACTIVE', 'PAUSED', 'CLOSED')",
                name="ck_inventory_group_status",
            ),
            sa.ForeignKeyConstraint(
                ["opportunity_id"], ["opportunity.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_inventory_group_opportunity_id", "inventory_group", ["opportunity_id"]
        )
        op.create_index(
            "ix_inventory_group_service_period_start",
            "inventory_group",
            ["service_period_start"],
        )
        op.create_index("ix_inventory_group_status", "inventory_group", ["status"])

    table_names = set(sa.inspect(bind).get_table_names())
    if "inventory_category_quota" not in table_names:
        op.create_table(
            "inventory_category_quota",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("inventory_group_id", sa.Integer(), nullable=False),
            sa.Column("category", sa.String(length=40), nullable=False),
            sa.Column("capacity", sa.Integer(), nullable=False),
            sa.CheckConstraint(
                "capacity >= 0", name="ck_inventory_category_quota_capacity"
            ),
            sa.ForeignKeyConstraint(
                ["inventory_group_id"], ["inventory_group.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "inventory_group_id",
                "category",
                name="uq_inventory_category_quota_group_category",
            ),
        )
        op.create_index(
            "ix_inventory_category_quota_inventory_group_id",
            "inventory_category_quota",
            ["inventory_group_id"],
        )

    table_names = set(sa.inspect(bind).get_table_names())
    if "supply_audit_event" not in table_names:
        op.create_table(
            "supply_audit_event",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("actor_user_id", sa.Integer()),
            sa.Column("provider_id", sa.Integer()),
            sa.Column("entity_type", sa.String(length=40), nullable=False),
            sa.Column("entity_id", sa.Integer(), nullable=False),
            sa.Column("event_type", sa.String(length=60), nullable=False),
            sa.Column("before_data", sa.JSON()),
            sa.Column("after_data", sa.JSON()),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["actor_user_id"], ["user.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["provider_id"], ["provider.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_supply_audit_event_actor_user_id",
            "supply_audit_event",
            ["actor_user_id"],
        )
        op.create_index(
            "ix_supply_audit_event_provider_id",
            "supply_audit_event",
            ["provider_id"],
        )
        op.create_index(
            "ix_supply_audit_event_event_type",
            "supply_audit_event",
            ["event_type"],
        )

    inspector = sa.inspect(bind)
    if "booking" not in inspector.get_table_names():
        return
    booking_columns = {
        column["name"]: column for column in inspector.get_columns("booking")
    }
    needs_batch_change = (
        "inventory_group_id" not in booking_columns
        or "vendor_category" not in booking_columns
        or not booking_columns["slot_id"]["nullable"]
    )
    if needs_batch_change:
        with op.batch_alter_table("booking") as batch_op:
            if "inventory_group_id" not in booking_columns:
                batch_op.add_column(sa.Column("inventory_group_id", sa.Integer()))
                batch_op.create_foreign_key(
                    "fk_booking_inventory_group_id_inventory_group",
                    "inventory_group",
                    ["inventory_group_id"],
                    ["id"],
                    ondelete="RESTRICT",
                )
            if "vendor_category" not in booking_columns:
                batch_op.add_column(sa.Column("vendor_category", sa.String(length=40)))
            if not booking_columns["slot_id"]["nullable"]:
                batch_op.alter_column(
                    "slot_id",
                    existing_type=sa.Integer(),
                    existing_nullable=False,
                    nullable=True,
                )

    booking_indexes = {
        index["name"] for index in sa.inspect(bind).get_indexes("booking")
    }
    if "ix_booking_inventory_group_id" not in booking_indexes:
        op.create_index(
            "ix_booking_inventory_group_id", "booking", ["inventory_group_id"]
        )
    if "ix_booking_vendor_category" not in booking_indexes:
        op.create_index("ix_booking_vendor_category", "booking", ["vendor_category"])
    if "ix_booking_inventory_active" not in booking_indexes:
        op.create_index(
            "ix_booking_inventory_active",
            "booking",
            ["inventory_group_id", "reservation_status", "hold_expires_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "booking" in inspector.get_table_names():
        booking_columns = {
            column["name"] for column in inspector.get_columns("booking")
        }
        if "inventory_group_id" in booking_columns:
            inventory_booking = bind.execute(
                sa.text(
                    "SELECT id FROM booking "
                    "WHERE inventory_group_id IS NOT NULL OR slot_id IS NULL LIMIT 1"
                )
            ).first()
            if inventory_booking is not None:
                raise RuntimeError(
                    "Cannot downgrade while inventory-based reservations exist."
                )

        booking_indexes = {
            index["name"] for index in inspector.get_indexes("booking")
        }
        for index_name in (
            "ix_booking_inventory_active",
            "ix_booking_vendor_category",
            "ix_booking_inventory_group_id",
        ):
            if index_name in booking_indexes:
                op.drop_index(index_name, table_name="booking")

        with op.batch_alter_table("booking") as batch_op:
            if "inventory_group_id" in booking_columns:
                batch_op.drop_constraint(
                    "fk_booking_inventory_group_id_inventory_group",
                    type_="foreignkey",
                )
                batch_op.drop_column("inventory_group_id")
            if "vendor_category" in booking_columns:
                batch_op.drop_column("vendor_category")
            batch_op.alter_column(
                "slot_id",
                existing_type=sa.Integer(),
                existing_nullable=True,
                nullable=False,
            )

    # Destructive for Phase 3A-only supply data; legacy Stall/Slot data remains.
    table_names = set(sa.inspect(bind).get_table_names())
    for table_name in (
        "supply_audit_event",
        "inventory_category_quota",
        "inventory_group",
        "opportunity",
        "venue",
        "provider",
    ):
        if table_name in table_names:
            op.drop_table(table_name)
