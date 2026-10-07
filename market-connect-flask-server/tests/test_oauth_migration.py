from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from flask_migrate import downgrade, stamp, upgrade
from sqlalchemy import inspect, text

from app import create_app
from models import Stall, StallCertification, User, db
from market_connect.models import Booking, InventoryGroup, Opportunity, Provider, Venue


MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"


def _migration_app(database_path: Path):
    return create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "migration-test-secret",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path.as_posix()}",
        }
    )


def test_initial_migration_upgrades_legacy_user_schema(tmp_path):
    database_path = tmp_path / "legacy.db"
    app = _migration_app(database_path)

    with app.app_context():
        with db.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE "user" (
                        id INTEGER NOT NULL PRIMARY KEY,
                        username VARCHAR(50) NOT NULL UNIQUE,
                        password_hash VARCHAR(255) NOT NULL,
                        first_name VARCHAR(50) NOT NULL,
                        last_name VARCHAR(50) NOT NULL,
                        birth_date DATE,
                        phone_number VARCHAR(20),
                        role VARCHAR(20) NOT NULL,
                        reputation_score FLOAT NOT NULL
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE stall (
                        id INTEGER NOT NULL PRIMARY KEY,
                        owner_id INTEGER NOT NULL,
                        loc_name VARCHAR(100) NOT NULL,
                        city VARCHAR(20) NOT NULL,
                        district VARCHAR(20) NOT NULL,
                        road VARCHAR(50) NOT NULL,
                        address_detail VARCHAR(100) NOT NULL,
                        facilities TEXT,
                        FOREIGN KEY(owner_id) REFERENCES "user" (id)
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE slot (
                        id INTEGER NOT NULL PRIMARY KEY,
                        stall_id INTEGER NOT NULL,
                        date DATE NOT NULL,
                        time INTEGER NOT NULL,
                        price INTEGER NOT NULL,
                        FOREIGN KEY(stall_id) REFERENCES stall (id)
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO stall (
                        id, owner_id, loc_name, city, district, road,
                        address_detail, facilities
                    ) VALUES (
                        1, 1, 'Legacy Stall', 'Taipei', 'Datong', 'Dihua St',
                        'No. 1', 'Power'
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO slot (id, stall_id, date, time, price)
                    VALUES (1, 1, '2026-10-15', 8, 300)
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO "user" (
                        id, username, password_hash, first_name, last_name,
                        birth_date, phone_number, role, reputation_score
                    ) VALUES (
                        1, 'legacy_tenant', 'legacy-hash', 'Legacy', 'Tenant',
                        '1988-06-15', '0912345678', 'Tenant', 5.0
                    )
                    """
                )
            )

        upgrade(directory=str(MIGRATIONS_DIR))

        inspector = inspect(db.engine)
        assert {
            "auth_identity",
            "user_role",
            "stall_certification",
            "stall_certification_document",
            "vendor_profile",
            "booking_requirement",
            "provider",
            "venue",
            "opportunity",
            "inventory_group",
            "inventory_category_quota",
            "supply_audit_event",
        }.issubset(
            inspector.get_table_names()
        )
        user_columns = {column["name"]: column for column in inspector.get_columns("user")}
        assert user_columns["password_hash"]["nullable"] is True
        assert {
            "status",
            "created_at",
            "updated_at",
            "profile_completed_at",
            "nickname",
            "birth_date",
            "is_admin",
        }.issubset(user_columns)
        assert user_columns["birth_date"]["nullable"] is True
        preserved_birth_date = db.session.execute(
            text('SELECT birth_date FROM "user" WHERE id = 1')
        ).scalar_one()
        assert str(preserved_birth_date) == "1988-06-15"
        assert db.session.execute(
            text("SELECT COUNT(*) FROM vendor_profile")
        ).scalar_one() == 0
        membership = db.session.execute(
            text("SELECT user_id, role FROM user_role WHERE user_id = 1")
        ).one()
        assert membership == (1, "Tenant")
        profile_completed_at = db.session.execute(
            text('SELECT profile_completed_at FROM "user" WHERE id = 1')
        ).scalar_one()
        assert profile_completed_at is not None
        stall_policy = db.session.execute(
            text(
                """
                SELECT environment_type, booking_mode, minimum_booking_hours
                FROM stall WHERE id = 1
                """
            )
        ).one()
        assert stall_policy == ("unspecified", "hourly", 1)
        duration_hours = db.session.execute(
            text("SELECT duration_hours FROM slot WHERE id = 1")
        ).scalar_one()
        assert duration_hours == 1
        certification_columns = {
            column["name"] for column in inspector.get_columns("stall_certification")
        }
        assert {
            "stall_id",
            "applicant_legal_name",
            "status",
            "reviewed_at",
            "reviewed_by_user_id",
        }.issubset(certification_columns)
        assert "evidence_url" not in certification_columns


def test_initial_migration_stamps_fresh_create_all_schema(tmp_path):
    app = _migration_app(tmp_path / "fresh.db")

    with app.app_context():
        db.create_all()
        upgrade(directory=str(MIGRATIONS_DIR))

        revision = db.session.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert revision == "20261004_12"
        inspector = inspect(db.engine)
        stall_columns = {column["name"] for column in inspector.get_columns("stall")}
        slot_columns = {column["name"] for column in inspector.get_columns("slot")}
        assert {
            "environment_type",
            "booking_mode",
            "minimum_booking_hours",
        }.issubset(stall_columns)
        assert "duration_hours" in slot_columns
        assert "stall_certification" in inspector.get_table_names()
        assert "stall_certification_document" in inspector.get_table_names()
        assert "stall_photo" in inspector.get_table_names()
        assert "payment_transaction" in inspector.get_table_names()
        assert "vendor_profile" in inspector.get_table_names()
        assert "booking_requirement" in inspector.get_table_names()
        assert {
            "provider",
            "venue",
            "opportunity",
            "inventory_group",
            "inventory_category_quota",
            "supply_audit_event",
        }.issubset(inspector.get_table_names())
        booking_columns = {column["name"] for column in inspector.get_columns("booking")}
        assert {
            "payment_id",
            "reservation_status",
            "hold_expires_at",
            "confirmed_at",
            "requirements_id",
            "inventory_group_id",
            "vendor_category",
        }.issubset(booking_columns)
        slot_column = next(
            column
            for column in inspector.get_columns("booking")
            if column["name"] == "slot_id"
        )
        assert slot_column["nullable"] is True


def test_supply_migration_refuses_downgrade_with_inventory_reservation(tmp_path):
    app = _migration_app(tmp_path / "phase3-downgrade-guard.db")

    with app.app_context():
        db.create_all()
        upgrade(directory=str(MIGRATIONS_DIR))
        manager = User(
            username="phase3-downgrade-manager",
            first_name="Supply",
            last_name="Manager",
            role="Landlord",
        )
        vendor = User(
            username="phase3-downgrade-vendor",
            first_name="Test",
            last_name="Vendor",
            role="Tenant",
        )
        provider = Provider(
            managing_user=manager,
            display_name="Downgrade Provider",
            contact_name="Supply Manager",
            contact_phone="0912000000",
            verification_status="VERIFIED",
        )
        venue = Venue(
            provider=provider,
            name="Downgrade Venue",
            city="Taipei",
            address_line="No. 12 Migration Road",
            verification_status="VERIFIED",
        )
        opportunity = Opportunity(
            provider=provider,
            venue=venue,
            title="Downgrade Opportunity",
            opportunity_type="EVENT",
            publication_status="PUBLISHED",
            required_requirement_types=[],
        )
        inventory_group = InventoryGroup(
            opportunity=opportunity,
            service_period_start=datetime.now(UTC) + timedelta(days=1),
            service_period_end=datetime.now(UTC) + timedelta(days=1, hours=8),
            allocated_capacity=1,
            price_amount=500,
            status="ACTIVE",
            required_requirement_types=[],
        )
        booking = Booking(
            user=vendor,
            inventory_group=inventory_group,
            vendor_category="handmade",
            qr_code="PHASE3-DOWNGRADE",
            reservation_status="HELD",
            hold_expires_at=datetime.now(UTC) + timedelta(minutes=15),
        )
        db.session.add(booking)
        db.session.commit()

        with pytest.raises(SystemExit) as downgrade_error:
            downgrade(directory=str(MIGRATIONS_DIR), revision="20261004_11")
        assert downgrade_error.value.code == 1

        assert db.session.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == "20261004_12"
        assert "inventory_group_id" in {
            column["name"] for column in inspect(db.engine).get_columns("booking")
        }


def test_booking_migration_preserves_legacy_paid_as_unverified_history(tmp_path):
    app = _migration_app(tmp_path / "legacy-booking.db")

    with app.app_context():
        with db.engine.begin() as connection:
            connection.execute(text('CREATE TABLE "user" (id INTEGER PRIMARY KEY)'))
            connection.execute(text("CREATE TABLE slot (id INTEGER PRIMARY KEY)"))
            connection.execute(
                text(
                    """
                    CREATE TABLE booking (
                        id INTEGER NOT NULL PRIMARY KEY,
                        user_id INTEGER NOT NULL,
                        slot_id INTEGER NOT NULL UNIQUE,
                        qr_code VARCHAR(100) NOT NULL,
                        payment_status VARCHAR(20) NOT NULL,
                        payment_method VARCHAR(20) NOT NULL,
                        created_at DATETIME NOT NULL,
                        FOREIGN KEY(user_id) REFERENCES "user" (id),
                        FOREIGN KEY(slot_id) REFERENCES slot (id)
                    )
                    """
                )
            )
            connection.execute(text('INSERT INTO "user" (id) VALUES (1)'))
            connection.execute(text("INSERT INTO slot (id) VALUES (1)"))
            connection.execute(
                text(
                    """
                    INSERT INTO booking (
                        id, user_id, slot_id, qr_code, payment_status,
                        payment_method, created_at
                    ) VALUES (
                        1, 1, 1, 'LEGACY01', 'Paid', 'Credit Card',
                        '2026-10-02 10:00:00'
                    )
                    """
                )
            )

        stamp(directory=str(MIGRATIONS_DIR), revision="20261004_09")
        upgrade(directory=str(MIGRATIONS_DIR))

        migrated = db.session.execute(
            text(
                """
                SELECT reservation_status, payment_id, requirements_id,
                       payment_status, payment_method, confirmed_at
                FROM booking WHERE id = 1
                """
            )
        ).one()
        assert migrated == (
            "CONFIRMED",
            None,
            None,
            "Paid",
            "Credit Card",
            None,
        )
        assert db.session.execute(
            text("SELECT COUNT(*) FROM payment_transaction")
        ).scalar_one() == 0

        indexes = {index["name"]: index for index in inspect(db.engine).get_indexes("booking")}
        assert indexes["uq_booking_active_slot"]["unique"] == 1

        booking_columns = {
            column["name"]: column
            for column in inspect(db.engine).get_columns("booking")
        }
        assert booking_columns["payment_status"]["default"] == "'NotApplicable'"
        assert booking_columns["payment_method"]["default"] == "''"

        downgrade(directory=str(MIGRATIONS_DIR), revision="20261004_09")
        downgraded_columns = {
            column["name"]: column
            for column in inspect(db.engine).get_columns("booking")
        }
        assert downgraded_columns["payment_status"]["default"] is None
        assert downgraded_columns["payment_method"]["default"] is None
        preserved = db.session.execute(
            text(
                "SELECT payment_status, payment_method FROM booking WHERE id = 1"
            )
        ).one()
        assert preserved == ("Paid", "Credit Card")


def test_booking_migration_refuses_unsafe_downgrade_before_schema_changes(
    tmp_path,
):
    app = _migration_app(tmp_path / "unsafe-booking-downgrade.db")

    with app.app_context():
        with db.engine.begin() as connection:
            connection.execute(text('CREATE TABLE "user" (id INTEGER PRIMARY KEY)'))
            connection.execute(text("CREATE TABLE slot (id INTEGER PRIMARY KEY)"))
            connection.execute(
                text(
                    """
                    CREATE TABLE booking (
                        id INTEGER NOT NULL PRIMARY KEY,
                        user_id INTEGER NOT NULL,
                        slot_id INTEGER NOT NULL UNIQUE,
                        qr_code VARCHAR(100) NOT NULL,
                        payment_status VARCHAR(20) NOT NULL,
                        payment_method VARCHAR(20) NOT NULL,
                        created_at DATETIME NOT NULL,
                        FOREIGN KEY(user_id) REFERENCES "user" (id),
                        FOREIGN KEY(slot_id) REFERENCES slot (id)
                    )
                    """
                )
            )
            connection.execute(text('INSERT INTO "user" (id) VALUES (1)'))
            connection.execute(text("INSERT INTO slot (id) VALUES (1)"))
            connection.execute(
                text(
                    """
                    INSERT INTO booking (
                        id, user_id, slot_id, qr_code, payment_status,
                        payment_method, created_at
                    ) VALUES (
                        1, 1, 1, 'ACTIVE', 'Paid', 'Credit Card',
                        '2026-10-02 10:00:00'
                    )
                    """
                )
            )

        stamp(directory=str(MIGRATIONS_DIR), revision="20261004_09")
        upgrade(directory=str(MIGRATIONS_DIR))
        db.session.execute(
            text(
                """
                INSERT INTO booking (
                    id, user_id, slot_id, qr_code, reservation_status,
                    created_at
                ) VALUES (
                    2, 1, 1, 'HISTORY', 'EXPIRED', '2026-10-02 11:00:00'
                )
                """
            )
        )
        db.session.commit()
        downgrade(directory=str(MIGRATIONS_DIR), revision="20261004_10")

        before_columns = {
            column["name"] for column in inspect(db.engine).get_columns("booking")
        }
        before_indexes = {
            index["name"] for index in inspect(db.engine).get_indexes("booking")
        }

        with pytest.raises(SystemExit) as downgrade_error:
            downgrade(directory=str(MIGRATIONS_DIR), revision="20261004_09")
        assert downgrade_error.value.code == 1

        after_columns = {
            column["name"] for column in inspect(db.engine).get_columns("booking")
        }
        after_indexes = {
            index["name"] for index in inspect(db.engine).get_indexes("booking")
        }
        revision = db.session.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
        assert after_columns == before_columns
        assert after_indexes == before_indexes
        assert revision == "20261004_10"


def test_link_only_certification_is_rejected_cleared_and_removed(tmp_path):
    app = _migration_app(tmp_path / "link-only.db")

    with app.app_context():
        db.create_all()
        db.session.execute(text("ALTER TABLE stall_certification ADD COLUMN evidence_url TEXT"))
        db.session.commit()
        stamp(directory=str(MIGRATIONS_DIR), revision="20261004_06")
        user = User(
            username="legacy_link_landlord",
            first_name="Legacy",
            last_name="Landlord",
            role="Landlord",
        )
        stall = Stall(
            owner=user,
            loc_name="Legacy Link Stall",
            city="Taipei",
            district="Datong",
            road="Dihua St",
            address_detail="No. 9",
        )
        certification = StallCertification(
            stall=stall,
            applicant_legal_name="Legacy Landlord",
            applicant_phone="0912345678",
            relationship_to_space="property_owner",
            proof_type="property_record",
            declaration_accepted=True,
            status="approved",
        )
        db.session.add(certification)
        db.session.commit()
        db.session.execute(
            text(
                "UPDATE stall_certification "
                "SET evidence_url = 'https://example.invalid/legacy-proof' "
                "WHERE id = :certification_id"
            ),
            {"certification_id": certification.id},
        )
        db.session.commit()

        upgrade(directory=str(MIGRATIONS_DIR), revision="20261004_07")
        db.session.expire_all()

        migrated = db.session.get(StallCertification, certification.id)
        assert migrated.status == "rejected"
        assert migrated.reviewer_reference == "system-migration"
        assert "Upload files" in migrated.review_note
        assert db.session.execute(
            text(
                "SELECT evidence_url FROM stall_certification "
                "WHERE id = :certification_id"
            ),
            {"certification_id": certification.id},
        ).scalar_one() is None

        upgrade(directory=str(MIGRATIONS_DIR))
        columns = {
            column["name"] for column in inspect(db.engine).get_columns("stall_certification")
        }
        assert "evidence_url" not in columns
