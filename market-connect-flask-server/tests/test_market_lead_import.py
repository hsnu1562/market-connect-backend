from __future__ import annotations

import pytest

from app import create_app
from models import ExternalMarketLead, ImportBatch, Slot, Stall, db
from market_connect.services.market_leads import import_market_leads


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
    yield app


def test_imported_market_leads_remain_private_and_idempotent(app):
    records = [
        {
            "title": "Weekend Market",
            "date": "2026.08.01~2026.08.02",
            "time": "10:00-18:00",
            "location": "Taipei Test Plaza",
            "fee": "NT$ 1000 / day",
            "contact": "Staff-only contact",
            "url": "https://example.test/market/weekend",
            "source_file": "weekend.txt",
            "source_dir": "links",
        },
        {
            "title": "Night Market",
            "date": "2026.08.08~2026.08.09",
            "time": "15:00-22:00",
            "location": "New Taipei Test Square",
            "fee": "Consult organizer",
            "contact": "Staff-only contact",
            "url": "https://example.test/market/night",
            "source_file": "night.txt",
            "source_dir": "links",
        },
    ]

    with app.app_context():
        first_result = import_market_leads(
            records,
            source_name="test-source",
            source_path="fixtures/test.json",
            test_mode=True,
        )

        assert first_result.created_count == 2
        assert first_result.updated_count == 0
        assert ExternalMarketLead.query.count() == 2
        assert ImportBatch.query.count() == 1
        assert Stall.query.count() == 0
        assert Slot.query.count() == 0

        lead = ExternalMarketLead.query.filter_by(source_url=records[0]["url"]).one()
        assert lead.source_name == "test-source"
        assert lead.review_status == "needs_review"
        assert lead.is_bookable is False
        assert lead.is_test_data is True
        assert lead.raw_payload == records[0]

        records[0]["fee"] = "NT$ 1200 / day"
        second_result = import_market_leads(
            records,
            source_name="test-source",
            source_path="fixtures/test.json",
            test_mode=True,
        )

        assert second_result.created_count == 0
        assert second_result.updated_count == 2
        assert ExternalMarketLead.query.count() == 2
        assert ImportBatch.query.count() == 2
        assert ExternalMarketLead.query.filter_by(source_url=records[0]["url"]).one().fee_text == "NT$ 1200 / day"
