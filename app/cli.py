from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.infrastructure.db.models import Source
from app.infrastructure.db.session import SessionLocal
from app.modules.acquisition.service import collect_source
from app.sources.config import load_sources
from app.sources.service import sync_sources

app = typer.Typer(no_args_is_help=True, pretty_exceptions_show_locals=False)
sources_app = typer.Typer(no_args_is_help=True, pretty_exceptions_show_locals=False)
app.add_typer(sources_app, name="sources")
collect_app = typer.Typer(no_args_is_help=True, pretty_exceptions_show_locals=False)
app.add_typer(collect_app, name="collect")


@sources_app.command("validate")
def validate_sources(
    path: Annotated[Path, typer.Argument(exists=True, readable=True)],
) -> None:
    try:
        config = load_sources(path)
    except (OSError, ValueError, ValidationError) as exc:
        typer.echo(f"invalid: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"valid: {len(config.sources)} source(s)")


@sources_app.command("sync")
def sync_source_file(
    path: Annotated[Path, typer.Argument(exists=True, readable=True)],
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
) -> None:
    try:
        config = load_sources(path)
    except (OSError, ValueError, ValidationError) as exc:
        typer.echo(f"invalid: {exc}", err=True)
        raise typer.Exit(1) from exc
    with SessionLocal.begin() as session:
        actions = sync_sources(session, config, dry_run=dry_run)
    for action in actions:
        typer.echo(f"{action.action}: {action.key} legal={action.legal_status}")
    if dry_run:
        typer.echo("dry-run: database unchanged")


@collect_app.command("run")
def run_collection(
    source: Annotated[
        str | None, typer.Option("--source", help="Synced source key; omit for all.")
    ] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="GET and preview; no database changes.")
    ] = False,
    force: Annotated[
        bool, typer.Option("--force", help="Ignore poll schedule, retaining rate limits.")
    ] = False,
) -> None:
    try:
        settings = get_settings()
        with SessionLocal() as session:
            keys = (
                [source]
                if source
                else list(session.scalars(select(Source.key).order_by(Source.key)))
            )
        failures = False
        if not keys:
            typer.echo("no sources registered; run sources sync first")
        for key in keys:
            with SessionLocal.begin() as session:
                result = collect_source(
                    session,
                    key,
                    dry_run=dry_run,
                    force=force,
                    github_token=settings.github_token.get_secret_value()
                    if settings.github_token
                    else None,
                )
            typer.echo(
                f"{result.source_key}: {result.status} created={result.created} "
                f"updated={result.updated} unchanged={result.unchanged}"
                + (f" error={result.error_code}" if result.error_code else "")
            )
            failures = (
                failures
                or result.status == "failed"
                or (source is not None and result.status == "blocked")
            )
        if dry_run:
            typer.echo("dry-run: database unchanged")
        if failures:
            raise typer.Exit(1)
    except SQLAlchemyError:
        typer.echo("collection failed: DATABASE_ERROR", err=True)
        raise typer.Exit(1) from None


if __name__ == "__main__":
    app()
