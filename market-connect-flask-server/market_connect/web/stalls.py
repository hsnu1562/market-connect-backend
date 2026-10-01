from __future__ import annotations

import json
from collections import OrderedDict

from flask import Blueprint, abort, redirect, render_template, request, url_for

from ..extensions import db
from ..models import Booking, Review, Slot, Stall, User
from ..security import get_current_user, login_required, require_current_user_id
from ..services.bookings import apply_payment_to_qr, confirm_booking_payment, create_booking_for_slots
from .utils import get_or_404


bp = Blueprint("web_stalls", __name__)


@bp.route("/stalls/")
def stall_list():
    tenant = get_current_user()
    can_book = tenant is not None and tenant.has_role("Tenant")
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
        user_id=tenant.id if tenant is not None else None,
        tenant_username=tenant.username if tenant is not None else None,
        tenant_reputation=tenant.reputation_score if tenant is not None else None,
        not_logged_in=False,
        can_book=can_book,
        account_url=url_for("web_auth.account", intent="tenant", next=url_for("web_stalls.stall_list")),
        stalls_json=json.dumps(stalls_data, ensure_ascii=False),
    )


@bp.route("/booking_page/<int:stall_id>/<int:user_id>/")
@login_required("Tenant")
def booking_page(stall_id: int, user_id: int):
    stall = get_or_404(Stall, stall_id)
    tenant = require_current_user_id(user_id)
    slots = (
        Slot.query.outerjoin(Booking)
        .filter(Slot.stall_id == stall.id, Booking.id.is_(None))
        .order_by(Slot.date, Slot.time)
        .all()
    )
    return render_template("booking_page.html", stall=stall, tenant=tenant, slots=slots)


@bp.route("/make_booking/", methods=["GET", "POST"])
@login_required("Tenant")
def make_booking():
    if request.method != "POST":
        return redirect("/stalls/")

    tenant = get_current_user()
    if tenant is None:
        abort(401)
    try:
        slot_ids = [int(slot_id) for slot_id in request.form.getlist("slot_ids")]
    except ValueError:
        abort(400, description="Invalid slot selection.")
    if not slot_ids:
        return redirect(request.referrer or "/stalls/")

    qr_code, created_count = create_booking_for_slots(tenant.id, slot_ids)
    if not created_count or qr_code is None:
        return redirect(request.referrer or "/stalls/")
    return redirect(f"/payment/{qr_code}/")


@bp.route("/payment/<qr_code>/")
@login_required("Tenant")
def payment_page(qr_code: str):
    tenant = get_current_user()
    if tenant is None:
        abort(401)
    bookings = _booking_group_for_tenant(qr_code, tenant)
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
@login_required("Tenant")
def process_payment():
    if request.method != "POST":
        return redirect("/stalls/")

    tenant = get_current_user()
    if tenant is None:
        abort(401)
    qr_code = request.form.get("qr_code", "")
    bookings = _booking_group_for_tenant(qr_code, tenant)
    if not bookings:
        return redirect("/stalls/")
    payment_method = request.form.get("payment_method", "Cash")
    apply_payment_to_qr(qr_code, payment_method)
    return redirect(f"/booking_success/{qr_code}/")


@bp.route("/confirm_payment/", methods=["GET", "POST"])
@login_required("Landlord")
def confirm_payment():
    if request.method == "POST":
        landlord = get_current_user()
        if landlord is None:
            abort(401)
        try:
            booking_id = int(request.form["booking_id"])
        except (KeyError, ValueError):
            abort(400, description="Invalid booking.")
        booking = get_or_404(Booking, booking_id)
        if booking.slot.stall.owner_id != landlord.id:
            abort(403)
        confirm_booking_payment(booking.id)
        return redirect(f"/landlord/history/{landlord.id}/")
    return redirect("/")


@bp.route("/booking_success/<qr_code>/")
@login_required("Tenant")
def booking_success(qr_code: str):
    tenant = get_current_user()
    if tenant is None:
        abort(401)
    bookings = _booking_group_for_tenant(qr_code, tenant)
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
@login_required("Tenant")
def my_bookings(user_id: int):
    tenant = require_current_user_id(user_id)
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


def _booking_group_for_tenant(qr_code: str, tenant: User) -> list[Booking]:
    bookings = Booking.query.filter_by(qr_code=qr_code).all()
    if bookings and any(booking.user_id != tenant.id for booking in bookings):
        abort(403)
    return bookings
