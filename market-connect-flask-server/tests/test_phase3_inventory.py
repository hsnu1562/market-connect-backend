from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app import create_app
from market_connect.extensions import db
from market_connect.models import (
    INVENTORY_ACTIVE,
    PAYMENT_PENDING,
    PUBLICATION_PUBLISHED,
    RESERVATION_CANCELLED,
    RESERVATION_CONFIRMED,
    RESERVATION_EXPIRED,
    Booking,
    BookingRequirements,
    InventoryGroup,
    Opportunity,
    PaymentTransaction,
    Provider,
    Slot,
    Stall,
    User,
    VendorProfile,
    Venue,
)
from market_connect.services.inventory import (
    InventoryError,
    InventoryUnavailable,
    cancel_inventory_reservation,
    create_inventory_hold,
    get_inventory_availability,
    replace_category_quotas,
    update_allocated_capacity,
)
from market_connect.services.payments import PaymentStateError, begin_payment


NOW = datetime.now(UTC).replace(microsecond=0)


@pytest.fixture()
def app():
    app = create_app(
        {
            "APP_ENV": "testing",
            "BOOKING_HOLD_SECONDS": 900,
            "CSRF_PROTECT": False,
            "SECRET_KEY": "phase3-test-secret",
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "TESTING": True,
        }
    )
    with app.app_context():
        db.create_all()
        admin = User(
            username="phase3-admin",
            first_name="Phase",
            last_name="Admin",
            role="Landlord",
            is_admin=True,
        )
        manager = User(
            username="phase3-manager",
            first_name="Supply",
            last_name="Manager",
            role="Landlord",
        )
        food_vendor = _vendor("phase3-food", "food", food_registration_number="F-123")
        handmade_vendor = _vendor("phase3-handmade", "handmade")
        clothing_vendor = _vendor("phase3-clothing", "clothing")
        db.session.add_all(
            [admin, manager, food_vendor, handmade_vendor, clothing_vendor]
        )
        db.session.flush()

        provider = Provider(
            managing_user=manager,
            display_name="Verified Market Operator",
            contact_name="Supply Manager",
            contact_phone="0912000000",
            verification_status="VERIFIED",
            verified_at=NOW,
        )
        venue = Venue(
            provider=provider,
            name="Phase 3 Venue",
            city="Taipei",
            district="Zhongzheng",
            address_line="No. 1 Test Road",
            verification_status="VERIFIED",
            verified_at=NOW,
        )
        opportunity = Opportunity(
            provider=provider,
            venue=venue,
            title="Weekend Market",
            opportunity_type="EVENT",
            visibility="PUBLIC",
            publication_status=PUBLICATION_PUBLISHED,
            booking_policy="INSTANT",
            required_requirement_types=[],
            published_at=NOW,
        )
        inventory_group = InventoryGroup(
            opportunity=opportunity,
            service_period_start=NOW + timedelta(days=30),
            service_period_end=NOW + timedelta(days=30, hours=9),
            allocated_capacity=10,
            price_amount=800,
            currency="TWD",
            status=INVENTORY_ACTIVE,
            required_requirement_types=[],
        )
        db.session.add(inventory_group)
        db.session.commit()

    yield app

    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def test_overall_capacity_blocks_the_sixth_active_reservation(app):
    with app.app_context():
        group = InventoryGroup.query.one()
        group.allocated_capacity = 5
        db.session.commit()
        vendor = User.query.filter_by(username="phase3-handmade").one()

        for offset in range(5):
            create_inventory_hold(vendor.id, group.id, now=NOW + timedelta(seconds=offset))

        with pytest.raises(InventoryUnavailable, match="No allocated inventory"):
            create_inventory_hold(vendor.id, group.id, now=NOW + timedelta(seconds=10))
        assert get_inventory_availability(group, now=NOW).available == 0


def test_expired_hold_does_not_consume_capacity(app):
    with app.app_context():
        group = InventoryGroup.query.one()
        group.allocated_capacity = 1
        db.session.commit()
        vendor = User.query.filter_by(username="phase3-handmade").one()
        first = create_inventory_hold(vendor.id, group.id, now=NOW)

        availability = get_inventory_availability(
            group,
            now=first.hold_expires_at + timedelta(seconds=1),
        )
        assert availability.active_commitments == 0
        assert availability.available == 1

        second = create_inventory_hold(
            vendor.id,
            group.id,
            now=first.hold_expires_at + timedelta(seconds=1),
        )
        db.session.refresh(first)
        assert first.reservation_status == RESERVATION_EXPIRED
        assert second.reservation_status == "HELD"


def test_cancellation_releases_inventory_and_is_idempotent(app):
    with app.app_context():
        group = InventoryGroup.query.one()
        group.allocated_capacity = 1
        db.session.commit()
        vendor = User.query.filter_by(username="phase3-handmade").one()
        booking = create_inventory_hold(vendor.id, group.id, now=NOW)

        cancelled, changed = cancel_inventory_reservation(
            booking.id, requesting_user=vendor
        )
        assert changed is True
        assert cancelled.reservation_status == RESERVATION_CANCELLED
        assert get_inventory_availability(group, now=NOW).available == 1

        cancelled_again, changed_again = cancel_inventory_reservation(
            booking.id, requesting_user=vendor
        )
        assert changed_again is False
        assert cancelled_again.reservation_status == RESERVATION_CANCELLED
        assert get_inventory_availability(group, now=NOW).available == 1


def test_category_quota_blocks_third_food_reservation(app):
    with app.app_context():
        group = InventoryGroup.query.one()
        manager = User.query.filter_by(username="phase3-manager").one()
        food_vendor = User.query.filter_by(username="phase3-food").one()
        replace_category_quotas(group.id, {"food": 2}, actor_user_id=manager.id, now=NOW)

        create_inventory_hold(food_vendor.id, group.id, now=NOW)
        create_inventory_hold(food_vendor.id, group.id, now=NOW)
        with pytest.raises(InventoryUnavailable, match="vendor category"):
            create_inventory_hold(food_vendor.id, group.id, now=NOW)
        availability = get_inventory_availability(group, now=NOW)
        assert availability.available == 8
        assert availability.for_category("food") == 0


def test_quota_rows_form_allowlist_and_unallocated_remainder_is_not_open(app):
    with app.app_context():
        group = InventoryGroup.query.one()
        manager = User.query.filter_by(username="phase3-manager").one()
        clothing = User.query.filter_by(username="phase3-clothing").one()
        handmade = User.query.filter_by(username="phase3-handmade").one()
        replace_category_quotas(
            group.id,
            {"food": 4, "handmade": 3},
            actor_user_id=manager.id,
            now=NOW,
        )

        with pytest.raises(InventoryUnavailable, match="not allowed"):
            create_inventory_hold(clothing.id, group.id, now=NOW)
        for _ in range(3):
            create_inventory_hold(handmade.id, group.id, now=NOW)
        with pytest.raises(InventoryUnavailable, match="vendor category"):
            create_inventory_hold(handmade.id, group.id, now=NOW)

        availability = get_inventory_availability(group, now=NOW)
        assert availability.available == 7
        assert availability.for_category("clothing") == 0
        assert availability.for_category("handmade") == 0


def test_allocation_reduction_cannot_cross_active_commitments(app):
    with app.app_context():
        group = InventoryGroup.query.one()
        manager = User.query.filter_by(username="phase3-manager").one()
        vendor = User.query.filter_by(username="phase3-handmade").one()
        for _ in range(7):
            create_inventory_hold(vendor.id, group.id, now=NOW)

        updated = update_allocated_capacity(
            group.id, 7, actor_user_id=manager.id, now=NOW
        )
        assert updated.allocated_capacity == 7
        with pytest.raises(InventoryError, match="active reservation commitments"):
            update_allocated_capacity(group.id, 6, actor_user_id=manager.id, now=NOW)
        assert db.session.get(InventoryGroup, group.id).allocated_capacity == 7


def test_category_quota_reduction_cannot_cross_active_commitments(app):
    with app.app_context():
        group = InventoryGroup.query.one()
        manager = User.query.filter_by(username="phase3-manager").one()
        food_vendor = User.query.filter_by(username="phase3-food").one()
        replace_category_quotas(group.id, {"food": 4}, actor_user_id=manager.id, now=NOW)
        for _ in range(3):
            create_inventory_hold(food_vendor.id, group.id, now=NOW)

        replace_category_quotas(group.id, {"food": 3}, actor_user_id=manager.id, now=NOW)
        with pytest.raises(InventoryError, match="below active commitments"):
            replace_category_quotas(
                group.id,
                {"food": 2},
                actor_user_id=manager.id,
                now=NOW,
            )
        assert get_inventory_availability(group, now=NOW).category_capacity == {"food": 3}


@pytest.mark.parametrize("entity", ["provider", "venue"])
def test_unverified_supply_cannot_accept_a_hold(app, entity):
    with app.app_context():
        group = InventoryGroup.query.one()
        vendor = User.query.filter_by(username="phase3-handmade").one()
        target = group.opportunity.provider if entity == "provider" else group.opportunity.venue
        target.verification_status = "PENDING"
        db.session.commit()

        with pytest.raises(InventoryUnavailable, match=entity.capitalize()):
            create_inventory_hold(vendor.id, group.id, now=NOW)


def test_provider_suspension_blocks_holds_and_payment_but_preserves_confirmed(app):
    with app.app_context():
        group = InventoryGroup.query.one()
        vendor = User.query.filter_by(username="phase3-handmade").one()
        confirmed = create_inventory_hold(vendor.id, group.id, now=NOW)
        confirmed.reservation_status = RESERVATION_CONFIRMED
        confirmed.confirmed_at = NOW
        pending = create_inventory_hold(vendor.id, group.id, now=NOW)
        provider = group.opportunity.provider
        provider.verification_status = "SUSPENDED"
        db.session.commit()

        with pytest.raises(InventoryUnavailable, match="Provider"):
            create_inventory_hold(vendor.id, group.id, now=NOW)
        with pytest.raises(PaymentStateError, match="Provider"):
            begin_payment(pending.payment_id, "test-provider", now=NOW)
        db.session.refresh(confirmed)
        assert confirmed.reservation_status == RESERVATION_CONFIRMED


def test_required_booking_data_uses_profile_and_requirement_snapshot(app):
    with app.app_context():
        group = InventoryGroup.query.one()
        group.required_requirement_types = ["FOOD_REGISTRATION", "ELECTRICITY"]
        db.session.commit()
        food_vendor = User.query.filter_by(username="phase3-food").one()

        with pytest.raises(InventoryUnavailable, match="ELECTRICITY"):
            create_inventory_hold(food_vendor.id, group.id, now=NOW)
        booking = create_inventory_hold(
            food_vendor.id,
            group.id,
            requirements=BookingRequirements(electricity_required=True),
            now=NOW,
        )
        assert booking.requirements.electricity_required is True
        assert booking.vendor_category == "food"


def test_public_availability_counts_only_confirmed_and_live_holds(app, client):
    with app.app_context():
        group = InventoryGroup.query.one()
        vendor = User.query.filter_by(username="phase3-handmade").one()
        live = create_inventory_hold(vendor.id, group.id, now=NOW)
        confirmed = create_inventory_hold(vendor.id, group.id, now=NOW)
        expired = create_inventory_hold(vendor.id, group.id, now=NOW)
        cancelled = create_inventory_hold(vendor.id, group.id, now=NOW)
        confirmed.reservation_status = RESERVATION_CONFIRMED
        expired.reservation_status = RESERVATION_EXPIRED
        cancelled.reservation_status = RESERVATION_CANCELLED
        db.session.commit()
        opportunity_id = group.opportunity_id
        assert live.reservation_status == "HELD"

    response = client.get(f"/api/v1/opportunities/{opportunity_id}")
    assert response.status_code == 200
    availability = response.get_json()["opportunity"]["inventory_groups"][0][
        "availability"
    ]
    assert availability["active_commitments"] == 2
    assert availability["available"] == 8
    assert "bookings" not in response.get_json()["opportunity"]


def test_admin_can_create_provider_for_manager_without_owning_it(app, client):
    with app.app_context():
        admin = User.query.filter_by(username="phase3-admin").one()
        manager = User.query.filter_by(username="phase3-manager").one()
        admin_id = admin.id
        manager_id = manager.id
    with client.session_transaction() as session:
        session["user_id"] = admin_id

    response = client.post(
        "/api/v1/supply/providers",
        json={
            "managing_user_id": manager_id,
            "display_name": "Concierge-created Provider",
            "contact_name": "Manager",
            "contact_phone": "0912111222",
        },
    )
    assert response.status_code == 201
    provider_id = response.get_json()["provider"]["id"]
    with app.app_context():
        provider = db.session.get(Provider, provider_id)
        assert provider.managing_user_id == manager_id
        assert provider.managing_user_id != admin_id


def test_legacy_slot_booking_remains_compatible(app):
    with app.app_context():
        manager = User.query.filter_by(username="phase3-manager").one()
        vendor = User.query.filter_by(username="phase3-handmade").one()
        stall = Stall(
            owner=manager,
            loc_name="Legacy Stall",
            city="Taipei",
            district="Datong",
            road="Legacy Road",
            address_detail="No. 2",
        )
        slot = Slot(
            stall=stall,
            date=(NOW + timedelta(days=40)).date(),
            time=8,
            duration_hours=1,
            price=500,
        )
        payment = PaymentTransaction(
            merchant_order_id="LEGACY-PHASE3",
            amount=500,
            status=PAYMENT_PENDING,
        )
        booking = Booking(
            user=vendor,
            slot=slot,
            payment=payment,
            qr_code="LEGACY-P3",
            reservation_status="HELD",
            hold_expires_at=NOW + timedelta(minutes=15),
        )
        db.session.add(booking)
        db.session.commit()

        assert booking.slot_id == slot.id
        assert booking.inventory_group_id is None


def _vendor(
    username: str,
    category: str,
    *,
    food_registration_number: str | None = None,
) -> User:
    user = User(
        username=username,
        first_name="Test",
        last_name="Vendor",
        role="Tenant",
    )
    user.vendor_profile = VendorProfile(
        brand_name=f"{category.title()} Brand",
        primary_category=category,
        contact_name="Test Vendor",
        contact_phone="0912333444",
        food_registration_number=food_registration_number,
    )
    return user
