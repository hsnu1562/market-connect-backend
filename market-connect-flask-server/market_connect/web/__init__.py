from __future__ import annotations

from flask import Flask

from .auth import bp as auth_bp
from .landlord import bp as landlord_bp
from .reviews import bp as reviews_bp
from .stalls import bp as stalls_bp


def register_web_blueprints(app: Flask) -> None:
    app.register_blueprint(auth_bp)
    app.register_blueprint(landlord_bp)
    app.register_blueprint(stalls_bp)
    app.register_blueprint(reviews_bp)
