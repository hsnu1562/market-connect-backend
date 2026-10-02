from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import UniqueConstraint

from .extensions import db


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
        required_profile_data = (
            self.profile_completed_at,
            self.nickname,
            self.birth_date,
            self.phone_number,
            self.first_name,
            self.last_name,
        )
        return has_google_identity and not all(required_profile_data)

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


class Stall(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    loc_name = db.Column(db.String(100), nullable=False)
    city = db.Column(db.String(20), nullable=False)
    district = db.Column(db.String(20), nullable=False)
    road = db.Column(db.String(50), nullable=False)
    address_detail = db.Column(db.String(100), nullable=False)
    facilities = db.Column(db.Text)

    owner = db.relationship("User", back_populates="stalls")
    slots = db.relationship("Slot", back_populates="stall", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Stall {self.loc_name}>"


class Slot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    stall_id = db.Column(db.Integer, db.ForeignKey("stall.id"), nullable=False)
    date = db.Column(db.Date, nullable=False)
    time = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Integer, nullable=False)

    stall = db.relationship("Stall", back_populates="slots")
    booking = db.relationship("Booking", back_populates="slot", uselist=False)

    def __repr__(self) -> str:
        return f"<Slot {self.date} {self.time}:00 ${self.price}>"


class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    slot_id = db.Column(db.Integer, db.ForeignKey("slot.id"), nullable=False, unique=True)
    qr_code = db.Column(db.String(100), nullable=False, index=True)
    payment_status = db.Column(db.String(20), default="Unpaid", nullable=False)
    payment_method = db.Column(db.String(20), default="", nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(UTC), nullable=False)

    user = db.relationship("User", back_populates="bookings")
    slot = db.relationship("Slot", back_populates="booking")
    reviews = db.relationship("Review", back_populates="booking", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Booking {self.id} {self.qr_code}>"


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
