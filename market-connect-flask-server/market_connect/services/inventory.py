from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from flask import current_app
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models import (
    BOOKING_POLICY_INSTANT,
    INVENTORY_ACTIVE,
    PAYMENT_FAILED,
    PAYMENT_PENDING,
    PUBLICATION_PUBLISHED,
    RESERVATION_CANCELLED,
    RESERVATION_CONFIRMED,
    RESERVATION_EXPIRED,
    RESERVATION_HELD,
    Booking,
    BookingRequirements,
    InventoryCategoryQuota,
    InventoryGroup,
    PaymentTransaction,
    User,
)
from .supply import SupplyDomainError, record_supply_audit, verification_is_current


class InventoryError(SupplyDomainError):
    """Raised when allocated inventory cannot satisfy an operation."""


class InventoryUnavailable(InventoryError):
    """Raised when a hold cannot consume the requested inventory unit."""


@dataclass(frozen=True)
class InventoryAvailability:
    allocated_capacity: int
    active_commitments: int
    available: int
    quota_allowlist_enabled: bool
    category_capacity: dict[str, int]
    category_commitments: dict[str, int]
    category_available: dict[str, int]

    def for_category(self, category: str) -> int:
        normalized = _normalize_category(category)
        if not self.quota_allowlist_enabled:
            return self.available
        return min(self.available, self.category_available.get(normalized, 0))

    def as_dict(self) -> dict:
        return {
            "allocated_capacity": self.allocated_capacity,
            "active_commitments": self.active_commitments,
            "available": self.available,
            "quota_allowlist_enabled": self.quota_allowlist_enabled,
            "category_capacity": self.category_capacity,
            "category_commitments": self.category_commitments,
            "category_available": self.category_available,
        }


def get_inventory_availability(
    inventory_group: InventoryGroup,
    *,
    now: datetime | None = None,
    lock_bookings: bool = False,
) -> InventoryAvailability:
    current_time = _as_utc(now or datetime.now(UTC))
    query = Booking.query.filter_by(inventory_group_id=inventory_group.id).order_by(
        Booking.id
    )
    if lock_bookings:
        query = query.with_for_update()
    bookings = query.all()

    active = [booking for booking in bookings if _is_active_commitment(booking, current_time)]
    category_commitments: dict[str, int] = {}
    for booking in active:
        if booking.vendor_category:
            category = _normalize_category(booking.vendor_category)
            category_commitments[category] = category_commitments.get(category, 0) + 1

    quota_rows = list(inventory_group.category_quotas)
    category_capacity = {
        _normalize_category(quota.category): quota.capacity for quota in quota_rows
    }
    overall_available = max(inventory_group.allocated_capacity - len(active), 0)
    category_available = {
        category: min(
            overall_available,
            max(capacity - category_commitments.get(category, 0), 0),
        )
        for category, capacity in category_capacity.items()
    }
    return InventoryAvailability(
        allocated_capacity=inventory_group.allocated_capacity,
        active_commitments=len(active),
        available=overall_available,
        quota_allowlist_enabled=bool(quota_rows),
        category_capacity=category_capacity,
        category_commitments=category_commitments,
        category_available=category_available,
    )


def create_inventory_hold(
    user_id: int,
    inventory_group_id: int,
    *,
    requirements: BookingRequirements | None = None,
    now: datetime | None = None,
) -> Booking:
    """Create one HELD reservation while locking the authoritative pool row."""

    current_time = _as_utc(now or datetime.now(UTC))
    try:
        # Lock order is InventoryGroup -> Booking rows -> PaymentTransaction rows.
        inventory_group = _lock_inventory_group(inventory_group_id)
        user = db.session.get(User, user_id)
        if user is None or user.status != "active" or not user.has_role("Tenant"):
            raise InventoryUnavailable("An active vendor account is required.")
        profile = user.vendor_profile
        if profile is None:
            raise InventoryUnavailable("Vendor profile is required before reservation.")

        _ensure_group_accepts_new_business(inventory_group, current_time)
        _expire_stale_holds_locked(inventory_group.id, current_time)
        availability = get_inventory_availability(
            inventory_group,
            now=current_time,
            lock_bookings=True,
        )
        category = _normalize_category(profile.primary_category)
        if availability.available <= 0:
            raise InventoryUnavailable("No allocated inventory remains.")
        if availability.quota_allowlist_enabled and category not in availability.category_capacity:
            raise InventoryUnavailable("Vendor category is not allowed for this inventory group.")
        if availability.for_category(category) <= 0:
            raise InventoryUnavailable("No inventory remains for this vendor category.")

        requirements_snapshot = requirements or BookingRequirements()
        _validate_requirements(inventory_group, user, requirements_snapshot)

        hold_seconds = _positive_hold_seconds()
        payment = PaymentTransaction(
            merchant_order_id=f"SPC-{uuid.uuid4().hex.upper()}",
            amount=inventory_group.price_amount,
            currency=inventory_group.currency,
            status=PAYMENT_PENDING,
        )
        booking = Booking(
            user=user,
            slot=None,
            inventory_group=inventory_group,
            vendor_category=category,
            payment=payment,
            requirements=requirements_snapshot,
            qr_code=uuid.uuid4().hex[:12].upper(),
            reservation_status=RESERVATION_HELD,
            hold_expires_at=current_time + timedelta(seconds=hold_seconds),
        )
        db.session.add(booking)
        db.session.commit()
        return booking
    except InventoryError:
        db.session.rollback()
        raise
    except IntegrityError:
        db.session.rollback()
        raise InventoryUnavailable(
            "Inventory changed while the reservation was being created."
        ) from None


def update_allocated_capacity(
    inventory_group_id: int,
    capacity: int,
    *,
    actor_user_id: int,
    now: datetime | None = None,
) -> InventoryGroup:
    normalized_capacity = _nonnegative_integer(capacity, "allocated_capacity")
    current_time = _as_utc(now or datetime.now(UTC))
    try:
        inventory_group = _lock_inventory_group(inventory_group_id)
        _expire_stale_holds_locked(inventory_group.id, current_time)
        availability = get_inventory_availability(
            inventory_group, now=current_time, lock_bookings=True
        )
        if normalized_capacity < availability.active_commitments:
            raise InventoryError(
                "Allocated capacity cannot be below active reservation commitments."
            )
        before = inventory_group.allocated_capacity
        inventory_group.allocated_capacity = normalized_capacity
        record_supply_audit(
            actor_user_id=actor_user_id,
            provider_id=inventory_group.opportunity.provider_id,
            entity_type="inventory_group",
            entity_id=inventory_group.id,
            event_type="allocation_changed",
            before={"allocated_capacity": before},
            after={"allocated_capacity": normalized_capacity},
        )
        db.session.commit()
        return inventory_group
    except InventoryError:
        db.session.rollback()
        raise


def replace_category_quotas(
    inventory_group_id: int,
    quotas: dict[str, int],
    *,
    actor_user_id: int,
    now: datetime | None = None,
) -> InventoryGroup:
    if not isinstance(quotas, dict):
        raise InventoryError("Category quotas must be an object.")
    normalized_quotas: dict[str, int] = {}
    for category, capacity in quotas.items():
        normalized_category = _normalize_category(category)
        if normalized_category in normalized_quotas:
            raise InventoryError("Category quota is duplicated.")
        normalized_quotas[normalized_category] = _nonnegative_integer(
            capacity, "category quota"
        )

    current_time = _as_utc(now or datetime.now(UTC))
    try:
        inventory_group = _lock_inventory_group(inventory_group_id)
        _expire_stale_holds_locked(inventory_group.id, current_time)
        availability = get_inventory_availability(
            inventory_group, now=current_time, lock_bookings=True
        )
        for category, commitments in availability.category_commitments.items():
            if normalized_quotas and category not in normalized_quotas:
                raise InventoryError(
                    f"Active category {category} must remain in the quota allowlist."
                )
            if normalized_quotas.get(category, commitments) < commitments:
                raise InventoryError(
                    f"Quota for {category} cannot be below active commitments."
                )

        before = availability.category_capacity
        for quota in list(inventory_group.category_quotas):
            db.session.delete(quota)
        db.session.flush()
        for category, capacity in normalized_quotas.items():
            db.session.add(
                InventoryCategoryQuota(
                    inventory_group_id=inventory_group.id,
                    category=category,
                    capacity=capacity,
                )
            )
        record_supply_audit(
            actor_user_id=actor_user_id,
            provider_id=inventory_group.opportunity.provider_id,
            entity_type="inventory_group",
            entity_id=inventory_group.id,
            event_type="category_quotas_changed",
            before={"quotas": before},
            after={"quotas": normalized_quotas},
        )
        db.session.commit()
        return inventory_group
    except InventoryError:
        db.session.rollback()
        raise


def cancel_inventory_reservation(
    booking_id: int,
    *,
    requesting_user: User,
) -> tuple[Booking, bool]:
    target = db.session.get(Booking, booking_id)
    if target is None or target.inventory_group_id is None:
        raise InventoryError("Inventory reservation was not found.")
    inventory_group_id = target.inventory_group_id

    try:
        _lock_inventory_group(inventory_group_id)
        booking = (
            Booking.query.filter_by(id=booking_id, inventory_group_id=inventory_group_id)
            .with_for_update()
            .one()
        )
        is_admin = requesting_user.is_admin and requesting_user.status == "active"
        if booking.user_id != requesting_user.id and not is_admin:
            raise InventoryError("Reservation access denied.")
        if booking.reservation_status == RESERVATION_CANCELLED:
            db.session.rollback()
            return booking, False
        if booking.reservation_status not in {
            RESERVATION_HELD,
            RESERVATION_CONFIRMED,
            RESERVATION_EXPIRED,
        }:
            raise InventoryError("Reservation cannot be cancelled from its current state.")
        booking.reservation_status = RESERVATION_CANCELLED
        db.session.commit()
        return booking, True
    except InventoryError:
        db.session.rollback()
        raise


def ensure_inventory_payment_allowed(
    bookings: list[Booking], *, now: datetime | None = None
) -> None:
    inventory_group_ids = {
        booking.inventory_group_id
        for booking in bookings
        if booking.inventory_group_id is not None
    }
    if not inventory_group_ids:
        return
    if len(inventory_group_ids) != 1 or any(
        booking.inventory_group_id is None for booking in bookings
    ):
        raise InventoryError("Payment group has inconsistent inventory targets.")
    inventory_group = db.session.get(InventoryGroup, inventory_group_ids.pop())
    if inventory_group is None:
        raise InventoryError("Inventory group was not found.")
    _ensure_group_accepts_new_business(
        inventory_group,
        _as_utc(now or datetime.now(UTC)),
    )


def inventory_booking_gate(
    inventory_group: InventoryGroup, *, now: datetime | None = None
) -> tuple[bool, str | None]:
    try:
        _ensure_group_accepts_new_business(
            inventory_group,
            _as_utc(now or datetime.now(UTC)),
        )
    except InventoryUnavailable as error:
        return False, str(error)
    return True, None


def _lock_inventory_group(inventory_group_id: int) -> InventoryGroup:
    inventory_group = (
        InventoryGroup.query.filter_by(id=inventory_group_id).with_for_update().first()
    )
    if inventory_group is None:
        raise InventoryError("Inventory group was not found.")
    return inventory_group


def _expire_stale_holds_locked(inventory_group_id: int, now: datetime) -> None:
    bookings = (
        Booking.query.filter_by(inventory_group_id=inventory_group_id)
        .order_by(Booking.id)
        .with_for_update()
        .all()
    )
    stale = [
        booking
        for booking in bookings
        if booking.reservation_status == RESERVATION_HELD
        and booking.hold_expires_at is not None
        and _as_utc(booking.hold_expires_at) <= now
    ]
    payment_ids = sorted(
        {booking.payment_id for booking in stale if booking.payment_id is not None}
    )
    payments = {
        payment.id: payment
        for payment in PaymentTransaction.query.filter(
            PaymentTransaction.id.in_(payment_ids)
        )
        .order_by(PaymentTransaction.id)
        .with_for_update()
        .all()
    } if payment_ids else {}
    for booking in stale:
        booking.reservation_status = RESERVATION_EXPIRED
        payment = payments.get(booking.payment_id)
        if payment is not None and payment.status == PAYMENT_PENDING:
            payment.status = PAYMENT_FAILED
            payment.failure_reason = "hold_expired"


def _ensure_group_accepts_new_business(
    inventory_group: InventoryGroup, now: datetime
) -> None:
    opportunity = inventory_group.opportunity
    if not verification_is_current(opportunity.provider, now=now):
        raise InventoryUnavailable("Provider is not currently verified.")
    if not verification_is_current(opportunity.venue, now=now):
        raise InventoryUnavailable("Venue is not currently verified.")
    if opportunity.publication_status != PUBLICATION_PUBLISHED:
        raise InventoryUnavailable("Opportunity is not published.")
    if opportunity.booking_policy != BOOKING_POLICY_INSTANT:
        raise InventoryUnavailable("Opportunity is not instant-bookable.")
    if inventory_group.status != INVENTORY_ACTIVE:
        raise InventoryUnavailable("Inventory group is not active.")
    if _as_utc(inventory_group.service_period_end) <= now:
        raise InventoryUnavailable("Inventory service period has ended.")


def _validate_requirements(
    inventory_group: InventoryGroup,
    user: User,
    requirements: BookingRequirements,
) -> None:
    required = set(inventory_group.opportunity.required_requirement_types or [])
    required.update(inventory_group.required_requirement_types or [])
    profile = user.vendor_profile
    available = {
        "FOOD_REGISTRATION": bool(profile and profile.food_registration_number),
        "STALL_PHOTO": bool(profile and profile.has_profile_image),
        "ELECTRICITY": bool(requirements.electricity_required),
        "GAS": bool(requirements.gas_required),
        "VEHICLE_PLATE": bool(requirements.vehicle_plate),
        "EQUIPMENT": bool(requirements.equipment_requirements),
    }
    missing = sorted(requirement for requirement in required if not available.get(requirement))
    if missing:
        raise InventoryUnavailable(
            "Missing required reservation information: " + ", ".join(missing)
        )


def _is_active_commitment(booking: Booking, now: datetime) -> bool:
    if booking.reservation_status == RESERVATION_CONFIRMED:
        return True
    return (
        booking.reservation_status == RESERVATION_HELD
        and booking.hold_expires_at is not None
        and _as_utc(booking.hold_expires_at) > now
    )


def _positive_hold_seconds() -> int:
    try:
        hold_seconds = int(current_app.config["BOOKING_HOLD_SECONDS"])
    except (KeyError, TypeError, ValueError):
        raise RuntimeError("BOOKING_HOLD_SECONDS must be a positive integer.") from None
    if hold_seconds <= 0:
        raise RuntimeError("BOOKING_HOLD_SECONDS must be a positive integer.")
    return hold_seconds


def _normalize_category(category: str) -> str:
    normalized = str(category).strip().lower()
    if not normalized or len(normalized) > 40:
        raise InventoryError("Vendor category is invalid.")
    return normalized


def _nonnegative_integer(value: int, field: str) -> int:
    if isinstance(value, bool):
        raise InventoryError(f"{field} must be a non-negative integer.")
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        raise InventoryError(f"{field} must be a non-negative integer.") from None
    if normalized < 0:
        raise InventoryError(f"{field} must be a non-negative integer.")
    return normalized


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
