from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any

from ..extensions import db
from ..models import ExternalMarketLead, ImportBatch


REQUIRED_FIELDS = (
    "title",
    "date",
    "time",
    "location",
    "fee",
    "contact",
    "url",
    "source_file",
    "source_dir",
)


@dataclass(frozen=True)
class ImportResult:
    batch_id: int
    processed_count: int
    created_count: int
    updated_count: int
    skipped_count: int


def load_market_lead_records(input_path: str | Path) -> list[dict[str, Any]]:
    path = Path(input_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("The market-lead input must be a JSON array.")

    records: list[dict[str, Any]] = []
    for index, raw_record in enumerate(payload, start=1):
        if not isinstance(raw_record, dict):
            raise ValueError(f"Record {index} is not a JSON object.")
        records.append(raw_record)
    return records


def import_market_leads(
    records: list[dict[str, Any]],
    *,
    source_name: str,
    source_path: str,
    test_mode: bool = False,
) -> ImportResult:
    """Upsert source announcements without making them bookable inventory."""

    source_digest = _digest(records)
    batch = ImportBatch(
        source_name=source_name,
        source_path=source_path,
        source_digest=source_digest,
        record_count=len(records),
        is_test_data=test_mode,
    )
    db.session.add(batch)
    db.session.flush()

    created_count = 0
    updated_count = 0
    skipped_count = 0
    now = datetime.now(UTC)

    try:
        for raw_record in records:
            normalized = _normalize_record(raw_record, source_name=source_name)
            if normalized is None:
                skipped_count += 1
                continue

            lead = ExternalMarketLead.query.filter_by(source_url=normalized["source_url"]).one_or_none()
            if lead is None:
                lead = ExternalMarketLead(
                    **normalized,
                    last_import_batch=batch,
                    is_test_data=test_mode,
                    first_seen_at=now,
                    last_seen_at=now,
                )
                db.session.add(lead)
                created_count += 1
            else:
                _update_lead(lead, normalized, batch=batch, test_mode=test_mode, seen_at=now)
                updated_count += 1

        batch.created_count = created_count
        batch.updated_count = updated_count
        batch.skipped_count = skipped_count
        batch.completed_at = now
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    return ImportResult(
        batch_id=batch.id,
        processed_count=len(records) - skipped_count,
        created_count=created_count,
        updated_count=updated_count,
        skipped_count=skipped_count,
    )


def import_market_leads_from_file(
    input_path: str | Path,
    *,
    source_name: str,
    limit: int | None = None,
    test_mode: bool = False,
) -> ImportResult:
    records = load_market_lead_records(input_path)
    if limit is not None:
        if limit < 1:
            raise ValueError("The import limit must be at least 1.")
        records = records[:limit]
    return import_market_leads(
        records,
        source_name=source_name,
        source_path=str(Path(input_path)),
        test_mode=test_mode,
    )


def _normalize_record(
    raw_record: dict[str, Any], *, source_name: str
) -> dict[str, Any] | None:
    values = {field: str(raw_record.get(field, "")).strip() for field in REQUIRED_FIELDS}
    if not values["title"] or not values["url"]:
        return None

    return {
        "source_name": source_name,
        "source_url": values["url"],
        "source_file": values["source_file"],
        "source_dir": values["source_dir"],
        "content_hash": _digest(raw_record),
        "title": values["title"],
        "date_text": values["date"],
        "time_text": values["time"],
        "location_text": values["location"],
        "fee_text": values["fee"],
        "contact_text": values["contact"],
        "raw_payload": raw_record,
    }


def _update_lead(
    lead: ExternalMarketLead,
    normalized: dict[str, Any],
    *,
    batch: ImportBatch,
    test_mode: bool,
    seen_at: datetime,
) -> None:
    for field, value in normalized.items():
        if field != "source_name":
            setattr(lead, field, value)
    lead.source_name = batch.source_name
    lead.last_import_batch = batch
    lead.last_seen_at = seen_at
    lead.is_test_data = lead.is_test_data or test_mode


def _digest(payload: Any) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
