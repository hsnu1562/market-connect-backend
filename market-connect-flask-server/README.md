# MarketConnect API / Flask Backend

This folder contains the Flask backend for MarketConnect/Expoflow. It includes
both browser-facing web pages and JSON API routes, so the server can be deployed
as one self-contained Flask application.

The Flask backend was rewritten from the earlier Django monolith prototype. The
previous FastAPI implementation remains available on the `legacy/fastapi-api`
branch for the existing Swagger/documentation service.

It preserves the prototype's main flows:

- Google OIDC login with required first-login profile setup
- tenant and landlord roles on the same user account
- landlord stall publishing with manual certification approval
- hourly minimum-duration and indivisible full-day pricing
- tenant stall search
- multi-slot booking with one QR code
- cash/card payment state
- booking history
- two-way reviews and reputation updates

For a detailed explanation of why HTML files live in this backend repo and how
the folders should be maintained, read [docs/PROJECT_STRUCTURE.md](docs/PROJECT_STRUCTURE.md).
The import and review boundary for crawler data is documented in
[docs/DATA_MODEL.md](docs/DATA_MODEL.md).
The local-account and Google OIDC implementation plus the future LINE boundary
are documented in [docs/AUTHENTICATION.md](docs/AUTHENTICATION.md).
The private evidence and operator approval workflow is documented in
[docs/STALL_CERTIFICATION.md](docs/STALL_CERTIFICATION.md).

## Run Locally

Recommended Conda env name: `SPACIS`.

Quick start from this folder after the initial setup:

```bash
conda run -n SPACIS python -m flask --app app run --debug --port 5001
```

If the env already exists:

```bash
conda activate SPACIS
pip install -r requirements.txt
flask --app app init-db
flask --app app db upgrade
flask --app app seed-demo
flask --app app run --port 5001
```

If the env needs to be recreated:

```bash
conda env create -f environment.yml
conda activate SPACIS
flask --app app init-db
flask --app app db upgrade
flask --app app seed-demo
flask --app app run --port 5001
```

Open `http://127.0.0.1:5001`.

## Run Tests

With `SPACIS` activated and this folder as the current directory:

```bash
python -m pytest -q
```

The test suite uses temporary databases, so `init-db`, `seed-demo`, and a
production `DATABASE_URL` are not required before running it.

## Deploy On Render

When connecting the repository manually, use:

- Branch: `main`
- Root Directory: `market-connect-flask-server`
- Build Command: `pip install -r requirements.txt`
- Start Command: `flask --app app init-db && flask --app app db upgrade && gunicorn --worker-tmp-dir /dev/shm --bind 0.0.0.0:$PORT app:app`
- Health Check Path: `/api/v1/health`

Set all production variables listed in [docs/AUTHENTICATION.md](docs/AUTHENTICATION.md).
For persistent data, set `DATABASE_URL` in Render's Environment page to the
database's Internal Database URL. Do not place credentials in source code or
commit them to Git. The startup command creates missing tables and applies
tracked migrations automatically.
Without `DATABASE_URL`, SQLite data can be lost whenever Render restarts or
redeploys the service.

Alternative virtualenv setup:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
flask --app app init-db
flask --app app db upgrade
flask --app app seed-demo
flask --app app run --port 5001
```

Demo accounts after `seed-demo` are available only when
`LOCAL_AUTH_ENABLED=true`:

- Tenant: `tenant1` / `tenant1_password`
- Landlord: `landlord1` / `landlord1_password`

## Structure

- `app.py`: thin compatibility entrypoint for `flask --app app ...`.
- `models.py`: compatibility re-export for older imports.
- `market_connect/`: application package.
- `market_connect/api/v1/`: JSON API routes under `/api/v1`.
- `market_connect/web/`: browser page routes for landlords and tenants.
- `market_connect/services/`: shared booking, payment, review, and seed logic.
- `market_connect/models.py`: SQLAlchemy models for users, stalls,
  certifications, slots, bookings, prices, and reviews.
- `templates/`: server-rendered frontend HTML files. They are frontend-facing,
  but they stay in this Flask backend repo because Flask renders them on the
  server with `render_template(...)`.
- `static/`: browser assets, currently including the replaceable MVP favicon.
- `migrations/`: Flask-Migrate/Alembic database migrations.
- `fixtures/`: future seed/demo data files.
- `tests/`: smoke tests for the booking/payment flow.

## API Routes

- `GET /api/v1/health`: service health check.
- `GET /api/v1/stalls`: list stalls with available slots.
- `GET /api/v1/stalls/<stall_id>/slots`: list available slots for one stall.
- `POST /api/v1/bookings`: create a booking for the signed-in tenant from JSON `slot_ids`.
- `GET /api/v1/bookings/<qr_code>`: fetch one accessible QR-code booking group.
- `POST /api/v1/payments`: update the signed-in tenant's booking state from JSON `qr_code` and `payment_method`.

State-changing API calls require the signed-in Flask session and an
`X-CSRF-Token` header. Read-only stall routes remain public.

## Notes

- Google OIDC is the only production login method. Local username/password
  routes are disabled unless `LOCAL_AUTH_ENABLED=true`; use that switch only
  for local demo testing. LINE login, phone OTP, automated document validation,
  and payment-provider integration are not implemented yet.
- SQLite is used by default at `instance/market_connect.db` and is local-only.
- `Booking.slot_id` is unique to prevent double-booking the same slot.
- Web routes and `/api/v1` routes intentionally live in the same backend repo so
  the team has one server to run, test, review, and deploy.
