from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.base import ContractModel
from app.contracts.envelope import canonical_payload_hash
from app.core.config import Settings
from app.core.editorial import EditorialError
from app.infrastructure.db.models import ApiUser, ArticleDraft, JobRun, ModuleMessage
from app.orchestration.editorial import EditorialService, item_for_update


class EditorialJobRequest(ContractModel):
    expected_version: int = Field(ge=1)
    mode: Literal["rules", "ai"] = "rules"
    auto_research: bool = True
    previous_item_ids: tuple[UUID, ...] = Field(default=(), max_length=10)
    competitor_item_ids: tuple[UUID, ...] = Field(default=(), max_length=10)
    draft_id: UUID | None = None
    request_id: UUID | None = None


Operation = Literal["facts", "select", "comparison", "draft", "verify", "pipeline"]


def queue_job(
    session: Session,
    item_id: UUID,
    operation: Operation,
    request: EditorialJobRequest,
    actor_id: UUID,
) -> JobRun:
    item = item_for_update(session, item_id, request.expected_version)
    args = {
        "item_id": str(item_id),
        "operation": operation,
        "request": request.model_dump(mode="json"),
        "actor_id": str(actor_id),
        "item_version": item.version,
    }
    identity = canonical_payload_hash(args)
    existing = session.scalar(select(JobRun).where(JobRun.idempotency_key == "phase3:" + identity))
    if existing:
        return existing
    job = JobRun(
        job_type="phase3",
        source_id=item.source_id,
        scheduled_for=datetime.now(UTC),
        status="queued",
        attempt=1,
        idempotency_key="phase3:" + identity,
        stats_json=args,
    )
    session.add(job)
    session.flush()
    return job


def execute_job(
    service: EditorialService, operation: Operation, item_id: UUID, request: EditorialJobRequest
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if operation in {"facts", "pipeline"}:
        evidence = service.facts(item_id, request.mode)
        if evidence is None or not evidence.payload_json["facts"]:
            return {"status": "review_required"}
        result["evidence_package_id"] = str(evidence.id)
    if operation in {"select", "pipeline"}:
        candidate = service.select(item_id)
        result["candidate_id"] = str(candidate.id)
        if candidate.decision != "selected":
            return {**result, "status": candidate.decision}
    if operation in {"comparison", "pipeline"}:
        from app.orchestration.research import prepare_comparison, record_package

        previous_ids, competitor_ids = request.previous_item_ids, request.competitor_item_ids
        request_ids: tuple[UUID, ...] = ()
        if request.auto_research and service.settings.comparison_auto_research:
            prepared = prepare_comparison(service, item_id, previous_ids, competitor_ids)
            previous_ids, competitor_ids, request_ids = (
                prepared.previous_ids,
                prepared.competitor_ids,
                prepared.request_ids,
            )
            result["research_request_ids"] = [str(value) for value in request_ids]
            if prepared.pending:
                return {**result, "status": "research_pending"}
        package = service.comparison(
            item_id,
            previous_ids,
            competitor_ids,
            request_missing=request.auto_research and not service.settings.comparison_auto_research,
        )
        record_package(service, request_ids, package.id)
        result["article_package_id"] = str(package.id)
    if operation in {"draft", "pipeline"}:
        draft = service.draft(item_id)
        if draft is None:
            return {**result, "status": "review_required"}
        result["draft_id"] = str(draft.id)
    if operation in {"verify", "pipeline"}:
        draft_id = UUID(result["draft_id"]) if "draft_id" in result else request.draft_id
        if draft_id is None:
            raise EditorialError("DRAFT_ID_REQUIRED", 422)
        draft_row = service.session.get(ArticleDraft, draft_id)
        if draft_row is None or draft_row.item_id != item_id:
            raise EditorialError("DRAFT_ITEM_MISMATCH")
        verification = service.verify(draft_id)
        result["verification_id"] = str(verification.id)
        result["status"] = verification.overall_result
    return result


def process_editorial_jobs(session: Session, settings: Settings, limit: int = 10) -> int:
    jobs = list(
        session.scalars(
            select(JobRun)
            .where(
                JobRun.job_type == "phase3",
                JobRun.status.in_(["queued", "waiting_research"]),
                JobRun.scheduled_for <= datetime.now(UTC),
            )
            .order_by(JobRun.scheduled_for, JobRun.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    )
    for job in jobs:
        args = job.stats_json
        waiting = job.status == "waiting_research"
        if waiting:
            job.attempt += 1
        job.status = "running"
        job.started_at = job.started_at or datetime.now(UTC)
        service = None
        try:
            request = EditorialJobRequest.model_validate(args["request"])
            item_id = UUID(args["item_id"])
            item = item_for_update(session, item_id, request.expected_version)
            if item.version != args["item_version"]:
                raise EditorialError("ITEM_VERSION_CONFLICT")
            actor = session.get(ApiUser, UUID(args["actor_id"]))
            if actor is None or not actor.active or "editor" not in actor.roles:
                raise EditorialError("EDITOR_AUTHORIZATION_REVOKED", 403)
            service = EditorialService(session, settings, actor_id=actor.id)
            service.research_job_id = job.id
            result = execute_job(
                service,
                args["operation"],
                item_id,
                request,
            )
            job.stats_json = {**args, "result": result}
            if result.get("status") == "research_pending":
                job.status = "waiting_research"
                job.scheduled_for = datetime.now(UTC) + timedelta(
                    seconds=settings.research_retry_seconds
                )
                job.stats_json = {
                    **job.stats_json,
                    "request": {**args["request"], "expected_version": item.workflow_version},
                }
            else:
                job.status = "success"
        except EditorialError as exc:
            job.status, job.error_code = "failed", exc.code
            for message in session.scalars(
                select(ModuleMessage).where(
                    ModuleMessage.consumer == "acquisition_research",
                    ModuleMessage.status == "pending",
                    ModuleMessage.payload_json["job_id"].as_string() == str(job.id),
                )
            ):
                message.status, message.processed_at = "blocked", datetime.now(UTC)
                message.error_json = {"code": exc.code}
        if service is not None:
            job.stats_json = {
                **job.stats_json,
                "ai_run_ids": list(
                    dict.fromkeys(
                        [
                            *args.get("ai_run_ids", []),
                            *[str(run_id) for run_id in service.runner.run_ids],
                        ]
                    )
                ),
            }
        if job.status != "waiting_research":
            job.finished_at = datetime.now(UTC)
    session.flush()
    return len(jobs)
