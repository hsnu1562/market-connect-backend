from __future__ import annotations

from datetime import UTC, datetime

from ..extensions import db
from ..models import (
    BOOKING_POLICY_INSTANT,
    INVENTORY_STATES,
    OPPORTUNITY_PUBLIC,
    OPPORTUNITY_TYPES,
    PUBLICATION_DRAFT,
    PUBLICATION_PUBLISHED,
    PUBLICATION_STATES,
    VERIFICATION_STATES,
    VERIFICATION_REVOKED,
    VERIFICATION_SUSPENDED,
    VERIFICATION_VERIFIED,
    InventoryGroup,
    Opportunity,
    Provider,
    SupplyAuditEvent,
    User,
    Venue,
)


REQUIREMENT_TYPES = frozenset(
    {
        "FOOD_REGISTRATION",
        "ELECTRICITY",
        "GAS",
        "VEHICLE_PLATE",
        "STALL_PHOTO",
        "EQUIPMENT",
    }
)


class SupplyDomainError(ValueError):
    """Raised when verified supply violates a Phase 3A invariant."""


def create_provider(
    *,
    managing_user_id: int,
    actor_user_id: int,
    display_name: str,
    contact_name: str,
    contact_phone: str,
    legal_name: str | None = None,
    description: str | None = None,
    contact_email: str | None = None,
) -> Provider:
    manager = db.session.get(User, managing_user_id)
    if manager is None or manager.status != "active":
        raise SupplyDomainError("Managing user account was not found or is inactive.")
    if not manager.has_role("Landlord"):
        raise SupplyDomainError("Managing user must have the Landlord role.")

    provider = Provider(
        managing_user=manager,
        display_name=_required_text(display_name, "display_name", 120),
        legal_name=_optional_text(legal_name, 160),
        description=_optional_text(description, 4000),
        contact_name=_required_text(contact_name, "contact_name", 100),
        contact_phone=_required_text(contact_phone, "contact_phone", 30),
        contact_email=_optional_text(contact_email, 320),
    )
    db.session.add(provider)
    db.session.flush()
    _audit(
        actor_user_id=actor_user_id,
        provider_id=provider.id,
        entity_type="provider",
        entity_id=provider.id,
        event_type="provider_created",
        after={"display_name": provider.display_name},
    )
    db.session.commit()
    return provider


def create_venue(
    provider: Provider,
    *,
    actor_user_id: int,
    name: str,
    city: str,
    address_line: str,
    country_code: str = "TW",
    district: str | None = None,
    postal_code: str | None = None,
    business_description: str | None = None,
) -> Venue:
    _ensure_provider_can_create_supply(provider)
    venue = Venue(
        provider=provider,
        name=_required_text(name, "name", 140),
        country_code=_required_text(country_code, "country_code", 2).upper(),
        city=_required_text(city, "city", 80),
        district=_optional_text(district, 80),
        address_line=_required_text(address_line, "address_line", 255),
        postal_code=_optional_text(postal_code, 20),
        business_description=_optional_text(business_description, 4000),
    )
    db.session.add(venue)
    db.session.flush()
    _audit(
        actor_user_id=actor_user_id,
        provider_id=provider.id,
        entity_type="venue",
        entity_id=venue.id,
        event_type="venue_created",
        after={"name": venue.name},
    )
    db.session.commit()
    return venue


def set_verification_status(
    entity: Provider | Venue,
    status: str,
    *,
    actor_user_id: int,
    expires_at: datetime | None = None,
) -> None:
    normalized = str(status).strip().upper()
    if normalized not in VERIFICATION_STATES:
        raise SupplyDomainError("Unsupported verification status.")
    before = {
        "status": entity.verification_status,
        "expires_at": _datetime_value(entity.verification_expires_at),
    }
    entity.verification_status = normalized
    entity.verified_at = datetime.now(UTC) if normalized == VERIFICATION_VERIFIED else None
    entity.verification_expires_at = expires_at if normalized == VERIFICATION_VERIFIED else None
    _audit(
        actor_user_id=actor_user_id,
        provider_id=entity.id if isinstance(entity, Provider) else entity.provider_id,
        entity_type="provider" if isinstance(entity, Provider) else "venue",
        entity_id=entity.id,
        event_type="verification_changed",
        before=before,
        after={"status": normalized, "expires_at": _datetime_value(expires_at)},
    )
    db.session.commit()


def create_opportunity(
    provider: Provider,
    venue: Venue,
    *,
    actor_user_id: int,
    title: str,
    opportunity_type: str,
    description: str | None = None,
    visibility: str = OPPORTUNITY_PUBLIC,
    pricing_context: str | None = None,
    requirements_summary: str | None = None,
    required_requirement_types: list[str] | None = None,
    cancellation_policy: str | None = None,
) -> Opportunity:
    _ensure_provider_can_create_supply(provider)
    if venue.provider_id != provider.id:
        raise SupplyDomainError("Venue does not belong to the Provider.")
    normalized_type = str(opportunity_type).strip().upper()
    if normalized_type not in OPPORTUNITY_TYPES:
        raise SupplyDomainError("Unsupported opportunity type.")
    normalized_visibility = str(visibility).strip().upper()
    if normalized_visibility not in {"PUBLIC", "PRIVATE"}:
        raise SupplyDomainError("Unsupported opportunity visibility.")

    opportunity = Opportunity(
        provider=provider,
        venue=venue,
        title=_required_text(title, "title", 180),
        description=_optional_text(description, 8000),
        opportunity_type=normalized_type,
        visibility=normalized_visibility,
        publication_status=PUBLICATION_DRAFT,
        booking_policy=BOOKING_POLICY_INSTANT,
        pricing_context=_optional_text(pricing_context, 2000),
        requirements_summary=_optional_text(requirements_summary, 2000),
        required_requirement_types=normalize_requirement_types(
            required_requirement_types or []
        ),
        cancellation_policy=_optional_text(cancellation_policy, 4000),
    )
    db.session.add(opportunity)
    db.session.flush()
    _audit(
        actor_user_id=actor_user_id,
        provider_id=provider.id,
        entity_type="opportunity",
        entity_id=opportunity.id,
        event_type="opportunity_created",
        after={"title": opportunity.title, "type": opportunity.opportunity_type},
    )
    db.session.commit()
    return opportunity


def set_publication_status(
    opportunity: Opportunity,
    status: str,
    *,
    actor_user_id: int,
) -> None:
    normalized = str(status).strip().upper()
    if normalized not in PUBLICATION_STATES:
        raise SupplyDomainError("Unsupported publication status.")
    if normalized == PUBLICATION_PUBLISHED:
        now = datetime.now(UTC)
        if not verification_is_current(opportunity.provider, now=now):
            raise SupplyDomainError("Provider must be verified before publication.")
        if not verification_is_current(opportunity.venue, now=now):
            raise SupplyDomainError("Venue must be verified before publication.")

    before = opportunity.publication_status
    opportunity.publication_status = normalized
    if normalized == PUBLICATION_PUBLISHED and opportunity.published_at is None:
        opportunity.published_at = datetime.now(UTC)
    _audit(
        actor_user_id=actor_user_id,
        provider_id=opportunity.provider_id,
        entity_type="opportunity",
        entity_id=opportunity.id,
        event_type="publication_changed",
        before={"status": before},
        after={"status": normalized},
    )
    db.session.commit()


def create_inventory_group(
    opportunity: Opportunity,
    *,
    actor_user_id: int,
    service_period_start: datetime,
    service_period_end: datetime,
    allocated_capacity: int,
    price_amount: int,
    currency: str = "TWD",
    status: str = "DRAFT",
    required_requirement_types: list[str] | None = None,
) -> InventoryGroup:
    _ensure_provider_can_create_supply(opportunity.provider)
    start = _aware_datetime(service_period_start, "service_period_start")
    end = _aware_datetime(service_period_end, "service_period_end")
    if end <= start:
        raise SupplyDomainError("Service period end must be after its start.")
    capacity = _nonnegative_integer(allocated_capacity, "allocated_capacity")
    price = _nonnegative_integer(price_amount, "price_amount")
    normalized_status = str(status).strip().upper()
    if normalized_status not in INVENTORY_STATES:
        raise SupplyDomainError("Unsupported inventory status.")
    if normalized_status == "ACTIVE":
        _ensure_inventory_can_activate(opportunity)

    inventory_group = InventoryGroup(
        opportunity=opportunity,
        service_period_start=start,
        service_period_end=end,
        allocated_capacity=capacity,
        price_amount=price,
        currency=_required_text(currency, "currency", 3).upper(),
        status=normalized_status,
        required_requirement_types=normalize_requirement_types(
            required_requirement_types or []
        ),
    )
    db.session.add(inventory_group)
    db.session.flush()
    _audit(
        actor_user_id=actor_user_id,
        provider_id=opportunity.provider_id,
        entity_type="inventory_group",
        entity_id=inventory_group.id,
        event_type="inventory_group_created",
        after={"allocated_capacity": capacity, "status": normalized_status},
    )
    db.session.commit()
    return inventory_group


def set_inventory_status(
    inventory_group: InventoryGroup,
    status: str,
    *,
    actor_user_id: int,
) -> None:
    normalized = str(status).strip().upper()
    if normalized not in INVENTORY_STATES:
        raise SupplyDomainError("Unsupported inventory status.")
    if normalized == "ACTIVE":
        _ensure_inventory_can_activate(inventory_group.opportunity)
    before = inventory_group.status
    inventory_group.status = normalized
    _audit(
        actor_user_id=actor_user_id,
        provider_id=inventory_group.opportunity.provider_id,
        entity_type="inventory_group",
        entity_id=inventory_group.id,
        event_type="inventory_status_changed",
        before={"status": before},
        after={"status": normalized},
    )
    db.session.commit()


def verification_is_current(entity: Provider | Venue, *, now: datetime) -> bool:
    if entity.verification_status != VERIFICATION_VERIFIED:
        return False
    expiry = entity.verification_expires_at
    if expiry is None:
        return True
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=UTC)
    return expiry > now


def _ensure_provider_can_create_supply(provider: Provider) -> None:
    if provider.verification_status in {
        VERIFICATION_SUSPENDED,
        VERIFICATION_REVOKED,
    }:
        raise SupplyDomainError(
            "Suspended or revoked Providers cannot create new supply."
        )


def _ensure_inventory_can_activate(opportunity: Opportunity) -> None:
    now = datetime.now(UTC)
    if not verification_is_current(opportunity.provider, now=now):
        raise SupplyDomainError("Provider must be verified before inventory activation.")
    if not verification_is_current(opportunity.venue, now=now):
        raise SupplyDomainError("Venue must be verified before inventory activation.")
    if opportunity.publication_status != PUBLICATION_PUBLISHED:
        raise SupplyDomainError("Opportunity must be published before inventory activation.")


def normalize_requirement_types(values: list[str]) -> list[str]:
    if not isinstance(values, list):
        raise SupplyDomainError("required_requirement_types must be a list.")
    normalized = []
    for value in values:
        requirement = str(value).strip().upper()
        if requirement not in REQUIREMENT_TYPES:
            raise SupplyDomainError(f"Unsupported requirement type: {requirement or value!r}.")
        if requirement not in normalized:
            normalized.append(requirement)
    return normalized


def _audit(
    *,
    actor_user_id: int,
    provider_id: int,
    entity_type: str,
    entity_id: int,
    event_type: str,
    before: dict | None = None,
    after: dict | None = None,
) -> None:
    db.session.add(
        SupplyAuditEvent(
            actor_user_id=actor_user_id,
            provider_id=provider_id,
            entity_type=entity_type,
            entity_id=entity_id,
            event_type=event_type,
            before_data=before,
            after_data=after,
        )
    )


def record_supply_audit(**kwargs) -> None:
    _audit(**kwargs)


def _required_text(value: str, field: str, limit: int) -> str:
    cleaned = " ".join(value.split()) if isinstance(value, str) else ""
    if not cleaned:
        raise SupplyDomainError(f"{field} is required.")
    if len(cleaned) > limit:
        raise SupplyDomainError(f"{field} exceeds {limit} characters.")
    return cleaned


def _optional_text(value: str | None, limit: int) -> str | None:
    cleaned = value.strip() if isinstance(value, str) else ""
    if not cleaned:
        return None
    if len(cleaned) > limit:
        raise SupplyDomainError(f"Text exceeds {limit} characters.")
    return cleaned


def _nonnegative_integer(value: int, field: str) -> int:
    if isinstance(value, bool):
        raise SupplyDomainError(f"{field} must be a non-negative integer.")
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        raise SupplyDomainError(f"{field} must be a non-negative integer.") from None
    if normalized < 0:
        raise SupplyDomainError(f"{field} must be a non-negative integer.")
    return normalized


def _aware_datetime(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime):
        raise SupplyDomainError(f"{field} must be an ISO 8601 datetime.")
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _datetime_value(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None
