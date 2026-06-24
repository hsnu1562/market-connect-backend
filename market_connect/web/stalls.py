from __future__ import annotations

import json
from collections import OrderedDict

from flask import Blueprint, redirect, render_template, request, session

from ..extensions import db
from ..models import Booking, Review, Slot, Stall, User
from ..services.bookings import apply_payment_to_qr, confirm_booking_payment, create_booking_for_slots
from .utils import get_or_404


bp = Blueprint("web_stalls", __name__)


@bp.route("/stalls/")
def stall_list():
    user_id = session.get("user_id")
    if not user_id or session.get("user_role") != "Tenant":
        return render_template("stalls.html", stalls=[], not_logged_in=True, stalls_json="[]")

    tenant = get_or_404(User, user_id)
    stalls = Stall.query.order_by(Stall.loc_name).all()
    stalls_data = []
    for stall in stalls:
        stall.available_slots = (
            Slot.query.outerjoin(Booking)
            .filter(Slot.stall_id == stall.id, Booking.id.is_(None))
            .order_by(Slot.date, Slot.time)
            .all()
        )
        stalls_data.append(
            {
                "id": str(stall.id),
                "slots": [
                    {
                        "date": slot.date.strftime("%Y-%m-%d"),
                        "time": slot.time or 0,
                        "price": slot.price or 0,
                    }
                    for slot in stall.available_slots
                ],
            }
        )

    return render_template(
        "stalls.html",
        stalls=stalls,
        user_id=user_id,
        tenant_username=tenant.username,
        tenant_reputation=tenant.reputation_score,
        not_logged_in=False,
        stalls_json=json.dumps(stalls_data, ensure_ascii=False),
    )


@bp.route("/booking_page/<int:stall_id>/<int:user_id>/")
def booking_page(stall_id: int, user_id: int):
    stall = get_or_404(Stall, stall_id)
    tenant = get_or_404(User, user_id)
    slots = (
        Slot.query.outerjoin(Booking)
        .filter(Slot.stall_id == stall.id, Booking.id.is_(None))
        .order_by(Slot.date, Slot.time)
        .all()
    )
    return render_template("booking_page.html", stall=stall, tenant=tenant, slots=slots)


@bp.route("/make_booking/", methods=["GET", "POST"])
def make_booking():
    if request.method != "POST":
        return redirect("/stalls/")

    slot_ids = [int(slot_id) for slot_id in request.form.getlist("slot_ids")]
    qr_code, created_count = create_booking_for_slots(int(request.form["user_id"]), slot_ids)
    if not created_count or qr_code is None:
        return redirect(request.referrer or "/stalls/")
    return redirect(f"/payment/{qr_code}/")


@bp.route("/payment/<qr_code>/")
def payment_page(qr_code: str):
    bookings = Booking.query.filter_by(qr_code=qr_code).all()
    if not bookings:
        return redirect("/stalls/")
    return render_template(
        "payment_page.html",
        bookings=bookings,
        qr_code=qr_code,
        tenant=bookings[0].user,
        stall=bookings[0].slot.stall,
        total_price=sum(booking.slot.price for booking in bookings),
    )


@bp.route("/process_payment/", methods=["GET", "POST"])
def process_payment():
    if request.method != "POST":
        return redirect("/stalls/")

    qr_code = request.form["qr_code"]
    payment_method = request.form.get("payment_method", "Cash")
    apply_payment_to_qr(qr_code, payment_method)
    return redirect(f"/booking_success/{qr_code}/")


@bp.route("/confirm_payment/", methods=["GET", "POST"])
def confirm_payment():
    if request.method == "POST":
        confirm_booking_payment(int(request.form["booking_id"]))
        return redirect(f"/landlord/history/{session.get('user_id')}/")
    return redirect("/")


@bp.route("/booking_success/<qr_code>/")
def booking_success(qr_code: str):
    bookings = Booking.query.filter_by(qr_code=qr_code).all()
    if not bookings:
        return redirect("/stalls/")
    return render_template(
        "booking_success.html",
        bookings=bookings,
        qr_code=qr_code,
        tenant=bookings[0].user,
        stall=bookings[0].slot.stall,
        total_price=sum(booking.slot.price for booking in bookings),
    )


@bp.route("/my_bookings/<int:user_id>/")
def my_bookings(user_id: int):
    tenant = get_or_404(User, user_id)
    bookings = (
        Booking.query.filter_by(user_id=tenant.id).order_by(Booking.created_at.desc()).all()
    )
    reviewed_bookings = {
        review.booking_id for review in Review.query.filter_by(reviewer_id=tenant.id).all()
    }

    grouped = OrderedDict()
    for booking in bookings:
        grouped.setdefault(
            booking.qr_code,
            {
                "qr_code": booking.qr_code,
                "booking_id": booking.id,
                "stall": booking.slot.stall,
                "payment_status": booking.payment_status,
                "payment_method": booking.payment_method,
                "created_at": booking.created_at,
                "slots": [],
                "total_price": 0,
                "is_reviewed": booking.id in reviewed_bookings,
            },
        )
        grouped[booking.qr_code]["slots"].append(booking.slot)
        grouped[booking.qr_code]["total_price"] += booking.slot.price

    booking_groups = list(grouped.values())
    for group in booking_groups:
        group["slots"].sort(key=lambda slot: (slot.date, slot.time))

    my_received_reviews = (
        Review.query.filter_by(reviewee_id=tenant.id).order_by(Review.created_at.desc()).all()
    )
    return render_template(
        "my_bookings.html",
        tenant=tenant,
        booking_groups=booking_groups,
        my_received_reviews=my_received_reviews,
    )
