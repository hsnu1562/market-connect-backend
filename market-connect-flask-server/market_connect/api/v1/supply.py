from __future__ import annotations

from datetime import datetime

from flask import Blueprint, jsonify, request

from ...extensions import db
from ...models import (
    INVENTORY_ACTIVE,
    OPPORTUNITY_PUBLIC,
    PUBLICATION_PUBLISHED,
    Booking,
    InventoryGroup,
    Opportunity,
    Provider,
    User,
    Venue,
)
from ...security import get_current_user
from ...services.booking_requirements import (
    BookingRequirementsError,
    build_booking_requirements,
)
from ...services.inventory import (
    InventoryError,
    InventoryUnavailable,
    cancel_inventory_reservation,
    create_inventory_hold,
    get_inventory_availability,
    inventory_booking_gate,
    replace_category_quotas,
    update_allocated_capacity,
)
from ...services.supply import (
    SupplyDomainError,
    create_inventory_group,
    create_opportunity,
    create_provider,
    create_venue,
    set_inventory_status,
    set_publication_status,
    set_verification_status,
)


bp = Blueprint("api_v1_supply", __name__, url_prefix="/api/v1")


@bp.post("/supply/providers")
def admin_create_provider():
    actor, error = _require_user(admin=True)
    if error:
        return error
    payload = _payload()
    try:
        provider = create_provider(
            managing_user_id=_integer(payload, "managing_user_id"),
            actor_user_id=actor.id,
            display_name=payload.get("display_name", ""),
            legal_name=payload.get("legal_name"),
            description=payload.get("description"),
            contact_name=payload.get("contact_name", ""),
            contact_phone=payload.get("contact_phone", ""),
            contact_email=payload.get("contact_email"),
        )
    except SupplyDomainError as exc:
        return _domain_error(exc)
    return jsonify({"provider": _provider_payload(provider)}), 201


@bp.get("/supply/providers/<int:provider_id>")
def get_owned_provider(provider_id: int):
    actor, error = _require_user()
    if error:
        return error
    provider = db.session.get(Provider, provider_id)
    if provider is None:
        return jsonify({"error": "provider not found"}), 404
    if not _can_manage(actor, provider):
        return jsonify({"error": "provider access denied"}), 403
    return jsonify({"provider": _provider_payload(provider, include_supply=True)})


@bp.post("/supply/venues")
def create_owned_venue():
    actor, error = _require_user()
    if error:
        return error
    payload = _payload()
    try:
        provider_id = _integer(payload, "provider_id")
    except SupplyDomainError as exc:
        return _domain_error(exc)
    provider = db.session.get(Provider, provider_id)
    if provider is None:
        return jsonify({"error": "provider not found"}), 404
    if not _can_manage(actor, provider):
        return jsonify({"error": "provider access denied"}), 403
    try:
        venue = create_venue(
            provider,
            actor_user_id=actor.id,
            name=payload.get("name", ""),
            country_code=payload.get("country_code", "TW"),
            city=payload.get("city", ""),
            district=payload.get("district"),
            address_line=payload.get("address_line", ""),
            postal_code=payload.get("postal_code"),
            business_description=payload.get("business_description"),
        )
    except SupplyDomainError as exc:
        return _domain_error(exc)
    return jsonify({"venue": _venue_payload(venue)}), 201


@bp.patch("/supply/providers/<int:provider_id>/verification")
def update_provider_verification(provider_id: int):
    actor, error = _require_user(admin=True)
    if error:
        return error
    provider = db.session.get(Provider, provider_id)
    if provider is None:
        return jsonify({"error": "provider not found"}), 404
    payload = _payload()
    try:
        set_verification_status(
            provider,
            payload.get("status", ""),
            actor_user_id=actor.id,
            expires_at=_optional_datetime(payload.get("expires_at")),
        )
    except SupplyDomainError as exc:
        return _domain_error(exc)
    return jsonify({"provider": _provider_payload(provider)})


@bp.patch("/supply/venues/<int:venue_id>/verification")
def update_venue_verification(venue_id: int):
    actor, error = _require_user(admin=True)
    if error:
        return error
    venue = db.session.get(Venue, venue_id)
    if venue is None:
        return jsonify({"error": "venue not found"}), 404
    payload = _payload()
    try:
        set_verification_status(
            venue,
            payload.get("status", ""),
            actor_user_id=actor.id,
            expires_at=_optional_datetime(payload.get("expires_at")),
        )
    except SupplyDomainError as exc:
        return _domain_error(exc)
    return jsonify({"venue": _venue_payload(venue)})


@bp.post("/supply/opportunities")
def create_owned_opportunity():
    actor, error = _require_user()
    if error:
        return error
    payload = _payload()
    try:
        provider_id = _integer(payload, "provider_id")
        venue_id = _integer(payload, "venue_id")
    except SupplyDomainError as exc:
        return _domain_error(exc)
    provider = db.session.get(Provider, provider_id)
    venue = db.session.get(Venue, venue_id)
    if provider is None or venue is None:
        return jsonify({"error": "provider or venue not found"}), 404
    if not _can_manage(actor, provider):
        return jsonify({"error": "provider access denied"}), 403
    try:
        opportunity = create_opportunity(
            provider,
            venue,
            actor_user_id=actor.id,
            title=payload.get("title", ""),
            opportunity_type=payload.get("opportunity_type", ""),
            description=payload.get("description"),
            visibility=payload.get("visibility", OPPORTUNITY_PUBLIC),
            pricing_context=payload.get("pricing_context"),
            requirements_summary=payload.get("requirements_summary"),
            required_requirement_types=payload.get("required_requirement_types", []),
            cancellation_policy=payload.get("cancellation_policy"),
        )
    except SupplyDomainError as exc:
        return _domain_error(exc)
    return jsonify({"opportunity": _opportunity_payload(opportunity)}), 201


@bp.patch("/supply/opportunities/<int:opportunity_id>/publication")
def update_opportunity_publication(opportunity_id: int):
    actor, opportunity, error = _owned_opportunity(opportunity_id)
    if error:
        return error
    try:
        set_publication_status(
            opportunity,
            _payload().get("status", ""),
            actor_user_id=actor.id,
        )
    except SupplyDomainError as exc:
        return _domain_error(exc)
    return jsonify({"opportunity": _opportunity_payload(opportunity)})


@bp.post("/supply/inventory-groups")
def create_owned_inventory_group():
    payload = _payload()
    try:
        opportunity_id = _integer(payload, "opportunity_id")
    except SupplyDomainError as exc:
        return _domain_error(exc)
    actor, opportunity, error = _owned_opportunity(opportunity_id)
    if error:
        return error
    try:
        inventory_group = create_inventory_group(
            opportunity,
            actor_user_id=actor.id,
            service_period_start=_required_datetime(payload.get("service_period_start")),
            service_period_end=_required_datetime(payload.get("service_period_end")),
            allocated_capacity=_integer(payload, "allocated_capacity"),
            price_amount=_integer(payload, "price_amount"),
            currency=payload.get("currency", "TWD"),
            status=payload.get("status", "DRAFT"),
            required_requirement_types=payload.get("required_requirement_types", []),
        )
    except SupplyDomainError as exc:
        return _domain_error(exc)
    return jsonify({"inventory_group": _inventory_group_payload(inventory_group)}), 201


@bp.patch("/supply/inventory-groups/<int:inventory_group_id>")
def update_owned_inventory_group(inventory_group_id: int):
    actor, inventory_group, error = _owned_inventory_group(inventory_group_id)
    if error:
        return error
    payload = _payload()
    try:
        if "allocated_capacity" in payload:
            inventory_group = update_allocated_capacity(
                inventory_group.id,
                payload["allocated_capacity"],
                actor_user_id=actor.id,
            )
        if "status" in payload:
            set_inventory_status(
                inventory_group,
                payload["status"],
                actor_user_id=actor.id,
            )
    except SupplyDomainError as exc:
        return _domain_error(exc, status=409)
    return jsonify({"inventory_group": _inventory_group_payload(inventory_group)})


@bp.put("/supply/inventory-groups/<int:inventory_group_id>/category-quotas")
def update_owned_category_quotas(inventory_group_id: int):
    actor, inventory_group, error = _owned_inventory_group(inventory_group_id)
    if error:
        return error
    payload = _payload()
    try:
        inventory_group = replace_category_quotas(
            inventory_group.id,
            payload.get("quotas", {}),
            actor_user_id=actor.id,
        )
    except SupplyDomainError as exc:
        return _domain_error(exc, status=409)
    return jsonify({"inventory_group": _inventory_group_payload(inventory_group)})


@bp.get("/opportunities/<int:opportunity_id>")
def public_opportunity(opportunity_id: int):
    opportunity = db.session.get(Opportunity, opportunity_id)
    if (
        opportunity is None
        or opportunity.visibility != OPPORTUNITY_PUBLIC
        or opportunity.publication_status != PUBLICATION_PUBLISHED
    ):
        return jsonify({"error": "opportunity not found"}), 404
    return jsonify({"opportunity": _opportunity_payload(opportunity, public=True)})


@bp.post("/inventory-groups/<int:inventory_group_id>/reservations")
def create_inventory_reservation(inventory_group_id: int):
    user, error = _require_user(role="Tenant")
    if error:
        return error
    payload = _payload()
    requirements_payload = payload.get("requirements", {})
    if not isinstance(requirements_payload, dict):
        return jsonify({"error": "requirements must be an object"}), 400
    try:
        requirements = build_booking_requirements(
            electricity_required=requirements_payload.get("electricity_required", False),
            electricity_details=requirements_payload.get("electricity_details", ""),
            gas_required=requirements_payload.get("gas_required", False),
            gas_details=requirements_payload.get("gas_details", ""),
            equipment_requirements=requirements_payload.get(
                "equipment_requirements", ""
            ),
            vehicle_plate=requirements_payload.get("vehicle_plate", ""),
        )
        booking = create_inventory_hold(
            user.id,
            inventory_group_id,
            requirements=requirements,
        )
    except BookingRequirementsError as exc:
        return jsonify({"error": str(exc)}), 400
    except InventoryUnavailable as exc:
        return _domain_error(exc, status=409)
    return jsonify({"reservation": _reservation_payload(booking)}), 201


@bp.post("/reservations/<int:booking_id>/cancel")
def cancel_reservation(booking_id: int):
    user, error = _require_user()
    if error:
        return error
    try:
        booking, changed = cancel_inventory_reservation(
            booking_id,
            requesting_user=user,
        )
    except InventoryError as exc:
        return _domain_error(exc, status=409)
    return jsonify({"changed": changed, "reservation": _reservation_payload(booking)})


def _owned_opportunity(opportunity_id: int):
    actor, error = _require_user()
    if error:
        return None, None, error
    opportunity = db.session.get(Opportunity, opportunity_id)
    if opportunity is None:
        return actor, None, (jsonify({"error": "opportunity not found"}), 404)
    if not _can_manage(actor, opportunity.provider):
        return actor, None, (jsonify({"error": "provider access denied"}), 403)
    return actor, opportunity, None


def _owned_inventory_group(inventory_group_id: int):
    actor, error = _require_user()
    if error:
        return None, None, error
    inventory_group = db.session.get(InventoryGroup, inventory_group_id)
    if inventory_group is None:
        return actor, None, (jsonify({"error": "inventory group not found"}), 404)
    if not _can_manage(actor, inventory_group.opportunity.provider):
        return actor, None, (jsonify({"error": "provider access denied"}), 403)
    return actor, inventory_group, None


def _require_user(*, admin: bool = False, role: str | None = None):
    user = get_current_user()
    if user is None:
        return None, (jsonify({"error": "authentication required"}), 401)
    if user.status != "active":
        return None, (jsonify({"error": "account is inactive"}), 403)
    if admin and not user.is_admin:
        return None, (jsonify({"error": "admin access required"}), 403)
    if role and not user.has_role(role):
        return None, (jsonify({"error": "account role is not permitted"}), 403)
    return user, None


def _can_manage(user: User, provider: Provider) -> bool:
    return (user.is_admin and user.status == "active") or provider.managing_user_id == user.id


def _provider_payload(provider: Provider, *, include_supply: bool = False) -> dict:
    payload = {
        "id": provider.id,
        "managing_user_id": provider.managing_user_id,
        "display_name": provider.display_name,
        "legal_name": provider.legal_name,
        "description": provider.description,
        "contact_name": provider.contact_name,
        "contact_phone": provider.contact_phone,
        "contact_email": provider.contact_email,
        "verification_status": provider.verification_status,
        "verification_expires_at": _datetime_payload(provider.verification_expires_at),
    }
    if include_supply:
        payload["venues"] = [_venue_payload(venue) for venue in provider.venues]
        payload["opportunities"] = [
            _opportunity_payload(opportunity) for opportunity in provider.opportunities
        ]
    return payload


def _venue_payload(venue: Venue) -> dict:
    return {
        "id": venue.id,
        "provider_id": venue.provider_id,
        "name": venue.name,
        "country_code": venue.country_code,
        "city": venue.city,
        "district": venue.district,
        "address_line": venue.address_line,
        "postal_code": venue.postal_code,
        "verification_status": venue.verification_status,
        "verification_expires_at": _datetime_payload(venue.verification_expires_at),
    }


def _opportunity_payload(opportunity: Opportunity, *, public: bool = False) -> dict:
    payload = {
        "id": opportunity.id,
        "provider_id": opportunity.provider_id,
        "venue_id": opportunity.venue_id,
        "title": opportunity.title,
        "description": opportunity.description,
        "opportunity_type": opportunity.opportunity_type,
        "visibility": opportunity.visibility,
        "publication_status": opportunity.publication_status,
        "booking_policy": opportunity.booking_policy,
        "pricing_context": opportunity.pricing_context,
        "requirements_summary": opportunity.requirements_summary,
        "required_requirement_types": opportunity.required_requirement_types,
        "cancellation_policy": opportunity.cancellation_policy,
    }
    if public:
        payload["provider"] = {
            "display_name": opportunity.provider.display_name,
            "verification_status": opportunity.provider.verification_status,
        }
        payload["venue"] = _venue_payload(opportunity.venue)
        payload["inventory_groups"] = [
            _inventory_group_payload(inventory_group, include_availability=True)
            for inventory_group in opportunity.inventory_groups
            if inventory_group.status == INVENTORY_ACTIVE
        ]
    else:
        payload["inventory_groups"] = [
            _inventory_group_payload(inventory_group)
            for inventory_group in opportunity.inventory_groups
        ]
    return payload


def _inventory_group_payload(
    inventory_group: InventoryGroup, *, include_availability: bool = False
) -> dict:
    payload = {
        "id": inventory_group.id,
        "opportunity_id": inventory_group.opportunity_id,
        "service_period_start": _datetime_payload(inventory_group.service_period_start),
        "service_period_end": _datetime_payload(inventory_group.service_period_end),
        "allocated_capacity": inventory_group.allocated_capacity,
        "price_amount": inventory_group.price_amount,
        "currency": inventory_group.currency,
        "status": inventory_group.status,
        "required_requirement_types": inventory_group.required_requirement_types,
        "category_quotas": {
            quota.category: quota.capacity for quota in inventory_group.category_quotas
        },
    }
    if include_availability:
        payload["availability"] = get_inventory_availability(inventory_group).as_dict()
        bookable, gate_reason = inventory_booking_gate(inventory_group)
        payload["accepting_reservations"] = bookable
        payload["unavailable_reason"] = gate_reason
    return payload


def _reservation_payload(booking: Booking) -> dict:
    return {
        "id": booking.id,
        "inventory_group_id": booking.inventory_group_id,
        "vendor_category": booking.vendor_category,
        "qr_code": booking.qr_code,
        "reservation_status": booking.reservation_status,
        "hold_expires_at": _datetime_payload(booking.hold_expires_at),
        "payment_id": booking.payment_id,
        "payment_status": booking.payment_state,
    }


def _payload() -> dict:
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else {}


def _integer(payload: dict, name: str) -> int:
    try:
        return int(payload.get(name))
    except (TypeError, ValueError):
        raise SupplyDomainError(f"{name} must be an integer.") from None


def _required_datetime(value) -> datetime:
    parsed = _optional_datetime(value)
    if parsed is None:
        raise SupplyDomainError("A valid ISO 8601 datetime is required.")
    return parsed


def _optional_datetime(value) -> datetime | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise SupplyDomainError("Datetime must use ISO 8601 format.")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise SupplyDomainError("Datetime must use ISO 8601 format.") from None


def _datetime_payload(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _domain_error(error: Exception, *, status: int = 400):
    return jsonify({"error": str(error)}), status
