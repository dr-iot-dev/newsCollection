"""Bounded source refresh, verified comparison retrieval and resumable research work."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

import structlog
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.comparison_analysis_v1 import ComparisonAnalysisV1
from app.contracts.content_v1 import NormalizedContentV1
from app.contracts.editorial_v1 import ResearchRequestV1
from app.contracts.envelope import canonical_payload_hash
from app.core.config import Settings
from app.core.editorial import EditorialError
from app.infrastructure.db.models import (
    ArticleDraft,
    ExtractionResult,
    Item,
    ItemStatus,
    JobRun,
    ModuleMessage,
    Source,
)
from app.modules.acquisition.http import CollectionError
from app.modules.acquisition.service import collect_source, source_config
from app.modules.research.service import POLICY_VERSION, topic_reasons, utc
from app.modules.selection.service import rule_selection
from app.orchestration.comparison_analysis import (
    SELECTION_CRITERIA,
    assess_candidate,
    record_contract,
    topic_for_item,
)
from app.orchestration.editorial import (
    EditorialService,
    checked_payload,
    eligible,
    item_for_update,
    latest,
)
from app.orchestration.phase2 import process_phase2

logger = structlog.get_logger()
PROTECTED = {
    ItemStatus.APPROVED,
    ItemStatus.WP_DRAFTED,
    ItemStatus.PUBLISH_APPROVED,
    ItemStatus.PUBLISHED,
}


@dataclass(frozen=True)
class ResearchPreparation:
    previous_ids: tuple[UUID, ...]
    competitor_ids: tuple[UUID, ...]
    request_ids: tuple[UUID, ...] = ()
    pending: bool = False


def has_active_comparison_job(session: Session, item_id: UUID) -> bool:
    return (
        session.scalar(
            select(JobRun.id)
            .where(
                JobRun.job_type == "phase3",
                JobRun.status.in_(["queued", "running", "waiting_research"]),
                JobRun.stats_json["item_id"].as_string() == str(item_id),
                JobRun.stats_json["operation"].as_string().in_(["pipeline", "comparison"]),
            )
            .limit(1)
        )
        is not None
    )


def approved_sources(session: Session) -> list[Source]:
    sources = []
    for row in session.scalars(select(Source).where(Source.enabled.is_(True)).order_by(Source.key)):
        try:
            source_config(row).assert_collectable()
        except (PermissionError, CollectionError):
            continue
        sources.append(row)
    return sources


def current_content(session: Session, item: Item) -> NormalizedContentV1:
    row = session.scalar(
        select(ExtractionResult).where(
            ExtractionResult.item_id == item.id, ExtractionResult.revision == item.version
        )
    )
    if row is None:
        raise EditorialError("EXTRACTION_REQUIRED")
    try:
        return cast(NormalizedContentV1, checked_payload(row, NormalizedContentV1))
    except ValidationError:
        raise EditorialError("EXTRACTION_INVALID") from None


def search_catalog(
    service: EditorialService, request: ResearchRequestV1, result: dict[str, Any]
) -> tuple[UUID, ...]:
    session = service.session
    target = item_for_update(session, request.item_id)
    eligible(session, target)
    _, target_evidence = service.evidence(target)
    target_topic = topic_for_item(service, target)
    rows = session.execute(
        select(Item, ExtractionResult)
        .join(Source, Source.id == Item.source_id)
        .join(
            ExtractionResult,
            (ExtractionResult.item_id == Item.id) & (ExtractionResult.revision == Item.version),
        )
        .where(
            Item.id != target.id,
            Item.duplicate_of_id.is_(None),
            Source.key.in_(request.approved_source_keys),
            Source.enabled.is_(True),
            Item.status.not_in(
                [ItemStatus.REJECTED, ItemStatus.BLOCKED_RIGHTS, ItemStatus.PUBLISHED]
            ),
        )
        .order_by(Item.published_at.desc().nulls_last(), Item.id)
        .limit(service.settings.research_max_candidates)
    ).all()
    ranked = []
    rejected = list(result.get("rejected", []))
    assessments = {}
    for item, row in rows:
        try:
            eligible(session, item)
            content = checked_payload(row, NormalizedContentV1)
            if content.quality_score < 0.6:
                rejected.append(
                    {"item_id": str(item.id), "code": "REFERENCE_EXTRACTION_QUALITY_LOW"}
                )
                continue
            assessment = assess_candidate(
                service, target, target_evidence, target_topic, item, request.relation
            )
        except (EditorialError, ValidationError):
            rejected.append(
                {"item_id": str(item.id), "code": "REFERENCE_SOURCE_OR_EXTRACTION_INVALID"}
            )
            continue
        assessments[str(item.id)] = assessment
        reasons = topic_reasons(assessment.selection_checks)
        if reasons:
            rejected.append({"item_id": str(item.id), "code": reasons[0]})
            continue
        ranked.append((assessment.score, item))
    ranked.sort(key=lambda value: (-value[0], str(value[1].id)))
    checked = dict(result.get("checked_item_versions", {}))
    selected = []
    for rank, (score, item) in enumerate(ranked, start=1):
        revision_key = str(item.id) + ":" + str(item.version)
        try:
            row, evidence = service.evidence(item)
        except (EditorialError, ValidationError):
            row, evidence = None, None
        if evidence is None or rule_selection(evidence).decision != "selected":
            if revision_key in checked or len(checked) >= service.settings.research_max_fact_checks:
                rejected.append(
                    {"item_id": str(item.id), "code": "REFERENCE_FACT_CHECK_BUDGET_EXHAUSTED"}
                )
                continue
            checked[revision_key] = True
            if item.status in PROTECTED:
                rejected.append({"item_id": str(item.id), "code": "REFERENCE_REVIEW_PROTECTED"})
                continue
            try:
                service.facts(item.id, "rules")
                row, evidence = service.evidence(item)
                if (
                    rule_selection(evidence).decision != "selected"
                    and service.runner.provider is not None
                ):
                    service.facts(item.id, "ai")
                    row, evidence = service.evidence(item)
            except (EditorialError, ValidationError):
                rejected.append({"item_id": str(item.id), "code": "REFERENCE_FACTS_UNAVAILABLE"})
                continue
        if evidence is None or row is None or rule_selection(evidence).decision != "selected":
            rejected.append({"item_id": str(item.id), "code": "REFERENCE_FACTS_INVALID"})
            continue
        assessment = assess_candidate(
            service, target, target_evidence, target_topic, item, request.relation, evidence
        )
        assessment = assessment.model_copy(
            update={"retrieval_score": score, "retrieval_rank": rank}
        )
        assessments[str(item.id)] = assessment
        if assessment.decision != "eligible":
            rejected.append({"item_id": str(item.id), "code": assessment.reason_codes[0]})
            continue
        selected = [
            {
                "item_id": str(item.id),
                "item_version": item.version,
                "evidence_package_id": str(row.id),
                "evidence_hash": row.payload_hash,
                "score": assessment.score,
                "retrieval_score": score,
                "retrieval_rank": rank,
            }
        ]
        break
    analysis = ComparisonAnalysisV1(
        item_id=target.id,
        item_version=target.version,
        policy_version=POLICY_VERSION,
        target_topic=target_topic,
        selection_criteria=SELECTION_CRITERIA,
        candidates=tuple(assessments.values()),
        selected_item_ids=tuple(UUID(v["item_id"]) for v in selected),
    )
    audit_id = record_contract(service, analysis, "comparison_audit")
    result.update(
        {
            "checked_item_versions": checked,
            "rejected": rejected[-20:],
            "scanned_candidates": len(rows),
            "selected": selected,
            "analysis_id": str(audit_id),
            "target_topic": target_topic.model_dump(mode="json"),
            "selection_criteria": list(SELECTION_CRITERIA),
            "candidate_assessments": [a.model_dump(mode="json") for a in assessments.values()],
        }
    )
    return tuple(UUID(v["item_id"]) for v in selected)


def cached_selection(
    service: EditorialService, request: ResearchRequestV1, result: dict[str, Any]
) -> tuple[UUID, ...]:
    target = item_for_update(service.session, request.item_id)
    _, target_evidence = service.evidence(target)
    target_topic = topic_for_item(service, target)
    ids = []
    for value in result.get("selected", []):
        item = item_for_update(service.session, UUID(value["item_id"]))
        eligible(service.session, item)
        row, evidence = service.evidence(item)
        if item.version != value["item_version"] or row.payload_hash != value["evidence_hash"]:
            raise EditorialError("COMPARISON_REFERENCE_STALE")
        assessment = assess_candidate(
            service, target, target_evidence, target_topic, item, request.relation, evidence
        )
        if assessment.decision != "eligible" or request.policy_version != POLICY_VERSION:
            raise EditorialError("COMPARISON_REFERENCE_STALE")
        ids.append(item.id)
    return tuple(ids)


def fulfill_search(
    service: EditorialService, message: ModuleMessage
) -> tuple[tuple[UUID, ...], bool]:
    request = ResearchRequestV1.model_validate(message.payload_json)
    if canonical_payload_hash(message.payload_json) != message.payload_hash:
        raise EditorialError("OUTBOX_HASH_MISMATCH")
    item = item_for_update(service.session, request.item_id)
    eligible(service.session, item)
    evidence, target_evidence = service.evidence(item)
    if item.version != request.item_version or (
        request.evidence_hash and request.evidence_hash != evidence.payload_hash
    ):
        raise EditorialError("RESEARCH_TARGET_STALE")
    if (
        request.expected_workflow_version
        and item.workflow_version != request.expected_workflow_version
    ):
        raise EditorialError("RESEARCH_TARGET_STALE")
    result = dict(message.result_json or {})
    if message.status == "processed":
        return cached_selection(service, request, result), False
    if message.status in {"unavailable", "blocked", "superseded"}:
        return (), False
    now = datetime.now(UTC)
    if utc(message.available_at) > now:
        return (), True
    message.attempt += 1
    target_topic = topic_for_item(service, item)
    if request.relation == "previous" and target_evidence.published_at is None:
        message.status, message.processed_at = "unavailable", now
        message.error_json = {"code": "PREVIOUS_PRODUCT_DATE_UNCONFIRMED"}
        message.result_json = {
            "selected": [],
            "rejected": [],
            "scanned_candidates": 0,
            "unavailable_reason": "PREVIOUS_PRODUCT_DATE_UNCONFIRMED",
            "target_topic": target_topic.model_dump(mode="json"),
            "selection_criteria": list(SELECTION_CRITERIA),
            "candidate_assessments": [],
        }
        return (), False
    ids = search_catalog(service, request, result)
    checks = dict(result.get("source_checks", {}))
    if (
        not ids
        and service.settings.research_refresh_sources
        and service.runner.provider is not None
    ):
        sources = [
            row
            for row in approved_sources(service.session)
            if row.key in request.approved_source_keys
        ]
        sources.sort(key=lambda row: (row.id != item.source_id, row.key))
        todo = [
            row
            for row in sources
            if checks.get(row.key, {}).get("status") not in {"success", "cached", "blocked"}
        ]
        for source in todo[: service.settings.research_max_sources_per_attempt]:
            collected = collect_source(
                service.session,
                source.key,
                github_token=service.settings.github_token.get_secret_value()
                if service.settings.github_token
                else None,
            )
            status = collected.status
            if (
                status == "deferred"
                and source.last_success_at is not None
                and utc(source.last_success_at)
                >= utc(message.created_at)
                - timedelta(minutes=source_config(source).interval_minutes or 60)
            ):
                status = "cached"
            checks[source.key] = {"status": status, "error_code": collected.error_code}
        process_phase2(service.session, limit=service.settings.research_max_candidates)
        if item.version != request.item_version:
            raise EditorialError("RESEARCH_TARGET_STALE")
        ids = search_catalog(service, request, result)
    result["source_checks"] = checks
    message.result_json = result
    if ids:
        message.status, message.processed_at, message.error_json = "processed", now, None
        logger.info(
            "comparison_research_selected",
            request_id=str(message.message_id),
            item_id=str(item.id),
            relation=request.relation,
            selected_item_ids=[str(v) for v in ids],
        )
        return ids, False
    remaining = [
        key
        for key in request.approved_source_keys
        if checks.get(key, {}).get("status") not in {"success", "cached", "blocked"}
    ]
    refresh_enabled = (
        service.settings.research_refresh_sources and service.runner.provider is not None
    )
    if refresh_enabled and remaining and message.attempt < service.settings.research_max_attempts:
        message.available_at = now + timedelta(seconds=service.settings.research_retry_seconds)
        message.error_json = {"code": "RESEARCH_RETRY_PENDING"}
        return (), True
    message.status, message.processed_at = "unavailable", now
    budget_exhausted = (
        (remaining and refresh_enabled)
        or result.get("scanned_candidates", 0) >= service.settings.research_max_candidates
        or len(result.get("checked_item_versions", {})) >= service.settings.research_max_fact_checks
    )
    code = "SEARCH_BUDGET_EXHAUSTED" if budget_exhausted else "NO_VERIFIED_COMPARISON_FOUND"
    message.error_json = {"code": code}
    message.result_json = {**result, "unavailable_reason": code, "remaining_source_keys": remaining}
    logger.info(
        "comparison_research_unavailable",
        request_id=str(message.message_id),
        item_id=str(item.id),
        relation=request.relation,
        reason_code=code,
    )
    return (), False


def prepare_comparison(
    service: EditorialService,
    item_id: UUID,
    previous_ids: tuple[UUID, ...] = (),
    competitor_ids: tuple[UUID, ...] = (),
) -> ResearchPreparation:
    if not service.settings.comparison_auto_research:
        return ResearchPreparation(previous_ids, competitor_ids)
    item = item_for_update(service.session, item_id)
    eligible(service.session, item)
    row, evidence = service.evidence(item)
    keys = tuple(source.key for source in approved_sources(service.session))
    selected = {"previous": previous_ids, "competitor": competitor_ids}
    request_ids = []
    pending = False
    for relation in ("previous", "competitor"):
        if selected[relation]:
            continue
        request = ResearchRequestV1(
            item_id=item.id,
            item_version=item.version,
            relation=relation,
            query=evidence.title,
            approved_source_keys=keys,
            evidence_package_id=row.id,
            evidence_hash=row.payload_hash,
            expected_workflow_version=item.workflow_version,
            job_id=service.research_job_id,
            policy_version=POLICY_VERSION,
        )
        request_id = service.research_port.request_search(request)
        request_ids.append(request_id)
        message = service.session.get(ModuleMessage, request_id)
        assert message is not None
        selected[relation], waiting = fulfill_search(service, message)
        pending = pending or waiting
    return ResearchPreparation(
        selected["previous"], selected["competitor"], tuple(request_ids), pending
    )


def record_package(
    service: EditorialService, request_ids: tuple[UUID, ...], package_id: UUID
) -> None:
    for request_id in request_ids:
        message = service.session.get(ModuleMessage, request_id)
        assert message is not None
        message.result_json = {**(message.result_json or {}), "article_package_id": str(package_id)}


def process_comparison_research(session: Session, settings: Settings, limit: int = 4) -> int:
    if (
        not settings.comparison_auto_research
        or not settings.ai_writer_model
        or not settings.ai_verifier_model
    ):
        return 0
    messages = list(
        session.scalars(
            select(ModuleMessage)
            .where(
                ModuleMessage.consumer == "acquisition_research",
                ModuleMessage.status == "pending",
                ModuleMessage.available_at <= datetime.now(UTC),
                ModuleMessage.payload_json["job_id"].as_string().is_(None),
            )
            .order_by(ModuleMessage.created_at, ModuleMessage.message_id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    )
    count = 0
    for message in messages:
        if message.status != "pending":
            continue
        try:
            request = ResearchRequestV1.model_validate(message.payload_json)
            if canonical_payload_hash(message.payload_json) != message.payload_hash:
                raise EditorialError("OUTBOX_HASH_MISMATCH")
            item = item_for_update(session, request.item_id)
            if item.version != request.item_version:
                raise EditorialError("RESEARCH_TARGET_STALE")
            if has_active_comparison_job(session, item.id):
                message.available_at = datetime.now(UTC) + timedelta(
                    seconds=settings.research_retry_seconds
                )
                continue
            if item.status not in {
                ItemStatus.CANDIDATE_SELECTED,
                ItemStatus.COMPARISON_READY,
            } or latest(session, ArticleDraft, item.id):
                message.status, message.processed_at = "superseded", datetime.now(UTC)
                message.error_json = {"code": "RESEARCH_REVIEW_PROTECTED"}
                continue
            if (
                request.expected_workflow_version
                and item.workflow_version != request.expected_workflow_version
            ):
                raise EditorialError("RESEARCH_TARGET_STALE")
            service = EditorialService(session, settings)
            prepared = prepare_comparison(service, item.id)
            if message.message_id not in prepared.request_ids:
                message.status, message.processed_at = "superseded", datetime.now(UTC)
            if not prepared.pending:
                package = service.comparison(
                    item.id, prepared.previous_ids, prepared.competitor_ids, request_missing=False
                )
                record_package(service, prepared.request_ids, package.id)
            count += 1
        except (EditorialError, ValidationError) as exc:
            message.status, message.processed_at = "blocked", datetime.now(UTC)
            message.error_json = {
                "code": exc.code if isinstance(exc, EditorialError) else "RESEARCH_REQUEST_INVALID"
            }
    session.flush()
    return count
