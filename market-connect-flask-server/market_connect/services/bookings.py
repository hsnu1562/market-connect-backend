from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from flask import current_app
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models import (
    ACTIVE_RESERVATION_STATUSES,
    PAYMENT_FAILED,
    PAYMENT_PENDING,
    PAYMENT_PROCESSING,
    RESERVATION_EXPIRED,
    RESERVATION_HELD,
    Booking,
    BookingRequirements,
    PaymentTransaction,
    Slot,
    Stall,
    User,
)


class BookingSelectionError(ValueError):
    """Raised when requested slots violate availability or the stall policy."""


class VendorProfileRequiredError(BookingSelectionError):
    """Raised when a booking account has no marketplace Vendor identity."""


def utc_now() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def hold_is_expired(booking: Booking, now: datetime | None = None) -> bool:
    if booking.hold_expires_at is None:
        return False
    return as_utc(booking.hold_expires_at) <= as_utc(now or utc_now())


def exclude_active_reservations(query):
    """Restrict a Slot query to inventory not held or confirmed."""

    return query.filter(
        ~Slot.bookings.any(Booking.reservation_status.in_(ACTIVE_RESERVATION_STATUSES))
    )


def expire_held_bookings(now: datetime | None = None, *, commit: bool = True) -> int:
    """Expire overdue holds on demand without deleting their audit history."""

    current_time = as_utc(now or utc_now())
    expired = (
        Booking.query.filter(
            Booking.reservation_status == RESERVATION_HELD,
            Booking.hold_expires_at.is_not(None),
            Booking.hold_expires_at <= current_time,
        )
        .order_by(Booking.id)
        .with_for_update()
        .all()
    )
    if not expired:
        return 0

    payment_ids = {booking.payment_id for booking in expired if booking.payment_id is not None}
    payments = []
    if payment_ids:
        payments = (
            PaymentTransaction.query.filter(PaymentTransaction.id.in_(payment_ids))
            .order_by(PaymentTransaction.id)
            .with_for_update()
            .all()
        )

    for booking in expired:
        booking.reservation_status = RESERVATION_EXPIRED
    for payment in payments:
        if payment.status in {PAYMENT_PENDING, PAYMENT_PROCESSING}:
            payment.status = PAYMENT_FAILED
            payment.failure_reason = "hold_expired"

    if commit:
        db.session.commit()
    else:
        db.session.flush()
    return len(expired)


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


def create_booking_for_slots(
    user_id: int,
    slot_ids: list[int],
    *,
    requirements: BookingRequirements | None = None,
    now: datetime | None = None,
) -> tuple[str | None, int]:
    user = db.session.get(User, user_id)
    if user is None or not slot_ids:
        return None, 0
    if not user.has_role("Tenant"):
        raise BookingSelectionError("此帳戶尚未啟用攤商功能。")
    if user.vendor_profile is None:
        raise VendorProfileRequiredError("預約前請先建立攤商品牌資料。")

    try:
        normalized_slot_ids = [int(slot_id) for slot_id in slot_ids]
    except (TypeError, ValueError):
        raise BookingSelectionError("預約時段資料無效，請重新選擇。") from None
    if len(set(normalized_slot_ids)) != len(normalized_slot_ids):
        raise BookingSelectionError("請勿重複選擇同一個時段。")

    current_time = as_utc(now or utc_now())
    expire_held_bookings(current_time)
    slots = (
        Slot.query.filter(Slot.id.in_(normalized_slot_ids))
        .with_for_update()
        .all()
    )
    if len(slots) != len(normalized_slot_ids):
        raise BookingSelectionError("部分時段不存在，請重新選擇。")
    if Booking.query.filter(
        Booking.slot_id.in_(normalized_slot_ids),
        Booking.reservation_status.in_(ACTIVE_RESERVATION_STATUSES),
    ).first() is not None:
        raise BookingSelectionError("部分時段已被預約，請重新選擇。")

    _validate_booking_policy(slots)

    try:
        hold_seconds = int(current_app.config["BOOKING_HOLD_SECONDS"])
    except (KeyError, TypeError, ValueError):
        raise RuntimeError("BOOKING_HOLD_SECONDS must be a positive integer.") from None
    if hold_seconds <= 0:
        raise RuntimeError("BOOKING_HOLD_SECONDS must be a positive integer.")

    qr_code = str(uuid.uuid4())[:8].upper()
    payment = PaymentTransaction(
        merchant_order_id=f"SPC-{uuid.uuid4().hex.upper()}",
        amount=sum(slot.price for slot in slots),
        currency="TWD",
        status=PAYMENT_PENDING,
    )
    db.session.add(payment)
    requirements_snapshot = requirements or BookingRequirements()
    db.session.add(requirements_snapshot)
    hold_expires_at = current_time + timedelta(seconds=hold_seconds)
    for slot in slots:
        db.session.add(
            Booking(
                user=user,
                slot=slot,
                payment=payment,
                requirements=requirements_snapshot,
                qr_code=qr_code,
                reservation_status=RESERVATION_HELD,
                hold_expires_at=hold_expires_at,
            )
        )

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
        raise BookingSelectionError("此攤位的出租方式設定無效，請聯絡供應方。")
    if any(slot.duration_hours != 1 for slot in slots):
        raise BookingSelectionError("按小時出租的時段資料無效，請聯絡供應方。")

    minimum_hours = stall.minimum_booking_hours
    if minimum_hours not in {1, 2, 3}:
        raise BookingSelectionError("此攤位的最低預約時數設定無效。")
    if len(slots) < minimum_hours:
        raise BookingSelectionError(f"此攤位每次至少需要預約 {minimum_hours} 小時。")

    hours = sorted(slot.time for slot in slots)
    if any(current != previous + 1 for previous, current in zip(hours, hours[1:])):
        raise BookingSelectionError("所選時段必須連續，不能跳過中間時段。")
