from __future__ import annotations

import uuid

from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models import Booking, Slot, Stall, User


class BookingSelectionError(ValueError):
    """Raised when requested slots violate availability or the stall policy."""


class PaymentMethodError(ValueError):
    """Raised when checkout requests an unsupported payment method."""


ONLINE_PAYMENT_METHOD = "Credit Card"


def filter_bookable_slots(stall: Stall, slots: list[Slot]) -> list[Slot]:
    """Remove hourly fragments that cannot satisfy the stall minimum."""

    if not stall.is_certified:
        return []
    if stall.booking_mode == "daily":
        return [slot for slot in slots if slot.duration_hours >= 1]
    if stall.booking_mode != "hourly" or stall.minimum_booking_hours not in {1, 2, 3}:
        return []

    slots_by_date = {}
    for slot in slots:
        if slot.duration_hours == 1:
            slots_by_date.setdefault(slot.date, []).append(slot)

    bookable_ids = set()
    minimum_hours = stall.minimum_booking_hours
    for date_slots in slots_by_date.values():
        run = []
        for slot in sorted(date_slots, key=lambda item: item.time):
            if run and slot.time != run[-1].time + 1:
                if len(run) >= minimum_hours:
                    bookable_ids.update(item.id for item in run)
                run = []
            run.append(slot)
        if len(run) >= minimum_hours:
            bookable_ids.update(item.id for item in run)

    return [slot for slot in slots if slot.id in bookable_ids]


def create_booking_for_slots(user_id: int, slot_ids: list[int]) -> tuple[str | None, int]:
    user = db.session.get(User, user_id)
    if user is None or not slot_ids:
        return None, 0

    try:
        normalized_slot_ids = [int(slot_id) for slot_id in slot_ids]
    except (TypeError, ValueError):
        raise BookingSelectionError("預約時段資料無效，請重新選擇。") from None
    if len(set(normalized_slot_ids)) != len(normalized_slot_ids):
        raise BookingSelectionError("請勿重複選擇同一個時段。")

    slots = (
        Slot.query.filter(Slot.id.in_(normalized_slot_ids))
        .with_for_update()
        .all()
    )
    if len(slots) != len(normalized_slot_ids):
        raise BookingSelectionError("部分時段不存在，請重新選擇。")
    if Booking.query.filter(Booking.slot_id.in_(normalized_slot_ids)).first() is not None:
        raise BookingSelectionError("部分時段已被預約，請重新選擇。")

    _validate_booking_policy(slots)

    qr_code = str(uuid.uuid4())[:8].upper()
    for slot in slots:
        db.session.add(Booking(user=user, slot=slot, qr_code=qr_code, payment_status="Unpaid"))

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise BookingSelectionError("部分時段剛被其他使用者預約，請重新選擇。") from None

    return qr_code, len(slots)


def _validate_booking_policy(slots: list[Slot]) -> None:
    stalls = {slot.stall_id for slot in slots}
    dates = {slot.date for slot in slots}
    if len(stalls) != 1 or len(dates) != 1:
        raise BookingSelectionError("一次預約只能選擇同一攤位、同一天的時段。")

    stall = slots[0].stall
    if not stall.is_certified:
        raise BookingSelectionError("此攤位尚未通過平台場地認證，暫時無法預約。")
    if stall.booking_mode == "daily":
        if len(slots) != 1 or slots[0].duration_hours < 1:
            raise BookingSelectionError("此攤位採整日出租，必須預約完整開放時段。")
        return

    if stall.booking_mode != "hourly":
        raise BookingSelectionError("此攤位的出租方式設定無效，請聯絡場地主。")
    if any(slot.duration_hours != 1 for slot in slots):
        raise BookingSelectionError("按小時出租的時段資料無效，請聯絡場地主。")

    minimum_hours = stall.minimum_booking_hours
    if minimum_hours not in {1, 2, 3}:
        raise BookingSelectionError("此攤位的最低預約時數設定無效。")
    if len(slots) < minimum_hours:
        raise BookingSelectionError(f"此攤位每次至少需要預約 {minimum_hours} 小時。")

    hours = sorted(slot.time for slot in slots)
    if any(current != previous + 1 for previous, current in zip(hours, hours[1:])):
        raise BookingSelectionError("所選時段必須連續，不能跳過中間時段。")


def apply_payment_to_qr(qr_code: str, payment_method: str) -> bool:
    if payment_method != ONLINE_PAYMENT_METHOD:
        raise PaymentMethodError("目前只接受線上信用卡付款。")

    bookings = Booking.query.filter_by(qr_code=qr_code).all()
    if not bookings:
        return False

    for booking in bookings:
        booking.payment_status = "Paid"
        booking.payment_method = ONLINE_PAYMENT_METHOD
    db.session.commit()
    return True
