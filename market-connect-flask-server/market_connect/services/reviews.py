from __future__ import annotations

from ..extensions import db
from ..models import (
    RESERVATION_CONFIRMED,
    Booking,
    Review,
    User,
    recalculate_reputation,
)


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
    if booking.reservation_status != RESERVATION_CONFIRMED:
        return False
    if user_role is None or not reviewer.has_role(user_role) or not 1 <= rating <= 5:
        return False

    if user_role == "Landlord":
        if booking.slot.stall.owner_id != reviewer.id:
            return False
        reviewee = booking.user
    elif user_role == "Tenant":
        if booking.user_id != reviewer.id:
            return False
        reviewee = booking.slot.stall.owner
    else:
        return False

    existing = Review.query.filter_by(booking_id=booking.id, reviewer_id=reviewer.id).first()
    if existing:
        return False

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
