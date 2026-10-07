from __future__ import annotations

from datetime import datetime

from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models import (
    PAYMENT_FAILED,
    PAYMENT_PENDING,
    PAYMENT_PROCESSING,
    PAYMENT_VERIFIED,
    RESERVATION_CONFIRMED,
    RESERVATION_EXPIRED,
    RESERVATION_HELD,
    Booking,
    PaymentTransaction,
)
from .bookings import as_utc, hold_is_expired, utc_now


class PaymentStateError(ValueError):
    """Raised when a trusted payment transition violates the state machine."""


def begin_payment(
    payment_id: int,
    provider: str,
    *,
    now: datetime | None = None,
) -> PaymentTransaction:
    """Begin a provider checkout from trusted server-side integration code."""

    provider_name = provider.strip()
    if not provider_name:
        raise PaymentStateError("Payment provider is required.")

    payment, bookings = _locked_payment_group(payment_id)
    if payment.status != PAYMENT_PENDING:
        raise PaymentStateError("Payment is not pending.")
    current_time = as_utc(now or utc_now())
    if _expire_if_overdue(payment, bookings, current_time):
        db.session.commit()
        raise PaymentStateError("Reservation hold has expired.")
    if not bookings or any(
        booking.reservation_status != RESERVATION_HELD for booking in bookings
    ):
        raise PaymentStateError("Reservation is not eligible for payment.")

    payment.provider = provider_name
    payment.status = PAYMENT_PROCESSING
    payment.initiated_at = current_time
    payment.failure_reason = None
    db.session.commit()
    return payment


def verify_payment(
    payment_id: int,
    provider_transaction_id: str,
    amount: int,
    currency: str,
    *,
    provider_metadata: dict | None = None,
    now: datetime | None = None,
) -> PaymentTransaction:
    """Confirm payment and reservation after a trusted provider verification."""

    transaction_id = provider_transaction_id.strip()
    if not transaction_id:
        raise PaymentStateError("Provider transaction ID is required.")

    payment, bookings = _locked_payment_group(payment_id)
    if payment.status != PAYMENT_PROCESSING:
        raise PaymentStateError("Payment is not processing.")
    current_time = as_utc(now or utc_now())
    if _expire_if_overdue(payment, bookings, current_time):
        db.session.commit()
        raise PaymentStateError("Reservation hold has expired.")
    if not bookings or any(
        booking.reservation_status != RESERVATION_HELD for booking in bookings
    ):
        raise PaymentStateError("Reservation is not eligible for confirmation.")
    if amount != payment.amount or currency.upper() != payment.currency:
        raise PaymentStateError("Verified payment amount or currency does not match.")
    duplicate = PaymentTransaction.query.filter(
        PaymentTransaction.provider_transaction_id == transaction_id,
        PaymentTransaction.id != payment.id,
    ).first()
    if duplicate is not None:
        raise PaymentStateError("Provider transaction ID has already been used.")

    payment.provider_transaction_id = transaction_id
    payment.provider_metadata = provider_metadata
    payment.status = PAYMENT_VERIFIED
    payment.verified_at = current_time
    for booking in bookings:
        booking.reservation_status = RESERVATION_CONFIRMED
        booking.confirmed_at = current_time

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise PaymentStateError("Payment verification conflicts with existing data.") from None
    return payment


def _locked_payment_group(
    payment_id: int,
) -> tuple[PaymentTransaction, list[Booking]]:
    bookings = (
        Booking.query.filter_by(payment_id=payment_id)
        .order_by(Booking.id)
        .with_for_update()
        .all()
    )
    payment = (
        PaymentTransaction.query.filter_by(id=payment_id).with_for_update().first()
    )
    if payment is None:
        raise PaymentStateError("Payment transaction was not found.")
    return payment, bookings


def _expire_if_overdue(
    payment: PaymentTransaction,
    bookings: list[Booking],
    now: datetime,
) -> bool:
    if not any(
        booking.reservation_status == RESERVATION_HELD
        and hold_is_expired(booking, now)
        for booking in bookings
    ):
        return False

    for booking in bookings:
        if booking.reservation_status == RESERVATION_HELD:
            booking.reservation_status = RESERVATION_EXPIRED
    payment.status = PAYMENT_FAILED
    payment.failure_reason = "hold_expired"
    return True
