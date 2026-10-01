from __future__ import annotations

from datetime import date

from authlib.integrations.base_client.errors import OAuthError
from flask import (
    Blueprint,
    abort,
    current_app,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from requests import RequestException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload

from ..extensions import db, oauth
from ..models import Booking, Slot, Stall, User
from ..security import (
    get_current_user,
    login_required,
    require_current_user_id,
    safe_next_url,
    sign_in,
)
from ..services.accounts import (
    ALLOWED_ROLES,
    RegistrationError,
    authenticate_local_user,
    ensure_user_role,
    register_local_user,
)
from ..services.identities import IdentityError, find_or_create_google_user


bp = Blueprint("web_auth", __name__)
_OAUTH_ROLE_KEY = "_oauth_requested_role"
_OAUTH_NEXT_KEY = "_oauth_next_url"


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
    current_user = get_current_user()
    is_tenant = current_user is not None and current_user.has_role("Tenant")

    for listing in listings:
        slots = listing["slots"]
        listing["next_date"] = slots[0].date
        listing["min_price"] = min(slot.price for slot in slots)
        listing["available_days"] = len({slot.date for slot in slots})
        listing["preview_slots"] = slots[:3]
        booking_url = (
            url_for(
                "web_stalls.booking_page",
                stall_id=listing["stall"].id,
                user_id=current_user.id,
            )
            if current_user is not None
            else url_for("web_stalls.stall_list")
        )
        listing["action_url"] = (
            booking_url
            if is_tenant
            else url_for("web_auth.account", intent="tenant", next=booking_url)
        )
        listing["action_label"] = "查看時段" if is_tenant else "登入後預約"

    stats = {
        "stalls": len(listings_by_stall),
        "slots": len(available_slots),
        "cities": len({listing["stall"].city for listing in listings_by_stall.values()}),
    }
    provider_url = (
        url_for("web_auth.landlord_hub", user_id=current_user.id)
        if current_user is not None and current_user.has_role("Landlord")
        else url_for("web_auth.account", intent="landlord")
    )
    return render_template(
        "index.html",
        listings=listings,
        stats=stats,
        current_user=current_user,
        provider_url=provider_url,
        account_url=url_for("web_auth.account"),
    )


@bp.route("/account", methods=["GET"])
@bp.route("/account/", methods=["GET"])
def account():
    current_user = get_current_user()
    intent = request.args.get("intent", "").lower()
    if intent not in {"", "tenant", "landlord"}:
        intent = ""
    return render_template(
        "account.html",
        intent=intent,
        next_url=safe_next_url(request.args.get("next")) or "",
        current_user=current_user,
        oauth_error=request.args.get("oauth_error") == "1",
    )


@bp.post("/account/roles/<role>")
@login_required()
def activate_role(role: str):
    role = _role_or_404(role)
    user = get_current_user()
    if user is None:
        abort(401)
    if ensure_user_role(user, role):
        db.session.commit()
    return redirect(safe_next_url(request.form.get("next")) or _dashboard_url(user, role))


@bp.get("/auth/google/login")
def google_login():
    role = _role_or_404(request.args.get("role", ""))
    next_url = safe_next_url(request.args.get("next"))
    current_user = get_current_user()
    if current_user is not None:
        if current_user.has_role(role):
            return redirect(next_url or _dashboard_url(current_user, role))
        return redirect(
            url_for("web_auth.account", intent=role.lower(), next=next_url or "")
        )

    if not _google_is_configured():
        current_app.logger.warning("Google login failed: provider is not configured")
        return _google_login_failed(role=role, next_url=next_url)

    session[_OAUTH_ROLE_KEY] = role
    session[_OAUTH_NEXT_KEY] = next_url or ""
    current_app.logger.info("Google login initiated")
    return oauth.google.authorize_redirect(_google_redirect_uri())


@bp.get("/auth/google/callback")
def google_callback():
    role = session.get(_OAUTH_ROLE_KEY)
    next_url = safe_next_url(session.get(_OAUTH_NEXT_KEY))
    if role not in ALLOWED_ROLES:
        current_app.logger.warning("Google login failed: missing role context")
        return _google_login_failed(next_url=next_url)

    try:
        token = oauth.google.authorize_access_token()
        userinfo = token.get("userinfo") or {}
        google_sub = userinfo.get("sub")
        email = userinfo.get("email")
        email_verified = _claim_is_true(userinfo.get("email_verified"))
        if not google_sub or not email or not email_verified:
            raise IdentityError("Required verified Google identity claims are missing.")

        user = find_or_create_google_user(
            google_sub=google_sub,
            email=email,
            email_verified=email_verified,
            display_name=userinfo.get("name") or "",
            picture_url=userinfo.get("picture"),
            requested_role=role,
            given_name=userinfo.get("given_name"),
            family_name=userinfo.get("family_name"),
        )
    except (OAuthError, RequestException, IdentityError, SQLAlchemyError) as error:
        db.session.rollback()
        current_app.logger.warning("Google login failed: %s", type(error).__name__)
        return _google_login_failed(role=role, next_url=next_url)

    sign_in(user)
    current_app.logger.info("Google login succeeded for user_id=%s", user.id)
    return redirect(next_url or _dashboard_url(user, role))


@bp.route("/register/<role>", methods=["GET", "POST"])
@bp.route("/register/<role>/", methods=["GET", "POST"])
def register(role: str):
    role = _role_or_404(role)
    current_user = get_current_user()
    if current_user is not None:
        return redirect(_dashboard_url(current_user, role))

    next_url = safe_next_url(request.args.get("next"))
    form_data = {"username": "", "fname": "", "lname": "", "phone": ""}
    error = ""
    if request.method == "POST":
        form_data = {key: request.form.get(key, "").strip() for key in form_data}
        try:
            user = register_local_user(
                username=form_data["username"],
                password=request.form.get("pw", ""),
                first_name=form_data["fname"],
                last_name=form_data["lname"],
                phone_number=form_data["phone"],
                role=role,
            )
        except RegistrationError as exc:
            error = str(exc)
        else:
            sign_in(user)
            return redirect(next_url or _dashboard_url(user, role))

    return render_template(
        "register.html",
        role=role,
        error=error,
        form_data=form_data,
        next_url=next_url or "",
    )


@bp.route("/login/<role>", methods=["GET", "POST"])
@bp.route("/login/<role>/", methods=["GET", "POST"])
def login_view(role: str):
    role = _role_or_404(role)
    current_user = get_current_user()
    if current_user is not None:
        return redirect(_dashboard_url(current_user, role))

    next_url = safe_next_url(request.args.get("next"))
    form_data = {"username": ""}
    error = ""
    if request.method == "POST":
        form_data["username"] = request.form.get("username", "").strip()
        user = authenticate_local_user(
            username=form_data["username"],
            password=request.form.get("pw", ""),
            role=role,
        )
        if user is None:
            error = "帳號、密碼或帳戶類型錯誤，請重新輸入。"
        else:
            sign_in(user)
            return redirect(next_url or _dashboard_url(user, role))

    return render_template(
        "login.html",
        role=role,
        error=error,
        form_data=form_data,
        next_url=next_url or "",
    )


@bp.route("/logout", methods=["POST"])
@bp.route("/logout/", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("web_auth.index"))


@bp.route("/tenant/hub/<int:user_id>/")
@login_required("Tenant")
def tenant_hub(user_id: int):
    return render_template("tenant_hub.html", user=require_current_user_id(user_id))


@bp.route("/landlord/hub/<int:user_id>/")
@login_required("Landlord")
def landlord_hub(user_id: int):
    return render_template("landlord_hub.html", user=require_current_user_id(user_id))


def _role_or_404(role: str) -> str:
    if role not in ALLOWED_ROLES:
        abort(404)
    return role


def _dashboard_url(user: User, preferred_role: str | None = None) -> str:
    if preferred_role == "Landlord" and user.has_role("Landlord"):
        return url_for("web_auth.landlord_hub", user_id=user.id)
    if preferred_role == "Tenant" and user.has_role("Tenant"):
        return url_for("web_auth.tenant_hub", user_id=user.id)
    if user.role == "Landlord" and user.has_role("Landlord"):
        return url_for("web_auth.landlord_hub", user_id=user.id)
    return url_for("web_auth.tenant_hub", user_id=user.id)


def _google_redirect_uri() -> str:
    configured_uri = (current_app.config.get("GOOGLE_REDIRECT_URI") or "").strip()
    if configured_uri:
        return configured_uri
    public_base_url = (
        current_app.config.get("PUBLIC_BASE_URL") or "http://localhost:5001"
    ).rstrip("/")
    return f"{public_base_url}/auth/google/callback"


def _google_is_configured() -> bool:
    return bool(
        current_app.config.get("GOOGLE_CLIENT_ID")
        and current_app.config.get("GOOGLE_CLIENT_SECRET")
    )


def _google_login_failed(*, role: str | None = None, next_url: str | None = None):
    session.pop(_OAUTH_ROLE_KEY, None)
    session.pop(_OAUTH_NEXT_KEY, None)
    intent = role.lower() if role in ALLOWED_ROLES else ""
    return redirect(
        url_for(
            "web_auth.account",
            intent=intent,
            next=next_url or "",
            oauth_error="1",
        )
    )


def _claim_is_true(value) -> bool:
    return value is True or (isinstance(value, str) and value.lower() == "true")
