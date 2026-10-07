"""Add Vendor profiles and booking requirement snapshots.

Revision ID: 20261004_11
Revises: 20261004_10
Create Date: 2026-10-04
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261004_11"
down_revision = "20261004_10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    if "vendor_profile" not in table_names:
        op.create_table(
            "vendor_profile",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("brand_name", sa.String(length=100), nullable=False),
            sa.Column("primary_category", sa.String(length=40), nullable=False),
            sa.Column("brand_description", sa.Text()),
            sa.Column("instagram_url", sa.Text()),
            sa.Column("facebook_url", sa.Text()),
            sa.Column("website_url", sa.Text()),
            sa.Column("contact_name", sa.String(length=100), nullable=False),
            sa.Column("contact_phone", sa.String(length=30), nullable=False),
            sa.Column("contact_email", sa.String(length=320)),
            sa.Column("food_registration_number", sa.String(length=100)),
            sa.Column("profile_image_filename", sa.String(length=255)),
            sa.Column("profile_image_content_type", sa.String(length=80)),
            sa.Column("profile_image_byte_size", sa.Integer()),
            sa.Column("profile_image_sha256", sa.String(length=64)),
            sa.Column("profile_image_data", sa.LargeBinary()),
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
            sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", name="uq_vendor_profile_user_id"),
        )
        op.create_index(
            "ix_vendor_profile_primary_category",
            "vendor_profile",
            ["primary_category"],
        )

    if "booking_requirement" not in table_names:
        op.create_table(
            "booking_requirement",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column(
                "electricity_required",
                sa.Boolean(),
                server_default=sa.false(),
                nullable=False,
            ),
            sa.Column("electricity_details", sa.String(length=255)),
            sa.Column(
                "gas_required",
                sa.Boolean(),
                server_default=sa.false(),
                nullable=False,
            ),
            sa.Column("gas_details", sa.String(length=255)),
            sa.Column("equipment_requirements", sa.Text()),
            sa.Column("vehicle_plate", sa.String(length=20)),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    inspector = sa.inspect(bind)
    if "booking" not in inspector.get_table_names():
        return
    booking_columns = {column["name"] for column in inspector.get_columns("booking")}
    if "requirements_id" not in booking_columns:
        with op.batch_alter_table("booking") as batch_op:
            batch_op.add_column(sa.Column("requirements_id", sa.Integer()))
            batch_op.create_foreign_key(
                "fk_booking_requirements_id_booking_requirement",
                "booking_requirement",
                ["requirements_id"],
                ["id"],
                ondelete="SET NULL",
            )

    booking_indexes = {
        index["name"] for index in sa.inspect(bind).get_indexes("booking")
    }
    if "ix_booking_requirements_id" not in booking_indexes:
        op.create_index(
            "ix_booking_requirements_id",
            "booking",
            ["requirements_id"],
        )


def downgrade() -> None:
    # Intentionally destructive: rolling back Phase 2 removes all VendorProfile
    # and BookingRequirements data created after this migration was applied.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "booking" in inspector.get_table_names():
        booking_columns = {
            column["name"] for column in inspector.get_columns("booking")
        }
        booking_indexes = {
            index["name"] for index in inspector.get_indexes("booking")
        }
        if "ix_booking_requirements_id" in booking_indexes:
            op.drop_index("ix_booking_requirements_id", table_name="booking")
        if "requirements_id" in booking_columns:
            with op.batch_alter_table("booking") as batch_op:
                batch_op.drop_constraint(
                    "fk_booking_requirements_id_booking_requirement",
                    type_="foreignkey",
                )
                batch_op.drop_column("requirements_id")

    table_names = set(sa.inspect(bind).get_table_names())
    if "booking_requirement" in table_names:
        op.drop_table("booking_requirement")
    if "vendor_profile" in table_names:
        op.drop_table("vendor_profile")
