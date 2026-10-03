from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from werkzeug.security import generate_password_hash

from ..extensions import db
from ..models import Slot, Stall, StallCertification, User


def seed_demo_data() -> None:
    if User.query.filter_by(username="tenant1").first():
        return

    landlord = User(
        username="landlord1",
        password_hash=generate_password_hash("landlord1_password"),
        first_name="Landlord",
        last_name="One",
        nickname="Demo Provider",
        birth_date=date(1990, 1, 1),
        phone_number="0912-000-001",
        role="Landlord",
        profile_completed_at=datetime.now(UTC),
    )
    tenant = User(
        username="tenant1",
        password_hash=generate_password_hash("tenant1_password"),
        first_name="Tenant",
        last_name="One",
        nickname="Demo Tenant",
        birth_date=date(1995, 1, 1),
        phone_number="0912-000-002",
        role="Tenant",
        profile_completed_at=datetime.now(UTC),
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
    db.session.add_all([landlord, tenant, stall])
    db.session.flush()
    db.session.add(
        StallCertification(
            stall=stall,
            applicant_legal_name="Demo Provider",
            applicant_phone="0912-000-001",
            relationship_to_space="property_owner",
            proof_type="property_record",
            proof_reference="DEMO-ONLY",
            evidence_url="https://example.invalid/demo-stall-proof",
            declaration_accepted=True,
            status="approved",
            reviewed_at=datetime.now(UTC),
            reviewer_reference="seed-demo",
            review_note="Development fixture only.",
        )
    )
    demo_date = date.today() + timedelta(days=7)
    for hour, price in [(8, 300), (9, 300), (10, 400)]:
        db.session.add(Slot(stall=stall, date=demo_date, time=hour, price=price))
    db.session.commit()
