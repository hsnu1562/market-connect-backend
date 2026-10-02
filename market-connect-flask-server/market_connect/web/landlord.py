from __future__ import annotations

import json
from collections import OrderedDict
from datetime import date

from flask import Blueprint, abort, redirect, render_template, request

from ..extensions import db
from ..models import Booking, Review, Slot, Stall
from ..security import get_current_user, login_required, require_current_user_id
from .utils import get_or_404, parse_date


bp = Blueprint("web_landlord", __name__)
ALLOWED_ENVIRONMENT_TYPES = {"indoor", "outdoor", "mixed"}
ALLOWED_BOOKING_MODES = {"hourly", "daily"}
ALLOWED_MINIMUM_HOURS = {1, 2, 3}


@bp.route("/landlord/<int:user_id>/", methods=["GET", "POST"])
@login_required("Landlord")
def landlord_dashboard(user_id: int):
    user = require_current_user_id(user_id)
    if request.method == "POST":
        environment_type = request.form.get("environment_type", "")
        if environment_type not in ALLOWED_ENVIRONMENT_TYPES:
            abort(400, description="Invalid stall environment type.")
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
        db.session.add(stall)
        db.session.commit()
        return redirect(f"/stall_pricing/{stall.id}/")
    return render_template("landlord_dashboard.html", user=user)


@bp.route("/landlord/history/<int:user_id>/")
@login_required("Landlord")
def landlord_history(user_id: int):
    landlord = require_current_user_id(user_id)
    stall_ids = [stall.id for stall in landlord.stalls]

    unbooked_slots = (
        Slot.query.outerjoin(Booking)
        .filter(Slot.stall_id.in_(stall_ids) if stall_ids else False, Booking.id.is_(None))
        .join(Stall)
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
        grouped.setdefault(
            booking.qr_code,
            {
                "booking_id": booking.id,
                "stall_name": booking.slot.stall.loc_name,
                "tenant_name": booking.user.display_name,
                "tenant_phone": booking.user.phone_number,
                "date": booking.slot.date.strftime("%Y-%m-%d"),
                "time_list": [],
                "end_time_list": [],
                "price": 0,
                "status": booking.payment_status,
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
    return render_template(
        "landlord_history.html",
        user=landlord,
        rented_slots=rented_slots,
        my_reviews=my_reviews,
        my_active_vacancies=my_active_vacancies,
    )


@bp.route("/stall_pricing/<int:stall_id>/", methods=["GET", "POST"])
@login_required("Landlord")
def stall_pricing(stall_id: int):
    stall = get_or_404(Stall, stall_id)
    user = get_current_user()
    if user is None or stall.owner_id != user.id:
        abort(403)
    if request.method == "POST":
        booking_mode = request.form.get("booking_mode", "")
        if booking_mode not in ALLOWED_BOOKING_MODES:
            abort(400, description="Invalid booking mode.")
        try:
            minimum_booking_hours = int(request.form.get("minimum_booking_hours", "1"))
        except ValueError:
            abort(400, description="Invalid minimum booking duration.")
        if booking_mode == "hourly" and minimum_booking_hours not in ALLOWED_MINIMUM_HOURS:
            abort(400, description="Invalid minimum booking duration.")

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
        abort(400, description="Invalid slot data.")
    if not isinstance(items, list) or not items:
        abort(400, description="At least one availability period is required.")

    normalized_items = []
    seen_periods = set()
    seen_daily_dates = set()
    for item in items:
        if not isinstance(item, dict):
            abort(400, description="Invalid slot data.")
        try:
            slot_date = parse_date(item["date"])
            hour = int(item["hour"])
            duration_hours = int(item.get("duration_hours", 1))
            price = int(item["price"])
        except (KeyError, TypeError, ValueError):
            abort(400, description="Invalid slot data.")

        if hour < 0 or duration_hours < 1 or hour + duration_hours > 24 or price <= 0:
            abort(400, description="Invalid slot time or price.")
        if slot_date < date.today():
            abort(400, description="Availability cannot be published in the past.")
        if booking_mode == "hourly" and duration_hours != 1:
            abort(400, description="Hourly slots must be one hour long.")
        if booking_mode == "daily":
            if slot_date in seen_daily_dates:
                abort(400, description="Only one full-day period is allowed per date.")
            seen_daily_dates.add(slot_date)

        period_key = (slot_date, hour, duration_hours)
        if period_key in seen_periods:
            abort(400, description="Duplicate availability period.")
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


def _validate_slot_update(
    stall: Stall,
    booking_mode: str,
    minimum_booking_hours: int,
    slot_items: list[dict],
) -> None:
    existing_slots = Slot.query.filter_by(stall_id=stall.id).all()
    if existing_slots and booking_mode != stall.booking_mode:
        abort(409, description="Rental mode cannot change after availability is published.")

    for item in slot_items:
        new_start = item["time"]
        new_end = new_start + item["duration_hours"]
        for existing in existing_slots:
            existing_end = existing.time + existing.duration_hours
            overlaps = new_start < existing_end and existing.time < new_end
            if item["date"] == existing.date and overlaps:
                abort(409, description="Availability overlaps an existing period.")

    if booking_mode != "hourly":
        return

    for slot_date in {item["date"] for item in slot_items}:
        hours = {
            existing.time
            for existing in existing_slots
            if (
                existing.date == slot_date
                and existing.duration_hours == 1
                and existing.booking is None
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
                    f"Each published date must offer at least "
                    f"{minimum_booking_hours} consecutive hours."
                ),
            )
