# MarketConnect Repo Structure

This repo is the Flask backend/server repo for MarketConnect. It contains both
backend logic and server-rendered frontend files.

## Why HTML Templates Are In The Backend Repo

`templates/` contains frontend-facing HTML pages. Users see these pages in the
browser, so they are part of the user interface.

They still belong in this backend repo because Flask renders them on the server:

```text
Browser request
  -> Flask route in market_connect/web/
  -> render_template("stalls.html")
  -> HTML response sent back to the browser
```

This is called server-rendered frontend. It is different from a separate React,
Vue, or Next.js frontend, where the frontend runs as its own app and usually has
its own repo.

## Folder Responsibilities

```text
market-connect-backend/
  market-connect-flask-server/
    app.py
    models.py
    market_connect/
      api/v1/
      web/
      services/
      security.py
      models.py
      extensions.py
    templates/
    static/
    docs/
    migrations/
    fixtures/
    tests/
    instance/
```

- `app.py`: Flask entrypoint used by `flask --app app ...`.
- `models.py`: compatibility re-export for older imports.
- `market_connect/api/v1/`: JSON API routes for clients such as LINE Bot, admin tools, or future mobile/web apps.
- `market_connect/web/`: Flask routes that render HTML pages from `templates/`.
- `market_connect/services/`: business logic shared by web routes and API routes.
- `market_connect/integrations/`: future external-service code, such as LINE Bot, payment, QR scanning, or notification adapters.
- `market_connect/models.py`: SQLAlchemy database models.
- `market_connect/extensions.py`: Flask extension objects for SQLAlchemy,
  Flask-Migrate, and Authlib.
- `templates/`: server-rendered frontend HTML files.
- `static/`: future CSS, JavaScript, images, and browser assets.
- `migrations/`: tracked Flask-Migrate/Alembic database migrations.
- `fixtures/`: future seed/demo data in JSON or CSV format.
- `tests/`: automated tests.
- `instance/`: local runtime files such as SQLite databases. This folder is ignored by Git and should not be pushed.

## Repo Boundaries

- `market-connect-backend`: owns the Flask server, HTML routes, JSON API routes, database models, migrations, tests, and deployment instructions.
- `market-connect-flask-server`: the deployable Flask service inside this repository. It owns `app.py`, `market_connect/`, templates, static assets, and service-level documentation.
- `market-connect-api`: the legacy FastAPI documentation service on the `legacy/fastapi-api` branch. It is not the active Flask source tree.
- `market-connect-utils`: owns crawlers, parsers, exporters, and import-preparation tools.
- `market-connect-docs`: product requirements and source documents that support the backend but are not served by Render.

## When To Create A Separate Frontend Repo

Do not create a frontend repo just because `templates/` contains HTML.

Create a separate frontend repo only if the team decides to build a standalone
frontend app, for example:

- React, Vue, Svelte, or Next.js app.
- Frontend deployed independently from Flask.
- Frontend talks to Flask only through `/api/v1`.

Until then, keeping `templates/` and future `static/` assets inside this Flask
repo is simpler and easier to deploy.

## Account Code

The first-party account flow is intentionally split by responsibility:

- `market_connect/web/auth.py`: browser routes for local login, Google OIDC,
  role activation, and logout.
- `market_connect/services/accounts.py`: User-table validation, registration, and password verification.
- `market_connect/services/identities.py`: external identity lookup and
  transactional Google account creation.
- `market_connect/security.py`: signed sessions, CSRF validation, and route ownership helpers.

Read [AUTHENTICATION.md](AUTHENTICATION.md) before changing Google OIDC or adding LINE Login.

## Database Policy

Do not push `instance/` or local `.db` / `.sqlite3` files.

Database structure should be tracked through:

- SQLAlchemy models in `market_connect/models.py`.
- Migration files in `migrations/`.
- Small documented seed files in `fixtures/` if needed.

Runtime database files are environment-specific state, not source code.
