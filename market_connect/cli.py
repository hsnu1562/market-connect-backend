from __future__ import annotations

from flask import Flask

from .extensions import db
from .services.seed import seed_demo_data


def register_cli(app: Flask) -> None:
    @app.cli.command("init-db")
    def init_db_command():
        with app.app_context():
            db.create_all()
        print("Initialized Flask SQLite database.")

    @app.cli.command("seed-demo")
    def seed_demo_command():
        with app.app_context():
            db.create_all()
            seed_demo_data()
        print("Seeded demo landlord, tenant, stall, and slots.")
