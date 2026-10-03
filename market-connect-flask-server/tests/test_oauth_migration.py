from __future__ import annotations

from pathlib import Path

from flask_migrate import stamp, upgrade
from sqlalchemy import inspect, text

from app import create_app
from models import Stall, StallCertification, User, db


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
                        phone_number, role, reputation_score
                    ) VALUES (
                        1, 'legacy_tenant', 'legacy-hash', 'Legacy', 'Tenant',
                        '0912345678', 'Tenant', 5.0
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
        assert revision == "20261004_08"
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
