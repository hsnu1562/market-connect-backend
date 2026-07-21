from __future__ import annotations

from flask import Blueprint, jsonify, request

from ...models import Booking, Slot, Stall
from ...services.bookings import apply_payment_to_qr, create_booking_for_slots


bp = Blueprint("api_v1", __name__, url_prefix="/api/v1")


@bp.get("/health")
def health_check():
    return jsonify({"service": "market-connect-flask-server", "status": "ok"})


@bp.get("/stalls")
def list_stalls():
    stalls = Stall.query.order_by(Stall.loc_name).all()
    return jsonify({"stalls": [_stall_payload(stall, include_slots=True) for stall in stalls]})


@bp.get("/stalls/<int:stall_id>/slots")
def list_available_slots(stall_id: int):
    slots = (
        Slot.query.outerjoin(Booking)
        .filter(Slot.stall_id == stall_id, Booking.id.is_(None))
        .order_by(Slot.date, Slot.time)
        .all()
    )
    return jsonify({"slots": [_slot_payload(slot) for slot in slots]})


@bp.post("/bookings")
def create_booking():
    payload = request.get_json(silent=True) or {}
    user_id = payload.get("user_id")
    slot_ids = payload.get("slot_ids", [])
    if not user_id or not isinstance(slot_ids, list):
        return jsonify({"error": "user_id and slot_ids are required"}), 400

    qr_code, created_count = create_booking_for_slots(int(user_id), [int(slot_id) for slot_id in slot_ids])
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
    bookings = Booking.query.filter_by(qr_code=qr_code).order_by(Booking.id).all()
    if not bookings:
        return jsonify({"error": "booking not found"}), 404

    return jsonify(
        {
            "bookings": [_booking_payload(booking) for booking in bookings],
            "qr_code": qr_code,
            "total_price": sum(booking.slot.price for booking in bookings),
        }
    )


@bp.post("/payments")
def update_payment():
    payload = request.get_json(silent=True) or {}
    qr_code = payload.get("qr_code")
    payment_method = payload.get("payment_method", "Cash")
    if not qr_code:
        return jsonify({"error": "qr_code is required"}), 400

    if not apply_payment_to_qr(qr_code, payment_method):
        return jsonify({"error": "booking not found"}), 404

    return jsonify({"payment_method": "Cash" if payment_method == "Cash" else "Credit Card", "qr_code": qr_code})


def _stall_payload(stall: Stall, include_slots: bool = False) -> dict:
    payload = {
        "address_detail": stall.address_detail,
        "city": stall.city,
        "district": stall.district,
        "facilities": stall.facilities,
        "id": stall.id,
        "loc_name": stall.loc_name,
        "owner_id": stall.owner_id,
        "road": stall.road,
    }
    if include_slots:
        payload["available_slots"] = [
            _slot_payload(slot)
            for slot in (
                Slot.query.outerjoin(Booking)
                .filter(Slot.stall_id == stall.id, Booking.id.is_(None))
                .order_by(Slot.date, Slot.time)
                .all()
            )
        ]
    return payload


def _slot_payload(slot: Slot) -> dict:
    return {
        "date": slot.date.isoformat(),
        "id": slot.id,
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
