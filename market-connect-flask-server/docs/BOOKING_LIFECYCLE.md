# Booking And Payment Lifecycle

## State Separation

Reservation state and payment state are independent.

Reservation lifecycle:

```text
HELD -> CONFIRMED
HELD -> EXPIRED
HELD -> CANCELLED
CONFIRMED -> CANCELLED
```

Payment lifecycle:

```text
PENDING -> PROCESSING -> VERIFIED
PENDING or PROCESSING -> FAILED
VERIFIED -> REFUNDED
```

The current application creates `HELD` reservations and `PENDING` payment
transactions. No public route can advance payment. A future provider adapter
must call the trusted payment service to start processing and may confirm the
reservation only after it verifies provider identity, transaction ID, amount,
and currency.

## Holds And Availability

`BOOKING_HOLD_SECONDS` controls the hold duration and defaults to 900 seconds
(15 minutes). It must be a positive integer. The setting is deliberately not
embedded in the model so a future payment method or organizer policy can choose
a different duration.

SPACIS has no background worker. It lazily expires overdue holds before public
availability, reservation, payment-status, and booking-history operations.
This keeps deployment simple, but a hold may remain stored as `HELD` until one
of those operations runs. Availability always performs expiration before it is
returned, so stale holds do not continue blocking inventory in normal use.

An active-slot partial unique index covers only `HELD` and `CONFIRMED` rows.
Together with slot row locking, an active-record check, and `IntegrityError`
fallback, this prevents two Vendors from receiving the same exclusive slot
while retaining expired and cancelled records for audit. A future capacity or
inventory-class design can replace this active-slot invariant with locked
capacity counters without combining payment state back into reservations.

## Historical Records

Migration `20261004_10` maps all existing bookings to `CONFIRMED` so deployment
does not unexpectedly reopen occupied inventory. It does not create payment
transactions for those rows. Existing `payment_status` and `payment_method`
columns are retained as legacy evidence and exposed by the model only as
`legacy_payment_status` and `legacy_payment_method`.

Consequently, an old `Paid` value is never `VERIFIED`. UI and API responses
identify rows without a payment transaction as `LEGACY_RECORDED` and describe
them as historical reservations whose payment was not provider-verified.

## PSP Integration Boundary

`market_connect/services/payments.py` is the minimal trusted boundary:

- `begin_payment(...)` changes `PENDING` to `PROCESSING` and records a provider.
- `verify_payment(...)` validates transaction ID, amount, currency, active hold,
  and transition order before atomically writing `VERIFIED` and `CONFIRMED`.
- Replay, expired-hold, wrong-amount, duplicate-transaction, and invalid-state
  transitions fail without confirming the reservation.

The browser payment page is intentionally disabled, and both compatibility
payment POST endpoints return HTTP 503. Do not expose these trusted service
functions directly as ordinary browser actions. A real integration must verify
signed server-to-server callbacks according to the selected PSP documentation,
must be idempotent, and must never store card numbers.
