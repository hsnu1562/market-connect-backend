# SPACIS Authentication

SPACIS uses Google OpenID Connect (OIDC) as its production login method. Stall
information is public. Authentication is required only when a visitor reserves
a stall, publishes a stall, or opens account-owned records.

After the first successful Google callback, the user must complete a profile
sheet before entering protected tools. First and last names are required. A
phone number is optional, unverified, and never accepted as a login method.

One user can hold both roles:

- `Tenant`: reserve stalls and manage bookings.
- `Landlord`: publish stalls and manage received bookings.

Choosing a role-specific login entry grants that role after successful
authentication. It does not create a second user.

## Code Ownership

```text
market_connect/
  web/auth.py                 Google, profile, and optional local browser routes
  services/accounts.py       profile validation and role membership
  services/identities.py     external identity find-or-create transaction
  security.py                session, CSRF, and authorization helpers
  models.py                  User, UserRole, and AuthIdentity
  extensions.py              SQLAlchemy, Flask-Migrate, and Authlib
migrations/                  tracked Alembic migrations
templates/account.html       Google-only role-aware account entry
templates/profile_setup.html first-login and profile editing sheet
```

The sibling `market-connect-api` checkout is the frozen FastAPI documentation
service. Do not implement Flask authentication there.

## Routes

- `GET /account/`: select or activate tenant/provider tools.
- `GET, POST /register/<role>`: optional local development registration; disabled by default.
- `GET, POST /login/<role>`: optional local development login; disabled by default.
- `GET /auth/google/login?role=<role>`: begin Google authorization.
- `GET /auth/google/callback`: validate OIDC identity and create the session.
- `GET, POST /account/profile`: complete or edit the SPACIS profile.
- `POST /account/roles/<role>`: add a second role to a signed-in account.
- `POST /logout`: clear the SPACIS session.

Google logout does not sign the user out of Google globally.

## Identity Data

`user` stores the SPACIS profile. `profile_completed_at` is null until a Google
user submits the required profile sheet. `password_hash` is null for
Google-only accounts. The original `role` column remains as a primary/legacy
role so existing data and templates remain compatible.

`user_role` stores all account roles with a composite primary key of
`(user_id, role)`.

`auth_identity` stores:

- `user_id`
- `provider`
- `provider_subject`
- email and verification state
- display name and picture URL
- creation and last-login timestamps

The unique `(provider, provider_subject)` constraint prevents duplicate Google
identities. Google's stable `sub` claim is `provider_subject`. Email is profile
data and is never used to merge or identify accounts. Access, ID, and refresh
tokens are not stored.

## Environment Variables

Copy `.env.example` to `.env` in the backend repository root for local use.
Never commit `.env`.

```text
APP_ENV=development
SECRET_KEY=<fixed-long-random-value>
DATABASE_URL=<optional-local-or-PostgreSQL-URL>
GOOGLE_CLIENT_ID=<Google-web-client-ID>
GOOGLE_CLIENT_SECRET=<Google-web-client-secret>
GOOGLE_REDIRECT_URI=http://localhost:5001/auth/google/callback
PUBLIC_BASE_URL=http://localhost:5001
LOCAL_AUTH_ENABLED=false
```

`SECRET_KEY` must stay unchanged across restarts because OAuth state is stored
in the signed Flask session. Production startup fails clearly when any required
Google setting or `SECRET_KEY` is absent. Do not log or paste secret values.

Production automatically uses:

```text
SESSION_COOKIE_SECURE=true
SESSION_COOKIE_HTTPONLY=true
SESSION_COOKIE_SAMESITE=Lax
PERMANENT_SESSION_LIFETIME=7 days
```

Development keeps `SESSION_COOKIE_SECURE=false` so local HTTP works.

## Google Cloud Setup

Create an OAuth client with application type **Web application**. Configure the
OAuth consent screen and add your Google account as a test user if the app is
still in testing mode.

Authorized JavaScript origins:

```text
http://localhost:5001
https://spacis.onrender.com
```

Authorized redirect URIs:

```text
http://localhost:5001/auth/google/callback
https://spacis.onrender.com/auth/google/callback
```

The redirect URI must match exactly, including scheme, host, port, path, and
trailing-slash behavior. SPACIS requests only `openid email profile`.

When the public app moves to `https://spacis.arcory.net`, add:

```text
https://spacis.arcory.net
https://spacis.arcory.net/auth/google/callback
```

Then change only `PUBLIC_BASE_URL` and `GOOGLE_REDIRECT_URI`; no source change
is required.

Google setup reference:
[Google OpenID Connect](https://developers.google.com/identity/openid-connect/openid-connect).

## Local Run

From `market-connect-backend/`:

```bash
conda activate SPACIS
python -m pip install -r market-connect-flask-server/requirements.txt
python -m flask --app market-connect-flask-server/app.py init-db
python -m flask --app market-connect-flask-server/app.py db upgrade
python -m flask --app market-connect-flask-server/app.py run --debug --port 5001
```

Open `http://localhost:5001/account/`. A real Google callback requires the local
redirect URI in Google Cloud and valid local client credentials.

## Render Setup

Configure these in the existing Render service before deploying OAuth code:

```text
APP_ENV=production
SECRET_KEY=<fixed-secret>
DATABASE_URL=<Render-PostgreSQL-internal-URL>
GOOGLE_CLIENT_ID=<Google-web-client-ID>
GOOGLE_CLIENT_SECRET=<Google-web-client-secret>
GOOGLE_REDIRECT_URI=https://spacis.onrender.com/auth/google/callback
PUBLIC_BASE_URL=https://spacis.onrender.com
```

Render service settings:

```text
Root Directory: market-connect-flask-server
Build Command: pip install -r requirements.txt
Start Command: flask --app app init-db && flask --app app db upgrade && gunicorn --worker-tmp-dir /dev/shm --bind 0.0.0.0:$PORT app:app
Health Check Path: /api/v1/health
```

For an existing Blueprint service, variables marked `sync: false` in
`render.yaml` must be added manually in Render. Do this before deploying because
`APP_ENV=production` enables strict startup validation.

## Database Migration

The tracked authentication migrations:

- makes `user.password_hash` nullable for Google-only users;
- adds account status and profile timestamps;
- creates `user_role` and backfills every existing user's current role;
- creates `auth_identity` with a provider/subject uniqueness constraint.
- adds `profile_completed_at` and marks existing non-Google accounts complete.

Run `init-db` before `db upgrade` during this transitional migration. The
tracked migration handles both the existing PostgreSQL schema and a fresh local
database.

## Testing

From `market-connect-flask-server/`:

```bash
conda run -n SPACIS python -m pytest -q
```

OAuth tests mock Authlib and never contact Google. For a manual production
check, confirm account selection, callback, role-specific dashboard access,
refresh persistence, and POST logout. `/health` and `/api/v1/health` do not
depend on Google connectivity.

## Security Rules

- Authlib validates OAuth state and the OIDC ID token.
- Only verified identities containing `sub`, `email`, and
  `email_verified=true` are accepted.
- Sessions contain only the internal `user_id` plus Flask's permanence marker.
- Incomplete Google profiles are redirected to `/account/profile` before any
  protected tenant or provider workflow.
- Phone numbers are optional contact data. They are not verified identities and
  cannot be used to authenticate.
- Role membership never bypasses booking or stall ownership checks.
- Accounts are not merged by email or display name.
- Linking Google or LINE to an existing local account requires a future,
  explicit authenticated linking flow.
- Client secrets and tokens never reach frontend JavaScript or application logs.
