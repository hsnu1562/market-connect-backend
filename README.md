# MarketConnect Backend Workspace

This repository keeps the current Flask backend, project reference data, and
planning documents together while preserving clear deployment boundaries.

## Repository Layout

- `market-connect-flask-server/`: the deployable Flask web application and JSON API.
- `market-connect-data/`: local reference data from the earlier Django prototype.
- `market-connect-docs/`: product planning and project reference documents.
- `render.yaml`: Render Blueprint for the Flask service on `main`.

Only `market-connect-flask-server/` is an executable service. The data and docs
folders are references and are not included in the Render runtime because the
service uses that folder as its Root Directory.

## Render Services

### Current Flask Backend

Use these settings for the new backend service:

- Repository: `https://github.com/hsnu1562/market-connect-backend`
- Branch: `main` after the backend monorepo pull request is merged
- Root Directory: `market-connect-flask-server`
- Runtime: Python
- Build Command: `pip install -r requirements.txt`
- Start Command: `flask --app app init-db && gunicorn --worker-tmp-dir /dev/shm --bind 0.0.0.0:$PORT app:app`
- Health Check Path: `/api/v1/health`

The root `render.yaml` contains the same configuration for creating a Render
Blueprint-managed service.

Set `DATABASE_URL` in Render's Environment page using the database's Internal
Database URL when the web service and database are in the same Render region.
Never commit the URL because it contains database credentials. The start command
runs `flask --app app init-db`, which creates any missing tables before Gunicorn
starts serving requests.

### Legacy FastAPI Documentation Service

The existing Swagger service must not deploy `main`. It should use:

- Repository: `https://github.com/hsnu1562/market-connect-backend`
- Branch: `legacy/fastapi-api`
- Root Directory: leave blank
- Build Command: `pip install -r requirements.txt`
- Start Command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- Health Check Path: `/`
- Swagger UI: `/docs`

The legacy branch is frozen from commit `db72902`. New backend development
belongs on `main`; do not merge legacy FastAPI code back into `main`.

## Database Policy

SQLite databases under `instance/` and `market-connect-data/db.sqlite3` are
ignored local files. They are useful for development and historical inspection,
but they are not production databases and must not be committed.

For persistent Render deployments, set `DATABASE_URL` to a managed PostgreSQL
connection string in Render's Environment page. If the service is created from
`render.yaml`, Render prompts for this secret during the initial Blueprint setup.
Without it, the Flask service uses local SQLite and Render can discard that data
during restarts or deployments.
