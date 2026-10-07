# Phase 3A Supply And Inventory

## Domain Boundary

Phase 3A adds the verified supply hierarchy:

```text
Provider -> Venue -> Opportunity -> InventoryGroup -> Booking
```

- `Provider` is owned by its managing User, including when an admin creates it.
- `Venue` is independently verified and reusable across Opportunities.
- `Opportunity` is the public commercial listing. V1 supports only `INSTANT`
  booking policy.
- `InventoryGroup` is one concrete service period and its SPACIS-exclusive
  `allocated_capacity`.
- `Booking` remains the canonical reservation record. New inventory bookings
  use `inventory_group_id`; legacy bookings continue using `slot_id`.

Provider and Venue verification uses `PENDING`, `VERIFIED`, `SUSPENDED`, and
`REVOKED`. Opportunity publication uses `DRAFT`, `PUBLISHED`, `PAUSED`, and
`ARCHIVED`. Inventory uses `DRAFT`, `ACTIVE`, `PAUSED`, and `CLOSED`.

## Derived Availability

No mutable remaining-capacity field exists. Availability is always derived:

```text
available = allocated_capacity
            - CONFIRMED reservations
            - HELD reservations whose hold_expires_at is still in the future
```

`EXPIRED` and `CANCELLED` records consume no capacity. Cancellation releases
inventory immediately and does not change payment or refund state.

If an InventoryGroup has category quota rows, those rows are an allowlist. An
unlisted category has zero availability. Listed categories must satisfy both
their own remaining quota and the overall remaining allocation. If no quota
rows exist, any Vendor category may consume the overall pool.

Allocation and quota reductions are rejected if they would fall below active
commitments. Existing reservations are never force-cancelled to make a
reduction succeed.

## Booking Gates And Requirements

A new hold and a new payment initiation require all of these conditions:

- Provider verification is current and `VERIFIED`.
- Venue verification is current and `VERIFIED`.
- Opportunity is `PUBLISHED` with `INSTANT` booking policy.
- InventoryGroup is `ACTIVE` and its service period has not ended.

Existing confirmed reservations are preserved if supply is later suspended.
Trusted payment verification callbacks remain able to resolve already-started
transactions; only new payment initiation is blocked.

Opportunity and InventoryGroup requirement declarations use a finite list:
`FOOD_REGISTRATION`, `ELECTRICITY`, `GAS`, `VEHICLE_PLATE`, `STALL_PHOTO`, and
`EQUIPMENT`. Reusable brand data stays in `VendorProfile`; operational data is
snapshotted into `BookingRequirements`.

## Transaction Lock Order

PostgreSQL is authoritative. Every inventory-affecting transaction follows:

```text
InventoryGroup row -> ordered Booking rows -> ordered PaymentTransaction rows
```

Holding the InventoryGroup row serializes final-capacity checks, category quota
checks, capacity changes, quota replacement, cancellation, and payment state
work for that inventory pool. Do not add a path that locks Payment before its
InventoryGroup and Booking rows.

## API Scope

The `/api/v1/supply/...` routes support founder/admin onboarding and management
by the Provider's managing User. Public `GET /api/v1/opportunities/<id>` returns
aggregate authoritative availability only. It never exposes active hold rows or
Vendor data. Authenticated Vendors create one-unit holds at
`POST /api/v1/inventory-groups/<id>/reservations` and cancel them at
`POST /api/v1/reservations/<id>/cancel`.

Important supply changes write structured `SupplyAuditEvent` rows for
verification, publication, allocation, quota, and inventory-status changes.

## Migration And PostgreSQL Rehearsal

Migration `20261004_12` is additive after revision 11. It creates the supply
tables, makes legacy `booking.slot_id` nullable, and adds nullable
`booking.inventory_group_id` and `booking.vendor_category`. It does not delete
or transform Stall/Slot data. Downgrade refuses to proceed while an
inventory-based Booking exists.

PostgreSQL tests require a clearly disposable `TEST_DATABASE_URL` and explicit
`SPACIS_ALLOW_DESTRUCTIVE_POSTGRES_TESTS=1`. They create and drop a unique
schema, migrate a real baseline through revision 09, then migrate to head. They
never fall back to `DATABASE_URL`.
