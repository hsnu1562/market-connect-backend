# Marketplace Data Model

## Purpose

SPACIS is a commercial stall-rental marketplace. The database must keep
verified, bookable inventory separate from external market announcements that
have been collected for research or provider outreach.

## Booking Layer

These existing tables support the customer-facing service:

- `user`: account profile, legacy primary role, status, reputation, and a
  non-self-assignable `is_admin` operations flag.
- `user_role`: all role memberships; one user can operate as both Vendor and
  Provider. The stored values remain `Tenant` and `Landlord` for compatibility.
- `auth_identity`: Google or future LINE identity keyed by provider subject.
- `vendor_profile`: the optional public marketplace identity for one Vendor
  account. The MVP enforces one profile per user with a unique `user_id`, while
  keeping brand data separate from login identity and personal account fields.
  Brand name, category, description, image, and social links are public;
  contact and food registration fields are private transaction data.
- `stall`: a provider-owned physical stall or rentable space. It records the
  indoor/outdoor environment, whether it rents hourly or as a complete daily
  period, and the 1/2/3-hour minimum for hourly reservations.
- `stall_photo`: one public JPG, PNG, or WebP listing image stored in PostgreSQL
  with its display order, byte size, and digest. New stalls require 1–5 photos;
  image bytes are loaded only by the media endpoint and are served only while
  the stall certification is approved.
- `stall_certification`: private legal/contact evidence and manual review state
  for one stall, including the reviewing admin. Missing, pending, and rejected
  certifications prevent public discovery and booking. Evidence must be supplied
  through uploaded documents; URL evidence is not stored or accepted.
- `stall_certification_document`: encrypted uploaded evidence for a
  certification, including safe display metadata, size, digest, AES-GCM nonce,
  ciphertext, and upload time. Plaintext document bytes are never stored.
- `slot`: one bookable period for a stall, including its date, start hour,
  duration, and price. In hourly mode each row is one hour and selected rows
  must be consecutive. In daily mode one row represents the entire indivisible
  opening period and its price is the flat total.
- `booking`: a Vendor's reservation for exactly one slot and a QR-code group.
  Reservation state is `HELD`, `CONFIRMED`, `EXPIRED`, or `CANCELLED`; it is
  independent from payment state. A partial unique index permits only one
  active hold/confirmation per slot while preserving expired history.
- `booking_requirement`: one immutable operational snapshot shared by all
  `booking` rows in a QR-code group. It records electricity, gas, equipment,
  and vehicle-plate needs for that reservation. Existing bookings retain a null
  reference and are not rewritten.
- `payment_transaction`: provider-independent payment intent for one QR-code
  booking group, including amount, currency, provider references, timestamps,
  and `PENDING`, `PROCESSING`, `VERIFIED`, `FAILED`, or `REFUNDED` state.
  Historical booking payment strings remain only as untrusted legacy evidence.
- `stall_price`: an optional pricing record for a stall date and hour.
- `review`: one Vendor or Provider review per booking and reviewer.

Providers may prepare `stall` and `slot` draft records, but only stalls with an
approved `stall_certification` power public availability and bookings.

## Baseline Technical Debt

Reservation and payment statuses remain application-validated strings. The
database does not yet enforce their allowed values with `CHECK` constraints or
PostgreSQL enums; that hardening is deferred to avoid widening the Phase 2
baseline repair.

Migration `20261004_05` historically represents
`stall_certification.stall_id` as a unique constraint plus a non-unique index,
while current SQLAlchemy metadata describes a unique index. Migrations 10 and
11 deliberately do not rewrite that older migration difference.

## Profile And Privacy Boundary

`user` remains the authenticated account and retains nullable historical
`birth_date`, nickname, name, and telephone fields. Birthday is no longer
collected or required; existing values are preserved. `vendor_profile` is
created only when the account first needs to book, never fabricated during
migration.

Public Vendor serializers explicitly whitelist brand fields. Contact phone,
private email, food registration number, vehicle plate, and operational
requirements are available only to the booking's Vendor, the Provider owning
the booked stall, or an authorized admin.

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
