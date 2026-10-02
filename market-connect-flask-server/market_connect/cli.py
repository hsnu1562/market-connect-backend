from __future__ import annotations

from pathlib import Path

import click
from flask import Flask

from .extensions import db
from .services.market_leads import import_market_leads_from_file
from .services.seed import seed_demo_data


def register_cli(app: Flask) -> None:
    @app.cli.command("init-db")
    def init_db_command():
        with app.app_context():
            db.create_all()
        print("Initialized application database.")

    @app.cli.command("seed-demo")
    def seed_demo_command():
        with app.app_context():
            db.create_all()
            seed_demo_data()
        print("Seeded demo landlord, tenant, stall, and slots.")

    @app.cli.command("import-market-leads")
    @click.option(
        "--file",
        "input_path",
        required=True,
        type=click.Path(exists=True, dir_okay=False, path_type=Path),
        help="Structured JSON output from market-connect-utils.",
    )
    @click.option("--source-name", default="168market", show_default=True)
    @click.option("--limit", type=click.IntRange(min=1))
    @click.option("--test", "test_mode", is_flag=True, help="Mark imported leads as test data.")
    def import_market_leads_command(
        input_path: Path,
        source_name: str,
        limit: int | None,
        test_mode: bool,
    ) -> None:
        with app.app_context():
            db.create_all()
            result = import_market_leads_from_file(
                input_path,
                source_name=source_name,
                limit=limit,
                test_mode=test_mode,
            )
        click.echo(
            "Imported market leads: "
            f"batch={result.batch_id}, processed={result.processed_count}, "
            f"created={result.created_count}, updated={result.updated_count}, "
            f"skipped={result.skipped_count}."
        )
