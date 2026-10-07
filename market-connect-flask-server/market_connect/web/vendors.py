from __future__ import annotations

from flask import (
    Blueprint,
    abort,
    make_response,
    redirect,
    render_template,
    request,
    url_for,
)

from ..models import VendorProfile
from ..security import get_current_user, login_required, safe_next_url
from ..services.vendor_profiles import (
    MAX_VENDOR_PROFILE_IMAGE_BYTES,
    VENDOR_CATEGORIES,
    VendorProfileError,
    update_vendor_profile,
)
from .utils import get_or_404


bp = Blueprint("web_vendors", __name__)


@bp.route("/vendor/profile/", methods=["GET", "POST"])
@login_required("Tenant")
def profile_setup():
    user = get_current_user()
    if user is None:
        abort(401)
    profile = user.vendor_profile
    next_url = safe_next_url(request.values.get("next"))
    google_identity = next(
        (identity for identity in user.auth_identities if identity.provider == "google"),
        None,
    )
    form_data = {
        "brand_name": profile.brand_name if profile else "",
        "primary_category": profile.primary_category if profile else "",
        "brand_description": profile.brand_description if profile else "",
        "instagram_url": profile.instagram_url if profile else "",
        "facebook_url": profile.facebook_url if profile else "",
        "website_url": profile.website_url if profile else "",
        "contact_name": profile.contact_name if profile else user.display_name,
        "contact_phone": (
            profile.contact_phone if profile else (user.phone_number or "")
        ),
        "contact_email": (
            profile.contact_email
            if profile
            else (google_identity.email if google_identity else "")
        ),
        "food_registration_number": (
            profile.food_registration_number if profile else ""
        ),
    }
    error = ""
    if request.method == "POST":
        form_data = {
            key: request.form.get(key, "").strip()
            for key in form_data
        }
        try:
            profile = update_vendor_profile(
                user,
                **form_data,
                profile_image=request.files.get("profile_image"),
            )
        except VendorProfileError as exc:
            error = str(exc)
        else:
            return redirect(
                next_url
                or url_for("web_vendors.public_profile", profile_id=profile.id)
            )

    return (
        render_template(
            "vendor_profile_setup.html",
            current_user=user,
            profile=profile,
            form_data=form_data,
            error=error,
            next_url=next_url or "",
            categories=VENDOR_CATEGORIES,
            max_image_mb=MAX_VENDOR_PROFILE_IMAGE_BYTES // (1024 * 1024),
        ),
        400 if error else 200,
    )


@bp.get("/vendors/<int:profile_id>/")
def public_profile(profile_id: int):
    profile = get_or_404(VendorProfile, profile_id)
    return render_template(
        "vendor_profile_public.html",
        profile=profile,
        category_label=VENDOR_CATEGORIES.get(
            profile.primary_category,
            profile.primary_category,
        ),
    )


@bp.get("/vendor_profiles/<int:profile_id>/image/")
def profile_image(profile_id: int):
    profile = get_or_404(VendorProfile, profile_id)
    if not profile.has_profile_image or profile.profile_image_data is None:
        abort(404)

    response = make_response(profile.profile_image_data)
    response.content_type = profile.profile_image_content_type
    response.headers["Cache-Control"] = "public, max-age=604800, immutable"
    response.headers["Content-Security-Policy"] = "default-src 'none'; sandbox"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.set_etag(profile.profile_image_sha256)
    return response.make_conditional(request)
