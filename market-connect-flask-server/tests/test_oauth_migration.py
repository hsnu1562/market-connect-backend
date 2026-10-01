from __future__ import annotations

from pathlib import Path

from flask_migrate import upgrade
from sqlalchemy import inspect, text

from app import create_app
from models import db


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
        assert {"auth_identity", "user_role"}.issubset(inspector.get_table_names())
        user_columns = {column["name"]: column for column in inspector.get_columns("user")}
        assert user_columns["password_hash"]["nullable"] is True
        assert {"status", "created_at", "updated_at"}.issubset(user_columns)
        membership = db.session.execute(
            text("SELECT user_id, role FROM user_role WHERE user_id = 1")
        ).one()
        assert membership == (1, "Tenant")


def test_initial_migration_stamps_fresh_create_all_schema(tmp_path):
    app = _migration_app(tmp_path / "fresh.db")

    with app.app_context():
        db.create_all()
        upgrade(directory=str(MIGRATIONS_DIR))

        revision = db.session.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert revision == "20261002_01"
