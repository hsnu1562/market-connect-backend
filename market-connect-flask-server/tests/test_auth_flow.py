from __future__ import annotations

import pytest
from werkzeug.security import check_password_hash, generate_password_hash

from app import create_app
from models import User, db


@pytest.fixture()
def app():
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "LOCAL_AUTH_ENABLED": True,
        }
    )
    with app.app_context():
        db.create_all()
    yield app


@pytest.fixture()
def client(app):
    return app.test_client()


def _set_csrf_token(client, token: str = "test-csrf-token") -> str:
    with client.session_transaction() as session:
        session["_csrf_token"] = token
    return token


def test_account_entry_exposes_local_auth_only_when_enabled(client):
    response = client.get("/account/?intent=landlord")

    assert response.status_code == 200
    assert "我要租攤位".encode() in response.data
    assert "我要出租攤位".encode() in response.data
    assert b"/register/Tenant" in response.data
    assert b"/login/Tenant" in response.data
    assert b"/register/Landlord" in response.data
    assert b"/login/Landlord" in response.data


def test_google_only_account_hides_and_disables_local_auth(app, client):
    app.config["LOCAL_AUTH_ENABLED"] = False

    response = client.get("/account/?intent=tenant")

    assert response.status_code == 200
    assert "使用 Google 登入".encode() in response.data
    assert b"/register/Tenant" not in response.data
    assert b"/login/Tenant" not in response.data
    assert client.get("/register/Tenant").status_code == 302
    assert client.get("/login/Tenant").status_code == 302


def test_registration_login_and_logout_use_the_user_table(app, client):
    token = _set_csrf_token(client)
    response = client.post(
        "/register/Tenant",
        data={
            "_csrf_token": token,
            "username": "market_renter",
            "pw": "a-secure-password",
            "fname": "Market",
            "lname": "Renter",
            "phone": "0912345678",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    with app.app_context():
        user = User.query.filter_by(username="market_renter").one()
        user_id = user.id
        assert user.role == "Tenant"
        assert user.profile_completed_at is not None
        assert check_password_hash(user.password_hash, "a-secure-password")

    assert response.headers["Location"].endswith(f"/tenant/hub/{user_id}/")
    assert client.get(f"/tenant/hub/{user_id}/").status_code == 200

    token = _set_csrf_token(client, "logout-token")
    response = client.post("/logout/", data={"_csrf_token": token}, follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")

    token = _set_csrf_token(client, "login-token")
    response = client.post(
        "/login/Tenant",
        data={
            "_csrf_token": token,
            "username": "market_renter",
            "pw": "a-secure-password",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/tenant/hub/{user_id}/")


def test_registration_validation_and_csrf_protection(app, client):
    form_data = {
        "username": "new_renter",
        "pw": "a-secure-password",
        "fname": "New",
        "lname": "Renter",
        "phone": "0912345678",
    }

    response = client.post("/register/Tenant", data=form_data)
    assert response.status_code == 400

    token = _set_csrf_token(client)
    response = client.post("/register/Tenant", data={"_csrf_token": token, **form_data})
    assert response.status_code == 302

    token = _set_csrf_token(client, "logout-before-duplicate")
    response = client.post("/logout/", data={"_csrf_token": token})
    assert response.status_code == 302

    token = _set_csrf_token(client, "duplicate-token")
    response = client.post(
        "/register/Tenant",
        data={"_csrf_token": token, **form_data},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "這個帳號已有人使用".encode() in response.data
    with app.app_context():
        assert User.query.filter_by(username="new_renter").count() == 1


def test_private_routes_reject_anonymous_cross_account_and_wrong_role(app, client):
    with app.app_context():
        tenant_one = User(
            username="tenant_one",
            password_hash=generate_password_hash("tenant-one-password"),
            first_name="Tenant",
            last_name="One",
            phone_number="0912345678",
            role="Tenant",
        )
        tenant_two = User(
            username="tenant_two",
            password_hash=generate_password_hash("tenant-two-password"),
            first_name="Tenant",
            last_name="Two",
            phone_number="0912345679",
            role="Tenant",
        )
        landlord = User(
            username="provider_one",
            password_hash=generate_password_hash("provider-password"),
            first_name="Provider",
            last_name="One",
            phone_number="0912345680",
            role="Landlord",
        )
        db.session.add_all([tenant_one, tenant_two, landlord])
        db.session.commit()
        tenant_one_id = tenant_one.id
        tenant_two_id = tenant_two.id
        landlord_id = landlord.id

    response = client.get(f"/tenant/hub/{tenant_one_id}/")
    assert response.status_code == 302
    assert "/account/?next=" in response.headers["Location"]

    with client.session_transaction() as session:
        session["user_id"] = tenant_one_id

    assert client.get(f"/tenant/hub/{tenant_two_id}/").status_code == 403
    assert client.get(f"/landlord/hub/{landlord_id}/").status_code == 403
    assert client.get("/register/Admin").status_code == 404
