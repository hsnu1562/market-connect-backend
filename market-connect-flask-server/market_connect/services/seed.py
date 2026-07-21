from __future__ import annotations

from datetime import date, timedelta

from werkzeug.security import generate_password_hash

from ..extensions import db
from ..models import Slot, Stall, User


def seed_demo_data() -> None:
    if User.query.filter_by(username="tenant1").first():
        return

    landlord = User(
        username="landlord1",
        password_hash=generate_password_hash("landlord1_password"),
        first_name="Landlord",
        last_name="One",
        phone_number="0912-000-001",
        role="Landlord",
    )
    tenant = User(
        username="tenant1",
        password_hash=generate_password_hash("tenant1_password"),
        first_name="Tenant",
        last_name="One",
        phone_number="0912-000-002",
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
    db.session.add_all([landlord, tenant, stall])
    db.session.flush()
    demo_date = date.today() + timedelta(days=7)
    for hour, price in [(8, 300), (9, 300), (10, 400)]:
        db.session.add(Slot(stall=stall, date=demo_date, time=hour, price=price))
    db.session.commit()
