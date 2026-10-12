"""Search vocabulary CLI; JSON input supports arbitrary article IDs without fact extraction."""

import json
from pathlib import Path
from typing import Annotated
from uuid import UUID

import typer
from sqlalchemy.exc import SQLAlchemyError

from app.contracts.discovery_search_vocabulary_v2 import (
    DiscoveryArticle,
    DiscoverySearchVocabularyV2,
    DiscoveryVocabularyInput,
)
from app.core.config import get_settings
from app.core.discovery_search_vocabulary import search_articles
from app.core.editorial import EditorialError
from app.infrastructure.db.session import SessionLocal
from app.orchestration.discovery_search_vocabulary import (
    DiscoveryVocabularyService,
    export_record,
    load_input,
    load_record,
    registered_articles,
)

vocabulary_app = typer.Typer(no_args_is_help=True, pretty_exceptions_show_locals=False)


def failure(exc: Exception) -> None:
    typer.echo(
        "discovery vocabulary failed: "
        + (exc.code if isinstance(exc, EditorialError) else type(exc).__name__),
        err=True,
    )
    raise typer.Exit(1) from None


@vocabulary_app.command("discover")
def discover(
    input_file: Annotated[Path | None, typer.Option("--input")] = None,
    item: Annotated[list[str] | None, typer.Option("--item")] = None,
    domain_hint: Annotated[str | None, typer.Option("--domain-hint")] = None,
    output: Annotated[Path | None, typer.Option("--output")] = None,
    call_budget: Annotated[int, typer.Option("--call-budget", min=1, max=2)] = 2,
) -> None:
    """Generate vocabulary only, using three to five extracted articles."""
    try:
        if bool(input_file) == bool(item):
            raise ValueError("supply either --input or three to five --item values")
        with SessionLocal() as session:
            if input_file:
                request = DiscoveryVocabularyInput.model_validate_json(
                    input_file.read_text(encoding="utf-8-sig")
                )
                if domain_hint is not None:
                    request = request.model_copy(update={"domain_hint": domain_hint})
            else:
                request = load_input(
                    session, tuple(UUID(value) for value in item or []), domain_hint
                )
            record = DiscoveryVocabularyService(session, get_settings()).discover(
                request, call_budget=call_budget
            )
            if output:
                export_record(record, output)
            typer.echo(
                json.dumps(
                    {
                        "run_id": str(record.run_id),
                        "status": record.status,
                        "error_code": record.error_code,
                        "vocabulary": record.vocabulary.model_dump(mode="json")
                        if record.vocabulary
                        else None,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            if record.status != "ready":
                raise typer.Exit(2)
    except (EditorialError, SQLAlchemyError, OSError, ValueError) as exc:
        failure(exc)


@vocabulary_app.command("show")
def show(run_id: str) -> None:
    """Display label, aliases, layer, priority and origin for every candidate."""
    try:
        with SessionLocal() as session:
            record = load_record(session, UUID(run_id))
        typer.echo("label\taliases\tlayer\tpriority\torigin")
        if record.vocabulary:
            for concept in record.vocabulary.concepts:
                typer.echo(
                    "\t".join(
                        (
                            concept.label,
                            " / ".join(concept.aliases),
                            concept.layer,
                            concept.priority,
                            concept.origin,
                        )
                    )
                )
        else:
            typer.echo(record.error_code)
            raise typer.Exit(2)
    except (EditorialError, SQLAlchemyError, ValueError) as exc:
        failure(exc)


@vocabulary_app.command("export")
def export(run_id: str, output: Annotated[Path, typer.Option("--output")]) -> None:
    """Export vocabulary JSON, candidate CSV and versioned audit without AI calls."""
    try:
        with SessionLocal() as session:
            record = load_record(session, UUID(run_id))
        export_record(record, output)
        typer.echo(str(output))
    except (EditorialError, SQLAlchemyError, OSError, ValueError) as exc:
        failure(exc)


@vocabulary_app.command("search")
def search(
    vocabulary_file: Annotated[Path, typer.Option("--vocabulary")],
    articles_file: Annotated[Path | None, typer.Option("--articles")] = None,
    registered: Annotated[bool, typer.Option("--registered")] = False,
    domain_filter: Annotated[bool, typer.Option("--domain-filter/--no-domain-filter")] = True,
    exclude: Annotated[list[str] | None, typer.Option("--exclude")] = None,
    output: Annotated[Path | None, typer.Option("--output")] = None,
) -> None:
    """Search title/body phrases; articles JSON is an array of extracted documents."""
    try:
        if bool(articles_file) == registered:
            raise ValueError("supply either --articles or --registered")
        vocabulary = DiscoverySearchVocabularyV2.model_validate_json(
            vocabulary_file.read_text(encoding="utf-8-sig")
        )
        if articles_file:
            payload = json.loads(articles_file.read_text(encoding="utf-8-sig"))
            if not isinstance(payload, list):
                raise ValueError("articles must be a JSON array")
            articles = tuple(DiscoveryArticle.model_validate(value) for value in payload)
            hits = search_articles(
                vocabulary,
                articles,
                require_domain=domain_filter,
                excluded_article_ids=exclude or [],
            )
        else:
            with SessionLocal() as session:
                hits = search_articles(
                    vocabulary,
                    registered_articles(session),
                    require_domain=domain_filter,
                    excluded_article_ids=exclude or [],
                )
        rendered = json.dumps(
            [hit.model_dump(mode="json") for hit in hits], ensure_ascii=False, indent=2
        )
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(rendered + "\n", encoding="utf-8")
        typer.echo(rendered)
    except (EditorialError, SQLAlchemyError, OSError, ValueError) as exc:
        failure(exc)
