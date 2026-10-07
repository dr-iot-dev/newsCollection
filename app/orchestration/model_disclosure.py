"""Resolve model names from the exact runs linked to an article, never settings."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.article_package_v1 import ArticlePackageV1
from app.infrastructure.db.models import (
    AiRun,
    ArticleDraft,
    AuditEvent,
    CandidateDecision,
    Fact,
    VerificationRun,
)


def recorded_model(session: Session, run_id: UUID | None, item_id: UUID, role: str) -> str:
    run = session.get(AiRun, run_id) if run_id else None
    if run is None or run.item_id != item_id or run.execution_role != role:
        return "モデルの記録なし"
    if run.provider == "mock":
        return "テスト用の模擬処理(実AIモデルの使用なし)"
    return run.model


def article_model_stages(
    session: Session, draft: ArticleDraft, verification: VerificationRun, package: ArticlePackageV1
) -> list[tuple[str, str]]:
    stages = []
    facts = list(session.scalars(select(Fact).where(Fact.id.in_(package.verified_fact_ids))))
    ai_evidence = {
        (fact.evidence_package_id, fact.item_id) for fact in facts if fact.extractor == "ai"
    }
    if ai_evidence:
        names = []
        for evidence_id, item_id in sorted(ai_evidence, key=lambda pair: str(pair[0])):
            events = session.scalars(
                select(AuditEvent).where(
                    AuditEvent.action == "facts.extracted",
                    AuditEvent.entity_type == "item",
                    AuditEvent.entity_id == str(item_id),
                )
            )
            linked = [
                event.after_json
                for event in events
                if event.after_json
                and event.after_json.get("evidence_package_id") == str(evidence_id)
            ]
            run_id = linked[0].get("ai_run_id") if len(linked) == 1 else None
            names.append(
                recorded_model(session, UUID(run_id) if run_id else None, item_id, "facts")
            )
        stages.append(("事実抽出", "、".join(dict.fromkeys(names))))
    elif facts:
        stages.append(("事実抽出", "ルール処理(AI使用なし)"))
    candidate = (
        session.get(CandidateDecision, package.candidate_id) if package.candidate_id else None
    )
    if candidate and candidate.item_id == draft.item_id and candidate.ai_run_id:
        stages.append(
            (
                "記事候補の選定",
                recorded_model(session, candidate.ai_run_id, draft.item_id, "selector"),
            )
        )
    writing = (
        recorded_model(session, draft.ai_run_id, draft.item_id, "writer")
        if draft.ai_run_id
        else "手動編集(AI執筆モデルの記録なし)"
    )
    stages.extend(
        [
            ("本文作成・編集", writing),
            (
                "原稿のAI検証",
                recorded_model(session, verification.ai_run_id, draft.item_id, "verifier"),
            ),
        ]
    )
    return stages
