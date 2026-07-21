# MarketConnect API / Flask Backend

This folder contains the Flask backend for MarketConnect/Expoflow. It includes
both browser-facing web pages and JSON API routes, so the server can be deployed
as one self-contained Flask application.

The Flask backend was rewritten from the earlier Django monolith prototype in
`smart_market.zip`; the previous FastAPI implementation remains available in Git
history before this migration branch.

It preserves the prototype's main flows:

- landlord and tenant registration/login
- landlord stall publishing
- hourly slot pricing
- tenant stall search
- multi-slot booking with one QR code
- cash/card payment state
- booking history
- two-way reviews and reputation updates

For a detailed explanation of why HTML files live in this backend repo and how
the folders should be maintained, read [docs/PROJECT_STRUCTURE.md](docs/PROJECT_STRUCTURE.md).

## Run Locally

Recommended Conda env name: `Market_Connection`.

If the env already exists:

```bash
conda activate Market_Connection
pip install -r requirements.txt
flask --app app init-db
flask --app app seed-demo
flask --app app run
```

If the env needs to be recreated:

```bash
conda env create -f environment.yml
conda activate Market_Connection
flask --app app init-db
flask --app app seed-demo
flask --app app run
```

Open `http://127.0.0.1:5000`.

## Deploy On Render

When connecting the repository manually, use:

- Branch: `main`
- Root Directory: `market-connect-flask-server`
- Build Command: `pip install -r requirements.txt`
- Start Command: `flask --app app init-db && gunicorn --worker-tmp-dir /dev/shm --bind 0.0.0.0:$PORT app:app`
- Health Check Path: `/api/v1/health`

Set a production `SECRET_KEY`. For persistent data, set `DATABASE_URL` in
Render's Environment page to the database's Internal Database URL. Do not place
the connection string in source code or commit it to Git. The startup command
creates missing tables automatically. Without `DATABASE_URL`, SQLite data can be
lost whenever Render restarts or redeploys the service.

Alternative virtualenv setup:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
flask --app app init-db
flask --app app seed-demo
flask --app app run
```

Demo accounts after `seed-demo`:

- Tenant: `tenant1` / `tenant1_password`
- Landlord: `landlord1` / `landlord1_password`

## Structure

- `app.py`: thin compatibility entrypoint for `flask --app app ...`.
- `models.py`: compatibility re-export for older imports.
- `market_connect/`: application package.
- `market_connect/api/v1/`: JSON API routes under `/api/v1`.
- `market_connect/web/`: browser page routes for landlords and tenants.
- `market_connect/services/`: shared booking, payment, review, and seed logic.
- `market_connect/models.py`: SQLAlchemy models for users, stalls, slots, bookings, prices, and reviews.
- `templates/`: server-rendered frontend HTML files. They are frontend-facing,
  but they stay in this Flask backend repo because Flask renders them on the
  server with `render_template(...)`.
- `static/`: future CSS, JavaScript, images, and browser assets.
- `migrations/`: future database migrations.
- `fixtures/`: future seed/demo data files.
- `tests/`: smoke tests for the booking/payment flow.

## API Routes

- `GET /api/v1/health`: service health check.
- `GET /api/v1/stalls`: list stalls with available slots.
- `GET /api/v1/stalls/<stall_id>/slots`: list available slots for one stall.
- `POST /api/v1/bookings`: create a booking from JSON `user_id` and `slot_ids`.
- `GET /api/v1/bookings/<qr_code>`: fetch one QR-code booking group.
- `POST /api/v1/payments`: update payment state from JSON `qr_code` and `payment_method`.

## Notes

- This is still a prototype, not production authentication or payment code.
- SQLite is used by default at `instance/market_connect.db` and is local-only.
- `Booking.slot_id` is unique to prevent double-booking the same slot.
- Web routes and `/api/v1` routes intentionally live in the same backend repo so
  the team has one server to run, test, review, and deploy.
