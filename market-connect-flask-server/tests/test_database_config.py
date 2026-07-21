from __future__ import annotations

from market_connect import create_app


def test_database_url_uses_postgresql_pool_settings(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgres://example-user:example-password@example.invalid/example-db",
    )

    app = create_app({"TESTING": True})

    assert app.config["SQLALCHEMY_DATABASE_URI"].startswith("postgresql://")
    assert app.config["SQLALCHEMY_ENGINE_OPTIONS"] == {
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }


def test_database_url_defaults_to_local_sqlite(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)

    app = create_app({"TESTING": True})

    assert app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite:///")
    assert app.config["SQLALCHEMY_ENGINE_OPTIONS"] == {}
