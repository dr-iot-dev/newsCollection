"""CLI for category-led pair discovery and explicit checkpoint resumption."""

from pathlib import Path
from typing import Annotated
from uuid import UUID

import typer
from sqlalchemy.exc import SQLAlchemyError

from app.contracts.comparison_pair_discovery_v3 import PairDiscoveryRequest
from app.core.config import get_settings
from app.core.editorial import EditorialError
from app.infrastructure.db.session import SessionLocal
from app.orchestration.comparison_pair_discovery import (
    PairDiscoveryService,
    export_pair_run,
    load_pair_request,
)

pair_app = typer.Typer(no_args_is_help=True, pretty_exceptions_show_locals=False)


def execute(request: PairDiscoveryRequest, call_budget: int, output: Path | None) -> None:
    with SessionLocal() as session:
        state = PairDiscoveryService(session, get_settings()).run(request, call_budget=call_budget)
        session.commit()
        if output:
            export_pair_run(session, request.run_id, output)
        typer.echo(state.model_dump_json(indent=2))
        if state.status != "selection_passed":
            raise typer.Exit(2)


@pair_app.command("discover")
def discover(
    source: Annotated[str, typer.Option("--source")],
    output: Annotated[Path | None, typer.Option("--output")] = None,
    call_budget: Annotated[int, typer.Option("--call-budget", min=1, max=5000)] = 100,
    initial_count: Annotated[int, typer.Option("--initial-count", min=3, max=20)] = 10,
    maximum_documents: Annotated[int, typer.Option("--maximum-documents", min=3, max=100)] = 100,
) -> None:
    """Discover using a PR TIMES category source; save audit only."""
    try:
        execute(
            PairDiscoveryRequest(
                source_key=source, initial_count=initial_count, maximum_documents=maximum_documents
            ),
            call_budget,
            output,
        )
    except (EditorialError, SQLAlchemyError, OSError, ValueError) as exc:
        typer.echo(
            "pair discovery failed: "
            + (exc.code if isinstance(exc, EditorialError) else type(exc).__name__),
            err=True,
        )
        raise typer.Exit(1) from None


@pair_app.command("resume")
def resume(
    run_id: Annotated[str, typer.Argument()],
    output: Annotated[Path | None, typer.Option("--output")] = None,
    call_budget: Annotated[int, typer.Option("--call-budget", min=1, max=5000)] = 100,
) -> None:
    """Resume the same frozen category snapshot and pair/candidate order."""
    try:
        with SessionLocal() as session:
            request = load_pair_request(session, UUID(run_id))
        execute(request, call_budget, output)
    except (EditorialError, SQLAlchemyError, OSError, ValueError) as exc:
        typer.echo(
            "pair resume failed: "
            + (exc.code if isinstance(exc, EditorialError) else type(exc).__name__),
            err=True,
        )
        raise typer.Exit(1) from None


@pair_app.command("export")
def export(
    run_id: Annotated[str, typer.Argument()],
    output: Annotated[Path, typer.Option("--output")],
) -> None:
    """Export persisted stages, distances, coverage and the selected comparison."""
    try:
        with SessionLocal() as session:
            export_pair_run(session, UUID(run_id), output)
        typer.echo(str(output))
    except (EditorialError, SQLAlchemyError, OSError, ValueError) as exc:
        typer.echo(
            "pair export failed: "
            + (exc.code if isinstance(exc, EditorialError) else type(exc).__name__),
            err=True,
        )
        raise typer.Exit(1) from None
