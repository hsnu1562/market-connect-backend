from __future__ import annotations

from io import BytesIO

import pytest

from app import create_app
from models import Stall, StallCertification, StallCertificationDocument, User, db


PDF_DOCUMENT = b"%PDF-1.7\nSPACIS private certification evidence\n%%EOF\n"


@pytest.fixture()
def app():
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "certification-admin-test-secret",
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        }
    )
    with app.app_context():
        admin = User(
            username="admin-reviewer",
            first_name="Admin",
            last_name="Reviewer",
            role="Tenant",
            is_admin=True,
        )
        landlord = User(
            username="document-landlord",
            first_name="Document",
            last_name="Landlord",
            phone_number="0912345678",
            role="Landlord",
        )
        member = User(
            username="ordinary-member",
            first_name="Ordinary",
            last_name="Member",
            role="Tenant",
        )
        stall = Stall(
            owner=landlord,
            loc_name="Encrypted Evidence Stall",
            city="Taipei",
            district="Datong",
            road="Dihua Street",
            address_detail="No. 1",
            environment_type="indoor",
        )
        db.create_all()
        db.session.add_all([admin, landlord, member, stall])
        db.session.commit()
    yield app


@pytest.fixture()
def client(app):
    return app.test_client()


def _user_id(app, username: str) -> int:
    with app.app_context():
        return User.query.filter_by(username=username).one().id


def _stall_id(app) -> int:
    with app.app_context():
        return Stall.query.filter_by(loc_name="Encrypted Evidence Stall").one().id


def _sign_in(client, user_id: int, token: str = "certification-test-token") -> None:
    with client.session_transaction() as session:
        session["user_id"] = user_id
        session["_csrf_token"] = token


def _certification_form(token: str = "certification-test-token") -> dict[str, str]:
    return {
        "_csrf_token": token,
        "applicant_legal_name": "Document Landlord",
        "applicant_phone": "0912345678",
        "relationship_to_space": "property_owner",
        "proof_type": "property_record",
        "proof_reference": "Deed reference 123",
        "evidence_url": "",
        "declaration_accepted": "yes",
    }


def _upload_certification(app, client) -> tuple[int, int]:
    landlord_id = _user_id(app, "document-landlord")
    stall_id = _stall_id(app)
    _sign_in(client, landlord_id)
    payload = _certification_form()
    payload["evidence_documents"] = (BytesIO(PDF_DOCUMENT), "venue-proof.pdf")
    response = client.post(
        f"/stall_certification/{stall_id}/",
        data=payload,
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert response.status_code == 302

    with app.app_context():
        certification = StallCertification.query.filter_by(stall_id=stall_id).one()
        document = certification.documents[0]
        return certification.id, document.id


def test_provider_upload_is_encrypted_and_can_replace_existing_documents(app, client):
    certification_id, first_document_id = _upload_certification(app, client)

    with app.app_context():
        document = db.session.get(StallCertificationDocument, first_document_id)
        assert document is not None
        assert document.original_filename == "venue-proof.pdf"
        assert document.content_type == "application/pdf"
        assert document.byte_size == len(PDF_DOCUMENT)
        assert PDF_DOCUMENT not in document.ciphertext
        assert len(document.nonce) == 12

    page = client.get(f"/stall_certification/{_stall_id(app)}/")
    assert page.status_code == 200
    assert b"venue-proof.pdf" in page.data
    assert PDF_DOCUMENT not in page.data

    replacement = b"%PDF-1.7\nreplacement evidence\n%%EOF\n"
    payload = _certification_form()
    payload["evidence_documents"] = (BytesIO(replacement), "replacement.pdf")
    response = client.post(
        f"/stall_certification/{_stall_id(app)}/",
        data=payload,
        content_type="multipart/form-data",
    )
    assert response.status_code == 302

    with app.app_context():
        certification = db.session.get(StallCertification, certification_id)
        assert [item.original_filename for item in certification.documents] == [
            "replacement.pdf"
        ]
        assert db.session.get(StallCertificationDocument, first_document_id) is None


def test_provider_upload_rejects_disguised_or_missing_evidence(app, client):
    _sign_in(client, _user_id(app, "document-landlord"))
    stall_id = _stall_id(app)

    payload = _certification_form()
    payload["evidence_documents"] = (BytesIO(b"<script>bad</script>"), "proof.pdf")
    response = client.post(
        f"/stall_certification/{stall_id}/",
        data=payload,
        content_type="multipart/form-data",
    )
    assert response.status_code == 400
    assert "內容與副檔名不符".encode() in response.data

    response = client.post(
        f"/stall_certification/{stall_id}/",
        data=_certification_form(),
        content_type="multipart/form-data",
    )
    assert response.status_code == 400
    assert "請上傳至少一份證明文件".encode() in response.data
    with app.app_context():
        assert StallCertification.query.count() == 0


def test_admin_queue_download_and_review_are_admin_only(app, client):
    certification_id, document_id = _upload_certification(app, client)
    document_path = (
        f"/admin/certifications/{certification_id}/documents/{document_id}/"
    )

    client.post(
        "/logout/",
        data={"_csrf_token": "certification-test-token"},
        follow_redirects=False,
    )
    anonymous = client.get("/admin/certifications/", follow_redirects=False)
    assert anonymous.status_code == 302
    assert "/account/" in anonymous.headers["Location"]

    _sign_in(client, _user_id(app, "ordinary-member"))
    assert client.get("/admin/certifications/").status_code == 403
    assert client.get(document_path).status_code == 403

    _sign_in(client, _user_id(app, "admin-reviewer"), "admin-review-token")
    queue = client.get("/admin/certifications/")
    assert queue.status_code == 200
    assert queue.headers["Cache-Control"].startswith("no-store")
    assert queue.headers["Referrer-Policy"] == "no-referrer"
    assert b"Encrypted Evidence Stall" in queue.data
    assert b"venue-proof.pdf" not in queue.data

    detail = client.get(f"/admin/certifications/{certification_id}/")
    assert detail.status_code == 200
    assert b"venue-proof.pdf" in detail.data
    download = client.get(document_path)
    assert download.status_code == 200
    assert download.data == PDF_DOCUMENT
    assert download.headers["Cache-Control"].startswith("no-store")
    assert download.headers["X-Content-Type-Options"] == "nosniff"
    assert "attachment" in download.headers["Content-Disposition"]

    rejected = client.post(
        f"/admin/certifications/{certification_id}/review",
        data={
            "_csrf_token": "admin-review-token",
            "decision": "reject",
            "review_note": "Address is not visible in the submitted document.",
        },
        follow_redirects=False,
    )
    assert rejected.status_code == 302
    with app.app_context():
        certification = db.session.get(StallCertification, certification_id)
        admin = User.query.filter_by(username="admin-reviewer").one()
        assert certification.status == "rejected"
        assert certification.reviewed_by_user_id == admin.id
        assert certification.reviewer_reference == admin.username
        assert certification.reviewed_at is not None


def test_admin_rejection_requires_note_and_cli_controls_admin_flag(app, client):
    certification_id, _ = _upload_certification(app, client)
    _sign_in(client, _user_id(app, "admin-reviewer"), "admin-review-token")
    response = client.post(
        f"/admin/certifications/{certification_id}/review",
        data={"_csrf_token": "admin-review-token", "decision": "reject"},
    )
    assert response.status_code == 400

    runner = app.test_cli_runner()
    enabled = runner.invoke(args=["set-admin", "ordinary-member", "--enable"])
    assert enabled.exit_code == 0
    with app.app_context():
        assert User.query.filter_by(username="ordinary-member").one().is_admin is True

    disabled = runner.invoke(args=["set-admin", "ordinary-member", "--disable"])
    assert disabled.exit_code == 0
    with app.app_context():
        assert User.query.filter_by(username="ordinary-member").one().is_admin is False
