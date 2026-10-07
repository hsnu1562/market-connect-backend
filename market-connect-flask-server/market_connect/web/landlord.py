from __future__ import annotations

import json
from collections import OrderedDict
from datetime import UTC, date, datetime

from flask import Blueprint, abort, redirect, render_template, request

from ..extensions import db
from ..models import Booking, Review, Slot, Stall, StallCertification
from ..security import get_current_user, login_required, require_current_user_id
from ..services.certification_documents import (
    MAX_DOCUMENTS,
    replace_certification_documents,
    validate_document_uploads,
)
from ..services.bookings import exclude_active_reservations, expire_held_bookings
from ..services.stall_photos import (
    MAX_STALL_PHOTOS,
    MAX_STALL_PHOTO_BYTES,
    attach_stall_photos,
    validate_stall_photo_uploads,
)
from .utils import get_or_404, parse_date


bp = Blueprint("web_landlord", __name__)
ALLOWED_ENVIRONMENT_TYPES = {"indoor", "outdoor", "mixed"}
ALLOWED_BOOKING_MODES = {"hourly", "daily"}
ALLOWED_MINIMUM_HOURS = {1, 2, 3}
RELATIONSHIP_LABELS = {
    "property_owner": "場地所有權人",
    "authorized_manager": "受委託管理人",
    "tenant_with_permission": "取得轉租同意的承租人",
    "event_organizer": "活動主辦或場地合作單位",
}
PROOF_TYPE_LABELS = {
    "property_record": "所有權或稅籍證明",
    "lease_or_consent": "租約與出租同意書",
    "venue_authorization": "場地方授權書",
    "event_permit": "活動核准或場地合作文件",
    "other": "其他可驗證文件",
}
CERTIFICATION_STATUS_LABELS = {
    "not_submitted": "尚未送審",
    "pending": "審核中",
    "approved": "已通過",
    "rejected": "退回補件",
}


@bp.route("/landlord/<int:user_id>/", methods=["GET", "POST"])
@login_required("Landlord")
def landlord_dashboard(user_id: int):
    user = require_current_user_id(user_id)
    error = None
    if request.method == "POST":
        try:
            uploaded_photos = validate_stall_photo_uploads(
                request.files.getlist("stall_photos")
            )
        except ValueError as exc:
            error = str(exc)
        else:
            environment_type = request.form.get("environment_type", "")
            if environment_type not in ALLOWED_ENVIRONMENT_TYPES:
                abort(400, description="請選擇場地類型。")
            stall = Stall(
                owner=user,
                loc_name=request.form["loc_name"],
                city=request.form["city"],
                district=request.form["district"],
                road=request.form["road"],
                address_detail=request.form["address_detail"],
                facilities=request.form.get("facilities"),
                environment_type=environment_type,
            )
            attach_stall_photos(stall, uploaded_photos)
            db.session.add(stall)
            db.session.commit()
            return redirect(f"/stall_certification/{stall.id}/")
    return (
        render_template(
            "landlord_dashboard.html",
            user=user,
            error=error,
            max_stall_photos=MAX_STALL_PHOTOS,
            max_stall_photo_mb=MAX_STALL_PHOTO_BYTES // (1024 * 1024),
        ),
        400 if error else 200,
    )


@bp.route("/stall_certification/<int:stall_id>/", methods=["GET", "POST"])
@login_required("Landlord")
def stall_certification(stall_id: int):
    stall = get_or_404(Stall, stall_id)
    user = get_current_user()
    if user is None or stall.owner_id != user.id:
        abort(403)

    certification = stall.certification
    error = None
    if request.method == "POST":
        if certification is not None and certification.status == "approved":
            abort(409, description="此場地已通過出租資格審核，無法直接修改。")
        try:
            uploaded_documents = validate_document_uploads(
                request.files.getlist("evidence_documents")
            )
            has_documents = bool(uploaded_documents) or bool(
                certification is not None and certification.documents
            )
            payload = _parse_certification_submission(
                request.form,
                has_documents=has_documents,
            )
        except ValueError as exc:
            error = str(exc)
        else:
            if certification is None:
                certification = StallCertification(stall=stall, **payload)
                db.session.add(certification)
                db.session.flush()
            else:
                for field, value in payload.items():
                    setattr(certification, field, value)
            if uploaded_documents:
                replace_certification_documents(certification, uploaded_documents)
            certification.status = "pending"
            certification.submitted_at = datetime.now(UTC)
            certification.reviewed_at = None
            certification.reviewed_by_user_id = None
            certification.reviewer_reference = None
            certification.review_note = None
            db.session.commit()
            return redirect(f"/stall_pricing/{stall.id}/")

    return (
        render_template(
            "stall_certification.html",
            stall=stall,
            user=user,
            certification=certification,
            error=error,
            relationship_labels=RELATIONSHIP_LABELS,
            proof_type_labels=PROOF_TYPE_LABELS,
            max_documents=MAX_DOCUMENTS,
        ),
        400 if error else 200,
    )


@bp.route("/landlord/history/<int:user_id>/")
@login_required("Landlord")
def landlord_history(user_id: int):
    landlord = require_current_user_id(user_id)
    expire_held_bookings()
    stall_ids = [stall.id for stall in landlord.stalls]

    unbooked_slots = (
        exclude_active_reservations(Slot.query)
        .filter(Slot.stall_id.in_(stall_ids) if stall_ids else False)
        .join(Stall)
        .join(StallCertification)
        .filter(StallCertification.status == "approved")
        .order_by(Stall.loc_name, Slot.date, Slot.time)
        .all()
    )

    vacancies = OrderedDict()
    for slot in unbooked_slots:
        key = f"{slot.stall.id}_{slot.date}"
        vacancies.setdefault(
            key,
            {
                "stall_name": slot.stall.loc_name,
                "date": slot.date.strftime("%Y-%m-%d"),
                "hours": [],
                "end_hours": [],
                "total_price": 0,
                "booking_mode": slot.stall.booking_mode,
            },
        )
        vacancies[key]["hours"].append(slot.time)
        vacancies[key]["end_hours"].append(slot.time + slot.duration_hours)
        vacancies[key]["total_price"] += slot.price

    my_active_vacancies = []
    for data in vacancies.values():
        data["hours"].sort()
        my_active_vacancies.append(
            {
                "stall_name": data["stall_name"],
                "date": data["date"],
                "time_zone": f"{min(data['hours'])}:00 - {max(data['end_hours'])}:00",
                "price": data["total_price"],
                "booking_mode": data["booking_mode"],
            }
        )

    bookings = (
        Booking.query.join(Slot)
        .filter(Slot.stall_id.in_(stall_ids) if stall_ids else False)
        .order_by(Booking.created_at.desc())
        .all()
    )
    reviewed_bookings = {
        review.booking_id for review in Review.query.filter_by(reviewer_id=landlord.id).all()
    }

    grouped = OrderedDict()
    for booking in bookings:
        vendor_profile = booking.user.vendor_profile
        grouped.setdefault(
            booking.qr_code,
            {
                "booking_id": booking.id,
                "stall_name": booking.slot.stall.loc_name,
                "tenant_name": (
                    vendor_profile.brand_name
                    if vendor_profile is not None
                    else booking.user.display_name
                ),
                "tenant_contact_name": (
                    vendor_profile.contact_name if vendor_profile is not None else None
                ),
                "tenant_phone": (
                    vendor_profile.contact_phone
                    if vendor_profile is not None
                    else booking.user.phone_number
                ),
                "tenant_email": (
                    vendor_profile.contact_email if vendor_profile is not None else None
                ),
                "food_registration_number": (
                    vendor_profile.food_registration_number
                    if vendor_profile is not None
                    else None
                ),
                "requirements": booking.requirements,
                "date": booking.slot.date.strftime("%Y-%m-%d"),
                "time_list": [],
                "end_time_list": [],
                "price": 0,
                "payment_status": booking.payment_state,
                "reservation_status": booking.reservation_status,
                "is_reviewed": booking.id in reviewed_bookings,
            },
        )
        grouped[booking.qr_code]["time_list"].append(booking.slot.time)
        grouped[booking.qr_code]["end_time_list"].append(
            booking.slot.time + booking.slot.duration_hours
        )
        grouped[booking.qr_code]["price"] += booking.slot.price

    rented_slots = []
    for data in grouped.values():
        data["time"] = (
            f"{min(data['time_list'])}:00 - {max(data['end_time_list'])}:00"
        )
        rented_slots.append(data)

    my_reviews = Review.query.filter_by(reviewee_id=landlord.id).order_by(Review.created_at.desc()).all()
    certification_records = [
        {
            "stall": stall,
            "certification": stall.certification,
            "status": stall.certification.status if stall.certification else "not_submitted",
            "status_label": CERTIFICATION_STATUS_LABELS[
                stall.certification.status if stall.certification else "not_submitted"
            ],
        }
        for stall in sorted(landlord.stalls, key=lambda item: item.loc_name)
    ]
    return render_template(
        "landlord_history.html",
        user=landlord,
        rented_slots=rented_slots,
        my_reviews=my_reviews,
        my_active_vacancies=my_active_vacancies,
        certification_records=certification_records,
    )


@bp.route("/stall_pricing/<int:stall_id>/", methods=["GET", "POST"])
@login_required("Landlord")
def stall_pricing(stall_id: int):
    stall = get_or_404(Stall, stall_id)
    user = get_current_user()
    if user is None or stall.owner_id != user.id:
        abort(403)
    if stall.certification is None or stall.certification.status == "rejected":
        return redirect(f"/stall_certification/{stall.id}/")
    if request.method == "POST":
        booking_mode = request.form.get("booking_mode", "")
        if booking_mode not in ALLOWED_BOOKING_MODES:
            abort(400, description="請選擇出租方式。")
        try:
            minimum_booking_hours = int(request.form.get("minimum_booking_hours", "1"))
        except ValueError:
            abort(400, description="請選擇最低預約時數。")
        if booking_mode == "hourly" and minimum_booking_hours not in ALLOWED_MINIMUM_HOURS:
            abort(400, description="請選擇最低預約時數。")

        slot_items = _parse_slot_items(request.form.get("slots_json", ""), booking_mode)
        _validate_slot_update(
            stall,
            booking_mode,
            minimum_booking_hours,
            slot_items,
        )
        stall.booking_mode = booking_mode
        stall.minimum_booking_hours = minimum_booking_hours if booking_mode == "hourly" else 1
        for item in slot_items:
            db.session.add(Slot(stall=stall, **item))
        db.session.commit()
        return redirect(f"/landlord/history/{user.id}/")
    return render_template("stall_pricing.html", stall=stall, user=user, hours=range(24))


@bp.route("/publish_success/")
@login_required("Landlord")
def publish_success():
    user = get_current_user()
    if user is None:
        abort(401)
    return render_template("publish_success.html", user=user)


def _parse_slot_items(raw_slots: str, booking_mode: str) -> list[dict]:
    try:
        items = json.loads(raw_slots)
    except (TypeError, ValueError):
        abort(400, description="時段資料有誤，請重新設定。")
    if not isinstance(items, list) or not items:
        abort(400, description="請至少新增一個可預約時段。")

    normalized_items = []
    seen_periods = set()
    seen_daily_dates = set()
    for item in items:
        if not isinstance(item, dict):
            abort(400, description="時段資料有誤，請重新設定。")
        try:
            slot_date = parse_date(item["date"])
            hour = int(item["hour"])
            duration_hours = int(item.get("duration_hours", 1))
            price = int(item["price"])
        except (KeyError, TypeError, ValueError):
            abort(400, description="時段資料有誤，請重新設定。")

        if hour < 0 or duration_hours < 1 or hour + duration_hours > 24 or price <= 0:
            abort(400, description="請確認時段與價格。")
        if slot_date < date.today():
            abort(400, description="無法刊登過去的時段。")
        if booking_mode == "hourly" and duration_hours != 1:
            abort(400, description="按小時出租的時段須為 1 小時。")
        if booking_mode == "daily":
            if slot_date in seen_daily_dates:
                abort(400, description="同一天只能刊登一個整日時段。")
            seen_daily_dates.add(slot_date)

        period_key = (slot_date, hour, duration_hours)
        if period_key in seen_periods:
            abort(400, description="這個時段已經加入。")
        seen_periods.add(period_key)
        normalized_items.append(
            {
                "date": slot_date,
                "time": hour,
                "duration_hours": duration_hours,
                "price": price,
            }
        )
    return normalized_items


def _parse_certification_submission(form, *, has_documents: bool) -> dict:
    legal_name = form.get("applicant_legal_name", "").strip()
    phone = form.get("applicant_phone", "").strip()
    relationship = form.get("relationship_to_space", "")
    proof_type = form.get("proof_type", "")
    proof_reference = form.get("proof_reference", "").strip()

    if any("\n" in value or "\r" in value for value in (legal_name, phone, proof_reference)):
        raise ValueError("姓名、電話與文件說明請勿換行。")
    if not 2 <= len(legal_name) <= 100:
        raise ValueError("請填寫 2 至 100 字的法定姓名或機構名稱。")
    if not 8 <= sum(character.isdigit() for character in phone) <= 20:
        raise ValueError("聯絡電話需包含 8–20 個數字。")
    if relationship not in RELATIONSHIP_LABELS:
        raise ValueError("請選擇與場地的關係。")
    if proof_type not in PROOF_TYPE_LABELS:
        raise ValueError("請選擇證明文件類型。")
    if len(proof_reference) > 120:
        raise ValueError("文件編號或補充說明不可超過 120 字。")

    if not has_documents:
        raise ValueError("請上傳至少一份證明文件。")
    if form.get("declaration_accepted") != "yes":
        raise ValueError("請確認有權出租場地，並同意人工審核。")

    return {
        "applicant_legal_name": legal_name,
        "applicant_phone": phone,
        "relationship_to_space": relationship,
        "proof_type": proof_type,
        "proof_reference": proof_reference or None,
        "declaration_accepted": True,
    }


def _validate_slot_update(
    stall: Stall,
    booking_mode: str,
    minimum_booking_hours: int,
    slot_items: list[dict],
) -> None:
    existing_slots = Slot.query.filter_by(stall_id=stall.id).all()
    if existing_slots and booking_mode != stall.booking_mode:
        abort(409, description="刊登時段後，無法變更出租方式。")

    for item in slot_items:
        new_start = item["time"]
        new_end = new_start + item["duration_hours"]
        for existing in existing_slots:
            existing_end = existing.time + existing.duration_hours
            overlaps = new_start < existing_end and existing.time < new_end
            if item["date"] == existing.date and overlaps:
                abort(409, description="這個時段與已刊登時段重疊。")

    if booking_mode != "hourly":
        return

    for slot_date in {item["date"] for item in slot_items}:
        hours = {
            existing.time
            for existing in existing_slots
            if (
                existing.date == slot_date
                and existing.duration_hours == 1
                and not existing.has_active_reservation
            )
        }
        hours.update(item["time"] for item in slot_items if item["date"] == slot_date)
        ordered_hours = sorted(hours)
        longest_run = 0
        current_run = 0
        previous_hour = None
        for hour in ordered_hours:
            current_run = (
                current_run + 1
                if previous_hour is not None and hour == previous_hour + 1
                else 1
            )
            longest_run = max(longest_run, current_run)
            previous_hour = hour
        if longest_run < minimum_booking_hours:
            abort(
                400,
                description=(
                    f"每個日期至少須提供連續 {minimum_booking_hours} 小時。"
                ),
            )
