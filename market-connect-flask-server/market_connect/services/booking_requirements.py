from __future__ import annotations

from ..models import BookingRequirements


class BookingRequirementsError(ValueError):
    """Raised when reservation-specific operational data is invalid."""


def build_booking_requirements(
    *,
    electricity_required: bool = False,
    electricity_details: str = "",
    gas_required: bool = False,
    gas_details: str = "",
    equipment_requirements: str = "",
    vehicle_plate: str = "",
) -> BookingRequirements:
    if not isinstance(electricity_required, bool) or not isinstance(gas_required, bool):
        raise BookingRequirementsError("電力與瓦斯需求格式無效。")

    return BookingRequirements(
        electricity_required=electricity_required,
        electricity_details=(
            _optional_text(electricity_details, "電力需求說明", 255)
            if electricity_required
            else None
        ),
        gas_required=gas_required,
        gas_details=(
            _optional_text(gas_details, "瓦斯需求說明", 255)
            if gas_required
            else None
        ),
        equipment_requirements=_optional_text(
            equipment_requirements,
            "設備需求",
            1000,
        ),
        vehicle_plate=_optional_single_line(vehicle_plate, "車牌號碼", 20),
    )


def _optional_text(value: str, label: str, limit: int) -> str | None:
    cleaned = value.strip() if isinstance(value, str) else ""
    if not cleaned:
        return None
    if len(cleaned) > limit:
        raise BookingRequirementsError(f"{label}不可超過 {limit} 個字元。")
    return cleaned


def _optional_single_line(value: str, label: str, limit: int) -> str | None:
    cleaned = " ".join(value.split()) if isinstance(value, str) else ""
    if not cleaned:
        return None
    if len(cleaned) > limit:
        raise BookingRequirementsError(f"{label}不可超過 {limit} 個字元。")
    return cleaned.upper()
