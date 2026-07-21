from __future__ import annotations

from datetime import date

from flask import Blueprint, redirect, render_template, request, session
from sqlalchemy.orm import joinedload
from werkzeug.security import check_password_hash, generate_password_hash

from ..extensions import db
from ..models import Booking, Slot, Stall, User
from .utils import get_or_404


bp = Blueprint("web_auth", __name__)


@bp.route("/")
def index():
    available_slots = (
        Slot.query.options(joinedload(Slot.stall).joinedload(Stall.owner))
        .outerjoin(Booking)
        .filter(Booking.id.is_(None), Slot.date >= date.today())
        .order_by(Slot.date, Slot.time, Slot.stall_id)
        .all()
    )

    listings_by_stall = {}
    for slot in available_slots:
        stall = slot.stall
        if stall.id not in listings_by_stall:
            raw_facilities = (stall.facilities or "").replace("，", ",")
            listings_by_stall[stall.id] = {
                "stall": stall,
                "facilities": [item.strip() for item in raw_facilities.split(",") if item.strip()],
                "slots": [],
            }
        listings_by_stall[stall.id]["slots"].append(slot)

    listings = list(listings_by_stall.values())[:6]
    for listing in listings:
        slots = listing["slots"]
        listing["next_date"] = slots[0].date
        listing["min_price"] = min(slot.price for slot in slots)
        listing["available_days"] = len({slot.date for slot in slots})
        listing["preview_slots"] = slots[:3]

    current_user = None
    user_id = session.get("user_id")
    if user_id:
        current_user = db.session.get(User, user_id)

    is_tenant = current_user is not None and current_user.role == "Tenant"
    for listing in listings:
        stall_id = listing["stall"].id
        listing["action_url"] = (
            f"/booking_page/{stall_id}/{current_user.id}/" if is_tenant else "/login/Tenant"
        )
        listing["action_label"] = "查看時段" if is_tenant else "登入後預約"

    stats = {
        "stalls": len(listings_by_stall),
        "slots": len(available_slots),
        "cities": len({listing["stall"].city for listing in listings_by_stall.values()}),
    }
    provider_url = (
        f"/landlord/hub/{current_user.id}/"
        if current_user is not None and current_user.role == "Landlord"
        else "/login/Landlord"
    )
    return render_template(
        "index.html",
        listings=listings,
        stats=stats,
        current_user=current_user,
        provider_url=provider_url,
    )


@bp.route("/register/<role>", methods=["GET", "POST"])
@bp.route("/register/<role>/", methods=["GET", "POST"])
def register(role: str):
    if request.method == "POST":
        user = User(
            username=request.form["username"],
            first_name=request.form["fname"],
            last_name=request.form["lname"],
            password_hash=generate_password_hash(request.form["pw"]),
            phone_number=request.form.get("phone"),
            role=role,
        )
        db.session.add(user)
        db.session.commit()
        session["user_id"] = user.id
        session["user_role"] = user.role
        if role == "Landlord":
            return redirect(f"/landlord/hub/{user.id}/")
        return redirect(f"/tenant/hub/{user.id}/")
    return render_template("register.html", role=role)


@bp.route("/login/<role>", methods=["GET", "POST"])
@bp.route("/login/<role>/", methods=["GET", "POST"])
def login_view(role: str):
    error = ""
    if request.method == "POST":
        user = User.query.filter_by(username=request.form.get("username"), role=role).first()
        if user and check_password_hash(user.password_hash, request.form.get("pw", "")):
            session["user_id"] = user.id
            session["user_role"] = user.role
            if role == "Landlord":
                return redirect(f"/landlord/hub/{user.id}/")
            return redirect(f"/tenant/hub/{user.id}/")
        error = "帳號、密碼或角色選取錯誤，請重新輸入！"
    return render_template("login.html", role=role, error=error)


@bp.route("/tenant/hub/<int:user_id>/")
def tenant_hub(user_id: int):
    return render_template("tenant_hub.html", user=get_or_404(User, user_id))


@bp.route("/landlord/hub/<int:user_id>/")
def landlord_hub(user_id: int):
    return render_template("landlord_hub.html", user=get_or_404(User, user_id))
