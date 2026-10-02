from __future__ import annotations

from flask import Flask

from .v1.routes import bp as api_v1_bp


def register_api_blueprints(app: Flask) -> None:
    app.register_blueprint(api_v1_bp)
