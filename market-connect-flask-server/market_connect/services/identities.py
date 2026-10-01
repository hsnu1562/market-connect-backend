"""External identity lookup and transactional account creation."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models import AuthIdentity, User
from .accounts import ensure_user_role, require_valid_role


class IdentityError(RuntimeError):
    """Raised when an external identity cannot be safely persisted."""


def find_or_create_google_user(
    *,
    google_sub: str,
    email: str,
    email_verified: bool,
    display_name: str,
    picture_url: str | None,
    requested_role: str,
    given_name: str | None = None,
    family_name: str | None = None,
) -> User:
    """Resolve Google by stable subject, never by email, and grant the requested role."""

    require_valid_role(requested_role)
    google_sub = _required_text(google_sub, "Google subject")
    email = _required_text(email, "Google email")
    if not email_verified:
        raise IdentityError("Google email is not verified.")

    identity = AuthIdentity.query.filter_by(
        provider="google",
        provider_subject=google_sub,
    ).one_or_none()
    if identity is not None:
        return _refresh_existing_identity(
            identity,
            email=email,
            display_name=display_name,
            picture_url=picture_url,
            requested_role=requested_role,
        )

    first_name, last_name = _profile_names(
        given_name=given_name,
        family_name=family_name,
        display_name=display_name,
    )
    user = User(
        username=_google_username(google_sub),
        password_hash=None,
        first_name=first_name,
        last_name=last_name,
        phone_number=None,
        role=requested_role,
    )
    ensure_user_role(user, requested_role)
    identity = AuthIdentity(
        user=user,
        provider="google",
        provider_subject=google_sub,
        email=email,
        email_verified=True,
        display_name=_trim(display_name, 255),
        picture_url=_trim(picture_url, 2048),
    )
    db.session.add_all((user, identity))
    try:
        db.session.commit()
    except IntegrityError as error:
        db.session.rollback()
        # A concurrent callback may have won the unique provider/subject insert.
        identity = AuthIdentity.query.filter_by(
            provider="google",
            provider_subject=google_sub,
        ).one_or_none()
        if identity is None:
            raise IdentityError("Google identity could not be created.") from error
        return _refresh_existing_identity(
            identity,
            email=email,
            display_name=display_name,
            picture_url=picture_url,
            requested_role=requested_role,
        )
    return user


def _refresh_existing_identity(
    identity: AuthIdentity,
    *,
    email: str,
    display_name: str,
    picture_url: str | None,
    requested_role: str,
) -> User:
    user = identity.user
    if user.status != "active":
        raise IdentityError("SPACIS account is not active.")

    identity.email = email
    identity.email_verified = True
    identity.display_name = _trim(display_name, 255)
    identity.picture_url = _trim(picture_url, 2048)
    identity.last_login_at = datetime.now(UTC)
    ensure_user_role(user, requested_role)
    try:
        db.session.commit()
    except IntegrityError as error:
        db.session.rollback()
        raise IdentityError("Google identity could not be updated.") from error
    return user


def _google_username(google_sub: str) -> str:
    digest = hashlib.sha256(google_sub.encode("utf-8")).hexdigest()[:20]
    return f"google_{digest}"


def _profile_names(
    *,
    given_name: str | None,
    family_name: str | None,
    display_name: str,
) -> tuple[str, str]:
    given = _trim(given_name, 50)
    family = _trim(family_name, 50)
    display = " ".join(display_name.split()) if isinstance(display_name, str) else ""
    if not given and display:
        parts = display.split(" ", 1)
        given = _trim(parts[0], 50)
        if len(parts) > 1 and not family:
            family = _trim(parts[1], 50)
    return given or "Google", family or "User"


def _required_text(value: str, label: str) -> str:
    cleaned = value.strip() if isinstance(value, str) else ""
    if not cleaned:
        raise IdentityError(f"{label} is missing.")
    return cleaned


def _trim(value: str | None, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    return cleaned[:limit] or None
