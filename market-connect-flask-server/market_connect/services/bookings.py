from __future__ import annotations

import uuid

from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models import Booking, Slot, User


def create_booking_for_slots(user_id: int, slot_ids: list[int]) -> tuple[str | None, int]:
    user = db.session.get(User, user_id)
    if user is None or not slot_ids:
        return None, 0

    qr_code = str(uuid.uuid4())[:8].upper()
    created_count = 0
    for slot_id in slot_ids:
        slot = db.session.get(Slot, int(slot_id))
        if slot is None or Booking.query.filter_by(slot_id=slot.id).first():
            continue
        db.session.add(Booking(user=user, slot=slot, qr_code=qr_code, payment_status="Unpaid"))
        created_count += 1

    if not created_count:
        return None, 0

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return None, 0

    return qr_code, created_count


def apply_payment_to_qr(qr_code: str, payment_method: str) -> bool:
    bookings = Booking.query.filter_by(qr_code=qr_code).all()
    if not bookings:
        return False

    payment_status = "Unpaid" if payment_method == "Cash" else "Paid"
    normalized_method = "Cash" if payment_method == "Cash" else "Credit Card"
    for booking in bookings:
        booking.payment_status = payment_status
        booking.payment_method = normalized_method
    db.session.commit()
    return True


def confirm_booking_payment(booking_id: int) -> bool:
    booking = db.session.get(Booking, booking_id)
    if booking is None:
        return False

    booking.payment_status = "Paid"
    db.session.commit()
    return True
