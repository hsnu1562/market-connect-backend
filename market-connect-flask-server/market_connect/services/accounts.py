"""Local account registration and password authentication services."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.security import check_password_hash, generate_password_hash

from ..extensions import db
from ..models import User, UserRole


ALLOWED_ROLES = frozenset({"Tenant", "Landlord"})
_PHONE_PATTERN = re.compile(r"^\+?[0-9][0-9 ()-]{6,19}$")


class RegistrationError(ValueError):
    """Raised when a registration form cannot create a valid account."""


class ProfileError(ValueError):
    """Raised when account profile data is incomplete or invalid."""


def require_valid_role(role: str) -> str:
    if role not in ALLOWED_ROLES:
        raise ValueError("Unsupported account role.")
    return role


def register_local_user(
    *,
    username: str,
    password: str,
    first_name: str,
    last_name: str,
    phone_number: str,
    role: str,
) -> User:
    """Validate form fields and persist one password-based account."""

    require_valid_role(role)
    username = _clean_username(username)
    first_name = _clean_name(first_name, "名字")
    last_name = _clean_name(last_name, "姓氏")
    phone_number = _clean_phone_number(phone_number, required=False)
    _validate_password(password)

    if _find_user_by_username(username) is not None:
        raise RegistrationError("這個帳號已有人使用，請換一個。")

    user = User(
        username=username,
        password_hash=generate_password_hash(password),
        first_name=first_name,
        last_name=last_name,
        phone_number=phone_number,
        role=role,
        profile_completed_at=datetime.now(UTC),
    )
    ensure_user_role(user, role)
    db.session.add(user)
    try:
        db.session.commit()
    except IntegrityError as error:
        db.session.rollback()
        raise RegistrationError("這個帳號已有人使用，請換一個。") from error
    return user


def update_user_profile(
    user: User,
    *,
    nickname: str,
    first_name: str,
    last_name: str,
    phone_number: str,
) -> User:
    """Validate and persist the personal details collected after Google login."""

    try:
        user.nickname = _clean_nickname(nickname, required=False)
        user.first_name = _clean_name(first_name, "名字")
        user.last_name = _clean_name(last_name, "姓氏")
        user.phone_number = _clean_phone_number(phone_number, required=False)
    except RegistrationError as error:
        raise ProfileError(str(error)) from error

    user.profile_completed_at = datetime.now(UTC)
    try:
        db.session.commit()
    except SQLAlchemyError as error:
        db.session.rollback()
        raise ProfileError("個人資料暫時無法儲存，請稍後再試。") from error
    return user


def authenticate_local_user(*, username: str, password: str, role: str) -> User | None:
    """Return the matching user only when the role and password both match."""

    require_valid_role(role)
    if not isinstance(password, str) or not password:
        return None

    try:
        username = _clean_username(username)
    except RegistrationError:
        return None

    user = _find_user_by_username(username)
    if user is None or not user.password_hash or not check_password_hash(user.password_hash, password):
        return None
    if ensure_user_role(user, role):
        db.session.commit()
    return user


def ensure_user_role(user: User, role: str) -> bool:
    """Add a role membership once and retain the legacy primary role."""

    require_valid_role(role)
    if any(membership.role == role for membership in user.role_memberships):
        return False
    user.role_memberships.append(UserRole(role=role))
    return True


def _find_user_by_username(username: str) -> User | None:
    query = User.query.filter(func.lower(User.username) == username.casefold())
    return query.one_or_none()


def _clean_username(value: str) -> str:
    username = value.strip() if isinstance(value, str) else ""
    if not 3 <= len(username) <= 50:
        raise RegistrationError("帳號限 3–50 個字元。")
    if any(character.isspace() for character in username):
        raise RegistrationError("帳號不可含空白。")
    return username


def _clean_name(value: str, field_label: str) -> str:
    name = " ".join(value.split()) if isinstance(value, str) else ""
    if not 1 <= len(name) <= 50:
        raise RegistrationError(f"{field_label}限 1–50 字。")
    return name


def _clean_phone_number(value: str, *, required: bool = True) -> str | None:
    phone_number = value.strip() if isinstance(value, str) else ""
    if not phone_number and not required:
        return None
    if not _PHONE_PATTERN.fullmatch(phone_number):
        raise RegistrationError("聯絡電話格式不正確。")
    return phone_number


def _clean_nickname(value: str, *, required: bool = True) -> str | None:
    nickname = " ".join(value.split()) if isinstance(value, str) else ""
    if not nickname and not required:
        return None
    if not 1 <= len(nickname) <= 50:
        raise RegistrationError("暱稱限 1–50 字。")
    return nickname


def _validate_password(value: str) -> None:
    if not isinstance(value, str) or not 8 <= len(value) <= 128:
        raise RegistrationError("密碼需為 8–128 個字元。")
