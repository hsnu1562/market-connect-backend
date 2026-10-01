from __future__ import annotations

import pytest

from market_connect import create_app


@pytest.mark.parametrize(
    "database_url",
    (
        "postgres://example-user:example-password@example.invalid/example-db",
        "postgresql://example-user:example-password@example.invalid/example-db",
        "postgresql+psycopg2://example-user:example-password@example.invalid/example-db",
        "postgresql+psycopg://example-user:example-password@example.invalid/example-db",
    ),
)
def test_database_url_uses_psycopg_and_pool_settings(monkeypatch, database_url):
    monkeypatch.setenv(
        "DATABASE_URL",
        database_url,
    )

    app = create_app({"TESTING": True})

    assert app.config["SQLALCHEMY_DATABASE_URI"].startswith("postgresql+psycopg://")
    assert app.config["SQLALCHEMY_ENGINE_OPTIONS"] == {
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }


def test_database_url_defaults_to_local_sqlite(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)

    app = create_app({"TESTING": True})

    assert app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite:///")
    assert app.config["SQLALCHEMY_ENGINE_OPTIONS"] == {}
