from __future__ import annotations

import json
from datetime import date, timedelta
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import pytest
from werkzeug.security import generate_password_hash

from app import create_app
from models import Booking, Slot, Stall, StallCertification, StallPhoto, User, db
from market_connect.services.certification_documents import (
    ValidatedDocument,
    replace_certification_documents,
)


CERTIFICATION_DOCUMENT = b"%PDF-1.7\nTest certification evidence\n%%EOF\n"
STALL_PHOTO = b"\x89PNG\r\n\x1a\nSPACIS test stall photo"


def _attach_certification_document(certification: StallCertification) -> None:
    db.session.add(certification)
    db.session.flush()
    replace_certification_documents(
        certification,
        [
            ValidatedDocument(
                filename="test-certification.pdf",
                content_type="application/pdf",
                data=CERTIFICATION_DOCUMENT,
                sha256=sha256(CERTIFICATION_DOCUMENT).hexdigest(),
            )
        ],
    )


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
            environment_type="indoor",
        )
        db.session.add_all([landlord, tenant1, tenant2, stall])
        db.session.flush()
        db.session.add(
            StallPhoto(
                stall=stall,
                original_filename="huashan-stall.png",
                content_type="image/png",
                byte_size=len(STALL_PHOTO),
                sha256=sha256(STALL_PHOTO).hexdigest(),
                display_order=0,
                data=STALL_PHOTO,
            )
        )
        certification = StallCertification(
            stall=stall,
            applicant_legal_name="Landlord One",
            applicant_phone="0912000000",
            relationship_to_space="property_owner",
            proof_type="property_record",
            declaration_accepted=True,
            status="approved",
            reviewer_reference="test-suite",
        )
        _attach_certification_document(certification)
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
    assert b'href="/account/"' in response.data
    assert b'id="auth-dialog"' in response.data
    assert b'data-auth-role="Tenant"' in response.data
    assert b'data-auth-role="Landlord"' in response.data
    assert b'<details class="home-mobile-menu">' in response.data
    assert 'aria-label="行動版主要導覽"'.encode() in response.data
    assert response.data.count("找攤位".encode()) >= 2
    assert response.data.count("刊登攤位".encode()) >= 2
    assert "讓每一次出攤，都從清楚開始。".encode() in response.data
    assert "可靠的租客".encode() in response.data
    assert "可靠的場地主".encode() in response.data
    assert "場地認證通過".encode() in response.data
    assert b"huashan-proof" not in response.data
    assert b'/stall_photos/' in response.data
    assert "先比較供應".encode() not in response.data


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
    assert b"Tenant One" in response.data
    assert b'href="/account/profile/"' in response.data


def test_marketplace_exposes_discovery_filters_and_booking_policy(app, client):
    response = client.get("/stalls/")

    assert response.status_code == 200
    assert b'id="keyword-filter"' in response.data
    assert b'id="city-filter"' in response.data
    assert b'id="district-filter"' in response.data
    assert b'id="environment-filter"' in response.data
    assert b'id="booking-mode-filter"' in response.data
    assert b'id="max-price-filter"' in response.data
    assert b"Huashan Stall A" in response.data
    assert b'"environment_type": "indoor"' in response.data
    assert b'"booking_mode": "hourly"' in response.data
    assert b'"minimum_booking_hours": 1' in response.data
    assert "場地認證通過".encode() in response.data
    assert b"huashan-proof" not in response.data
    assert b'/stall_photos/' in response.data


def test_approved_stall_photo_is_public_and_cacheable(app, client):
    with app.app_context():
        photo = StallPhoto.query.one()
        photo_url = f"/stall_photos/{photo.id}/"

    response = client.get(photo_url)
    assert response.status_code == 200
    assert response.data == STALL_PHOTO
    assert response.content_type == "image/png"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Cache-Control"] == "public, max-age=604800, immutable"

    cached = client.get(photo_url, headers={"If-None-Match": response.headers["ETag"]})
    assert cached.status_code == 304


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
        session["_csrf_token"] = "booking-test-token"

    response = client.get(f"/booking_page/{stall.id}/{tenant1.id}/")
    assert response.status_code == 200
    assert b"Huashan Stall A" in response.data
    assert b'class="stall-gallery"' in response.data

    response = client.post(
        "/make_booking/",
        data={
            "_csrf_token": "booking-test-token",
            "user_id": tenant2.id,
            "slot_ids": [slot1.id, slot2.id],
        },
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
    assert "線上信用卡付款".encode() in response.data
    assert "現場現金".encode() not in response.data
    assert b"Card Number" not in response.data

    cash_response = client.post(
        "/process_payment/",
        data={
            "_csrf_token": "booking-test-token",
            "qr_code": qr_code,
            "payment_method": "Cash",
        },
    )
    assert cash_response.status_code == 400
    with app.app_context():
        unpaid_bookings = Booking.query.filter_by(qr_code=qr_code).all()
        assert {booking.payment_status for booking in unpaid_bookings} == {"Unpaid"}
        assert {booking.payment_method for booking in unpaid_bookings} == {""}

    response = client.post(
        "/process_payment/",
        data={
            "_csrf_token": "booking-test-token",
            "qr_code": qr_code,
            "payment_method": "Credit Card",
        },
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
    assert "線上信用卡付款".encode() in response.data

    response = client.get(f"/my_bookings/{tenant1.id}/")
    assert response.status_code == 200
    assert b"Huashan Stall A" in response.data

    with client.session_transaction() as session:
        session["user_id"] = tenant2.id
        session["_csrf_token"] = "booking-test-token"

    response = client.get(f"/booking_page/{stall.id}/{tenant2.id}/")
    assert response.status_code == 200
    assert f'name="slot_ids" value="{slot1.id}"'.encode() not in response.data
    assert f'name="slot_ids" value="{slot2.id}"'.encode() not in response.data
    assert f'name="slot_ids" value="{slot3.id}"'.encode() in response.data
    assert b'name="user_id"' not in response.data


def test_provider_can_publish_full_day_stall(app, client):
    with app.app_context():
        landlord = User.query.filter_by(username="landlord1").one()

    with client.session_transaction() as session:
        session["user_id"] = landlord.id
        session["_csrf_token"] = "publish-test-token"

    stall_payload = {
        "_csrf_token": "publish-test-token",
        "loc_name": "Riverside Market",
        "city": "New Taipei",
        "district": "Banqiao",
        "road": "Xianmin Blvd",
        "address_detail": "No. 7",
        "environment_type": "outdoor",
        "facilities": "Power",
    }
    missing_photos = client.post(
        f"/landlord/{landlord.id}/",
        data=stall_payload,
    )
    assert missing_photos.status_code == 400
    assert "請上傳至少一張攤位照片".encode() in missing_photos.data

    response = client.post(
        f"/landlord/{landlord.id}/",
        data={
            **stall_payload,
            "stall_photos": [
                (BytesIO(STALL_PHOTO + bytes([index])), f"riverside-{index}.png")
                for index in range(5)
            ],
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert response.status_code == 302

    with app.app_context():
        stall = Stall.query.filter_by(loc_name="Riverside Market").one()
        stall_id = stall.id
        assert stall.environment_type == "outdoor"
        assert stall.certification is None
        assert [photo.display_order for photo in stall.photos] == list(range(5))
        assert stall.photos[0].original_filename == "riverside-0.png"
        first_photo_id = stall.photos[0].id
    assert response.headers["Location"].endswith(f"/stall_certification/{stall_id}/")
    assert client.get(f"/stall_photos/{first_photo_id}/").status_code == 404

    response = client.post(
        f"/stall_certification/{stall_id}/",
        data={
            "_csrf_token": "publish-test-token",
            "applicant_legal_name": "Landlord One",
            "applicant_phone": "0912000000",
            "relationship_to_space": "property_owner",
            "proof_type": "property_record",
            "declaration_accepted": "yes",
        },
    )
    assert response.status_code == 400
    assert "請上傳至少一份證明文件".encode() in response.data

    certification_document = b"%PDF-1.7\nRiverside ownership evidence\n%%EOF\n"
    response = client.post(
        f"/stall_certification/{stall_id}/",
        data={
            "_csrf_token": "publish-test-token",
            "applicant_legal_name": "Landlord One",
            "applicant_phone": "0912000000",
            "relationship_to_space": "property_owner",
            "proof_type": "property_record",
            "proof_reference": "TEST-OWNERSHIP-001",
            "declaration_accepted": "yes",
            "evidence_documents": (
                BytesIO(certification_document),
                "riverside-ownership.pdf",
            ),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/stall_pricing/{stall_id}/")

    with app.app_context():
        certification = StallCertification.query.filter_by(stall_id=stall_id).one()
        assert certification.status == "pending"
        assert [document.original_filename for document in certification.documents] == [
            "riverside-ownership.pdf"
        ]

    available_date = (date.today() + timedelta(days=10)).isoformat()
    response = client.post(
        f"/stall_pricing/{stall_id}/",
        data={
            "_csrf_token": "publish-test-token",
            "booking_mode": "daily",
            "slots_json": json.dumps(
                [
                    {
                        "date": available_date,
                        "hour": 8,
                        "duration_hours": 9,
                        "price": 3600,
                    }
                ]
            ),
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/landlord/history/{landlord.id}/")

    with app.app_context():
        stall = db.session.get(Stall, stall_id)
        slot = Slot.query.filter_by(stall_id=stall_id).one()
        assert stall.booking_mode == "daily"
        assert stall.minimum_booking_hours == 1
        assert (slot.time, slot.duration_hours, slot.price) == (8, 9, 3600)

    response = client.post(
        f"/stall_pricing/{stall_id}/",
        data={
            "_csrf_token": "publish-test-token",
            "booking_mode": "daily",
            "slots_json": json.dumps(
                [
                    {
                        "date": available_date,
                        "hour": 9,
                        "duration_hours": 2,
                        "price": 900,
                    }
                ]
            ),
        },
        follow_redirects=False,
    )
    assert response.status_code == 409
    with app.app_context():
        assert Slot.query.filter_by(stall_id=stall_id).count() == 1


def test_provider_stall_photo_upload_enforces_count_and_file_signature(app, client):
    with app.app_context():
        landlord_id = User.query.filter_by(username="landlord1").one().id

    with client.session_transaction() as session:
        session["user_id"] = landlord_id
        session["_csrf_token"] = "photo-validation-token"

    base_payload = {
        "_csrf_token": "photo-validation-token",
        "loc_name": "Rejected Photo Stall",
        "city": "Taipei",
        "district": "Datong",
        "road": "Dihua Street",
        "address_detail": "No. 10",
        "environment_type": "indoor",
    }
    too_many = client.post(
        f"/landlord/{landlord_id}/",
        data={
            **base_payload,
            "stall_photos": [
                (BytesIO(STALL_PHOTO + bytes([index])), f"stall-{index}.png")
                for index in range(6)
            ],
        },
        content_type="multipart/form-data",
    )
    assert too_many.status_code == 400
    assert "最多上傳 5 張照片".encode() in too_many.data

    disguised = client.post(
        f"/landlord/{landlord_id}/",
        data={
            **base_payload,
            "stall_photos": (BytesIO(b"not an image"), "fake.png"),
        },
        content_type="multipart/form-data",
    )
    assert disguised.status_code == 400
    assert "內容與副檔名不符".encode() in disguised.data
    with app.app_context():
        assert Stall.query.filter_by(loc_name="Rejected Photo Stall").count() == 0


def test_pending_certification_blocks_discovery_and_booking_until_approved(app, client):
    with app.app_context():
        landlord = User.query.filter_by(username="landlord1").one()
        tenant = User.query.filter_by(username="tenant1").one()
        pending_stall = Stall(
            owner=landlord,
            loc_name="Pending Harbor Stall",
            city="Keelung",
            district="Zhongzheng",
            road="Harbor Rd",
            address_detail="Pier 3",
            environment_type="outdoor",
        )
        pending_stall.certification = StallCertification(
            applicant_legal_name="Landlord One",
            applicant_phone="0912000000",
            relationship_to_space="authorized_manager",
            proof_type="venue_authorization",
            declaration_accepted=True,
            status="pending",
        )
        pending_stall.photos.append(
            StallPhoto(
                original_filename="pending.png",
                content_type="image/png",
                byte_size=len(STALL_PHOTO),
                sha256=sha256(STALL_PHOTO).hexdigest(),
                display_order=0,
                data=STALL_PHOTO,
            )
        )
        pending_slot = Slot(
            stall=pending_stall,
            date=date.today() + timedelta(days=20),
            time=9,
            price=500,
        )
        db.session.add_all([pending_stall, pending_slot])
        db.session.flush()
        _attach_certification_document(pending_stall.certification)
        db.session.commit()
        stall_id = pending_stall.id
        slot_id = pending_slot.id
        tenant_id = tenant.id
        photo_id = pending_stall.photos[0].id

    homepage = client.get("/")
    assert b"Pending Harbor Stall" not in homepage.data
    marketplace = client.get("/stalls/")
    assert f'data-stall-id="{stall_id}"'.encode() not in marketplace.data
    public_api = client.get("/api/v1/stalls")
    assert stall_id not in {item["id"] for item in public_api.get_json()["stalls"]}
    assert client.get(f"/api/v1/stalls/{stall_id}/slots").status_code == 404
    assert client.get(f"/stall_photos/{photo_id}/").status_code == 404

    with client.session_transaction() as session:
        session["user_id"] = tenant_id
        session["_csrf_token"] = "certification-gate-token"

    assert client.get(f"/booking_page/{stall_id}/{tenant_id}/").status_code == 404
    response = client.post(
        "/api/v1/bookings",
        json={"slot_ids": [slot_id]},
        headers={"X-CSRF-Token": "certification-gate-token"},
    )
    assert response.status_code == 409
    assert "尚未通過平台場地認證" in response.get_json()["error"]

    runner = app.test_cli_runner()
    pending_result = runner.invoke(args=["list-stall-certifications"])
    assert pending_result.exit_code == 0
    assert f"stall_id={stall_id}" in pending_result.output
    assert "documents=1" in pending_result.output

    rejected_without_note = runner.invoke(
        args=[
            "review-stall-certification",
            str(stall_id),
            "--decision",
            "reject",
            "--reviewer",
            "test-operator",
        ]
    )
    assert rejected_without_note.exit_code != 0

    approved = runner.invoke(
        args=[
            "review-stall-certification",
            str(stall_id),
            "--decision",
            "approve",
            "--reviewer",
            "test-operator",
            "--note",
            "Authorization confirmed.",
        ]
    )
    assert approved.exit_code == 0
    assert "is now approved" in approved.output

    homepage = client.get("/")
    assert b"Pending Harbor Stall" in homepage.data
    slots_response = client.get(f"/api/v1/stalls/{stall_id}/slots")
    assert slots_response.status_code == 200
    assert slots_response.get_json()["slots"][0]["id"] == slot_id
    assert client.get(f"/stall_photos/{photo_id}/").status_code == 200

    revoked = runner.invoke(
        args=[
            "review-stall-certification",
            str(stall_id),
            "--decision",
            "reject",
            "--reviewer",
            "test-operator",
            "--note",
            "Authorization expired.",
        ]
    )
    assert revoked.exit_code == 0
    assert b"Pending Harbor Stall" not in client.get("/").data
    assert client.get(f"/api/v1/stalls/{stall_id}/slots").status_code == 404
    assert client.get(f"/stall_photos/{photo_id}/").status_code == 404


def test_provider_cannot_publish_hourly_date_below_its_minimum(app, client):
    with app.app_context():
        landlord_id = User.query.filter_by(username="landlord1").one().id
        stall_id = Stall.query.filter_by(loc_name="Huashan Stall A").one().id

    with client.session_transaction() as session:
        session["user_id"] = landlord_id
        session["_csrf_token"] = "short-schedule-token"

    available_date = (date.today() + timedelta(days=30)).isoformat()
    response = client.post(
        f"/stall_pricing/{stall_id}/",
        data={
            "_csrf_token": "short-schedule-token",
            "booking_mode": "hourly",
            "minimum_booking_hours": "2",
            "slots_json": json.dumps(
                [
                    {
                        "date": available_date,
                        "hour": 8,
                        "duration_hours": 1,
                        "price": 300,
                    }
                ]
            ),
        },
        follow_redirects=False,
    )

    assert response.status_code == 400
    with app.app_context():
        assert Slot.query.filter_by(stall_id=stall_id, date=date.fromisoformat(available_date)).count() == 0


def test_hourly_booking_requires_consecutive_minimum_and_sums_prices(app, client):
    with app.app_context():
        tenant = User.query.filter_by(username="tenant1").one()
        stall = Stall.query.filter_by(loc_name="Huashan Stall A").one()
        stall.minimum_booking_hours = 2
        slots = Slot.query.order_by(Slot.time).all()
        slot1_id, slot2_id, slot3_id = (slot.id for slot in slots)
        db.session.commit()
        booking_url = f"/booking_page/{stall.id}/{tenant.id}/"

    with client.session_transaction() as session:
        session["user_id"] = tenant.id
        session["_csrf_token"] = "minimum-test-token"

    response = client.post(
        "/make_booking/",
        data={"_csrf_token": "minimum-test-token", "slot_ids": [slot1_id]},
        headers={"Referer": booking_url},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "至少需要預約 2 小時".encode() in response.data

    response = client.post(
        "/make_booking/",
        data={
            "_csrf_token": "minimum-test-token",
            "slot_ids": [slot1_id, slot3_id],
        },
        headers={"Referer": booking_url},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "所選時段必須連續".encode() in response.data

    with app.app_context():
        assert Booking.query.count() == 0

    response = client.post(
        "/make_booking/",
        data={
            "_csrf_token": "minimum-test-token",
            "slot_ids": [slot1_id, slot2_id],
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    payment = client.get(response.headers["Location"])
    assert payment.status_code == 200
    assert b"$600" in payment.data


def test_hourly_fragments_that_cannot_meet_minimum_are_hidden(app, client):
    with app.app_context():
        tenant1 = User.query.filter_by(username="tenant1").one()
        tenant2 = User.query.filter_by(username="tenant2").one()
        stall = Stall.query.filter_by(loc_name="Huashan Stall A").one()
        slots = Slot.query.order_by(Slot.time).all()
        stall.minimum_booking_hours = 2
        db.session.add(
            Booking(
                user=tenant2,
                slot=slots[1],
                qr_code="MIDDLE01",
                payment_status="Paid",
                payment_method="Credit Card",
            )
        )
        db.session.commit()
        tenant_id = tenant1.id
        stall_id = stall.id

    homepage = client.get("/")
    assert homepage.status_code == 200
    assert b"Huashan Stall A" not in homepage.data

    marketplace = client.get("/stalls/")
    assert marketplace.status_code == 200
    assert f'data-stall-id="{stall_id}"'.encode() not in marketplace.data

    api_response = client.get(f"/api/v1/stalls/{stall_id}/slots")
    assert api_response.status_code == 200
    assert api_response.get_json()["slots"] == []

    with client.session_transaction() as session:
        session["user_id"] = tenant_id
    booking_page = client.get(f"/booking_page/{stall_id}/{tenant_id}/")
    assert booking_page.status_code == 200
    assert b'class="slot-checkbox"' not in booking_page.data


def test_full_day_booking_is_one_flat_price(app, client):
    with app.app_context():
        landlord = User.query.filter_by(username="landlord1").one()
        tenant = User.query.filter_by(username="tenant1").one()
        full_day_stall = Stall(
            owner=landlord,
            loc_name="Full Day Hall",
            city="Taipei",
            district="Datong",
            road="Dihua St",
            address_detail="No. 10",
            environment_type="indoor",
            booking_mode="daily",
        )
        full_day_stall.certification = StallCertification(
            applicant_legal_name="Landlord One",
            applicant_phone="0912000000",
            relationship_to_space="property_owner",
            proof_type="property_record",
            declaration_accepted=True,
            status="approved",
            reviewer_reference="test-suite",
        )
        first_date = date.today() + timedelta(days=12)
        db.session.add_all(
            [
                full_day_stall,
                Slot(
                    stall=full_day_stall,
                    date=first_date,
                    time=8,
                    duration_hours=9,
                    price=3600,
                ),
                Slot(
                    stall=full_day_stall,
                    date=first_date + timedelta(days=1),
                    time=8,
                    duration_hours=9,
                    price=4000,
                ),
            ]
        )
        db.session.flush()
        _attach_certification_document(full_day_stall.certification)
        db.session.commit()
        tenant_id = tenant.id
        slot_ids = [slot.id for slot in full_day_stall.slots]

    with client.session_transaction() as session:
        session["user_id"] = tenant_id
        session["_csrf_token"] = "daily-test-token"

    response = client.post(
        "/make_booking/",
        data={"_csrf_token": "daily-test-token", "slot_ids": slot_ids},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/stalls/")

    response = client.post(
        "/make_booking/",
        data={"_csrf_token": "daily-test-token", "slot_ids": [slot_ids[0]]},
        follow_redirects=False,
    )
    assert response.status_code == 302
    payment = client.get(response.headers["Location"])
    assert payment.status_code == 200
    assert b"$3600" in payment.data

    with app.app_context():
        bookings = Booking.query.filter_by(user_id=tenant_id).all()
        assert len(bookings) == 1
        assert bookings[0].slot.duration_hours == 9


def test_tenant_navigation_stays_available_across_member_pages(app, client):
    with app.app_context():
        tenant = User.query.filter_by(username="tenant1").one()

    with client.session_transaction() as session:
        session["user_id"] = tenant.id

    expected_links = (
        'href="/"',
        'href="/stalls/"',
        f'href="/tenant/hub/{tenant.id}/"',
        'href="/account/profile/"',
    )
    for path in (f"/tenant/hub/{tenant.id}/", "/stalls/", "/account/profile/"):
        response = client.get(path)

        assert response.status_code == 200
        assert response.data.count(b'class="mc-nav"') == 1
        assert b'<details class="mc-nav__mobile">' in response.data
        for expected_link in expected_links:
            assert expected_link.encode() in response.data

    hub_response = client.get(f"/tenant/hub/{tenant.id}/")
    assert 'aria-current="page">租客中心'.encode() in hub_response.data
    assert "開通出租".encode() in hub_response.data


def test_provider_can_enable_tenant_navigation_without_dead_end(app, client):
    with app.app_context():
        landlord = User.query.filter_by(username="landlord1").one()
        stall = Stall.query.filter_by(loc_name="Huashan Stall A").one()

    with client.session_transaction() as session:
        session["user_id"] = landlord.id
        session["_csrf_token"] = "navigation-test-token"

    for path in (
        f"/landlord/hub/{landlord.id}/",
        f"/landlord/{landlord.id}/",
        f"/stall_pricing/{stall.id}/",
        f"/landlord/history/{landlord.id}/",
        "/publish_success/",
    ):
        response = client.get(path)

        assert response.status_code == 200
        assert response.data.count(b'class="mc-nav"') == 1
        assert f'href="/landlord/hub/{landlord.id}/"'.encode() in response.data
        assert b'intent=tenant' in response.data

    activation_page = client.get("/account/?intent=tenant")
    assert activation_page.status_code == 200
    assert "啟用租客功能".encode() in activation_page.data
    assert 'aria-current="page">+ 開通租客'.encode() in activation_page.data

    response = client.post(
        "/account/roles/Tenant",
        data={"_csrf_token": "navigation-test-token", "next": "/stalls/"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/stalls/")

    marketplace = client.get("/stalls/")
    assert marketplace.status_code == 200
    assert f'href="/tenant/hub/{landlord.id}/"'.encode() in marketplace.data
    assert f'href="/booking_page/{stall.id}/{landlord.id}/"'.encode() in marketplace.data


def test_api_booking_flow(app, client):
    with app.app_context():
        tenant = User.query.filter_by(username="tenant1").one()
        stall = Stall.query.filter_by(loc_name="Huashan Stall A").one()
        slot = Slot.query.order_by(Slot.time).first()

    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"
    assert response.get_json()["release"] == "20261004.11"

    response = client.get(f"/api/v1/stalls/{stall.id}/slots")
    assert response.status_code == 200
    assert response.get_json()["slots"][0]["id"] == slot.id

    stalls_payload = client.get("/api/v1/stalls").get_json()["stalls"]
    assert stalls_payload[0]["certification_status"] == "approved"
    assert stalls_payload[0]["photo_urls"]
    assert stalls_payload[0]["photo_urls"][0].startswith("/stall_photos/")
    assert "evidence_url" not in stalls_payload[0]

    with client.session_transaction() as session:
        session["user_id"] = tenant.id
        session["_csrf_token"] = "api-test-token"

    response = client.post(
        "/api/v1/bookings",
        json={"user_id": 999999, "slot_ids": [slot.id]},
        headers={"X-CSRF-Token": "api-test-token"},
    )
    assert response.status_code == 201
    payload = response.get_json()
    assert payload["booking_count"] == 1
    qr_code = payload["qr_code"]

    with app.app_context():
        assert Booking.query.filter_by(qr_code=qr_code).one().user_id == tenant.id

    cash_response = client.post(
        "/api/v1/payments",
        json={"qr_code": qr_code, "payment_method": "Cash"},
        headers={"X-CSRF-Token": "api-test-token"},
    )
    assert cash_response.status_code == 400
    assert "只接受線上信用卡付款" in cash_response.get_json()["error"]
    with app.app_context():
        assert Booking.query.filter_by(qr_code=qr_code).one().payment_status == "Unpaid"

    response = client.post(
        "/api/v1/payments",
        json={"qr_code": qr_code, "payment_method": "Credit Card"},
        headers={"X-CSRF-Token": "api-test-token"},
    )
    assert response.status_code == 200

    response = client.get(f"/api/v1/bookings/{qr_code}")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["bookings"][0]["payment_status"] == "Paid"

    removed_cash_confirmation = client.post(
        "/confirm_payment/",
        data={"_csrf_token": "api-test-token", "booking_id": payload["bookings"][0]["id"]},
    )
    assert removed_cash_confirmation.status_code == 404


def test_api_rejects_booking_below_hourly_minimum(app, client):
    with app.app_context():
        tenant = User.query.filter_by(username="tenant1").one()
        stall = Stall.query.filter_by(loc_name="Huashan Stall A").one()
        stall.minimum_booking_hours = 2
        slot_id = Slot.query.order_by(Slot.time).first().id
        db.session.commit()
        tenant_id = tenant.id

    with client.session_transaction() as session:
        session["user_id"] = tenant_id
        session["_csrf_token"] = "api-minimum-token"

    response = client.post(
        "/api/v1/bookings",
        json={"slot_ids": [slot_id]},
        headers={"X-CSRF-Token": "api-minimum-token"},
    )

    assert response.status_code == 409
    assert "至少需要預約 2 小時" in response.get_json()["error"]
    with app.app_context():
        assert Booking.query.count() == 0
