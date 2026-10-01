from __future__ import annotations

from flask import Blueprint, abort, redirect, request

from ..models import Booking
from ..security import get_current_user, login_required
from ..services.reviews import create_review_for_booking
from .utils import get_or_404


bp = Blueprint("web_reviews", __name__)


@bp.route("/submit_review/", methods=["GET", "POST"])
@login_required("Tenant", "Landlord")
def submit_review():
    if request.method != "POST":
        return redirect("/")

    try:
        booking_id = int(request.form["booking_id"])
        rating = int(request.form["rating"])
    except (KeyError, ValueError):
        abort(400, description="Invalid review.")

    booking = get_or_404(Booking, booking_id)
    reviewer = get_current_user()
    if reviewer is None:
        abort(401)
    if booking.slot.stall.owner_id == reviewer.id and reviewer.has_role("Landlord"):
        reviewer_role = "Landlord"
    elif booking.user_id == reviewer.id and reviewer.has_role("Tenant"):
        reviewer_role = "Tenant"
    else:
        abort(403)

    if not create_review_for_booking(
        booking_id=booking.id,
        reviewer_id=reviewer.id,
        user_role=reviewer_role,
        rating=rating,
        comment=request.form.get("comment", ""),
    ):
        abort(400, description="This review could not be submitted.")

    if reviewer_role == "Landlord":
        return redirect(f"/landlord/history/{reviewer.id}/")
    return redirect(f"/my_bookings/{reviewer.id}/")
