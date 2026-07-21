from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import UniqueConstraint

from .extensions import db


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    phone_number = db.Column(db.String(20))
    role = db.Column(db.String(20), nullable=False)
    reputation_score = db.Column(db.Float, default=5.0, nullable=False)

    stalls = db.relationship("Stall", back_populates="owner", cascade="all, delete-orphan")
    bookings = db.relationship("Booking", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<User {self.username} ({self.role})>"


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


def recalculate_reputation(user: User) -> None:
    reviews = Review.query.filter_by(reviewee_id=user.id).all()
    if not reviews:
        return
    user.reputation_score = round(sum(review.rating for review in reviews) / len(reviews), 1)
