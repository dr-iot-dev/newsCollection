from pathlib import Path
from typing import Annotated, cast

import typer
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.discovery_vocabulary_cli import vocabulary_app
from app.dynamic_axes_cli import axes_app
from app.infrastructure.db.models import Source
from app.infrastructure.db.session import SessionLocal
from app.modules.acquisition.service import collect_source
from app.orchestration.phase2 import process_phase2
from app.pair_cli import pair_app
from app.sources.config import load_sources
from app.sources.service import sync_sources
from app.term_extraction_cli import extraction_app

app = typer.Typer(no_args_is_help=True, pretty_exceptions_show_locals=False)
sources_app = typer.Typer(no_args_is_help=True, pretty_exceptions_show_locals=False)
app.add_typer(sources_app, name="sources")
collect_app = typer.Typer(no_args_is_help=True, pretty_exceptions_show_locals=False)
app.add_typer(collect_app, name="collect")

app.add_typer(pair_app, name="comparison-pair")
app.add_typer(axes_app, name="comparison-axes")
app.add_typer(vocabulary_app, name="discovery-vocabulary")
app.add_typer(extraction_app, name="extraction")


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


comparison_app = typer.Typer(no_args_is_help=True, pretty_exceptions_show_locals=False)
app.add_typer(comparison_app, name="comparison")


@comparison_app.command("shadow")
def evaluate_comparison_shadow(
    item: Annotated[str, typer.Option("--item")],
    candidate: Annotated[list[str], typer.Option("--candidate")],
    output: Annotated[Path | None, typer.Option("--output")] = None,
    exclusion_baseline: Annotated[
        Path | None, typer.Option("--exclusion-baseline", exists=True, readable=True)
    ] = None,
) -> None:
    """Evaluate supplied registered sources, saving audit only; never send an article."""
    import json
    from uuid import UUID

    from app.contracts.comparison_selection_v1 import SourceExclusionBaselineV1
    from app.core.comparison_selection import render_selection_table
    from app.core.editorial import EditorialError
    from app.orchestration.comparison_selection import ComparisonSelectionService

    try:
        key, candidates = UUID(item), tuple(UUID(v) for v in candidate)
        baseline = (
            SourceExclusionBaselineV1.model_validate_json(
                exclusion_baseline.read_text(encoding="utf-8")
            )
            if exclusion_baseline
            else None
        )
        settings = get_settings().model_copy(update={"comparison_selection_mode": "shadow"})
        with SessionLocal() as session:
            service = ComparisonSelectionService(session, settings, checkpoint=True)
            try:
                audit = service.evaluate(key, candidates, baseline)
                session.commit()
            except EditorialError:
                session.commit()  # Preserve failed AI diagnostics and completed stages.
                raise
        report = audit.model_dump(mode="json")
        group = [
            e for e in audit.evaluations if e.product.product_key in audit.selected_product_keys
        ]
        report["comparison_table"] = render_selection_table(audit.plan.plan, group) if group else ""
        text = json.dumps(report, ensure_ascii=False, indent=2)
        if output:
            output.write_text(text + "\n", encoding="utf-8")
        else:
            typer.echo(text)
        if audit.outcome != "eligible":
            raise typer.Exit(2)
    except EditorialError as exc:
        typer.echo("comparison deferred: " + exc.code, err=True)
        raise typer.Exit(2) from None
    except (OSError, ValueError):
        typer.echo("comparison failed: INVALID_INPUT_OR_OUTPUT", err=True)
        raise typer.Exit(1) from None
    except SQLAlchemyError:
        typer.echo("comparison failed: DATABASE_ERROR", err=True)
        raise typer.Exit(1) from None


@comparison_app.command("discover")
def discover_comparison(
    seed: Annotated[str, typer.Option("--seed")],
    group_selection: Annotated[str, typer.Option("--group-selection")] = "keyword_mmr",
    semantic_profiles: Annotated[bool, typer.Option("--semantic-profiles")] = False,
    evidence_first: Annotated[bool, typer.Option("--evidence-first")] = False,
    exclude_group: Annotated[list[str] | None, typer.Option("--exclude-group")] = None,
    budget_id: Annotated[str | None, typer.Option("--budget-id")] = None,
    candidate: Annotated[list[str] | None, typer.Option("--candidate")] = None,
    purpose: Annotated[str | None, typer.Option("--purpose")] = None,
    mode: Annotated[str, typer.Option("--mode")] = "shadow",
    maximum_groups: Annotated[int, typer.Option("--maximum-groups", min=1, max=5)] = 3,
    maximum_api_calls: Annotated[int, typer.Option("--maximum-api-calls", min=1, max=30)] = 30,
    output: Annotated[Path | None, typer.Option("--output")] = None,
    exclusion_baseline: Annotated[
        Path | None, typer.Option("--exclusion-baseline", exists=True, readable=True)
    ] = None,
) -> None:
    """Jointly discover questions and source groups; save V2 audit only."""
    from uuid import UUID

    from app.contracts.comparison_discovery_v2 import ComparisonDiscoveryRequestV2
    from app.contracts.comparison_selection_v1 import SourceExclusionBaselineV1
    from app.core.editorial import EditorialError
    from app.orchestration.comparison_discovery import ComparisonDiscoveryService

    if mode != "shadow":
        typer.echo("discovery failed: SHADOW_MODE_REQUIRED", err=True)
        raise typer.Exit(1)
    try:
        request = ComparisonDiscoveryRequestV2(
            seed_item_id=UUID(seed),
            candidate_item_ids=tuple(UUID(v) for v in candidate or ()),
            budget_id=UUID(budget_id) if budget_id else None,
            group_selection=group_selection,
            semantic_profiles=semantic_profiles,
            evidence_first=evidence_first,
            excluded_group_item_ids=tuple(
                tuple(UUID(k) for k in value.split(",")) for value in exclude_group or ()
            ),
            editorial_intent=purpose,
            maximum_groups=maximum_groups,
            maximum_api_calls=maximum_api_calls,
        )
        baseline = (
            SourceExclusionBaselineV1.model_validate_json(
                exclusion_baseline.read_text(encoding="utf-8")
            )
            if exclusion_baseline
            else None
        )
        with SessionLocal() as session:
            service = ComparisonDiscoveryService(session, get_settings(), checkpoint=True)
            try:
                audit = service.discover(request, baseline)
                session.commit()
            except EditorialError:
                session.commit()
                raise
        text = audit.model_dump_json(indent=2)
        if output:
            output.write_text(text + "\n", encoding="utf-8")
        else:
            typer.echo(text)
        if audit.outcome != "eligible":
            raise typer.Exit(2)
    except EditorialError as exc:
        typer.echo("discovery deferred: " + exc.code, err=True)
        raise typer.Exit(2) from None
    except (OSError, ValueError):
        typer.echo("discovery failed: INVALID_INPUT_OR_OUTPUT", err=True)
        raise typer.Exit(1) from None
    except SQLAlchemyError:
        typer.echo("discovery failed: DATABASE_ERROR", err=True)
        raise typer.Exit(1) from None


drafts_app = typer.Typer(no_args_is_help=True, pretty_exceptions_show_locals=False)
app.add_typer(drafts_app, name="drafts")


@drafts_app.command("export")
def export_draft(
    draft_id: Annotated[str, typer.Argument()],
    output: Annotated[Path | None, typer.Option("--output")] = None,
    artifact_revision: Annotated[int, typer.Option("--artifact-revision", min=1)] = 1,
) -> None:
    from uuid import UUID

    from app.core.editorial import EditorialError
    from app.orchestration.draft_exports import DraftExporter
    from nw_generation.protocol import atomic_write

    try:
        with SessionLocal() as session:
            row = DraftExporter(session, get_settings()).export(
                UUID(draft_id), artifact_revision=artifact_revision
            )
            if output and row.file_path:
                atomic_write(output, Path(row.file_path).read_bytes())
            typer.echo(f"{row.id}: {row.state} {output or row.file_path}")
    except (EditorialError, OSError, ValueError, SQLAlchemyError) as exc:
        typer.echo(getattr(exc, "code", "EXPORT_FAILED"), err=True)
        raise typer.Exit(1) from None


@drafts_app.command("export-pending")
def export_pending(limit: Annotated[int, typer.Option(min=1, max=1000)] = 10) -> None:
    from app.orchestration.draft_exports import process_draft_exports

    with SessionLocal() as session:
        typer.echo(f"exported: {process_draft_exports(session, get_settings(), limit)}")


@drafts_app.command("preview")
def preview_draft(draft_id: Annotated[str, typer.Argument()]) -> None:
    from uuid import UUID

    from app.infrastructure.db.models import ArticleDraft

    with SessionLocal() as session:
        draft = session.get(ArticleDraft, UUID(draft_id))
        if draft is None:
            raise typer.BadParameter("draft not found")
        typer.echo(draft.title + "\n\n" + draft.lead + "\n\n" + draft.body_markdown)


@drafts_app.command("approve-image")
def approve_draft_image(
    export_id: Annotated[str, typer.Argument()],
    reviewer_id: Annotated[str, typer.Option("--reviewer")],
    expected_image_hash: Annotated[str, typer.Option("--expected-image-hash")],
) -> None:
    from uuid import UUID

    from app.orchestration.draft_exports import approve_export_image

    with SessionLocal() as session:
        row = approve_export_image(
            session, get_settings(), UUID(export_id), UUID(reviewer_id), expected_image_hash
        )
        typer.echo(f"{row.id}: image approved")


@drafts_app.command("retry-image")
def retry_draft_image(
    draft_id: Annotated[str, typer.Argument()],
    confirmed_generation_stopped: Annotated[
        bool, typer.Option("--confirmed-generation-stopped")
    ] = False,
) -> None:
    from uuid import UUID

    from app.infrastructure.db.models import DraftAsset

    if not confirmed_generation_stopped:
        raise typer.BadParameter("confirm previous generation has stopped before retry")
    with SessionLocal.begin() as session:
        asset = session.scalar(
            select(DraftAsset).where(DraftAsset.draft_id == UUID(draft_id)).with_for_update()
        )
        if asset is None or asset.state not in {"uncertain", "generating"}:
            raise typer.BadParameter("no unresolved image generation")
        if asset.attempt >= get_settings().ai_image_max_attempts:
            raise typer.BadParameter("image generation attempt budget exhausted")
        asset.state, asset.last_error = "prepared", None
    typer.echo("image retry permitted; run drafts export to continue")


@drafts_app.command("export-history")
def export_delivery_history(
    target_id: Annotated[str, typer.Option("--target")],
    output: Annotated[Path, typer.Option("--output")],
) -> None:
    from app.orchestration.delivery_history import export_history

    with SessionLocal() as session:
        count = export_history(session, get_settings(), target_id, output)
        typer.echo(f"historical deliveries: {count}")


if __name__ == "__main__":
    app()
