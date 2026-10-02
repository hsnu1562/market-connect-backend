from __future__ import annotations

from datetime import timedelta

import pytest
from flask import redirect

from app import create_app
from market_connect.extensions import oauth
from models import AuthIdentity, User, UserRole, db


@pytest.fixture()
def app():
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "GOOGLE_CLIENT_ID": "test-client-id",
            "GOOGLE_CLIENT_SECRET": "test-client-secret",
            "GOOGLE_REDIRECT_URI": "http://localhost:5001/auth/google/callback",
            "PUBLIC_BASE_URL": "http://localhost:5001",
        }
    )
    with app.app_context():
        db.create_all()
    yield app


@pytest.fixture()
def client(app):
    return app.test_client()


def _google_userinfo(**overrides):
    userinfo = {
        "sub": "google-subject-123",
        "email": "vendor@example.com",
        "email_verified": True,
        "name": "Market Vendor",
        "given_name": "Market",
        "family_name": "Vendor",
        "picture": "https://example.invalid/avatar.png",
    }
    userinfo.update(overrides)
    return userinfo


def _set_oauth_context(client, role: str, next_url: str = "") -> None:
    with client.session_transaction() as flask_session:
        flask_session["_oauth_requested_role"] = role
        flask_session["_oauth_next_url"] = next_url


def test_production_requires_fixed_secret_and_google_configuration(monkeypatch):
    for key in (
        "SECRET_KEY",
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "GOOGLE_REDIRECT_URI",
        "PUBLIC_BASE_URL",
    ):
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(RuntimeError, match="Missing required production configuration"):
        create_app(
            {
                "APP_ENV": "production",
                "TESTING": True,
                "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                "PUBLIC_BASE_URL": None,
            }
        )


def test_production_session_cookie_and_duration_are_secure():
    app = create_app(
        {
            "APP_ENV": "production",
            "TESTING": True,
            "SECRET_KEY": "fixed-production-secret",
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "GOOGLE_CLIENT_ID": "test-client-id",
            "GOOGLE_CLIENT_SECRET": "test-client-secret",
            "GOOGLE_REDIRECT_URI": "https://spacis.example/auth/google/callback",
            "PUBLIC_BASE_URL": "https://spacis.example",
        }
    )

    assert app.config["SESSION_COOKIE_SECURE"] is True
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
    assert app.config["PERMANENT_SESSION_LIFETIME"] == timedelta(days=7)


def test_google_login_uses_configured_redirect_uri(app, client, monkeypatch):
    captured = {}

    def authorize_redirect(redirect_uri):
        captured["redirect_uri"] = redirect_uri
        return redirect("https://accounts.google.test/authorize")

    monkeypatch.setattr(oauth.google, "authorize_redirect", authorize_redirect)
    response = client.get("/auth/google/login?role=Tenant&next=/stalls/")

    assert response.status_code == 302
    assert response.headers["Location"] == "https://accounts.google.test/authorize"
    assert captured["redirect_uri"] == "http://localhost:5001/auth/google/callback"
    with client.session_transaction() as flask_session:
        assert flask_session["_oauth_requested_role"] == "Tenant"
        assert flask_session["_oauth_next_url"] == "/stalls/"


def test_google_callback_creates_identity_role_and_permanent_session(app, client, monkeypatch):
    monkeypatch.setattr(
        oauth.google,
        "authorize_access_token",
        lambda: {"userinfo": _google_userinfo()},
    )
    _set_oauth_context(client, "Tenant")

    response = client.get("/auth/google/callback")

    assert response.status_code == 302
    assert response.headers["Location"].startswith("/account/profile")
    with app.app_context():
        user = User.query.one()
        identity = AuthIdentity.query.one()
        assert user.password_hash is None
        assert user.profile_completed_at is None
        assert user.needs_profile_completion is True
        assert user.has_role("Tenant")
        assert identity.user_id == user.id
        assert identity.provider == "google"
        assert identity.provider_subject == "google-subject-123"
        assert identity.email_verified is True
        user_id = user.id
    with client.session_transaction() as flask_session:
        assert flask_session["user_id"] == user_id
        assert flask_session["_permanent"] is True
        assert "_oauth_requested_role" not in flask_session
        assert "_oauth_next_url" not in flask_session


def test_first_google_login_collects_profile_then_returns_to_intended_page(
    app, client, monkeypatch
):
    monkeypatch.setattr(
        oauth.google,
        "authorize_access_token",
        lambda: {"userinfo": _google_userinfo()},
    )
    _set_oauth_context(client, "Tenant", "/stalls/")

    callback = client.get("/auth/google/callback")
    profile_url = callback.headers["Location"]
    profile_page = client.get(profile_url)

    assert profile_page.status_code == 200
    assert b"vendor@example.com" in profile_page.data
    assert "不會發送 OTP".encode() in profile_page.data

    with client.session_transaction() as flask_session:
        csrf_token = flask_session["_csrf_token"]
    response = client.post(
        profile_url,
        data={
            "_csrf_token": csrf_token,
            "role": "Tenant",
            "next": "/stalls/",
            "first_name": "小明",
            "last_name": "陳",
            "phone_number": "0912 345 678",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/stalls/")
    with app.app_context():
        user = User.query.one()
        assert user.first_name == "小明"
        assert user.last_name == "陳"
        assert user.phone_number == "0912 345 678"
        assert user.profile_completed_at is not None
        assert user.needs_profile_completion is False


def test_profile_rejects_invalid_optional_phone(app, client, monkeypatch):
    monkeypatch.setattr(
        oauth.google,
        "authorize_access_token",
        lambda: {"userinfo": _google_userinfo()},
    )
    _set_oauth_context(client, "Landlord")
    profile_url = client.get("/auth/google/callback").headers["Location"]
    client.get(profile_url)
    with client.session_transaction() as flask_session:
        csrf_token = flask_session["_csrf_token"]

    response = client.post(
        profile_url,
        data={
            "_csrf_token": csrf_token,
            "role": "Landlord",
            "first_name": "Market",
            "last_name": "Vendor",
            "phone_number": "not-a-phone",
        },
    )

    assert response.status_code == 200
    assert "請輸入有效的聯絡電話".encode() in response.data
    with app.app_context():
        assert User.query.one().profile_completed_at is None


def test_incomplete_google_profile_cannot_open_protected_tools(app, client, monkeypatch):
    monkeypatch.setattr(
        oauth.google,
        "authorize_access_token",
        lambda: {"userinfo": _google_userinfo()},
    )
    _set_oauth_context(client, "Tenant")
    client.get("/auth/google/callback")
    with app.app_context():
        user_id = User.query.one().id

    response = client.get(f"/tenant/hub/{user_id}/")

    assert response.status_code == 302
    assert response.headers["Location"].startswith("/account/profile")


def test_existing_google_identity_gains_second_role_without_duplicate_user(
    app, client, monkeypatch
):
    monkeypatch.setattr(
        oauth.google,
        "authorize_access_token",
        lambda: {"userinfo": _google_userinfo()},
    )
    _set_oauth_context(client, "Tenant")
    assert client.get("/auth/google/callback").status_code == 302

    _set_oauth_context(client, "Landlord")
    assert client.get("/auth/google/callback").status_code == 302

    with app.app_context():
        user = User.query.one()
        assert User.query.count() == 1
        assert AuthIdentity.query.count() == 1
        assert UserRole.query.filter_by(user_id=user.id).count() == 2
        assert user.role_names == frozenset({"Tenant", "Landlord"})


@pytest.mark.parametrize(
    "userinfo",
    (
        _google_userinfo(email_verified=False),
        _google_userinfo(sub=None),
    ),
)
def test_google_callback_rejects_invalid_identity(app, client, monkeypatch, userinfo):
    monkeypatch.setattr(
        oauth.google,
        "authorize_access_token",
        lambda: {"userinfo": userinfo},
    )
    _set_oauth_context(client, "Tenant")

    response = client.get("/auth/google/callback")

    assert response.status_code == 302
    assert "oauth_error=1" in response.headers["Location"]
    with app.app_context():
        assert User.query.count() == 0
        assert AuthIdentity.query.count() == 0


def test_stall_browsing_is_public_but_booking_is_protected(app, client):
    assert client.get("/stalls/").status_code == 200
    assert client.get("/booking_page/1/1/").status_code == 302


def test_health_does_not_depend_on_google(app, client, monkeypatch):
    monkeypatch.setitem(app.config, "GOOGLE_CLIENT_ID", None)
    monkeypatch.setitem(app.config, "GOOGLE_CLIENT_SECRET", None)

    assert client.get("/health").status_code == 200
    assert client.get("/api/v1/health").status_code == 200
