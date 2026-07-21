from __future__ import annotations

from ..extensions import db
from ..models import Booking, Review, User, recalculate_reputation


def create_review_for_booking(
    booking_id: int,
    reviewer_id: int,
    user_role: str | None,
    rating: int,
    comment: str = "",
) -> bool:
    booking = db.session.get(Booking, booking_id)
    reviewer = db.session.get(User, reviewer_id)
    if booking is None or reviewer is None:
        return False

    existing = Review.query.filter_by(booking_id=booking.id, reviewer_id=reviewer.id).first()
    if existing:
        return False

    reviewee = booking.user if user_role == "Landlord" else booking.slot.stall.owner
    review = Review(
        booking=booking,
        reviewer=reviewer,
        reviewee=reviewee,
        rating=rating,
        comment=comment,
    )
    db.session.add(review)
    db.session.flush()
    recalculate_reputation(reviewee)
    db.session.commit()
    return True
