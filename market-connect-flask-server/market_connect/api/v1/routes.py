from __future__ import annotations

from datetime import date

from flask import Blueprint, jsonify, request

from ...models import Booking, Slot, Stall, StallCertification
from ...security import get_current_user
from ...services.bookings import (
    BookingSelectionError,
    apply_payment_to_qr,
    create_booking_for_slots,
    filter_bookable_slots,
)


bp = Blueprint("api_v1", __name__, url_prefix="/api/v1")
SERVICE_RELEASE = "20261004.09"


@bp.get("/health")
def health_check():
    return jsonify(
        {
            "release": SERVICE_RELEASE,
            "service": "market-connect-flask-server",
            "status": "ok",
        }
    )


@bp.get("/stalls")
def list_stalls():
    stalls = (
        Stall.query.join(StallCertification)
        .filter(StallCertification.status == "approved")
        .order_by(Stall.loc_name)
        .all()
    )
    return jsonify({"stalls": [_stall_payload(stall, include_slots=True) for stall in stalls]})


@bp.get("/stalls/<int:stall_id>/slots")
def list_available_slots(stall_id: int):
    stall = (
        Stall.query.join(StallCertification)
        .filter(Stall.id == stall_id, StallCertification.status == "approved")
        .first()
    )
    if stall is None:
        return jsonify({"error": "stall not found"}), 404
    available_slots = (
        Slot.query.outerjoin(Booking)
        .filter(
            Slot.stall_id == stall_id,
            Booking.id.is_(None),
            Slot.date >= date.today(),
        )
        .order_by(Slot.date, Slot.time)
        .all()
    )
    slots = filter_bookable_slots(stall, available_slots)
    return jsonify({"slots": [_slot_payload(slot) for slot in slots]})


@bp.post("/bookings")
def create_booking():
    user, error_response = _require_api_user("Tenant")
    if error_response is not None:
        return error_response

    payload = request.get_json(silent=True) or {}
    slot_ids = payload.get("slot_ids", [])
    if not isinstance(slot_ids, list) or not slot_ids:
        return jsonify({"error": "slot_ids are required"}), 400
    try:
        normalized_slot_ids = [int(slot_id) for slot_id in slot_ids]
    except (TypeError, ValueError):
        return jsonify({"error": "slot_ids must contain integers"}), 400

    try:
        qr_code, created_count = create_booking_for_slots(user.id, normalized_slot_ids)
    except BookingSelectionError as error:
        return jsonify({"error": str(error)}), 409
    if not created_count or qr_code is None:
        return jsonify({"error": "no available slots were booked"}), 409

    bookings = Booking.query.filter_by(qr_code=qr_code).all()
    return jsonify(
        {
            "booking_count": created_count,
            "bookings": [_booking_payload(booking) for booking in bookings],
            "qr_code": qr_code,
        }
    ), 201


@bp.get("/bookings/<qr_code>")
def get_booking_group(qr_code: str):
    user, error_response = _require_api_user()
    if error_response is not None:
        return error_response

    bookings = Booking.query.filter_by(qr_code=qr_code).order_by(Booking.id).all()
    if not bookings:
        return jsonify({"error": "booking not found"}), 404
    is_tenant_owner = user.has_role("Tenant") and all(
        booking.user_id == user.id for booking in bookings
    )
    is_landlord_owner = user.has_role("Landlord") and all(
        booking.slot.stall.owner_id == user.id for booking in bookings
    )
    if not (is_tenant_owner or is_landlord_owner):
        return jsonify({"error": "booking access denied"}), 403

    return jsonify(
        {
            "bookings": [_booking_payload(booking) for booking in bookings],
            "qr_code": qr_code,
            "total_price": sum(booking.slot.price for booking in bookings),
        }
    )


@bp.post("/payments")
def update_payment():
    user, error_response = _require_api_user("Tenant")
    if error_response is not None:
        return error_response

    payload = request.get_json(silent=True) or {}
    qr_code = payload.get("qr_code")
    payment_method = payload.get("payment_method", "Cash")
    if not qr_code:
        return jsonify({"error": "qr_code is required"}), 400
    bookings = Booking.query.filter_by(qr_code=qr_code).all()
    if not bookings:
        return jsonify({"error": "booking not found"}), 404
    if any(booking.user_id != user.id for booking in bookings):
        return jsonify({"error": "booking access denied"}), 403

    if not apply_payment_to_qr(qr_code, payment_method):
        return jsonify({"error": "booking not found"}), 404

    return jsonify({"payment_method": "Cash" if payment_method == "Cash" else "Credit Card", "qr_code": qr_code})


def _require_api_user(required_role: str | None = None):
    user = get_current_user()
    if user is None:
        return None, (jsonify({"error": "authentication required"}), 401)
    if required_role is not None and not user.has_role(required_role):
        return None, (jsonify({"error": "account role is not permitted"}), 403)
    return user, None


def _stall_payload(stall: Stall, include_slots: bool = False) -> dict:
    payload = {
        "address_detail": stall.address_detail,
        "city": stall.city,
        "district": stall.district,
        "environment_type": stall.environment_type,
        "facilities": stall.facilities,
        "id": stall.id,
        "loc_name": stall.loc_name,
        "owner_id": stall.owner_id,
        "road": stall.road,
        "booking_mode": stall.booking_mode,
        "certification_status": "approved",
        "minimum_booking_hours": stall.minimum_booking_hours,
    }
    if include_slots:
        available_slots = (
            Slot.query.outerjoin(Booking)
            .filter(
                Slot.stall_id == stall.id,
                Booking.id.is_(None),
                Slot.date >= date.today(),
            )
            .order_by(Slot.date, Slot.time)
            .all()
        )
        payload["available_slots"] = [
            _slot_payload(slot)
            for slot in filter_bookable_slots(stall, available_slots)
        ]
    return payload


def _slot_payload(slot: Slot) -> dict:
    return {
        "date": slot.date.isoformat(),
        "id": slot.id,
        "duration_hours": slot.duration_hours,
        "price": slot.price,
        "stall_id": slot.stall_id,
        "time": slot.time,
    }


def _booking_payload(booking: Booking) -> dict:
    return {
        "created_at": booking.created_at.isoformat(),
        "id": booking.id,
        "payment_method": booking.payment_method,
        "payment_status": booking.payment_status,
        "qr_code": booking.qr_code,
        "slot": _slot_payload(booking.slot),
        "stall_id": booking.slot.stall_id,
        "user_id": booking.user_id,
    }
