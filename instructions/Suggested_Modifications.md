# Suggested API Modifications

This note is based on the current `/utils` crawler output and the current API
structure. The goal is to make the API ready to consume real market listing
data while keeping the MVP small.

## Context

The `/utils` repo is producing structured records from `168market.tw` with
fields like:

- `title`
- `date`
- `time`
- `location`
- `fee`
- `contact`
- `url`
- `source_file`
- `source_dir`

The API currently has these core tables:

- `users`
- `stalls`
- `slots`
- `bookings`

That is a good MVP foundation, but the crawler data is closer to an
event/listing feed than a simple physical stall table.

## Priority 1: Align API Tables With Real Listing Data

Recommended additions or adjustments:

- Add a `listings` or `events` table for imported market/event postings.
- Preserve `source_url`, `source_name`, `source_file`, and optionally `raw_text`
  so imports are traceable.
- Store parsed fields separately from raw fields: `title`, `date_start`,
  `date_end`, `time_text`, `location_text`, `fee_text`, `contact_text`.
- Keep `stalls` for actual bookable physical inventory, not scraped
  announcement pages.
- Let one listing create one or more slots after review/normalization.

Suggested direction:

```text
listings -> reviewed/normalized into stalls + slots
```

This prevents scraped text from becoming trusted inventory too early.

## Priority 2: Fix Current Schema and Script Mismatches

Current issues to clean up:

- `utils/makeTestData.py` inserts into `availability`, but the schema defines
  `slots`.
- `routers/enums.py` has statuses `0`, `1`, `2`, but docs/schema also mention
  `3: maintenance`.
- `slots.status` and `bookings.payment_status` are doing too much; booking state
  and payment state should be separate.
- Consider renaming `long` to `lng` or `longitude` to avoid confusion and keep
  naming consistent with `lat`.

## Priority 3: Improve Booking State Model

Current `/book` immediately sets a slot to `BOOKED` while payment is still
`PENDING`.

For MVP, consider this flow:

```text
AVAILABLE -> LOCKED/PENDING_APPROVAL -> BOOKED after approval/payment
```

Recommended fields:

- `bookings.status`: `PENDING`, `APPROVED`, `REJECTED`, `CANCELED`, `CONFIRMED`
- `bookings.payment_status`: `UNPAID`, `PAID`, `REFUNDED`
- `slots.status`: `AVAILABLE`, `LOCKED`, `BOOKED`, `MAINTENANCE`

This will support both request-to-book and future instant-book models.

## Priority 4: Add Import Contract For `/utils`

The API should define a stable import format that `/utils` can target.

Minimum import contract:

```json
{
  "title": "string",
  "date": "string from crawler",
  "time": "string",
  "location": "string",
  "fee": "string",
  "contact": "string",
  "url": "string",
  "source_file": "string",
  "source_dir": "string"
}
```

Recommended backend behavior:

- Import records idempotently using `url` as the unique source key.
- Store raw crawler fields first.
- Add a later review step before records become bookable slots.
- Validate dates but do not drop records just because parsing is imperfect.

## Priority 5: Add Basic Tests

Recommended first tests:

- Database initialization creates all documented tables.
- Test data script uses valid table names.
- `/book` prevents double booking under concurrent requests.
- `/cancel_booking` frees slots only when cancellation is valid.
- Import logic does not duplicate records with the same `source_url`.

## Suggested Next API Tasks

1. Fix `makeTestData.py` table mismatch.
2. Add `MAINTENANCE = 3` to slot status enum or remove it from docs/schema.
3. Add a `listings` table for crawler/imported event data.
4. Add an import script or endpoint for `/utils` crawler JSON.
5. Separate booking status from payment status.
6. Add minimal tests around database setup and booking state transitions.

## Coordination With `/utils`

The `/utils` side should focus on reliable collection, normalization,
deduplication, and export. The API side should own database schema, import
validation, review workflow, and conversion from listing data into real bookable
inventory.
