from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest
from werkzeug.security import generate_password_hash

from app import create_app
from models import Booking, Slot, Stall, User, db


@pytest.fixture()
def app():
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        }
    )
    with app.app_context():
        db.create_all()
        landlord = User(
            username="landlord1",
            password_hash=generate_password_hash("landlord1_password"),
            first_name="Landlord",
            last_name="One",
            phone_number="0912",
            role="Landlord",
        )
        tenant1 = User(
            username="tenant1",
            password_hash=generate_password_hash("tenant1_password"),
            first_name="Tenant",
            last_name="One",
            phone_number="0913",
            role="Tenant",
        )
        tenant2 = User(
            username="tenant2",
            password_hash=generate_password_hash("tenant2_password"),
            first_name="Tenant",
            last_name="Two",
            phone_number="0914",
            role="Tenant",
        )
        stall = Stall(
            owner=landlord,
            loc_name="Huashan Stall A",
            city="Taipei",
            district="Zhongzheng",
            road="Bade Rd",
            address_detail="東2A",
            facilities="Power, Water",
        )
        db.session.add_all([landlord, tenant1, tenant2, stall])
        db.session.flush()
        available_date = date.today() + timedelta(days=7)
        db.session.add_all(
            [
                Slot(stall=stall, date=available_date, time=8, price=300),
                Slot(stall=stall, date=available_date, time=9, price=300),
                Slot(stall=stall, date=available_date, time=10, price=400),
            ]
        )
        db.session.commit()

    yield app


@pytest.fixture()
def client(app):
    return app.test_client()


def test_homepage_shows_available_stalls(client):
    response = client.get("/")

    assert response.status_code == 200
    assert b"SPACIS" in response.data
    assert b"Huashan Stall A" in response.data
    assert b"Taipei" in response.data
    assert b"NT$ 300" in response.data
    assert b'href="/login/Tenant"' in response.data


def test_homepage_links_tenant_to_booking(app, client):
    with app.app_context():
        tenant = User.query.filter_by(username="tenant1").one()
        stall = Stall.query.filter_by(loc_name="Huashan Stall A").one()
        booking_url = f"/booking_page/{stall.id}/{tenant.id}/"

    with client.session_transaction() as session:
        session["user_id"] = tenant.id
        session["user_role"] = "Tenant"

    response = client.get("/")

    assert response.status_code == 200
    assert f'href="{booking_url}"'.encode() in response.data
    assert b"tenant1" in response.data


def test_templates_use_spacis_brand():
    templates_dir = Path(__file__).resolve().parents[1] / "templates"

    for template_path in templates_dir.glob("*.html"):
        template = template_path.read_text(encoding="utf-8")
        assert "SMARKET" not in template
        assert "S-Market" not in template


def test_complete_booking_flow(app, client):
    with app.app_context():
        tenant1 = User.query.filter_by(username="tenant1").one()
        tenant2 = User.query.filter_by(username="tenant2").one()
        stall = Stall.query.filter_by(loc_name="Huashan Stall A").one()
        slots = Slot.query.order_by(Slot.time).all()
        slot1, slot2, slot3 = slots

    with client.session_transaction() as session:
        session["user_id"] = tenant1.id
        session["user_role"] = "Tenant"

    response = client.get(f"/booking_page/{stall.id}/{tenant1.id}/")
    assert response.status_code == 200
    assert b"Huashan Stall A" in response.data

    response = client.post(
        "/make_booking/",
        data={"user_id": tenant1.id, "slot_ids": [slot1.id, slot2.id]},
        follow_redirects=False,
    )
    with app.app_context():
        bookings = Booking.query.filter_by(user_id=tenant1.id).all()
        assert len(bookings) == 2
        qr_code = bookings[0].qr_code
        assert bookings[0].payment_status == "Unpaid"
    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/payment/{qr_code}/")

    response = client.get(f"/payment/{qr_code}/")
    assert response.status_code == 200
    assert b"Huashan Stall A" in response.data

    response = client.post(
        "/process_payment/",
        data={"qr_code": qr_code, "payment_method": "Credit Card"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/booking_success/{qr_code}/")

    with app.app_context():
        paid_bookings = Booking.query.filter_by(qr_code=qr_code).all()
        assert {booking.payment_status for booking in paid_bookings} == {"Paid"}
        assert {booking.payment_method for booking in paid_bookings} == {"Credit Card"}

    response = client.get(f"/booking_success/{qr_code}/")
    assert response.status_code == 200
    assert "信用卡支付".encode() in response.data

    response = client.get(f"/my_bookings/{tenant1.id}/")
    assert response.status_code == 200
    assert b"Huashan Stall A" in response.data

    with client.session_transaction() as session:
        session["user_id"] = tenant2.id
        session["user_role"] = "Tenant"

    response = client.get(f"/booking_page/{stall.id}/{tenant2.id}/")
    assert response.status_code == 200
    assert f'name="slot_ids" value="{slot1.id}"'.encode() not in response.data
    assert f'name="slot_ids" value="{slot2.id}"'.encode() not in response.data
    assert f'name="slot_ids" value="{slot3.id}"'.encode() in response.data


def test_api_booking_flow(app, client):
    with app.app_context():
        tenant = User.query.filter_by(username="tenant1").one()
        stall = Stall.query.filter_by(loc_name="Huashan Stall A").one()
        slot = Slot.query.order_by(Slot.time).first()

    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"

    response = client.get(f"/api/v1/stalls/{stall.id}/slots")
    assert response.status_code == 200
    assert response.get_json()["slots"][0]["id"] == slot.id

    response = client.post(
        "/api/v1/bookings",
        json={"user_id": tenant.id, "slot_ids": [slot.id]},
    )
    assert response.status_code == 201
    payload = response.get_json()
    assert payload["booking_count"] == 1
    qr_code = payload["qr_code"]

    response = client.post(
        "/api/v1/payments",
        json={"qr_code": qr_code, "payment_method": "Credit Card"},
    )
    assert response.status_code == 200

    response = client.get(f"/api/v1/bookings/{qr_code}")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["bookings"][0]["payment_status"] == "Paid"
