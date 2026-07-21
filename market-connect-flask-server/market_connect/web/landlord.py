from __future__ import annotations

import json
from collections import OrderedDict

from flask import Blueprint, redirect, render_template, request, session

from ..extensions import db
from ..models import Booking, Review, Slot, Stall, User
from .utils import get_or_404, parse_date


bp = Blueprint("web_landlord", __name__)


@bp.route("/landlord/<int:user_id>/", methods=["GET", "POST"])
def landlord_dashboard(user_id: int):
    user = get_or_404(User, user_id)
    if request.method == "POST":
        stall = Stall(
            owner=user,
            loc_name=request.form["loc_name"],
            city=request.form["city"],
            district=request.form["district"],
            road=request.form["road"],
            address_detail=request.form["address_detail"],
            facilities=request.form.get("facilities"),
        )
        db.session.add(stall)
        db.session.commit()
        return redirect(f"/stall_pricing/{stall.id}/")
    return render_template("landlord_dashboard.html", user=user)


@bp.route("/landlord/history/<int:user_id>/")
def landlord_history(user_id: int):
    landlord = get_or_404(User, user_id)
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
                "total_price": 0,
            },
        )
        vacancies[key]["hours"].append(slot.time)
        vacancies[key]["total_price"] += slot.price

    my_active_vacancies = []
    for data in vacancies.values():
        data["hours"].sort()
        my_active_vacancies.append(
            {
                "stall_name": data["stall_name"],
                "date": data["date"],
                "time_zone": f"{data['hours'][0]}:00 - {data['hours'][-1] + 1}:00",
                "price": data["total_price"],
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
                "tenant_name": (
                    f"{booking.user.first_name} {booking.user.last_name} ({booking.user.username})"
                ),
                "tenant_phone": booking.user.phone_number,
                "date": booking.slot.date.strftime("%Y-%m-%d"),
                "time_list": [],
                "price": 0,
                "status": booking.payment_status,
                "is_reviewed": booking.id in reviewed_bookings,
            },
        )
        grouped[booking.qr_code]["time_list"].append(booking.slot.time)
        grouped[booking.qr_code]["price"] += booking.slot.price

    rented_slots = []
    for data in grouped.values():
        data["time_list"].sort()
        data["time"] = f"{data['time_list'][0]}:00 - {data['time_list'][-1] + 1}:00"
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
def stall_pricing(stall_id: int):
    stall = get_or_404(Stall, stall_id)
    user = stall.owner
    if request.method == "POST":
        slots_json = request.form.get("slots_json")
        if slots_json:
            for item in json.loads(slots_json):
                db.session.add(
                    Slot(
                        stall=stall,
                        date=parse_date(item["date"]),
                        time=int(item["hour"]),
                        price=int(item["price"]),
                    )
                )
        else:
            rental_date = parse_date(request.form["rental_date"])
            for key, value in request.form.items():
                if key.startswith("hour_"):
                    db.session.add(
                        Slot(
                            stall=stall,
                            date=rental_date,
                            time=int(key.split("_")[1]),
                            price=int(value),
                        )
                    )
        db.session.commit()
        return redirect(f"/landlord/history/{user.id}/")
    return render_template("stall_pricing.html", stall=stall, user=user, hours=range(24))


@bp.route("/publish_success/")
def publish_success():
    user_id = session.get("user_id")
    if not user_id:
        return redirect("/")
    return render_template("publish_success.html", user_id=user_id)
