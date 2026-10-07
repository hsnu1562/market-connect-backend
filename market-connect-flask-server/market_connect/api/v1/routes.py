from __future__ import annotations

from datetime import date

from flask import Blueprint, jsonify, request, url_for

from ...extensions import db
from ...models import (
    RESERVATION_EXPIRED,
    Booking,
    BookingRequirements,
    Slot,
    Stall,
    StallCertification,
    VendorProfile,
)
from ...security import get_current_user
from ...services.bookings import (
    BookingSelectionError,
    create_booking_for_slots,
    exclude_active_reservations,
    expire_held_bookings,
    filter_bookable_slots,
)
from ...services.booking_requirements import (
    BookingRequirementsError,
    build_booking_requirements,
)


bp = Blueprint("api_v1", __name__, url_prefix="/api/v1")
SERVICE_RELEASE = "20261004.13"


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
    expire_held_bookings()
    stalls = (
        Stall.query.join(StallCertification)
        .filter(StallCertification.status == "approved")
        .order_by(Stall.loc_name)
        .all()
    )
    return jsonify({"stalls": [_stall_payload(stall, include_slots=True) for stall in stalls]})


@bp.get("/stalls/<int:stall_id>/slots")
def list_available_slots(stall_id: int):
    expire_held_bookings()
    stall = (
        Stall.query.join(StallCertification)
        .filter(Stall.id == stall_id, StallCertification.status == "approved")
        .first()
    )
    if stall is None:
        return jsonify({"error": "stall not found"}), 404
    available_slots = (
        exclude_active_reservations(Slot.query)
        .filter(
            Slot.stall_id == stall_id,
            Slot.date >= date.today(),
        )
        .order_by(Slot.date, Slot.time)
        .all()
    )
    slots = filter_bookable_slots(stall, available_slots)
    return jsonify({"slots": [_slot_payload(slot) for slot in slots]})


@bp.get("/vendors/<int:profile_id>")
def get_public_vendor_profile(profile_id: int):
    profile = db.session.get(VendorProfile, profile_id)
    if profile is None:
        return jsonify({"error": "vendor profile not found"}), 404
    return jsonify({"vendor": _public_vendor_payload(profile)})


@bp.post("/bookings")
def create_booking():
    user, error_response = _require_api_user("Tenant")
    if error_response is not None:
        return error_response
    if user.vendor_profile is None:
        return jsonify(
            {
                "error": "vendor profile is required before booking",
                "profile_setup_url": url_for(
                    "web_vendors.profile_setup",
                    next=url_for("web_stalls.stall_list"),
                ),
            }
        ), 409

    payload = request.get_json(silent=True) or {}
    slot_ids = payload.get("slot_ids", [])
    if not isinstance(slot_ids, list) or not slot_ids:
        return jsonify({"error": "slot_ids are required"}), 400
    try:
        normalized_slot_ids = [int(slot_id) for slot_id in slot_ids]
    except (TypeError, ValueError):
        return jsonify({"error": "slot_ids must contain integers"}), 400

    try:
        requirements_payload = payload.get("requirements") or {}
        if not isinstance(requirements_payload, dict):
            return jsonify({"error": "requirements must be an object"}), 400
        requirements = build_booking_requirements(
            electricity_required=requirements_payload.get(
                "electricity_required",
                False,
            ),
            electricity_details=requirements_payload.get("electricity_details", ""),
            gas_required=requirements_payload.get("gas_required", False),
            gas_details=requirements_payload.get("gas_details", ""),
            equipment_requirements=requirements_payload.get(
                "equipment_requirements",
                "",
            ),
            vehicle_plate=requirements_payload.get("vehicle_plate", ""),
        )
        qr_code, created_count = create_booking_for_slots(
            user.id,
            normalized_slot_ids,
            requirements=requirements,
        )
    except BookingRequirementsError as error:
        return jsonify({"error": str(error)}), 400
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
            "requirements": _booking_requirements_payload(
                bookings[0].requirements
            ),
        }
    ), 201


@bp.get("/bookings/<qr_code>")
def get_booking_group(qr_code: str):
    user, error_response = _require_api_user()
    if error_response is not None:
        return error_response

    expire_held_bookings()
    bookings = Booking.query.filter_by(qr_code=qr_code).order_by(Booking.id).all()
    if not bookings:
        return jsonify({"error": "booking not found"}), 404
    is_tenant_owner = user.has_role("Tenant") and all(
        booking.user_id == user.id for booking in bookings
    )
    is_landlord_owner = user.has_role("Landlord") and all(
        booking.slot.stall.owner_id == user.id for booking in bookings
    )
    is_active_admin = user.is_admin and user.status == "active"
    if not (is_tenant_owner or is_landlord_owner or is_active_admin):
        return jsonify({"error": "booking access denied"}), 403

    return jsonify(
        {
            "bookings": [_booking_payload(booking) for booking in bookings],
            "qr_code": qr_code,
            "requirements": _booking_requirements_payload(
                bookings[0].requirements
            ),
            "total_price": sum(booking.slot.price for booking in bookings),
            "vendor_private": _private_vendor_payload(bookings[0].user.vendor_profile),
        }
    )


@bp.post("/payments")
def update_payment():
    user, error_response = _require_api_user("Tenant")
    if error_response is not None:
        return error_response

    payload = request.get_json(silent=True) or {}
    qr_code = payload.get("qr_code")
    if not qr_code:
        return jsonify({"error": "qr_code is required"}), 400
    expire_held_bookings()
    bookings = Booking.query.filter_by(qr_code=qr_code).all()
    if not bookings:
        return jsonify({"error": "booking not found"}), 404
    if any(booking.user_id != user.id for booking in bookings):
        return jsonify({"error": "booking access denied"}), 403

    if all(booking.reservation_status == RESERVATION_EXPIRED for booking in bookings):
        return jsonify({"error": "reservation hold has expired"}), 409
    return jsonify(
        {
            "error": "online payment is unavailable until a provider is connected",
            "qr_code": qr_code,
        }
    ), 503


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
        "road": stall.road,
        "booking_mode": stall.booking_mode,
        "certification_status": "approved",
        "minimum_booking_hours": stall.minimum_booking_hours,
        "photo_urls": [
            url_for("web_stalls.stall_photo", photo_id=photo.id)
            for photo in stall.photos
        ],
    }
    if include_slots:
        available_slots = (
            exclude_active_reservations(Slot.query)
            .filter(
                Slot.stall_id == stall.id,
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
        "hold_expires_at": (
            booking.hold_expires_at.isoformat() if booking.hold_expires_at else None
        ),
        "id": booking.id,
        "payment_provider": booking.payment.provider if booking.payment else None,
        "payment_status": booking.payment_state,
        "qr_code": booking.qr_code,
        "reservation_status": booking.reservation_status,
        "slot": _slot_payload(booking.slot),
        "stall_id": booking.slot.stall_id,
    }


def _public_vendor_payload(profile: VendorProfile) -> dict:
    return {
        "brand_description": profile.brand_description,
        "brand_name": profile.brand_name,
        "facebook_url": profile.facebook_url,
        "id": profile.id,
        "instagram_url": profile.instagram_url,
        "primary_category": profile.primary_category,
        "profile_image_url": (
            url_for("web_vendors.profile_image", profile_id=profile.id)
            if profile.has_profile_image
            else None
        ),
        "website_url": profile.website_url,
    }


def _private_vendor_payload(profile: VendorProfile | None) -> dict | None:
    if profile is None:
        return None
    return {
        "brand_name": profile.brand_name,
        "contact_email": profile.contact_email,
        "contact_name": profile.contact_name,
        "contact_phone": profile.contact_phone,
        "food_registration_number": profile.food_registration_number,
        "primary_category": profile.primary_category,
    }


def _booking_requirements_payload(
    requirements: BookingRequirements | None,
) -> dict | None:
    if requirements is None:
        return None
    return {
        "electricity_details": requirements.electricity_details,
        "electricity_required": requirements.electricity_required,
        "equipment_requirements": requirements.equipment_requirements,
        "gas_details": requirements.gas_details,
        "gas_required": requirements.gas_required,
        "vehicle_plate": requirements.vehicle_plate,
    }
