"""Session, CSRF, and ownership helpers shared by web and API routes."""

from __future__ import annotations

import hmac
import secrets
from functools import wraps
from urllib.parse import urlsplit

from flask import abort, g, redirect, request, session, url_for

from .extensions import db
from .models import User


_UNSET = object()


def get_current_user() -> User | None:
    """Resolve the signed-in user from the server-side database record."""

    cached_user = getattr(g, "_spacis_current_user", _UNSET)
    if cached_user is not _UNSET:
        return cached_user

    user_id = session.get("user_id")
    user = db.session.get(User, user_id) if isinstance(user_id, int) else None
    if user is None:
        session.pop("user_id", None)
        session.pop("user_role", None)
    g._spacis_current_user = user
    return user


def sign_in(user: User) -> None:
    """Rotate session state after authentication to limit session fixation."""

    session.clear()
    session.permanent = True
    session["user_id"] = user.id


def login_required(*roles: str):
    """Redirect anonymous users and reject accounts outside the required roles."""

    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = get_current_user()
            if user is None:
                return redirect(url_for("web_auth.account", next=request.full_path.rstrip("?")))
            if roles and not any(user.has_role(role) for role in roles):
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


def require_current_user_id(user_id: int) -> User:
    """Ensure a path user ID belongs to the signed-in account."""

    user = get_current_user()
    if user is None:
        abort(401)
    if user.id != user_id:
        abort(403)
    return user


def safe_next_url(value: str | None) -> str | None:
    """Accept only local absolute paths for post-authentication redirects."""

    if not value or not value.startswith("/"):
        return None
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc:
        return None
    return value


def csrf_token() -> str:
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


def validate_csrf_token() -> None:
    """Reject state-changing browser or session-authenticated API requests without a token."""

    expected = session.get("_csrf_token", "")
    received = request.form.get("_csrf_token") or request.headers.get("X-CSRF-Token", "")
    if not expected or not received or not hmac.compare_digest(expected, received):
        abort(400, description="Invalid or missing CSRF token.")
