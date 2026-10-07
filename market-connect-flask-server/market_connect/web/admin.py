from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from io import BytesIO

from cryptography.exceptions import InvalidTag
from flask import (
    Blueprint,
    abort,
    current_app,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

from ..extensions import db
from ..models import StallCertification, StallCertificationDocument
from ..security import admin_required, get_current_user
from ..services.certification_documents import decrypt_certification_document
from .landlord import PROOF_TYPE_LABELS, RELATIONSHIP_LABELS
from .utils import get_or_404


bp = Blueprint("web_admin", __name__, url_prefix="/admin")
ALLOWED_STATUSES = ("pending", "approved", "rejected")


@bp.after_request
def prevent_sensitive_response_caching(response):
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@bp.get("/")
@admin_required
def dashboard():
    return redirect(url_for("web_admin.certification_queue"))


@bp.get("/certifications/")
@admin_required
def certification_queue():
    selected_status = request.args.get("status", "pending")
    if selected_status not in (*ALLOWED_STATUSES, "all"):
        abort(400, description="Invalid certification status.")

    query = StallCertification.query.order_by(StallCertification.submitted_at.asc())
    if selected_status != "all":
        query = query.filter_by(status=selected_status)
    certifications = query.limit(200).all()
    status_counts = {
        status: StallCertification.query.filter_by(status=status).count()
        for status in ALLOWED_STATUSES
    }
    return render_template(
        "admin_certifications.html",
        certifications=certifications,
        selected_status=selected_status,
        status_counts=status_counts,
    )


@bp.get("/certifications/<int:certification_id>/")
@admin_required
def certification_detail(certification_id: int):
    certification = get_or_404(StallCertification, certification_id)
    return render_template(
        "admin_certification_detail.html",
        certification=certification,
        relationship_labels=RELATIONSHIP_LABELS,
        proof_type_labels=PROOF_TYPE_LABELS,
    )


@bp.get("/certifications/<int:certification_id>/documents/<int:document_id>/")
@admin_required
def certification_document(certification_id: int, document_id: int):
    document = StallCertificationDocument.query.filter_by(
        id=document_id,
        certification_id=certification_id,
    ).first()
    if document is None:
        abort(404)

    try:
        plaintext = decrypt_certification_document(document)
    except (InvalidTag, ValueError):
        current_app.logger.exception(
            "Certification document decryption failed for document_id=%s",
            document.id,
        )
        abort(500, description="The certification document could not be decrypted.")
    if hashlib.sha256(plaintext).hexdigest() != document.sha256:
        current_app.logger.error(
            "Certification document digest mismatch for document_id=%s",
            document.id,
        )
        abort(500, description="The certification document failed its integrity check.")

    response = send_file(
        BytesIO(plaintext),
        mimetype=document.content_type,
        as_attachment=True,
        download_name=document.original_filename,
        max_age=0,
    )
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = "sandbox"
    return response


@bp.post("/certifications/<int:certification_id>/review")
@admin_required
def review_certification(certification_id: int):
    certification = get_or_404(StallCertification, certification_id)
    decision = request.form.get("decision", "")
    note = request.form.get("review_note", "").strip()
    if decision not in {"approve", "reject"}:
        abort(400, description="Invalid certification decision.")
    if decision == "reject" and not note:
        abort(400, description="A rejection reason is required.")
    if len(note) > 2000:
        abort(400, description="Review note cannot exceed 2000 characters.")
    if decision == "approve" and not certification.documents:
        abort(409, description="Certification has no evidence to review.")
    if decision == "approve" and not certification.declaration_accepted:
        abort(409, description="Certification declaration has not been accepted.")

    admin = get_current_user()
    if admin is None:
        abort(401)
    certification.status = "approved" if decision == "approve" else "rejected"
    certification.reviewed_at = datetime.now(UTC)
    certification.reviewed_by = admin
    certification.reviewer_reference = admin.username
    certification.review_note = note or None
    db.session.commit()
    return redirect(url_for("web_admin.certification_detail", certification_id=certification.id))
