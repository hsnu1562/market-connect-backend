from __future__ import annotations

from flask import Blueprint, redirect, request, session

from ..models import Booking
from ..services.reviews import create_review_for_booking
from .utils import get_or_404


bp = Blueprint("web_reviews", __name__)


@bp.route("/submit_review/", methods=["GET", "POST"])
def submit_review():
    if request.method != "POST":
        return redirect("/")

    booking = get_or_404(Booking, int(request.form["booking_id"]))
    reviewer_id = int(session["user_id"])
    user_role = session.get("user_role")
    create_review_for_booking(
        booking_id=booking.id,
        reviewer_id=reviewer_id,
        user_role=user_role,
        rating=int(request.form["rating"]),
        comment=request.form.get("comment", ""),
    )

    if user_role == "Landlord":
        return redirect(f"/landlord/history/{reviewer_id}/")
    return redirect(f"/my_bookings/{reviewer_id}/")
