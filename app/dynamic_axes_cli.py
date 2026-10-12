"""Explicit shadow commands for a supplied group of registered releases."""

import json
from pathlib import Path
from typing import Annotated
from uuid import UUID

import typer
from sqlalchemy.exc import SQLAlchemyError

from app.contracts.comparison_dynamic_axes_v1 import DynamicAxesRequest
from app.core.config import get_settings
from app.core.editorial import EditorialError
from app.infrastructure.db.session import SessionLocal
from app.orchestration.comparison_dynamic_axes import (
    DynamicAxesService,
    export_run,
    load_documents,
    load_request,
)

axes_app = typer.Typer(no_args_is_help=True, pretty_exceptions_show_locals=False)


def execute(request: DynamicAxesRequest, call_budget: int, output: Path | None) -> None:
    with SessionLocal() as session:
        state = DynamicAxesService(session, get_settings()).run(request, call_budget=call_budget)
        if output:
            export_run(session, request.run_id, output)
        typer.echo(
            json.dumps(
                {
                    "run_id": str(request.run_id),
                    **state.model_dump(
                        mode="json", exclude={"request", "stages", "values", "candidates"}
                    ),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        if state.status not in {"selection_passed", "candidates_ready"}:
            raise typer.Exit(2)


def failure(exc: Exception) -> None:
    typer.echo(
        "dynamic axes failed: "
        + (exc.code if isinstance(exc, EditorialError) else type(exc).__name__),
        err=True,
    )
    raise typer.Exit(1) from None


@axes_app.command("discover")
def discover(
    item: Annotated[list[str], typer.Option("--item")],
    output: Annotated[Path | None, typer.Option("--output")] = None,
    editorial_intent: Annotated[str, typer.Option("--editorial-intent")] = "",
    call_budget: Annotated[int, typer.Option("--call-budget", min=1, max=100)] = 20,
    discovery_only: Annotated[bool, typer.Option("--discovery-only")] = False,
) -> None:
    """Analyze three to five registered releases; save comparison material only."""
    try:
        with SessionLocal() as session:
            documents = load_documents(session, tuple(UUID(value) for value in item))
        execute(
            DynamicAxesRequest(
                documents=documents,
                editorial_intent=editorial_intent,
                mode="discovery_only" if discovery_only else "shadow",
            ),
            call_budget,
            output,
        )
    except (EditorialError, SQLAlchemyError, OSError, ValueError) as exc:
        failure(exc)


@axes_app.command("resume")
def resume(
    run_id: str,
    output: Annotated[Path | None, typer.Option("--output")] = None,
    call_budget: Annotated[int, typer.Option("--call-budget", min=1, max=100)] = 20,
) -> None:
    """Resume the same documents, candidates and model configuration."""
    try:
        with SessionLocal() as session:
            request = load_request(session, UUID(run_id))
        execute(request, call_budget, output)
    except (EditorialError, SQLAlchemyError, OSError, ValueError) as exc:
        failure(exc)


@axes_app.command("export")
def export(run_id: str, output: Annotated[Path, typer.Option("--output")]) -> None:
    """Export audit, coverage and verified comparison material."""
    try:
        with SessionLocal() as session:
            export_run(session, UUID(run_id), output)
        typer.echo(str(output))
    except (EditorialError, SQLAlchemyError, OSError, ValueError) as exc:
        failure(exc)
