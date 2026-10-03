from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import click
from flask import Flask

from .extensions import db
from .models import StallCertification
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

    @app.cli.command("list-stall-certifications")
    @click.option(
        "--status",
        type=click.Choice(["pending", "approved", "rejected", "all"]),
        default="pending",
        show_default=True,
    )
    def list_stall_certifications_command(status: str) -> None:
        query = StallCertification.query.order_by(StallCertification.submitted_at)
        if status != "all":
            query = query.filter_by(status=status)
        certifications = query.all()
        if not certifications:
            click.echo("No stall certifications found.")
            return

        for certification in certifications:
            evidence_host = urlsplit(certification.evidence_url).hostname or "invalid-url"
            click.echo(
                f"stall_id={certification.stall_id} "
                f"stall={certification.stall.loc_name!r} "
                f"owner={certification.stall.owner.username!r} "
                f"status={certification.status} "
                f"submitted={certification.submitted_at.isoformat()} "
                f"evidence_host={evidence_host}"
            )

    @app.cli.command("show-stall-certification")
    @click.argument("stall_id", type=int)
    def show_stall_certification_command(stall_id: int) -> None:
        certification = StallCertification.query.filter_by(stall_id=stall_id).first()
        if certification is None:
            raise click.ClickException("Certification not found for this stall.")
        click.echo(f"Stall: {certification.stall.loc_name} (ID {stall_id})")
        click.echo(f"Owner account: {certification.stall.owner.username}")
        click.echo(f"Status: {certification.status}")
        click.echo(f"Applicant: {certification.applicant_legal_name}")
        click.echo(f"Phone: {certification.applicant_phone}")
        click.echo(f"Relationship: {certification.relationship_to_space}")
        click.echo(f"Proof type: {certification.proof_type}")
        click.echo(f"Proof reference: {certification.proof_reference or '-'}")
        click.echo(f"Private evidence URL: {certification.evidence_url}")
        click.echo(f"Review note: {certification.review_note or '-'}")

    @app.cli.command("review-stall-certification")
    @click.argument("stall_id", type=int)
    @click.option(
        "--decision",
        type=click.Choice(["approve", "reject"]),
        required=True,
    )
    @click.option("--reviewer", required=True, help="Internal operator name or reference.")
    @click.option("--note", default="", help="Internal review note; required for rejection.")
    def review_stall_certification_command(
        stall_id: int,
        decision: str,
        reviewer: str,
        note: str,
    ) -> None:
        certification = StallCertification.query.filter_by(stall_id=stall_id).first()
        if certification is None:
            raise click.ClickException("Certification not found for this stall.")
        if decision == "reject" and not note.strip():
            raise click.ClickException("A review note is required when rejecting a stall.")
        if not reviewer.strip():
            raise click.ClickException("Reviewer reference cannot be blank.")

        certification.status = "approved" if decision == "approve" else "rejected"
        certification.reviewed_at = datetime.now(UTC)
        certification.reviewer_reference = reviewer.strip()
        certification.review_note = note.strip() or None
        db.session.commit()
        click.echo(
            f"Stall {stall_id} certification is now {certification.status}."
        )
