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
market-connect-api/
  app.py
  models.py
  market_connect/
    api/v1/
    web/
    services/
    integrations/
    models.py
    extensions.py
  templates/
  static/
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
- `market_connect/extensions.py`: Flask extension objects such as `db`.
- `templates/`: server-rendered frontend HTML files.
- `static/`: future CSS, JavaScript, images, and browser assets.
- `migrations/`: future database migration files, probably managed by Flask-Migrate/Alembic.
- `fixtures/`: future seed/demo data in JSON or CSV format.
- `tests/`: automated tests.
- `instance/`: local runtime files such as SQLite databases. This folder is ignored by Git and should not be pushed.

## Repo Boundaries

- `market-connect-api`: owns the Flask server, HTML routes, JSON API routes, database models, migrations, tests, and deployment instructions.
- `market-connect-utils`: owns crawlers, parsers, exporters, and import-preparation tools.
- `market-connect-data`: local/reference data only. Do not treat raw SQLite files as the production database source.
- `market-connect-flask-server`: temporary staging copy only. After this Flask migration is accepted in `market-connect-api`, remove the staging copy to avoid duplicate backend code.

## When To Create A Separate Frontend Repo

Do not create a frontend repo just because `templates/` contains HTML.

Create a separate frontend repo only if the team decides to build a standalone
frontend app, for example:

- React, Vue, Svelte, or Next.js app.
- Frontend deployed independently from Flask.
- Frontend talks to Flask only through `/api/v1`.

Until then, keeping `templates/` and future `static/` assets inside this Flask
repo is simpler and easier to deploy.

## Database Policy

Do not push `instance/` or local `.db` / `.sqlite3` files.

Database structure should be tracked through:

- SQLAlchemy models in `market_connect/models.py`.
- Migration files in `migrations/` once migration tooling is added.
- Small documented seed files in `fixtures/` if needed.

Runtime database files are environment-specific state, not source code.
