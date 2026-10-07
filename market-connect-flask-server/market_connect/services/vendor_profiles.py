from __future__ import annotations

import re
from urllib.parse import urlsplit

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.datastructures import FileStorage

from ..extensions import db
from ..models import User, VendorProfile
from .stall_photos import MAX_STALL_PHOTO_BYTES, validate_stall_photo_uploads


VENDOR_CATEGORIES = {
    "food": "餐飲食品",
    "handmade": "手作設計",
    "clothing": "服飾配件",
    "services": "服務體驗",
    "other": "其他",
}
MAX_VENDOR_PROFILE_IMAGE_BYTES = MAX_STALL_PHOTO_BYTES
_PHONE_PATTERN = re.compile(r"^\+?[0-9][0-9 ()-]{6,29}$")


class VendorProfileError(ValueError):
    """Raised when a Vendor profile cannot be safely persisted."""


def update_vendor_profile(
    user: User,
    *,
    brand_name: str,
    primary_category: str,
    brand_description: str = "",
    instagram_url: str = "",
    facebook_url: str = "",
    website_url: str = "",
    contact_name: str,
    contact_phone: str,
    contact_email: str = "",
    food_registration_number: str = "",
    profile_image: FileStorage | None = None,
) -> VendorProfile:
    if not user.has_role("Tenant"):
        raise VendorProfileError("請先開通攤商功能。")

    category = primary_category.strip().lower()
    if category not in VENDOR_CATEGORIES:
        raise VendorProfileError("請選擇品牌分類。")

    profile = user.vendor_profile or VendorProfile(user=user)
    profile.brand_name = _required_single_line(brand_name, "品牌名稱", 100)
    profile.primary_category = category
    profile.brand_description = _optional_text(brand_description, "品牌介紹", 2000)
    profile.instagram_url = _optional_url(instagram_url, "Instagram")
    profile.facebook_url = _optional_url(facebook_url, "Facebook")
    profile.website_url = _optional_url(website_url, "品牌網站")
    profile.contact_name = _required_single_line(contact_name, "聯絡人姓名", 100)
    profile.contact_phone = _phone(contact_phone)
    profile.contact_email = _optional_email(contact_email)
    profile.food_registration_number = (
        _optional_single_line(food_registration_number, "食品業者登錄字號", 100)
        if category == "food"
        else None
    )

    if profile_image is not None and profile_image.filename:
        try:
            validated = validate_stall_photo_uploads([profile_image])[0]
        except ValueError as error:
            message = (
                str(error)
                .replace("攤位照片", "品牌圖片")
                .replace("每個攤位", "每個品牌")
            )
            raise VendorProfileError(message) from error
        profile.profile_image_filename = validated.filename
        profile.profile_image_content_type = validated.content_type
        profile.profile_image_byte_size = len(validated.data)
        profile.profile_image_sha256 = validated.sha256
        profile.profile_image_data = validated.data

    db.session.add(profile)
    try:
        db.session.commit()
    except IntegrityError as error:
        db.session.rollback()
        raise VendorProfileError("此帳戶已有攤商品牌資料。") from error
    except SQLAlchemyError as error:
        db.session.rollback()
        raise VendorProfileError("攤商品牌資料暫時無法儲存，請稍後再試。") from error
    return profile


def _required_single_line(value: str, label: str, limit: int) -> str:
    cleaned = _optional_single_line(value, label, limit)
    if not cleaned:
        raise VendorProfileError(f"請填寫{label}。")
    return cleaned


def _optional_single_line(value: str, label: str, limit: int) -> str | None:
    cleaned = " ".join(value.split()) if isinstance(value, str) else ""
    if not cleaned:
        return None
    if len(cleaned) > limit:
        raise VendorProfileError(f"{label}最多 {limit} 字。")
    return cleaned


def _optional_text(value: str, label: str, limit: int) -> str | None:
    cleaned = value.strip() if isinstance(value, str) else ""
    if not cleaned:
        return None
    if len(cleaned) > limit:
        raise VendorProfileError(f"{label}最多 {limit} 字。")
    return cleaned


def _phone(value: str) -> str:
    cleaned = value.strip() if isinstance(value, str) else ""
    if not _PHONE_PATTERN.fullmatch(cleaned):
        raise VendorProfileError("聯絡電話格式不正確。")
    return cleaned


def _optional_email(value: str) -> str | None:
    cleaned = value.strip() if isinstance(value, str) else ""
    if not cleaned:
        return None
    if (
        len(cleaned) > 320
        or cleaned.count("@") != 1
        or any(char.isspace() for char in cleaned)
    ):
        raise VendorProfileError("聯絡信箱格式不正確。")
    local, domain = cleaned.rsplit("@", 1)
    if not local or "." not in domain or domain.startswith(".") or domain.endswith("."):
        raise VendorProfileError("聯絡信箱格式不正確。")
    return cleaned


def _optional_url(value: str, label: str) -> str | None:
    cleaned = value.strip() if isinstance(value, str) else ""
    if not cleaned:
        return None
    if len(cleaned) > 2048:
        raise VendorProfileError(f"{label}網址過長。")
    parsed = urlsplit(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise VendorProfileError(
            f"{label}請輸入完整網址（以 http:// 或 https:// 開頭）。"
        )
    return cleaned
