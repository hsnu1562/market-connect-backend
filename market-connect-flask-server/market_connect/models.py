from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import deferred

from .extensions import db


RESERVATION_HELD = "HELD"
RESERVATION_CONFIRMED = "CONFIRMED"
RESERVATION_EXPIRED = "EXPIRED"
RESERVATION_CANCELLED = "CANCELLED"
ACTIVE_RESERVATION_STATUSES = frozenset(
    {RESERVATION_HELD, RESERVATION_CONFIRMED}
)

PAYMENT_PENDING = "PENDING"
PAYMENT_PROCESSING = "PROCESSING"
PAYMENT_VERIFIED = "VERIFIED"
PAYMENT_FAILED = "FAILED"
PAYMENT_REFUNDED = "REFUNDED"
PAYMENT_LEGACY_RECORDED = "LEGACY_RECORDED"

VERIFICATION_PENDING = "PENDING"
VERIFICATION_VERIFIED = "VERIFIED"
VERIFICATION_SUSPENDED = "SUSPENDED"
VERIFICATION_REVOKED = "REVOKED"
VERIFICATION_STATES = frozenset(
    {
        VERIFICATION_PENDING,
        VERIFICATION_VERIFIED,
        VERIFICATION_SUSPENDED,
        VERIFICATION_REVOKED,
    }
)

OPPORTUNITY_EVENT = "EVENT"
OPPORTUNITY_LONG_TERM = "LONG_TERM"
OPPORTUNITY_RECURRING = "RECURRING"
OPPORTUNITY_TYPES = frozenset(
    {OPPORTUNITY_EVENT, OPPORTUNITY_LONG_TERM, OPPORTUNITY_RECURRING}
)

PUBLICATION_DRAFT = "DRAFT"
PUBLICATION_PUBLISHED = "PUBLISHED"
PUBLICATION_PAUSED = "PAUSED"
PUBLICATION_ARCHIVED = "ARCHIVED"
PUBLICATION_STATES = frozenset(
    {
        PUBLICATION_DRAFT,
        PUBLICATION_PUBLISHED,
        PUBLICATION_PAUSED,
        PUBLICATION_ARCHIVED,
    }
)

INVENTORY_DRAFT = "DRAFT"
INVENTORY_ACTIVE = "ACTIVE"
INVENTORY_PAUSED = "PAUSED"
INVENTORY_CLOSED = "CLOSED"
INVENTORY_STATES = frozenset(
    {INVENTORY_DRAFT, INVENTORY_ACTIVE, INVENTORY_PAUSED, INVENTORY_CLOSED}
)

OPPORTUNITY_PUBLIC = "PUBLIC"
OPPORTUNITY_PRIVATE = "PRIVATE"
BOOKING_POLICY_INSTANT = "INSTANT"


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255))
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    nickname = db.Column(db.String(50))
    birth_date = db.Column(db.Date)
    phone_number = db.Column(db.String(20))
    # Retained as the primary/legacy role while UserRole stores all memberships.
    role = db.Column(db.String(20), nullable=False)
    is_admin = db.Column(
        db.Boolean,
        default=False,
        server_default=db.false(),
        nullable=False,
    )
    status = db.Column(db.String(20), default="active", server_default="active", nullable=False)
    reputation_score = db.Column(db.Float, default=5.0, nullable=False)
    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(UTC),
        server_default=db.func.now(),
        nullable=False,
    )
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        server_default=db.func.now(),
        nullable=False,
    )
    profile_completed_at = db.Column(db.DateTime)

    stalls = db.relationship("Stall", back_populates="owner", cascade="all, delete-orphan")
    bookings = db.relationship("Booking", back_populates="user", cascade="all, delete-orphan")
    vendor_profile = db.relationship(
        "VendorProfile",
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False,
    )
    role_memberships = db.relationship(
        "UserRole",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    auth_identities = db.relationship(
        "AuthIdentity",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    certification_reviews = db.relationship(
        "StallCertification",
        back_populates="reviewed_by",
        foreign_keys="StallCertification.reviewed_by_user_id",
    )
    managed_providers = db.relationship("Provider", back_populates="managing_user")

    @property
    def display_name(self) -> str:
        if self.nickname:
            return self.nickname
        return " ".join(part for part in (self.first_name, self.last_name) if part).strip()

    @property
    def role_names(self) -> frozenset[str]:
        roles = {membership.role for membership in self.role_memberships}
        roles.add(self.role)
        return frozenset(roles)

    def has_role(self, role: str) -> bool:
        return role in self.role_names

    @property
    def needs_profile_completion(self) -> bool:
        has_google_identity = any(
            identity.provider == "google" for identity in self.auth_identities
        )
        return has_google_identity and self.profile_completed_at is None

    def __repr__(self) -> str:
        return f"<User {self.username} ({', '.join(sorted(self.role_names))})>"


class UserRole(db.Model):
    __tablename__ = "user_role"

    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), primary_key=True)
    role = db.Column(db.String(20), primary_key=True)
    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(UTC),
        server_default=db.func.now(),
        nullable=False,
    )

    user = db.relationship("User", back_populates="role_memberships")


class AuthIdentity(db.Model):
    __tablename__ = "auth_identity"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider = db.Column(db.String(30), nullable=False)
    provider_subject = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(320))
    email_verified = db.Column(db.Boolean, default=False, nullable=False)
    display_name = db.Column(db.String(255))
    picture_url = db.Column(db.Text)
    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(UTC),
        server_default=db.func.now(),
        nullable=False,
    )
    last_login_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(UTC),
        server_default=db.func.now(),
        nullable=False,
    )

    user = db.relationship("User", back_populates="auth_identities")

    __table_args__ = (
        UniqueConstraint("provider", "provider_subject", name="uq_auth_identity_provider_subject"),
    )


class VendorProfile(db.Model):
    __tablename__ = "vendor_profile"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    brand_name = db.Column(db.String(100), nullable=False)
    primary_category = db.Column(db.String(40), nullable=False, index=True)
    brand_description = db.Column(db.Text)
    instagram_url = db.Column(db.Text)
    facebook_url = db.Column(db.Text)
    website_url = db.Column(db.Text)
    contact_name = db.Column(db.String(100), nullable=False)
    contact_phone = db.Column(db.String(30), nullable=False)
    contact_email = db.Column(db.String(320))
    food_registration_number = db.Column(db.String(100))
    profile_image_filename = db.Column(db.String(255))
    profile_image_content_type = db.Column(db.String(80))
    profile_image_byte_size = db.Column(db.Integer)
    profile_image_sha256 = db.Column(db.String(64))
    profile_image_data = deferred(db.Column(db.LargeBinary))
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=db.func.now(),
        nullable=False,
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        server_default=db.func.now(),
        nullable=False,
    )

    user = db.relationship("User", back_populates="vendor_profile")

    @property
    def has_profile_image(self) -> bool:
        return bool(self.profile_image_filename and self.profile_image_content_type)

    def __repr__(self) -> str:
        return f"<VendorProfile {self.brand_name!r}>"


class Provider(db.Model):
    __tablename__ = "provider"

    id = db.Column(db.Integer, primary_key=True)
    managing_user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    display_name = db.Column(db.String(120), nullable=False)
    legal_name = db.Column(db.String(160))
    description = db.Column(db.Text)
    contact_name = db.Column(db.String(100), nullable=False)
    contact_phone = db.Column(db.String(30), nullable=False)
    contact_email = db.Column(db.String(320))
    verification_status = db.Column(
        db.String(20),
        default=VERIFICATION_PENDING,
        server_default=VERIFICATION_PENDING,
        nullable=False,
        index=True,
    )
    verified_at = db.Column(db.DateTime(timezone=True))
    verification_expires_at = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=db.func.now(),
        nullable=False,
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        server_default=db.func.now(),
        nullable=False,
    )

    managing_user = db.relationship("User", back_populates="managed_providers")
    venues = db.relationship(
        "Venue", back_populates="provider", cascade="all, delete-orphan"
    )
    opportunities = db.relationship(
        "Opportunity", back_populates="provider", cascade="all, delete-orphan"
    )

    __table_args__ = (
        db.CheckConstraint(
            "verification_status IN ('PENDING', 'VERIFIED', 'SUSPENDED', 'REVOKED')",
            name="ck_provider_verification_status",
        ),
    )


class Venue(db.Model):
    __tablename__ = "venue"

    id = db.Column(db.Integer, primary_key=True)
    provider_id = db.Column(
        db.Integer,
        db.ForeignKey("provider.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = db.Column(db.String(140), nullable=False)
    country_code = db.Column(db.String(2), default="TW", server_default="TW", nullable=False)
    city = db.Column(db.String(80), nullable=False)
    district = db.Column(db.String(80))
    address_line = db.Column(db.String(255), nullable=False)
    postal_code = db.Column(db.String(20))
    business_description = db.Column(db.Text)
    verification_status = db.Column(
        db.String(20),
        default=VERIFICATION_PENDING,
        server_default=VERIFICATION_PENDING,
        nullable=False,
        index=True,
    )
    verified_at = db.Column(db.DateTime(timezone=True))
    verification_expires_at = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=db.func.now(),
        nullable=False,
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        server_default=db.func.now(),
        nullable=False,
    )

    provider = db.relationship("Provider", back_populates="venues")
    opportunities = db.relationship("Opportunity", back_populates="venue")

    __table_args__ = (
        db.CheckConstraint(
            "verification_status IN ('PENDING', 'VERIFIED', 'SUSPENDED', 'REVOKED')",
            name="ck_venue_verification_status",
        ),
    )


class Opportunity(db.Model):
    __tablename__ = "opportunity"

    id = db.Column(db.Integer, primary_key=True)
    provider_id = db.Column(
        db.Integer,
        db.ForeignKey("provider.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    venue_id = db.Column(
        db.Integer,
        db.ForeignKey("venue.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    title = db.Column(db.String(180), nullable=False)
    description = db.Column(db.Text)
    opportunity_type = db.Column(db.String(20), nullable=False)
    visibility = db.Column(
        db.String(20),
        default=OPPORTUNITY_PUBLIC,
        server_default=OPPORTUNITY_PUBLIC,
        nullable=False,
    )
    publication_status = db.Column(
        db.String(20),
        default=PUBLICATION_DRAFT,
        server_default=PUBLICATION_DRAFT,
        nullable=False,
        index=True,
    )
    booking_policy = db.Column(
        db.String(30),
        default=BOOKING_POLICY_INSTANT,
        server_default=BOOKING_POLICY_INSTANT,
        nullable=False,
    )
    pricing_context = db.Column(db.Text)
    requirements_summary = db.Column(db.Text)
    required_requirement_types = db.Column(db.JSON, nullable=False, default=list)
    cancellation_policy = db.Column(db.Text)
    published_at = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=db.func.now(),
        nullable=False,
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        server_default=db.func.now(),
        nullable=False,
    )

    provider = db.relationship("Provider", back_populates="opportunities")
    venue = db.relationship("Venue", back_populates="opportunities")
    inventory_groups = db.relationship(
        "InventoryGroup", back_populates="opportunity", cascade="all, delete-orphan"
    )

    __table_args__ = (
        db.CheckConstraint(
            "opportunity_type IN ('EVENT', 'LONG_TERM', 'RECURRING')",
            name="ck_opportunity_type",
        ),
        db.CheckConstraint(
            "visibility IN ('PUBLIC', 'PRIVATE')",
            name="ck_opportunity_visibility",
        ),
        db.CheckConstraint(
            "publication_status IN ('DRAFT', 'PUBLISHED', 'PAUSED', 'ARCHIVED')",
            name="ck_opportunity_publication_status",
        ),
        db.CheckConstraint(
            "booking_policy = 'INSTANT'",
            name="ck_opportunity_booking_policy",
        ),
    )


class InventoryGroup(db.Model):
    __tablename__ = "inventory_group"

    id = db.Column(db.Integer, primary_key=True)
    opportunity_id = db.Column(
        db.Integer,
        db.ForeignKey("opportunity.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    service_period_start = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    service_period_end = db.Column(db.DateTime(timezone=True), nullable=False)
    allocated_capacity = db.Column(db.Integer, nullable=False)
    price_amount = db.Column(db.Integer, nullable=False)
    currency = db.Column(db.String(3), default="TWD", server_default="TWD", nullable=False)
    status = db.Column(
        db.String(20),
        default=INVENTORY_DRAFT,
        server_default=INVENTORY_DRAFT,
        nullable=False,
        index=True,
    )
    required_requirement_types = db.Column(db.JSON, nullable=False, default=list)
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=db.func.now(),
        nullable=False,
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        server_default=db.func.now(),
        nullable=False,
    )

    opportunity = db.relationship("Opportunity", back_populates="inventory_groups")
    category_quotas = db.relationship(
        "InventoryCategoryQuota",
        back_populates="inventory_group",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    bookings = db.relationship("Booking", back_populates="inventory_group")

    __table_args__ = (
        db.CheckConstraint("allocated_capacity >= 0", name="ck_inventory_group_capacity"),
        db.CheckConstraint("price_amount >= 0", name="ck_inventory_group_price"),
        db.CheckConstraint(
            "service_period_end > service_period_start",
            name="ck_inventory_group_service_period",
        ),
        db.CheckConstraint(
            "status IN ('DRAFT', 'ACTIVE', 'PAUSED', 'CLOSED')",
            name="ck_inventory_group_status",
        ),
    )


class InventoryCategoryQuota(db.Model):
    __tablename__ = "inventory_category_quota"

    id = db.Column(db.Integer, primary_key=True)
    inventory_group_id = db.Column(
        db.Integer,
        db.ForeignKey("inventory_group.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    category = db.Column(db.String(40), nullable=False)
    capacity = db.Column(db.Integer, nullable=False)

    inventory_group = db.relationship("InventoryGroup", back_populates="category_quotas")

    __table_args__ = (
        UniqueConstraint(
            "inventory_group_id",
            "category",
            name="uq_inventory_category_quota_group_category",
        ),
        db.CheckConstraint("capacity >= 0", name="ck_inventory_category_quota_capacity"),
    )


class SupplyAuditEvent(db.Model):
    __tablename__ = "supply_audit_event"

    id = db.Column(db.Integer, primary_key=True)
    actor_user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", ondelete="SET NULL"),
        index=True,
    )
    provider_id = db.Column(
        db.Integer,
        db.ForeignKey("provider.id", ondelete="SET NULL"),
        index=True,
    )
    entity_type = db.Column(db.String(40), nullable=False)
    entity_id = db.Column(db.Integer, nullable=False)
    event_type = db.Column(db.String(60), nullable=False, index=True)
    before_data = db.Column(db.JSON)
    after_data = db.Column(db.JSON)
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=db.func.now(),
        nullable=False,
    )


class Stall(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    loc_name = db.Column(db.String(100), nullable=False)
    city = db.Column(db.String(20), nullable=False)
    district = db.Column(db.String(20), nullable=False)
    road = db.Column(db.String(50), nullable=False)
    address_detail = db.Column(db.String(100), nullable=False)
    facilities = db.Column(db.Text)
    environment_type = db.Column(
        db.String(20),
        default="unspecified",
        server_default="unspecified",
        nullable=False,
    )
    booking_mode = db.Column(
        db.String(20),
        default="hourly",
        server_default="hourly",
        nullable=False,
    )
    minimum_booking_hours = db.Column(
        db.Integer,
        default=1,
        server_default="1",
        nullable=False,
    )

    owner = db.relationship("User", back_populates="stalls")
    slots = db.relationship("Slot", back_populates="stall", cascade="all, delete-orphan")
    photos = db.relationship(
        "StallPhoto",
        back_populates="stall",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="StallPhoto.display_order",
    )
    certification = db.relationship(
        "StallCertification",
        back_populates="stall",
        cascade="all, delete-orphan",
        uselist=False,
    )

    @property
    def is_certified(self) -> bool:
        return self.certification is not None and self.certification.status == "approved"

    def __repr__(self) -> str:
        return f"<Stall {self.loc_name}>"


class StallPhoto(db.Model):
    __tablename__ = "stall_photo"

    id = db.Column(db.Integer, primary_key=True)
    stall_id = db.Column(
        db.Integer,
        db.ForeignKey("stall.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    original_filename = db.Column(db.String(255), nullable=False)
    content_type = db.Column(db.String(80), nullable=False)
    byte_size = db.Column(db.Integer, nullable=False)
    sha256 = db.Column(db.String(64), nullable=False)
    display_order = db.Column(db.Integer, nullable=False)
    data = deferred(db.Column(db.LargeBinary, nullable=False))
    uploaded_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(UTC),
        server_default=db.func.now(),
        nullable=False,
    )

    stall = db.relationship("Stall", back_populates="photos")

    __table_args__ = (
        UniqueConstraint("stall_id", "display_order", name="uq_stall_photo_display_order"),
    )

    def __repr__(self) -> str:
        return f"<StallPhoto stall={self.stall_id} order={self.display_order}>"


class Slot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    stall_id = db.Column(db.Integer, db.ForeignKey("stall.id"), nullable=False)
    date = db.Column(db.Date, nullable=False)
    time = db.Column(db.Integer, nullable=False)
    duration_hours = db.Column(db.Integer, default=1, server_default="1", nullable=False)
    price = db.Column(db.Integer, nullable=False)

    stall = db.relationship("Stall", back_populates="slots")
    bookings = db.relationship("Booking", back_populates="slot")

    @property
    def has_active_reservation(self) -> bool:
        return any(
            booking.reservation_status in ACTIVE_RESERVATION_STATUSES
            for booking in self.bookings
        )

    def __repr__(self) -> str:
        return (
            f"<Slot {self.date} {self.time}:00 "
            f"+{self.duration_hours}h ${self.price}>"
        )


class StallCertification(db.Model):
    __tablename__ = "stall_certification"

    id = db.Column(db.Integer, primary_key=True)
    stall_id = db.Column(
        db.Integer,
        db.ForeignKey("stall.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    applicant_legal_name = db.Column(db.String(100), nullable=False)
    applicant_phone = db.Column(db.String(30), nullable=False)
    relationship_to_space = db.Column(db.String(40), nullable=False)
    proof_type = db.Column(db.String(40), nullable=False)
    proof_reference = db.Column(db.String(120))
    declaration_accepted = db.Column(
        db.Boolean,
        default=False,
        server_default=db.false(),
        nullable=False,
    )
    status = db.Column(
        db.String(20),
        default="pending",
        server_default="pending",
        nullable=False,
        index=True,
    )
    submitted_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(UTC),
        server_default=db.func.now(),
        nullable=False,
    )
    reviewed_at = db.Column(db.DateTime)
    reviewed_by_user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", ondelete="SET NULL"),
        index=True,
    )
    reviewer_reference = db.Column(db.String(100))
    review_note = db.Column(db.Text)

    stall = db.relationship("Stall", back_populates="certification")
    reviewed_by = db.relationship(
        "User",
        back_populates="certification_reviews",
        foreign_keys=[reviewed_by_user_id],
    )
    documents = db.relationship(
        "StallCertificationDocument",
        back_populates="certification",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="StallCertificationDocument.uploaded_at",
    )

    def __repr__(self) -> str:
        return f"<StallCertification stall={self.stall_id} status={self.status}>"


class StallCertificationDocument(db.Model):
    __tablename__ = "stall_certification_document"

    id = db.Column(db.Integer, primary_key=True)
    certification_id = db.Column(
        db.Integer,
        db.ForeignKey("stall_certification.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    original_filename = db.Column(db.String(255), nullable=False)
    content_type = db.Column(db.String(80), nullable=False)
    byte_size = db.Column(db.Integer, nullable=False)
    sha256 = db.Column(db.String(64), nullable=False)
    nonce = db.Column(db.LargeBinary(12), nullable=False)
    ciphertext = db.Column(db.LargeBinary, nullable=False)
    uploaded_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(UTC),
        server_default=db.func.now(),
        nullable=False,
    )

    certification = db.relationship("StallCertification", back_populates="documents")

    def __repr__(self) -> str:
        return f"<StallCertificationDocument {self.original_filename!r}>"


class PaymentTransaction(db.Model):
    __tablename__ = "payment_transaction"

    id = db.Column(db.Integer, primary_key=True)
    provider = db.Column(db.String(50))
    merchant_order_id = db.Column(db.String(64), nullable=False, unique=True)
    provider_transaction_id = db.Column(db.String(128), unique=True)
    amount = db.Column(db.Integer, nullable=False)
    currency = db.Column(db.String(3), default="TWD", server_default="TWD", nullable=False)
    status = db.Column(
        db.String(20),
        default=PAYMENT_PENDING,
        server_default=PAYMENT_PENDING,
        nullable=False,
        index=True,
    )
    initiated_at = db.Column(db.DateTime(timezone=True))
    verified_at = db.Column(db.DateTime(timezone=True))
    provider_metadata = db.Column(db.JSON)
    failure_reason = db.Column(db.String(255))
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=db.func.now(),
        nullable=False,
    )

    bookings = db.relationship("Booking", back_populates="payment", lazy="selectin")

    def __repr__(self) -> str:
        return f"<PaymentTransaction {self.merchant_order_id} {self.status}>"


class BookingRequirements(db.Model):
    __tablename__ = "booking_requirement"

    id = db.Column(db.Integer, primary_key=True)
    electricity_required = db.Column(
        db.Boolean,
        default=False,
        server_default=db.false(),
        nullable=False,
    )
    electricity_details = db.Column(db.String(255))
    gas_required = db.Column(
        db.Boolean,
        default=False,
        server_default=db.false(),
        nullable=False,
    )
    gas_details = db.Column(db.String(255))
    equipment_requirements = db.Column(db.Text)
    vehicle_plate = db.Column(db.String(20))
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=db.func.now(),
        nullable=False,
    )

    bookings = db.relationship("Booking", back_populates="requirements")

    def __repr__(self) -> str:
        return f"<BookingRequirements {self.id}>"


class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    slot_id = db.Column(db.Integer, db.ForeignKey("slot.id"))
    inventory_group_id = db.Column(
        db.Integer,
        db.ForeignKey("inventory_group.id", ondelete="RESTRICT"),
        index=True,
    )
    vendor_category = db.Column(db.String(40), index=True)
    payment_id = db.Column(
        db.Integer,
        db.ForeignKey("payment_transaction.id", ondelete="SET NULL"),
        index=True,
    )
    requirements_id = db.Column(
        db.Integer,
        db.ForeignKey("booking_requirement.id", ondelete="SET NULL"),
        index=True,
    )
    qr_code = db.Column(db.String(100), nullable=False, index=True)
    reservation_status = db.Column(
        db.String(20),
        default=RESERVATION_HELD,
        server_default=RESERVATION_HELD,
        nullable=False,
        index=True,
    )
    hold_expires_at = db.Column(db.DateTime(timezone=True), index=True)
    confirmed_at = db.Column(db.DateTime(timezone=True))
    # Keep the original columns as historical evidence. They are never trusted
    # as proof that a payment provider verified a transaction.
    legacy_payment_status = db.Column(
        "payment_status",
        db.String(20),
        default="NotApplicable",
        server_default="NotApplicable",
        nullable=False,
    )
    legacy_payment_method = db.Column(
        "payment_method",
        db.String(20),
        default="",
        server_default="",
        nullable=False,
    )
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(UTC), nullable=False)

    user = db.relationship("User", back_populates="bookings")
    slot = db.relationship("Slot", back_populates="bookings")
    inventory_group = db.relationship("InventoryGroup", back_populates="bookings")
    payment = db.relationship("PaymentTransaction", back_populates="bookings")
    requirements = db.relationship("BookingRequirements", back_populates="bookings")
    reviews = db.relationship("Review", back_populates="booking", cascade="all, delete-orphan")

    __table_args__ = (
        db.Index(
            "uq_booking_active_slot",
            "slot_id",
            unique=True,
            postgresql_where=db.text(
                "reservation_status IN ('HELD', 'CONFIRMED')"
            ),
            sqlite_where=db.text("reservation_status IN ('HELD', 'CONFIRMED')"),
        ),
        db.Index(
            "ix_booking_inventory_active",
            "inventory_group_id",
            "reservation_status",
            "hold_expires_at",
        ),
    )

    @property
    def payment_state(self) -> str:
        if self.payment is None:
            return PAYMENT_LEGACY_RECORDED
        return self.payment.status

    def __repr__(self) -> str:
        return f"<Booking {self.id} {self.qr_code} {self.reservation_status}>"


class StallPrice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    stall_id = db.Column(db.Integer, db.ForeignKey("stall.id"), nullable=False)
    date = db.Column(db.Date, nullable=False)
    hour = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Integer, nullable=False)

    stall = db.relationship("Stall")


class Review(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey("booking.id"), nullable=False)
    reviewer_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    reviewee_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    rating = db.Column(db.Integer, nullable=False)
    comment = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(UTC), nullable=False)

    booking = db.relationship("Booking", back_populates="reviews")
    reviewer = db.relationship("User", foreign_keys=[reviewer_id], backref="reviews_written")
    reviewee = db.relationship("User", foreign_keys=[reviewee_id], backref="reviews_received")

    __table_args__ = (
        UniqueConstraint("booking_id", "reviewer_id", name="uq_review_booking_reviewer"),
    )


class ImportBatch(db.Model):
    """Audit record for one crawler or spreadsheet import."""

    id = db.Column(db.Integer, primary_key=True)
    source_name = db.Column(db.String(100), nullable=False)
    source_path = db.Column(db.String(500), nullable=False)
    source_digest = db.Column(db.String(64), nullable=False, index=True)
    status = db.Column(db.String(20), default="completed", nullable=False)
    record_count = db.Column(db.Integer, default=0, nullable=False)
    created_count = db.Column(db.Integer, default=0, nullable=False)
    updated_count = db.Column(db.Integer, default=0, nullable=False)
    skipped_count = db.Column(db.Integer, default=0, nullable=False)
    is_test_data = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(UTC), nullable=False)
    completed_at = db.Column(db.DateTime, default=lambda: datetime.now(UTC), nullable=False)

    leads = db.relationship("ExternalMarketLead", back_populates="last_import_batch")


class ExternalMarketLead(db.Model):
    """A private, source-traceable announcement awaiting marketplace review."""

    id = db.Column(db.Integer, primary_key=True)
    source_name = db.Column(db.String(100), nullable=False)
    source_url = db.Column(db.String(500), nullable=False, unique=True)
    source_file = db.Column(db.String(255), nullable=False)
    source_dir = db.Column(db.String(255), nullable=False)
    content_hash = db.Column(db.String(64), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    date_text = db.Column(db.Text, nullable=False)
    time_text = db.Column(db.String(255), nullable=False)
    location_text = db.Column(db.Text, nullable=False)
    fee_text = db.Column(db.Text, nullable=False)
    contact_text = db.Column(db.Text, nullable=False)
    raw_payload = db.Column(db.JSON, nullable=False)
    review_status = db.Column(db.String(30), default="needs_review", nullable=False)
    is_bookable = db.Column(db.Boolean, default=False, nullable=False)
    is_test_data = db.Column(db.Boolean, default=False, nullable=False)
    first_seen_at = db.Column(db.DateTime, default=lambda: datetime.now(UTC), nullable=False)
    last_seen_at = db.Column(db.DateTime, default=lambda: datetime.now(UTC), nullable=False)
    last_import_batch_id = db.Column(db.Integer, db.ForeignKey("import_batch.id"), nullable=False)

    last_import_batch = db.relationship("ImportBatch", back_populates="leads")


def recalculate_reputation(user: User) -> None:
    reviews = Review.query.filter_by(reviewee_id=user.id).all()
    if not reviews:
        return
    user.reputation_score = round(sum(review.rating for review in reviews) / len(reviews), 1)
