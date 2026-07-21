from __future__ import annotations

import os

from flask import Flask

from .api import register_api_blueprints
from .cli import register_cli
from .extensions import db
from .filters import register_template_filters
from .web import register_web_blueprints


BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _normalize_database_url(database_url: str) -> str:
    database_url = database_url.strip()
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql://", 1)
    return database_url


def create_app(config: dict | None = None) -> Flask:
    app = Flask(
        __name__,
        instance_path=os.path.join(BASE_DIR, "instance"),
        instance_relative_config=True,
        template_folder=os.path.join(BASE_DIR, "templates"),
    )
    default_database_url = f"sqlite:///{os.path.join(app.instance_path, 'market_connect.db')}"
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-market-connect-change-me"),
        SQLALCHEMY_DATABASE_URI=os.environ.get("DATABASE_URL") or default_database_url,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    if config:
        app.config.update(config)

    database_url = _normalize_database_url(app.config["SQLALCHEMY_DATABASE_URI"])
    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    if database_url.startswith("postgresql"):
        app.config.setdefault(
            "SQLALCHEMY_ENGINE_OPTIONS",
            {"pool_pre_ping": True, "pool_recycle": 300},
        )

    os.makedirs(app.instance_path, exist_ok=True)
    db.init_app(app)
    register_template_filters(app)
    register_cli(app)
    register_web_blueprints(app)
    register_api_blueprints(app)
    return app
