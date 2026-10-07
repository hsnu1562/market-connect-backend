# MarketConnect Backend Workspace

This repository keeps the current Flask backend, project reference data, and
planning documents together while preserving clear deployment boundaries.

## Repository Layout

- `market-connect-flask-server/`: the deployable Flask web application and JSON API.
- `market-connect-docs/`: product planning and project reference documents.
- `render.yaml`: Render Blueprint for the Flask service on `main`.

Only `market-connect-flask-server/` is an executable service. The documents
folder is reference material and is not included in the Render runtime because
the service uses the Flask folder as its Root Directory.

## Run And Test Locally

After dependencies and the local database have been initialized once, start the
real Flask application from the repository root with one command:

```bash
conda run -n SPACIS python -m flask --app market-connect-flask-server/app.py run --debug --port 5001
```

This is the Flask equivalent of `py -m http.server`. Do not use
`py -m http.server` for this project because it cannot execute Flask routes,
database queries, login, or booking logic.

From the repository root, enter the Flask service and activate its Conda
environment:

```bash
cd market-connect-flask-server
conda activate SPACIS
python -m pip install -r requirements.txt
```

Initialize the local SQLite database and add the demo accounts and stall:

```bash
python -m flask --app app init-db
python -m flask --app app db upgrade
python -m flask --app app seed-demo
```

Start the local development server:

```bash
python -m flask --app app run --debug --port 5001
```

Open `http://127.0.0.1:5001`. Stop the server with `Ctrl+C`.

Run the automated test suite from `market-connect-flask-server/`:

```bash
python -m pytest -q
```

The tests use temporary databases and do not require the Render PostgreSQL
connection. The Gunicorn command below is for Render's Linux environment; do
not use it as the normal Windows local-development command.

## Render Services

### Current Flask Backend

Use these settings for the new backend service:

- Repository: `https://github.com/hsnu1562/market-connect-backend`
- Branch: `main` after the backend monorepo pull request is merged
- Root Directory: `market-connect-flask-server`
- Runtime: Python
- Build Command: `pip install -r requirements.txt`
- Start Command: `flask --app app init-db && flask --app app db upgrade && gunicorn --worker-tmp-dir /dev/shm --bind 0.0.0.0:$PORT app:app`
- Health Check Path: `/api/v1/health`

The root `render.yaml` contains the same configuration for creating a Render
Blueprint-managed service.

Set `DATABASE_URL` in Render's Environment page using the database's Internal
Database URL when the web service and database are in the same Render region.
Never commit the URL because it contains database credentials. The start command
runs `init-db` followed by `db upgrade`, which creates missing tables and then
applies tracked schema migrations before Gunicorn starts serving requests.

For account sessions and Google login, configure `APP_ENV`, `SECRET_KEY`,
`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`, and
`PUBLIC_BASE_URL` in Render before deploying. The active account flow lives in
`market-connect-flask-server/market_connect/web/auth.py`; see
[market-connect-flask-server/docs/AUTHENTICATION.md](market-connect-flask-server/docs/AUTHENTICATION.md)
for exact local, Google Cloud, and Render setup.

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

SQLite databases under `market-connect-flask-server/instance/` are ignored local
runtime files. They can be recreated with `flask --app app init-db` and must not
be committed.

For persistent Render deployments, set `DATABASE_URL` to a managed PostgreSQL
connection string in Render's Environment page. If the service is created from
`render.yaml`, Render prompts for this secret during the initial Blueprint setup.
Without it, the Flask service uses local SQLite and Render can discard that data
during restarts or deployments.
