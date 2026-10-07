from __future__ import annotations

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import flask_migrate
import pytest
from flask import Flask
from flask_migrate import downgrade, upgrade
from sqlalchemy import create_engine, delete, inspect, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import IntegrityError

from app import create_app
from market_connect.extensions import db
from market_connect.models import (
    ACTIVE_RESERVATION_STATUSES,
    RESERVATION_CONFIRMED,
    RESERVATION_EXPIRED,
    RESERVATION_HELD,
    Booking,
    InventoryCategoryQuota,
    InventoryGroup,
    Opportunity,
    PaymentTransaction,
    Provider,
    Stall,
    StallCertification,
    User,
    VendorProfile,
    Venue,
)
from market_connect.services.bookings import (
    BookingSelectionError,
    create_booking_for_slots,
)
from market_connect.services.inventory import (
    InventoryUnavailable,
    create_inventory_hold,
)


pytestmark = pytest.mark.postgres

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"
SAFE_DATABASE_NAME_PARTS = (
    "test",
    "testing",
    "tmp",
    "temporary",
    "disposable",
    "ci",
    "sandbox",
    "staging",
)


@dataclass(frozen=True)
class PostgresHarness:
    app: Flask
    schema: str


@pytest.fixture()
def postgres_harness() -> PostgresHarness:
    test_url = _validated_test_database_url()
    admin_engine = create_engine(test_url, pool_pre_ping=True)
    schema = f"spacis_test_{uuid.uuid4().hex}"

    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))

    scoped_url = _url_with_search_path(test_url, schema)
    app = create_app(
        {
            "APP_ENV": "testing",
            "BOOKING_HOLD_SECONDS": 900,
            "CSRF_PROTECT": False,
            "SECRET_KEY": "postgres-integration-test-secret",
            "SQLALCHEMY_DATABASE_URI": scoped_url.render_as_string(
                hide_password=False
            ),
            "TESTING": True,
        }
    )

    try:
        with app.app_context():
            _create_pre_alembic_schema()
            upgrade(directory=str(MIGRATIONS_DIR), revision="20261004_09")
            _assert_revision_09_schema(schema)
        yield PostgresHarness(app=app, schema=schema)
    finally:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin_engine.dispose()


def test_postgres_migrates_09_to_12_and_applies_legacy_defaults(
    postgres_harness: PostgresHarness,
) -> None:
    with postgres_harness.app.app_context():
        seeded = _seed_revision_09_inventory()
        db.session.execute(
            text(
                """
                INSERT INTO booking (
                    user_id, slot_id, qr_code, payment_status,
                    payment_method, created_at
                ) VALUES (
                    :user_id, :slot_id, 'PG-LEGACY', 'Paid',
                    'Credit Card', CURRENT_TIMESTAMP
                )
                """
            ),
            {
                "user_id": seeded["tenant_id"],
                "slot_id": seeded["slot_ids"][0],
            },
        )
        db.session.commit()

        _upgrade_to_head()

        migrated_legacy_row = db.session.execute(
            text(
                """
                SELECT reservation_status, payment_id,
                       payment_status, payment_method
                FROM booking
                WHERE qr_code = 'PG-LEGACY'
                """
            )
        ).one()
        assert migrated_legacy_row == (
            RESERVATION_CONFIRMED,
            None,
            "Paid",
            "Credit Card",
        )

        row = db.session.execute(
            text(
                """
                INSERT INTO booking (user_id, slot_id, qr_code, created_at)
                VALUES (:user_id, :slot_id, :qr_code, CURRENT_TIMESTAMP)
                RETURNING payment_status, payment_method, reservation_status
                """
            ),
            {
                "user_id": seeded["tenant_id"],
                "slot_id": seeded["slot_ids"][1],
                "qr_code": "PG-DEFAULTS",
            },
        ).one()
        db.session.commit()

        assert row == ("NotApplicable", "", RESERVATION_HELD)
        assert {
            "payment_transaction",
            "vendor_profile",
            "booking_requirement",
            "provider",
            "venue",
            "opportunity",
            "inventory_group",
            "inventory_category_quota",
        }.issubset(inspect(db.engine).get_table_names())


def test_postgres_partial_unique_index_allows_history_but_one_active_booking(
    postgres_harness: PostgresHarness,
) -> None:
    with postgres_harness.app.app_context():
        _upgrade_to_head()
        seeded = _seed_inventory()
        user_id = seeded["tenant_ids"][0]
        slot_id = seeded["slot_id"]

        _insert_booking(user_id, slot_id, "PG-ACTIVE-1", RESERVATION_HELD)
        db.session.commit()

        with pytest.raises(IntegrityError):
            _insert_booking(
                user_id,
                slot_id,
                "PG-ACTIVE-2",
                RESERVATION_CONFIRMED,
            )
            db.session.commit()
        db.session.rollback()

        db.session.execute(
            text(
                "UPDATE booking SET reservation_status = :status "
                "WHERE qr_code = 'PG-ACTIVE-1'"
            ),
            {"status": RESERVATION_EXPIRED},
        )
        db.session.commit()

        _insert_booking(
            user_id,
            slot_id,
            "PG-ACTIVE-3",
            RESERVATION_CONFIRMED,
        )
        _insert_booking(user_id, slot_id, "PG-HISTORY", "CANCELLED")
        db.session.commit()

        active_count = Booking.query.filter(
            Booking.slot_id == slot_id,
            Booking.reservation_status.in_(ACTIVE_RESERVATION_STATUSES),
        ).count()
        assert active_count == 1
        assert Booking.query.filter_by(slot_id=slot_id).count() == 3


def test_postgres_for_update_prevents_two_services_taking_final_slot(
    postgres_harness: PostgresHarness,
) -> None:
    with postgres_harness.app.app_context():
        _upgrade_to_head()
        seeded = _seed_inventory(vendor_count=2)
    barrier = threading.Barrier(2)

    def attempt_booking(user_id: int) -> bool:
        with postgres_harness.app.app_context():
            try:
                barrier.wait(timeout=10)
                qr_code, created = create_booking_for_slots(
                    user_id,
                    [seeded["slot_id"]],
                )
                return bool(qr_code and created == 1)
            except BookingSelectionError:
                db.session.rollback()
                return False
            finally:
                db.session.remove()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(attempt_booking, seeded["tenant_ids"]))

    assert sorted(results) == [False, True]
    with postgres_harness.app.app_context():
        assert Booking.query.filter(
            Booking.slot_id == seeded["slot_id"],
            Booking.reservation_status.in_(ACTIVE_RESERVATION_STATUSES),
        ).count() == 1


def test_postgres_rejects_duplicate_provider_transaction_ids(
    postgres_harness: PostgresHarness,
) -> None:
    with postgres_harness.app.app_context():
        _upgrade_to_head()
        first = PaymentTransaction(
            merchant_order_id="PG-MERCHANT-1",
            provider_transaction_id="PG-PROVIDER-TX",
            amount=500,
        )
        db.session.add(first)
        db.session.commit()

        db.session.add(
            PaymentTransaction(
                merchant_order_id="PG-MERCHANT-2",
                provider_transaction_id="PG-PROVIDER-TX",
                amount=500,
            )
        )
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_postgres_phase2_foreign_key_delete_actions(
    postgres_harness: PostgresHarness,
) -> None:
    with postgres_harness.app.app_context():
        _upgrade_to_head()
        seeded = _seed_inventory()
        qr_code, created = create_booking_for_slots(
            seeded["tenant_ids"][0],
            [seeded["slot_id"]],
        )
        assert qr_code is not None and created == 1
        booking = Booking.query.filter_by(qr_code=qr_code).one()
        booking_id = booking.id
        payment_id = booking.payment_id
        requirements_id = booking.requirements_id

        db.session.execute(
            delete(PaymentTransaction).where(PaymentTransaction.id == payment_id)
        )
        db.session.commit()
        db.session.expire_all()
        assert db.session.get(Booking, booking_id).payment_id is None

        db.session.execute(
            text("DELETE FROM booking_requirement WHERE id = :requirements_id"),
            {"requirements_id": requirements_id},
        )
        db.session.commit()
        db.session.expire_all()
        assert db.session.get(Booking, booking_id).requirements_id is None

        standalone_user = User(
            username="postgres-cascade-vendor",
            first_name="Cascade",
            last_name="Vendor",
            role="Tenant",
        )
        standalone_profile = VendorProfile(
            user=standalone_user,
            brand_name="Cascade Brand",
            primary_category="other",
            contact_name="Cascade Vendor",
            contact_phone="0912000999",
        )
        db.session.add(standalone_profile)
        db.session.commit()
        user_id = standalone_user.id
        profile_id = standalone_profile.id

        db.session.execute(delete(User).where(User.id == user_id))
        db.session.commit()
        assert db.session.get(VendorProfile, profile_id) is None


def test_postgres_inventory_lock_allows_only_one_final_capacity_hold(
    postgres_harness: PostgresHarness,
) -> None:
    with postgres_harness.app.app_context():
        _upgrade_to_head()
        seeded = _seed_phase3_inventory(allocated_capacity=1)
    barrier = threading.Barrier(2)

    def attempt_hold(user_id: int) -> bool:
        with postgres_harness.app.app_context():
            try:
                barrier.wait(timeout=10)
                create_inventory_hold(
                    user_id,
                    seeded["inventory_group_id"],
                    now=datetime(2029, 1, 1, tzinfo=UTC),
                )
                return True
            except InventoryUnavailable:
                db.session.rollback()
                return False
            finally:
                db.session.remove()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(attempt_hold, seeded["tenant_ids"]))

    assert sorted(results) == [False, True]
    with postgres_harness.app.app_context():
        assert Booking.query.filter_by(
            inventory_group_id=seeded["inventory_group_id"],
            reservation_status=RESERVATION_HELD,
        ).count() == 1


def test_postgres_inventory_lock_allows_only_one_final_category_hold(
    postgres_harness: PostgresHarness,
) -> None:
    with postgres_harness.app.app_context():
        _upgrade_to_head()
        seeded = _seed_phase3_inventory(
            allocated_capacity=5,
            category_quota=1,
        )
    barrier = threading.Barrier(2)

    def attempt_hold(user_id: int) -> bool:
        with postgres_harness.app.app_context():
            try:
                barrier.wait(timeout=10)
                create_inventory_hold(
                    user_id,
                    seeded["inventory_group_id"],
                    now=datetime(2029, 1, 1, tzinfo=UTC),
                )
                return True
            except InventoryUnavailable:
                db.session.rollback()
                return False
            finally:
                db.session.remove()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(attempt_hold, seeded["tenant_ids"]))

    assert sorted(results) == [False, True]
    with postgres_harness.app.app_context():
        assert Booking.query.filter_by(
            inventory_group_id=seeded["inventory_group_id"],
            vendor_category="food",
            reservation_status=RESERVATION_HELD,
        ).count() == 1


def test_postgres_migration_12_refuses_downgrade_with_inventory_reservation(
    postgres_harness: PostgresHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    phase3_tables = {
        "provider",
        "venue",
        "opportunity",
        "inventory_group",
        "inventory_category_quota",
        "supply_audit_event",
    }
    with postgres_harness.app.app_context():
        _upgrade_to_head()
        seeded = _seed_phase3_inventory(allocated_capacity=1)
        booking = create_inventory_hold(
            seeded["tenant_ids"][0],
            seeded["inventory_group_id"],
            now=datetime(2029, 1, 1, tzinfo=UTC),
        )
        inventory_group = db.session.get(
            InventoryGroup,
            seeded["inventory_group_id"],
        )
        booking_id = booking.id
        inventory_group_id = inventory_group.id
        opportunity_id = inventory_group.opportunity_id
        provider_id = inventory_group.opportunity.provider_id
        venue_id = inventory_group.opportunity.venue_id

        before_revision = db.session.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
        before_tables = set(inspect(db.engine).get_table_names())
        before_booking_columns = {
            column["name"]: (str(column["type"]), column["nullable"])
            for column in inspect(db.engine).get_columns("booking")
        }
        assert before_revision == "20261004_12"
        assert phase3_tables.issubset(before_tables)
        assert booking.inventory_group_id == inventory_group_id
        assert db.session.get(Booking, booking_id) is not None
        db.session.remove()

        migration_errors = []
        monkeypatch.setattr(flask_migrate.log, "error", migration_errors.append)
        with pytest.raises(SystemExit) as downgrade_error:
            downgrade(directory=str(MIGRATIONS_DIR), revision="20261004_11")
        assert downgrade_error.value.code == 1
        assert migration_errors == [
            "Error: Cannot downgrade while inventory-based reservations exist."
        ]

        db.session.remove()
        after_revision = db.session.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
        after_tables = set(inspect(db.engine).get_table_names())
        after_booking_columns = {
            column["name"]: (str(column["type"]), column["nullable"])
            for column in inspect(db.engine).get_columns("booking")
        }
        preserved_booking = db.session.get(Booking, booking_id)

        assert after_revision == "20261004_12"
        assert after_tables == before_tables
        assert phase3_tables.issubset(after_tables)
        assert after_booking_columns == before_booking_columns
        assert preserved_booking is not None
        assert preserved_booking.inventory_group_id == inventory_group_id
        assert db.session.get(InventoryGroup, inventory_group_id) is not None
        assert db.session.get(Opportunity, opportunity_id) is not None
        assert db.session.get(Provider, provider_id) is not None
        assert db.session.get(Venue, venue_id) is not None


def _validated_test_database_url() -> URL:
    raw_url = os.environ.get("TEST_DATABASE_URL", "").strip()
    if not raw_url:
        pytest.skip(
            "TEST_DATABASE_URL is not configured; PostgreSQL integration tests "
            "require a disposable database."
        )

    url = make_url(raw_url)
    if url.drivername in {"postgres", "postgresql", "postgresql+psycopg2"}:
        url = url.set(drivername="postgresql+psycopg")
    if url.get_backend_name() != "postgresql":
        pytest.skip("TEST_DATABASE_URL is not PostgreSQL.")
    if os.environ.get("SPACIS_ALLOW_DESTRUCTIVE_POSTGRES_TESTS") != "1":
        pytest.skip(
            "Set SPACIS_ALLOW_DESTRUCTIVE_POSTGRES_TESTS=1 only for a disposable "
            "PostgreSQL test database."
        )

    database_name = (url.database or "").lower()
    if not any(part in database_name for part in SAFE_DATABASE_NAME_PARTS):
        pytest.fail(
            "The PostgreSQL test database name must clearly identify a test, "
            "staging, CI, sandbox, temporary, or disposable database."
        )

    production_url = os.environ.get("DATABASE_URL", "").strip()
    if production_url:
        production = make_url(production_url)
        if _database_identity(url) == _database_identity(production):
            pytest.fail("TEST_DATABASE_URL must not target DATABASE_URL.")
    return url


def _database_identity(url: URL) -> tuple[str | None, int | None, str | None, str | None]:
    return (url.host, url.port or 5432, url.database, url.username)


def _url_with_search_path(url: URL, schema: str) -> URL:
    query = dict(url.query)
    existing_options = query.get("options", "")
    query["options"] = f"{existing_options} -csearch_path={schema}".strip()
    return url.set(query=query)


def _create_pre_alembic_schema() -> None:
    db.session.execute(
        text(
            """
            CREATE TABLE "user" (
                id SERIAL PRIMARY KEY,
                username VARCHAR(50) NOT NULL UNIQUE,
                password_hash VARCHAR(255) NOT NULL,
                first_name VARCHAR(50) NOT NULL,
                last_name VARCHAR(50) NOT NULL,
                phone_number VARCHAR(20),
                role VARCHAR(20) NOT NULL,
                reputation_score DOUBLE PRECISION NOT NULL
            )
            """
        )
    )
    db.session.execute(
        text(
            """
            CREATE TABLE stall (
                id SERIAL PRIMARY KEY,
                owner_id INTEGER NOT NULL REFERENCES "user" (id),
                loc_name VARCHAR(100) NOT NULL,
                city VARCHAR(20) NOT NULL,
                district VARCHAR(20) NOT NULL,
                road VARCHAR(50) NOT NULL,
                address_detail VARCHAR(100) NOT NULL,
                facilities TEXT
            )
            """
        )
    )
    db.session.execute(
        text(
            """
            CREATE TABLE slot (
                id SERIAL PRIMARY KEY,
                stall_id INTEGER NOT NULL REFERENCES stall (id),
                date DATE NOT NULL,
                time INTEGER NOT NULL,
                price INTEGER NOT NULL
            )
            """
        )
    )
    db.session.execute(
        text(
            """
            CREATE TABLE booking (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES "user" (id),
                slot_id INTEGER NOT NULL UNIQUE REFERENCES slot (id),
                qr_code VARCHAR(100) NOT NULL,
                payment_status VARCHAR(20) NOT NULL,
                payment_method VARCHAR(20) NOT NULL,
                created_at TIMESTAMP NOT NULL
            )
            """
        )
    )
    db.session.execute(text("CREATE INDEX ix_booking_qr_code ON booking (qr_code)"))
    db.session.execute(
        text(
            """
            CREATE TABLE stall_price (
                id SERIAL PRIMARY KEY,
                stall_id INTEGER NOT NULL REFERENCES stall (id),
                date DATE NOT NULL,
                hour INTEGER NOT NULL,
                price INTEGER NOT NULL
            )
            """
        )
    )
    db.session.execute(
        text(
            """
            CREATE TABLE review (
                id SERIAL PRIMARY KEY,
                booking_id INTEGER NOT NULL REFERENCES booking (id),
                reviewer_id INTEGER NOT NULL REFERENCES "user" (id),
                reviewee_id INTEGER NOT NULL REFERENCES "user" (id),
                rating INTEGER NOT NULL,
                comment TEXT,
                created_at TIMESTAMP NOT NULL,
                CONSTRAINT uq_review_booking_reviewer
                    UNIQUE (booking_id, reviewer_id)
            )
            """
        )
    )
    db.session.commit()


def _assert_revision_09_schema(schema: str) -> None:
    assert db.session.execute(text("SELECT current_schema()")).scalar_one() == schema
    assert db.session.execute(
        text("SELECT version_num FROM alembic_version")
    ).scalar_one() == "20261004_09"

    table_names = set(inspect(db.engine).get_table_names())
    assert {"user", "auth_identity", "stall", "slot", "booking"}.issubset(
        table_names
    )
    version_table_schema = db.session.execute(
        text(
            """
            SELECT table_schema
            FROM information_schema.tables
            WHERE table_name = 'alembic_version'
              AND table_schema = :schema
            """
        ),
        {"schema": schema},
    ).scalar_one()
    assert version_table_schema == schema


def _upgrade_to_head() -> None:
    upgrade(directory=str(MIGRATIONS_DIR))
    assert db.session.execute(
        text("SELECT version_num FROM alembic_version")
    ).scalar_one() == "20261004_12"


def _seed_revision_09_inventory() -> dict[str, int | list[int]]:
    provider_id = db.session.execute(
        text(
            """
            INSERT INTO "user" (
                username, password_hash, first_name, last_name,
                role, reputation_score
            ) VALUES (
                :username, 'legacy-test', 'Legacy', 'Provider',
                'Landlord', 5.0
            )
            RETURNING id
            """
        ),
        {"username": f"pg-legacy-p-{uuid.uuid4().hex}"},
    ).scalar_one()
    tenant_id = db.session.execute(
        text(
            """
            INSERT INTO "user" (
                username, password_hash, first_name, last_name,
                role, reputation_score
            ) VALUES (
                :username, 'legacy-test', 'Legacy', 'Tenant',
                'Tenant', 5.0
            )
            RETURNING id
            """
        ),
        {"username": f"pg-legacy-t-{uuid.uuid4().hex}"},
    ).scalar_one()
    stall_id = db.session.execute(
        text(
            """
            INSERT INTO stall (
                owner_id, loc_name, city, district, road, address_detail
            ) VALUES (
                :owner_id, 'Legacy PostgreSQL Stall', 'Taipei',
                'Datong', 'Legacy Road', 'No. 9'
            )
            RETURNING id
            """
        ),
        {"owner_id": provider_id},
    ).scalar_one()

    slot_ids = []
    for hour in (9, 10):
        slot_ids.append(
            db.session.execute(
                text(
                    """
                    INSERT INTO slot (stall_id, date, time, price)
                    VALUES (:stall_id, :date, :time, 500)
                    RETURNING id
                    """
                ),
                {"stall_id": stall_id, "date": date(2030, 1, 1), "time": hour},
            ).scalar_one()
        )
    db.session.commit()
    return {
        "provider_id": provider_id,
        "tenant_id": tenant_id,
        "slot_ids": slot_ids,
    }


def _seed_inventory(vendor_count: int = 1) -> dict[str, int | list[int]]:
    provider = User(
        username=f"postgres-provider-{uuid.uuid4().hex}",
        first_name="Postgres",
        last_name="Provider",
        role="Landlord",
    )
    tenants = []
    for index in range(vendor_count):
        tenant = User(
            username=f"postgres-vendor-{index}-{uuid.uuid4().hex}",
            first_name="Postgres",
            last_name=f"Vendor {index}",
            role="Tenant",
        )
        tenant.vendor_profile = VendorProfile(
            brand_name=f"Postgres Test Brand {index}",
            primary_category="handmade",
            contact_name=f"Postgres Vendor {index}",
            contact_phone=f"0912000{index:03d}",
        )
        tenants.append(tenant)

    stall = Stall(
        owner=provider,
        loc_name="PostgreSQL Test Stall",
        city="Taipei",
        district="Datong",
        road="Test Road",
        address_detail="No. 1",
        booking_mode="hourly",
        minimum_booking_hours=1,
    )
    stall.certification = StallCertification(
        applicant_legal_name="Postgres Provider",
        applicant_phone="0912000000",
        relationship_to_space="property_owner",
        proof_type="property_record",
        declaration_accepted=True,
        status="approved",
    )
    slot = db.metadata.tables["slot"]
    db.session.add_all([provider, *tenants, stall])
    db.session.flush()
    result = db.session.execute(
        slot.insert()
        .values(
            stall_id=stall.id,
            date=date(2030, 1, 1),
            time=9,
            duration_hours=1,
            price=500,
        )
        .returning(slot.c.id)
    )
    slot_id = result.scalar_one()
    db.session.commit()
    return {
        "provider_id": provider.id,
        "slot_id": slot_id,
        "tenant_ids": [tenant.id for tenant in tenants],
    }


def _seed_phase3_inventory(
    *,
    allocated_capacity: int,
    category_quota: int | None = None,
) -> dict[str, int | list[int]]:
    manager = User(
        username=f"postgres-phase3-manager-{uuid.uuid4().hex[:12]}",
        first_name="Postgres",
        last_name="Manager",
        role="Landlord",
    )
    tenants = []
    for index in range(2):
        tenant = User(
            username=f"postgres-phase3-vendor-{index}-{uuid.uuid4().hex[:12]}",
            first_name="Postgres",
            last_name=f"Vendor {index}",
            role="Tenant",
        )
        tenant.vendor_profile = VendorProfile(
            brand_name=f"Postgres Food Brand {index}",
            primary_category="food",
            contact_name=f"Postgres Vendor {index}",
            contact_phone=f"0912888{index:03d}",
            food_registration_number=f"PG-FOOD-{index}",
        )
        tenants.append(tenant)

    provider = Provider(
        managing_user=manager,
        display_name="PostgreSQL Phase 3 Provider",
        contact_name="Postgres Manager",
        contact_phone="0912000000",
        verification_status="VERIFIED",
        verified_at=datetime(2028, 1, 1, tzinfo=UTC),
    )
    venue = Venue(
        provider=provider,
        name="PostgreSQL Phase 3 Venue",
        city="Taipei",
        address_line="No. 3 Test Road",
        verification_status="VERIFIED",
        verified_at=datetime(2028, 1, 1, tzinfo=UTC),
    )
    opportunity = Opportunity(
        provider=provider,
        venue=venue,
        title="PostgreSQL Contention Market",
        opportunity_type="EVENT",
        visibility="PUBLIC",
        publication_status="PUBLISHED",
        booking_policy="INSTANT",
        required_requirement_types=[],
        published_at=datetime(2028, 1, 1, tzinfo=UTC),
    )
    inventory_group = InventoryGroup(
        opportunity=opportunity,
        service_period_start=datetime(2030, 1, 1, 8, tzinfo=UTC),
        service_period_end=datetime(2030, 1, 1, 18, tzinfo=UTC),
        allocated_capacity=allocated_capacity,
        price_amount=500,
        currency="TWD",
        status="ACTIVE",
        required_requirement_types=[],
    )
    if category_quota is not None:
        inventory_group.category_quotas.append(
            InventoryCategoryQuota(category="food", capacity=category_quota)
        )
    db.session.add_all([manager, *tenants, inventory_group])
    db.session.commit()
    return {
        "inventory_group_id": inventory_group.id,
        "tenant_ids": [tenant.id for tenant in tenants],
    }


def _insert_booking(user_id: int, slot_id: int, qr_code: str, status: str) -> None:
    db.session.execute(
        text(
            """
            INSERT INTO booking (
                user_id, slot_id, qr_code, reservation_status, created_at
            ) VALUES (
                :user_id, :slot_id, :qr_code, :status, CURRENT_TIMESTAMP
            )
            """
        ),
        {
            "user_id": user_id,
            "slot_id": slot_id,
            "qr_code": qr_code,
            "status": status,
        },
    )
