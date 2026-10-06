from pathlib import Path
from typing import Annotated, cast

import typer
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.infrastructure.db.models import Source
from app.infrastructure.db.session import SessionLocal
from app.modules.acquisition.service import collect_source
from app.orchestration.phase2 import process_phase2
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
            if not dry_run and result.status in {"success", "not_modified"}:
                with SessionLocal.begin() as session:
                    process_phase2(session)
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


pipeline_app = typer.Typer(no_args_is_help=True, pretty_exceptions_show_locals=False)
app.add_typer(pipeline_app, name="pipeline")


@pipeline_app.command("run")
def run_pipeline(limit: Annotated[int, typer.Option(min=1, max=1000)] = 100) -> None:
    try:
        with SessionLocal.begin() as session:
            counts = process_phase2(session, limit=limit)
        typer.echo(
            f"processed: extraction={counts['extraction']} deduplication={counts['deduplication']}"
        )
    except (SQLAlchemyError, ValueError):
        typer.echo("pipeline failed: PROCESSING_ERROR", err=True)
        raise typer.Exit(1) from None


auth_app = typer.Typer(no_args_is_help=True, pretty_exceptions_show_locals=False)
app.add_typer(auth_app, name="auth")


@auth_app.command("create-user")
def create_api_identity(
    name: Annotated[str, typer.Option()],
    role: Annotated[
        list[str], typer.Option(help="Repeat viewer/editor/reviewer/publisher as needed.")
    ],
) -> None:
    from app.api.auth import create_user
    from app.core.editorial import EditorialError

    if not role or any(r not in {"viewer", "editor", "reviewer", "publisher"} for r in role):
        typer.echo("invalid role", err=True)
        raise typer.Exit(1)
    try:
        with SessionLocal.begin() as session:
            user, token = create_user(session, name, role)
            user_id = user.id
        typer.echo(f"user_id: {user_id}")
        typer.echo("Bearer token (displayed once; keep private): " + token)
    except (SQLAlchemyError, EditorialError):
        typer.echo("user creation failed", err=True)
        raise typer.Exit(1) from None


@auth_app.command("revoke")
def revoke_api_identity(name: Annotated[str, typer.Option()]) -> None:
    from app.infrastructure.db.models import ApiUser

    with SessionLocal.begin() as session:
        user = session.scalar(select(ApiUser).where(ApiUser.name == name))
        if user is None:
            typer.echo("user not found", err=True)
            raise typer.Exit(1)
        user.active = False
    typer.echo("revoked")


editorial_app = typer.Typer(no_args_is_help=True, pretty_exceptions_show_locals=False)
app.add_typer(editorial_app, name="editorial")


@editorial_app.command("run")
def run_editorial(
    item: Annotated[str, typer.Option(help="Article UUID")],
    stage: Annotated[str, typer.Option()] = "facts",
    mode: Annotated[str, typer.Option()] = "rules",
    draft: Annotated[str | None, typer.Option()] = None,
) -> None:
    import json
    from uuid import UUID

    from app.core.editorial import EditorialError
    from app.orchestration.editorial import EditorialService
    from app.orchestration.editorial_jobs import EditorialJobRequest, Operation, execute_job

    if stage not in {
        "facts",
        "select",
        "comparison",
        "draft",
        "verify",
        "pipeline",
    } or mode not in {"rules", "ai"}:
        typer.echo("invalid stage or mode", err=True)
        raise typer.Exit(1)
    try:
        with SessionLocal.begin() as session:
            result = execute_job(
                EditorialService(session, get_settings()),
                cast(Operation, stage),
                UUID(item),
                EditorialJobRequest(
                    expected_version=1, mode=mode, draft_id=UUID(draft) if draft else None
                ),
            )
        typer.echo(json.dumps(result, ensure_ascii=False))
    except (EditorialError, ValueError) as exc:
        typer.echo(getattr(exc, "code", "INVALID_ARGUMENT"), err=True)
        raise typer.Exit(1) from None
    except SQLAlchemyError:
        typer.echo("DATABASE_ERROR", err=True)
        raise typer.Exit(1) from None


if __name__ == "__main__":
    app()
