from __future__ import annotations

from datetime import date, datetime

from flask import abort

from ..extensions import db


def get_or_404(model, object_id: int):
    item = db.session.get(model, object_id)
    if item is None:
        abort(404)
    return item


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()
