# Marketplace Data Model

## Purpose

SPACIS is a commercial stall-rental marketplace. The database must keep
verified, bookable inventory separate from external market announcements that
have been collected for research or provider outreach.

## Booking Layer

These existing tables support the customer-facing service:

- `user`: account profile, legacy primary role, status, and reputation.
- `user_role`: all role memberships; one user can be both renter and provider.
- `auth_identity`: Google or future LINE identity keyed by provider subject.
- `stall`: a provider-owned physical stall or rentable space. It records the
  indoor/outdoor environment, whether it rents hourly or as a complete daily
  period, and the 1/2/3-hour minimum for hourly reservations.
- `slot`: one bookable period for a stall, including its date, start hour,
  duration, and price. In hourly mode each row is one hour and selected rows
  must be consecutive. In daily mode one row represents the entire indivisible
  opening period and its price is the flat total.
- `booking`: a renter's reservation for exactly one slot, payment state, and QR
  code group.
- `stall_price`: an optional pricing record for a stall date and hour.
- `review`: one renter or provider review per booking and reviewer.

Only verified providers should create `stall` and `slot` records. These are the
only tables that power public availability and bookings.

## External Intake Layer

Crawler output is external announcement data, not confirmed SPACIS inventory.
It is stored privately for review and provider outreach.

- `import_batch`: one import attempt, including source name, input path,
  content fingerprint, timestamps, record counts, and whether it was test data.
- `external_market_lead`: one source announcement, keyed by source URL.

`external_market_lead` saves:

- source traceability: source URL, source file, source directory, raw JSON, and
  a content hash;
- display/review fields: title, free-form date, time, location, and fee text;
- restricted operational data: source contact text, visible only to staff;
- lifecycle state: `review_status`, `is_bookable`, `is_test_data`, first/last
  seen timestamps, and its last import batch.

All imported leads begin as `review_status = needs_review` and
`is_bookable = false`. They must never be displayed as bookable space merely
because a crawler found them.

## Promotion Path

After source permission and provider verification, a staff member should create
or link the provider `user`, then create the verified `stall` and its actual
`slot` availability. The source lead remains as the audit trail.

Do not automatically parse free-form dates or fees into booking slots. The
current crawler output contains date ranges and mixed fee descriptions, so an
operator must validate date, time, capacity, price, cancellation policy,
facilities, and provider authority before publication.

## Importing Crawler Output

From `market-connect-flask-server/`, use a test import first:

```bash
python -m flask --app app import-market-leads \
  --file ../../market-connect-utils/crawlers/parsed/combined.json \
  --source-name 168market \
  --limit 1 \
  --test
```

The command is idempotent by source URL: a repeated import updates the existing
lead rather than creating a duplicate. Use a current `DATABASE_URL` in the
environment to target Render PostgreSQL; otherwise it writes to local SQLite.

## Render PostgreSQL Test Import

Do not place the Render connection string in source code. In a local Command
Prompt, set a current database URL only for that terminal session, then run the
following from the backend repository root:

```bat
set DATABASE_URL=YOUR_CURRENT_RENDER_DATABASE_URL
conda run -n SPACIS python -m flask --app market-connect-flask-server/app.py init-db
conda run -n SPACIS python -m flask --app market-connect-flask-server/app.py db upgrade
conda run -n SPACIS python -m flask --app market-connect-flask-server/app.py import-market-leads --file ../market-connect-utils/crawlers/parsed/combined.json --source-name 168market --limit 1 --test
```

This creates the new intake tables if necessary and writes one clearly marked,
private test lead. It does not create a provider, stall, slot, or booking.
