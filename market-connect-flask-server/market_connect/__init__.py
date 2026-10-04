from __future__ import annotations

import os
from datetime import timedelta

from flask import Flask, jsonify, request, send_from_directory

from .api import register_api_blueprints
from .cli import register_cli
from .extensions import db, migrate, oauth
from .filters import register_template_filters
from .security import csrf_token, get_current_user, validate_csrf_token
from .web import register_web_blueprints


BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"
SERVICE_RELEASE = "20261004.10"


def _normalize_database_url(database_url: str) -> str:
    database_url = database_url.strip()
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgresql+psycopg2://"):
        return database_url.replace(
            "postgresql+psycopg2://",
            "postgresql+psycopg://",
            1,
        )
    return database_url


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def create_app(config: dict | None = None) -> Flask:
    app_env = os.environ.get("APP_ENV", "development").strip().lower()
    is_production = app_env == "production"
    app = Flask(
        __name__,
        instance_path=os.path.join(BASE_DIR, "instance"),
        instance_relative_config=True,
        static_folder=os.path.join(BASE_DIR, "static"),
        static_url_path="/static",
        template_folder=os.path.join(BASE_DIR, "templates"),
    )
    default_database_url = f"sqlite:///{os.path.join(app.instance_path, 'market_connect.db')}"
    app.config.from_mapping(
        APP_ENV=app_env,
        SECRET_KEY=os.environ.get("SECRET_KEY") or (
            None if is_production else "dev-market-connect-change-me"
        ),
        SQLALCHEMY_DATABASE_URI=os.environ.get("DATABASE_URL") or default_database_url,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        GOOGLE_CLIENT_ID=os.environ.get("GOOGLE_CLIENT_ID"),
        GOOGLE_CLIENT_SECRET=os.environ.get("GOOGLE_CLIENT_SECRET"),
        GOOGLE_REDIRECT_URI=os.environ.get("GOOGLE_REDIRECT_URI"),
        PUBLIC_BASE_URL=os.environ.get("PUBLIC_BASE_URL", "http://localhost:5001"),
        LOCAL_AUTH_ENABLED=_env_flag("LOCAL_AUTH_ENABLED"),
        PERMANENT_SESSION_LIFETIME=timedelta(days=7),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=is_production or _env_flag("SESSION_COOKIE_SECURE"),
        CSRF_PROTECT=True,
        MAX_CONTENT_LENGTH=24 * 1024 * 1024,
    )
    if config:
        app.config.update(config)

    if app.config.get("APP_ENV") == "production":
        app.config["SESSION_COOKIE_SECURE"] = True
        if not os.environ.get("SECRET_KEY") and not (config or {}).get("SECRET_KEY"):
            app.config["SECRET_KEY"] = None

    _validate_production_config(app)

    database_url = _normalize_database_url(app.config["SQLALCHEMY_DATABASE_URI"])
    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    if database_url.startswith("postgresql"):
        app.config.setdefault(
            "SQLALCHEMY_ENGINE_OPTIONS",
            {"pool_pre_ping": True, "pool_recycle": 300},
        )

    os.makedirs(app.instance_path, exist_ok=True)
    db.init_app(app)
    migrate.init_app(app, db, compare_type=True)
    oauth.init_app(app)
    oauth.register(
        name="google",
        client_id=app.config.get("GOOGLE_CLIENT_ID"),
        client_secret=app.config.get("GOOGLE_CLIENT_SECRET"),
        server_metadata_url=GOOGLE_DISCOVERY_URL,
        client_kwargs={"scope": "openid email profile"},
    )
    app.jinja_env.globals["csrf_token"] = csrf_token

    @app.context_processor
    def inject_member_navigation():
        return {"navigation_user": get_current_user()}

    @app.before_request
    def protect_state_changing_requests():
        if app.config["CSRF_PROTECT"] and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            validate_csrf_token()

    register_template_filters(app)
    register_cli(app)
    register_web_blueprints(app)
    register_api_blueprints(app)

    @app.get("/health")
    def health():
        return jsonify(
            {
                "release": SERVICE_RELEASE,
                "service": "market-connect-flask-server",
                "status": "ok",
            }
        )

    @app.get("/favicon.ico")
    def favicon():
        return send_from_directory(
            app.static_folder,
            "favicon.svg",
            mimetype="image/svg+xml",
            max_age=86400,
        )

    return app


def _validate_production_config(app: Flask) -> None:
    if app.config.get("APP_ENV") != "production":
        return

    required_keys = (
        "SECRET_KEY",
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "GOOGLE_REDIRECT_URI",
        "PUBLIC_BASE_URL",
    )
    missing = [key for key in required_keys if not app.config.get(key)]
    if missing:
        joined_keys = ", ".join(missing)
        raise RuntimeError(f"Missing required production configuration: {joined_keys}")
