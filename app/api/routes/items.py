import difflib
from typing import Annotated, Any, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.auth import current_user, require_role
from app.contracts.base import ContractModel
from app.contracts.editorial_v1 import ManualDraftRequestV1, ReviewRequestV1
from app.core.config import get_settings
from app.core.editorial import EditorialError
from app.infrastructure.db.models import (
    AiRun,
    ApiUser,
    ArticleDraft,
    ArticlePackage,
    AuditEvent,
    CandidateDecision,
    EvidencePackage,
    ExtractionResult,
    Fact,
    Item,
    ItemStatus,
    JobRun,
    ModuleMessage,
    Source,
    VerificationRun,
)
from app.infrastructure.db.repositories.audit import AuditEventWriter
from app.infrastructure.db.session import get_db
from app.modules.research.service import POLICY_VERSION as RESEARCH_POLICY
from app.modules.research.topics import POLICY_VERSION as TOPIC_POLICY
from app.modules.verification.service import POLICY_VERSION as VERIFICATION_POLICY
from app.orchestration.comparison_analysis import analysis_for_items, record_contract
from app.orchestration.editorial import EditorialService, item_for_update, latest
from app.orchestration.editorial_jobs import EditorialJobRequest, Operation, queue_job

router = APIRouter(prefix="/api/v1", tags=["internal editorial"])
DB = Annotated[Session, Depends(get_db)]
User = Annotated[ApiUser, Depends(current_user)]


def item_view(item: Item, source: Source) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "source_key": source.key,
        "source_name": source.name,
        "title": item.title_original,
        "url": item.canonical_url,
        "status": item.status.value,
        "item_version": item.version,
        "workflow_version": item.workflow_version,
        "duplicate_of_id": str(item.duplicate_of_id) if item.duplicate_of_id else None,
    }


def verification_view(row: VerificationRun) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "draft_id": str(row.draft_id),
        "policy_version": row.policy_version,
        "policy_current": row.policy_version == VERIFICATION_POLICY,
        "reverification_required": row.policy_version != VERIFICATION_POLICY,
        "overall_result": row.overall_result,
        "criteria": row.criteria_json,
        "blocking_issues": row.blocking_issues_json,
        "warnings": row.warnings_json,
        "verified_at": row.verified_at.isoformat(),
    }


def ai_run_view(row: AiRun) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "item_id": str(row.item_id) if row.item_id else None,
        "task_type": row.task_type,
        "model": row.model,
        "validation_status": row.validation_status,
        "validation_errors": row.validation_errors_json,
        "token_in": row.token_in,
        "token_out": row.token_out,
        "created_at": row.created_at.isoformat(),
    }


class ComparisonAnalysisRequest(ContractModel):
    expected_version: int = Field(ge=1)
    previous_item_ids: tuple[UUID, ...] = Field(default=(), max_length=10)
    competitor_item_ids: tuple[UUID, ...] = Field(default=(), max_length=10)


def analysis_records(
    session: Session, item_id: UUID, consumer: str, limit: int = 20
) -> list[dict[str, Any]]:
    return [
        {
            "id": str(row.message_id),
            "created_at": row.created_at.isoformat(),
            "analysis": row.payload_json,
        }
        for row in session.scalars(
            select(ModuleMessage)
            .where(
                ModuleMessage.consumer == consumer,
                ModuleMessage.payload_json["item_id"].as_string() == str(item_id),
            )
            .order_by(ModuleMessage.created_at.desc(), ModuleMessage.message_id.desc())
            .limit(limit)
        )
    ]


def current_topic(
    session: Session, item: Item, extracted: ExtractionResult | None
) -> dict[str, Any] | None:
    for value in analysis_records(session, item.id, "article_topic"):
        topic = value["analysis"]
        if (
            extracted
            and topic["item_version"] == item.version
            and topic["extraction_hash"] == extracted.payload_hash
            and topic["policy_version"] == TOPIC_POLICY
        ):
            return cast(dict[str, Any], topic)
    return None


@router.get("/items/{item_id}/comparison-analysis")
def comparison_analysis_history(item_id: UUID, session: DB, user: User) -> dict[str, Any]:
    item = session.get(Item, item_id)
    if item is None:
        raise EditorialError("ITEM_NOT_FOUND", 404)
    extracted = session.scalar(
        select(ExtractionResult).where(
            ExtractionResult.item_id == item.id, ExtractionResult.revision == item.version
        )
    )
    return {
        "selection_policy_version": RESEARCH_POLICY,
        "topic_policy_version": TOPIC_POLICY,
        "topic_profile": current_topic(session, item, extracted),
        "analyses": analysis_records(session, item_id, "comparison_audit"),
        "topic_history": analysis_records(session, item_id, "article_topic"),
    }


@router.post("/items/{item_id}/comparison-analysis")
def analyze_comparison(
    item_id: UUID, request: ComparisonAnalysisRequest, session: DB, user: User
) -> dict[str, Any]:
    """Record topic, selection checks and feature differences without generation or collection."""
    require_role(user, "editor")
    item = item_for_update(session, item_id, request.expected_version)
    service = EditorialService(session, get_settings(), actor_id=user.id)
    analysis = analysis_for_items(
        service, item, request.previous_item_ids, request.competitor_item_ids
    )
    key = record_contract(service, analysis, "comparison_audit")
    AuditEventWriter(session).append(
        actor_type="user",
        actor_id=str(user.id),
        action="comparison.analyzed",
        entity_type="item",
        entity_id=str(item.id),
        trace_id=str(uuid4()),
        after={"analysis_id": str(key), "policy_version": analysis.policy_version},
    )
    session.commit()
    return {"analysis_id": str(key), "analysis": analysis.model_dump(mode="json")}


@router.get("/items")
def items(
    session: DB,
    user: User,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    status: ItemStatus | None = None,
    source: str | None = None,
    search: str | None = Query(None, max_length=200),
) -> dict[str, Any]:
    query = select(Item, Source).join(Source, Source.id == Item.source_id)
    if status:
        query = query.where(Item.status == status)
    if source:
        query = query.where(Source.key == source)
    if search:
        query = query.where(
            Item.title_original.ilike(
                "%" + search.replace("%", "\\%").replace("_", "\\_") + "%", escape="\\"
            )
        )
    total = session.scalar(select(func.count()).select_from(query.subquery()))
    rows = session.execute(
        query.order_by(Item.created_at.desc(), Item.id).offset(offset).limit(limit)
    )
    return {
        "items": [item_view(item, src) for item, src in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/items/{item_id}")
def item_detail(item_id: UUID, session: DB, user: User) -> dict[str, Any]:
    item = session.get(Item, item_id)
    if item is None:
        raise EditorialError("ITEM_NOT_FOUND", 404)
    source = session.get(Source, item.source_id)
    assert source is not None
    extracted = session.scalar(
        select(ExtractionResult).where(
            ExtractionResult.item_id == item.id, ExtractionResult.revision == item.version
        )
    )
    evidence = latest(session, EvidencePackage, item.id)
    facts = (
        list(session.scalars(select(Fact).where(Fact.evidence_package_id == evidence.id)))
        if evidence
        else []
    )
    drafts = list(
        session.scalars(
            select(ArticleDraft)
            .where(ArticleDraft.item_id == item.id)
            .order_by(ArticleDraft.revision.desc())
        )
    )
    verifications = list(
        session.scalars(
            select(VerificationRun)
            .where(VerificationRun.item_id == item.id)
            .order_by(VerificationRun.verified_at.desc())
        )
    )
    research = list(
        session.scalars(
            select(ModuleMessage)
            .where(
                ModuleMessage.consumer == "acquisition_research",
                ModuleMessage.payload_json["item_id"].as_string() == str(item.id),
            )
            .order_by(ModuleMessage.created_at.desc())
            .limit(100)
        )
    )
    result = item_view(item, source)
    result["topic_profile"] = current_topic(session, item, extracted)
    result["comparison_analyses"] = analysis_records(session, item.id, "comparison_audit")
    package = latest(session, ArticlePackage, item.id)
    result["article_package"] = package.payload_json if package else None
    result["research_requests"] = [
        {
            "id": str(m.message_id),
            "status": m.status,
            "request": m.payload_json,
            "result": m.result_json,
            "attempt": m.attempt,
            "error": m.error_json,
            "available_at": m.available_at.isoformat(),
        }
        for m in research
        if m.payload_json.get("item_id") == str(item.id)
    ]
    result.update(
        {
            "ai_runs": [
                ai_run_view(row)
                for row in session.scalars(
                    select(AiRun)
                    .where(AiRun.item_id == item.id)
                    .order_by(AiRun.created_at.desc(), AiRun.id.desc())
                    .limit(20)
                )
            ],
            "extraction": extracted.payload_json if extracted else None,
            "evidence_package": evidence.payload_json if evidence else None,
            "facts": [
                {
                    "id": str(f.id),
                    "evidence_id": str(f.evidence_id),
                    "item_version": f.item_version,
                    "value": f.value_json,
                    "source_url": f.source_url,
                }
                for f in facts
            ],
            "drafts": [d.source_block["draft"] for d in drafts],
            "verifications": [verification_view(v) for v in verifications],
            "latest_draft_diff": "\n".join(
                difflib.unified_diff(
                    drafts[1].body_markdown.splitlines(),
                    drafts[0].body_markdown.splitlines(),
                    fromfile="previous",
                    tofile="latest",
                    lineterm="",
                )
            )
            if len(drafts) > 1
            else "",
        }
    )
    return result


@router.get("/items/{item_id}/candidate-decisions")
def candidates(item_id: UUID, session: DB, user: User) -> list[dict[str, Any]]:
    return [
        {
            "id": str(r.id),
            "evidence_package_id": str(r.evidence_package_id),
            "decision": r.decision,
            "score": float(r.score),
            "reasons": r.reason_codes,
            "missing_requirements": r.missing_requirements,
            "policy_version": r.policy_version,
        }
        for r in session.scalars(
            select(CandidateDecision)
            .where(CandidateDecision.item_id == item_id)
            .order_by(CandidateDecision.created_at.desc())
        )
    ]


def submit(
    item_id: UUID,
    operation: Operation,
    request: EditorialJobRequest,
    session: Session,
    user: ApiUser,
) -> dict[str, str]:
    require_role(user, "editor")
    job = queue_job(session, item_id, operation, request, user.id)
    session.commit()
    return {"job_id": str(job.id), "status": job.status}


@router.post("/items/{item_id}/facts", status_code=202)
def facts_job(
    item_id: UUID, request: EditorialJobRequest, session: DB, user: User
) -> dict[str, str]:
    return submit(item_id, "facts", request, session, user)


@router.post("/items/{item_id}/select", status_code=202)
def select_job(
    item_id: UUID, request: EditorialJobRequest, session: DB, user: User
) -> dict[str, str]:
    return submit(item_id, "select", request, session, user)


@router.post("/items/{item_id}/comparison-package", status_code=202)
def comparison_job(
    item_id: UUID, request: EditorialJobRequest, session: DB, user: User
) -> dict[str, str]:
    return submit(item_id, "comparison", request, session, user)


@router.post("/items/{item_id}/ai-draft", status_code=202)
def draft_job(
    item_id: UUID, request: EditorialJobRequest, session: DB, user: User
) -> dict[str, str]:
    return submit(item_id, "draft", request, session, user)


@router.post("/items/{item_id}/reprocess", status_code=202)
def pipeline_job(
    item_id: UUID, request: EditorialJobRequest, session: DB, user: User
) -> dict[str, str]:
    return submit(item_id, "pipeline", request, session, user)


@router.post("/drafts/{draft_id}/verify", status_code=202)
def verify_job(
    draft_id: UUID, request: EditorialJobRequest, session: DB, user: User
) -> dict[str, str]:
    draft = session.get(ArticleDraft, draft_id)
    if draft is None:
        raise EditorialError("DRAFT_NOT_FOUND", 404)
    request = request.model_copy(update={"draft_id": draft_id})
    return submit(draft.item_id, "verify", request, session, user)


@router.get("/drafts/{draft_id}/verifications")
def verifications(draft_id: UUID, session: DB, user: User) -> list[dict[str, Any]]:
    return [
        verification_view(v)
        for v in session.scalars(
            select(VerificationRun)
            .where(VerificationRun.draft_id == draft_id)
            .order_by(VerificationRun.verified_at.desc())
        )
    ]


@router.get("/article-packages/{package_id}")
def package_detail(package_id: UUID, session: DB, user: User) -> dict[str, Any]:
    package = session.get(ArticlePackage, package_id)
    if package is None:
        raise EditorialError("ARTICLE_PACKAGE_NOT_FOUND", 404)
    return package.payload_json


@router.post("/items/{item_id}/reviews", status_code=201)
def review(item_id: UUID, request: ReviewRequestV1, session: DB, user: User) -> dict[str, str]:
    require_role(user, "reviewer")
    result = EditorialService(session, get_settings()).review(item_id, request, user.id)
    session.commit()
    return {"review_id": str(result.id), "decision": result.decision}


@router.get("/jobs/{job_id}")
def job_detail(job_id: UUID, session: DB, user: User) -> dict[str, Any]:
    job = session.get(JobRun, job_id)
    if job is None:
        raise EditorialError("JOB_NOT_FOUND", 404)
    return {
        "job_id": str(job.id),
        "status": job.status,
        "attempt": job.attempt,
        "next_run_at": job.scheduled_for.isoformat() if job.status == "waiting_research" else None,
        "error_code": job.error_code,
        "ai_runs": [
            ai_run_view(row)
            for run_id in job.stats_json.get("ai_run_ids", [])
            if (row := session.get(AiRun, UUID(run_id))) is not None
        ],
        "result": job.stats_json.get("result", {}),
    }


@router.get("/audit-events")
def audit_events(
    session: DB, user: User, item_id: UUID, limit: int = Query(100, ge=1, le=500)
) -> list[dict[str, Any]]:
    return [
        {
            "id": str(a.id),
            "action": a.action,
            "actor_type": a.actor_type,
            "actor_id": a.actor_id,
            "at": a.created_at.isoformat(),
            "before": a.before_json,
            "after": a.after_json,
        }
        for a in session.scalars(
            select(AuditEvent)
            .where(AuditEvent.entity_type == "item", AuditEvent.entity_id == str(item_id))
            .order_by(AuditEvent.created_at.desc())
            .limit(limit)
        )
    ]


@router.post("/items/{item_id}/drafts", status_code=201)
def manual_draft(
    item_id: UUID, request: ManualDraftRequestV1, session: DB, user: User
) -> dict[str, str]:
    require_role(user, "editor")
    item_for_update(session, item_id, request.expected_version)
    draft = EditorialService(session, get_settings(), actor_id=user.id).draft(
        item_id, request.output
    )
    assert draft is not None
    session.commit()
    return {"draft_id": str(draft.id), "revision": str(draft.revision)}
