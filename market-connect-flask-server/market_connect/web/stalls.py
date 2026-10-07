from __future__ import annotations

from collections import OrderedDict
from datetime import date

from flask import (
    Blueprint,
    abort,
    flash,
    make_response,
    redirect,
    render_template,
    request,
    url_for,
)

from ..models import (
    RESERVATION_CONFIRMED,
    RESERVATION_EXPIRED,
    Booking,
    Review,
    Slot,
    Stall,
    StallPhoto,
    User,
)
from ..security import get_current_user, login_required, require_current_user_id
from ..services.bookings import (
    BookingSelectionError,
    VendorProfileRequiredError,
    create_booking_for_slots,
    exclude_active_reservations,
    expire_held_bookings,
    filter_bookable_slots,
)
from ..services.booking_requirements import (
    BookingRequirementsError,
    build_booking_requirements,
)
from .utils import get_or_404


bp = Blueprint("web_stalls", __name__)


@bp.get("/stall_photos/<int:photo_id>/")
def stall_photo(photo_id: int):
    photo = get_or_404(StallPhoto, photo_id)
    if not photo.stall.is_certified:
        abort(404)

    response = make_response(photo.data)
    response.content_type = photo.content_type
    response.headers["Cache-Control"] = "public, max-age=604800, immutable"
    response.headers["Content-Security-Policy"] = "default-src 'none'; sandbox"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.set_etag(photo.sha256)
    return response.make_conditional(request)


@bp.route("/stalls/")
def stall_list():
    expire_held_bookings()
    tenant = get_current_user()
    can_book = tenant is not None and tenant.has_role("Tenant")
    stalls = Stall.query.order_by(Stall.city, Stall.district, Stall.loc_name).all()
    available_stalls = []
    stalls_data = []
    locations = {}
    for stall in stalls:
        available_slots = (
            exclude_active_reservations(Slot.query)
            .filter(
                Slot.stall_id == stall.id,
                Slot.date >= date.today(),
            )
            .order_by(Slot.date, Slot.time)
            .all()
        )
        stall.available_slots = filter_bookable_slots(stall, available_slots)
        if not stall.available_slots:
            continue
        available_stalls.append(stall)
        locations.setdefault(stall.city, set()).add(stall.district)
        stalls_data.append(
            {
                "id": str(stall.id),
                "name": stall.loc_name,
                "city": stall.city,
                "district": stall.district,
                "road": stall.road,
                "environment_type": stall.environment_type,
                "booking_mode": stall.booking_mode,
                "minimum_booking_hours": stall.minimum_booking_hours,
                "slots": [
                    {
                        "date": slot.date.strftime("%Y-%m-%d"),
                        "time": slot.time or 0,
                        "duration_hours": slot.duration_hours,
                        "price": slot.price or 0,
                    }
                    for slot in stall.available_slots
                ],
            }
        )

    return render_template(
        "stalls.html",
        stalls=available_stalls,
        stalls_data=stalls_data,
        locations={city: sorted(districts) for city, districts in sorted(locations.items())},
        user_id=tenant.id if tenant is not None else None,
        tenant_display_name=(
            tenant.vendor_profile.brand_name
            if tenant is not None and tenant.vendor_profile is not None
            else tenant.display_name if tenant is not None else None
        ),
        tenant_reputation=tenant.reputation_score if tenant is not None else None,
        profile_url=url_for("web_auth.profile_setup"),
        not_logged_in=False,
        can_book=can_book,
        account_url=(
            url_for(
                "web_auth.account",
                intent="tenant",
                next=url_for("web_stalls.stall_list"),
            )
        ),
    )


@bp.route("/booking_page/<int:stall_id>/<int:user_id>/")
@login_required("Tenant")
def booking_page(stall_id: int, user_id: int):
    expire_held_bookings()
    stall = get_or_404(Stall, stall_id)
    if not stall.is_certified:
        abort(404)
    tenant = require_current_user_id(user_id)
    if tenant.vendor_profile is None:
        return redirect(
            url_for(
                "web_vendors.profile_setup",
                next=request.full_path.rstrip("?"),
            )
        )
    available_slots = (
        exclude_active_reservations(Slot.query)
        .filter(
            Slot.stall_id == stall.id,
            Slot.date >= date.today(),
        )
        .order_by(Slot.date, Slot.time)
        .all()
    )
    slots = filter_bookable_slots(stall, available_slots)
    return render_template("booking_page.html", stall=stall, tenant=tenant, slots=slots)


@bp.route("/make_booking/", methods=["GET", "POST"])
@login_required("Tenant")
def make_booking():
    if request.method != "POST":
        return redirect("/stalls/")

    tenant = get_current_user()
    if tenant is None:
        abort(401)
    if tenant.vendor_profile is None:
        return redirect(
            url_for(
                "web_vendors.profile_setup",
                next=url_for("web_stalls.stall_list"),
            )
        )
    try:
        slot_ids = [int(slot_id) for slot_id in request.form.getlist("slot_ids")]
    except ValueError:
        abort(400, description="選取的時段有誤，請重新選擇。")
    if not slot_ids:
        return redirect(request.referrer or "/stalls/")

    try:
        requirements = build_booking_requirements(
            electricity_required=request.form.get("electricity_required") == "yes",
            electricity_details=request.form.get("electricity_details", ""),
            gas_required=request.form.get("gas_required") == "yes",
            gas_details=request.form.get("gas_details", ""),
            equipment_requirements=request.form.get("equipment_requirements", ""),
            vehicle_plate=request.form.get("vehicle_plate", ""),
        )
        qr_code, created_count = create_booking_for_slots(
            tenant.id,
            slot_ids,
            requirements=requirements,
        )
    except VendorProfileRequiredError:
        return redirect(
            url_for(
                "web_vendors.profile_setup",
                next=url_for("web_stalls.stall_list"),
            )
        )
    except BookingRequirementsError as error:
        flash(str(error), "booking-error")
        return redirect(request.referrer or "/stalls/")
    except BookingSelectionError as error:
        flash(str(error), "booking-error")
        return redirect(request.referrer or "/stalls/")
    if not created_count or qr_code is None:
        return redirect(request.referrer or "/stalls/")
    return redirect(f"/payment/{qr_code}/")


@bp.route("/payment/<qr_code>/")
@login_required("Tenant")
def payment_page(qr_code: str):
    tenant = get_current_user()
    if tenant is None:
        abort(401)
    expire_held_bookings()
    bookings = _booking_group_for_tenant(qr_code, tenant)
    if not bookings:
        return redirect("/stalls/")
    if all(
        booking.reservation_status == RESERVATION_CONFIRMED for booking in bookings
    ):
        return redirect(f"/booking_success/{qr_code}/")
    return render_template(
        "payment_page.html",
        bookings=bookings,
        qr_code=qr_code,
        tenant=bookings[0].user,
        stall=bookings[0].slot.stall,
        total_price=sum(booking.slot.price for booking in bookings),
        hold_expires_at=bookings[0].hold_expires_at,
        reservation_status=bookings[0].reservation_status,
    )


@bp.route("/process_payment/", methods=["GET", "POST"])
@login_required("Tenant")
def process_payment():
    if request.method != "POST":
        return redirect("/stalls/")

    tenant = get_current_user()
    if tenant is None:
        abort(401)
    expire_held_bookings()
    qr_code = request.form.get("qr_code", "")
    bookings = _booking_group_for_tenant(qr_code, tenant)
    if not bookings:
        return redirect("/stalls/")
    if all(booking.reservation_status == RESERVATION_EXPIRED for booking in bookings):
        abort(409, description="保留時間已結束，請重新選擇時段。")
    abort(503, description="目前尚未開放線上付款。")


@bp.route("/booking_success/<qr_code>/")
@login_required("Tenant")
def booking_success(qr_code: str):
    tenant = get_current_user()
    if tenant is None:
        abort(401)
    expire_held_bookings()
    bookings = _booking_group_for_tenant(qr_code, tenant)
    if not bookings:
        return redirect("/stalls/")
    if any(
        booking.reservation_status != RESERVATION_CONFIRMED for booking in bookings
    ):
        if any(booking.reservation_status == RESERVATION_EXPIRED for booking in bookings):
            return redirect(f"/my_bookings/{tenant.id}/")
        return redirect(f"/payment/{qr_code}/")
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
    expire_held_bookings()
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
                "payment_status": booking.payment_state,
                "payment_provider": booking.payment.provider if booking.payment else None,
                "reservation_status": booking.reservation_status,
                "hold_expires_at": booking.hold_expires_at,
                "requirements": booking.requirements,
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
