"""Resolve model names from the exact runs linked to an article, never settings."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.article_package_v1 import ArticlePackageV1
from app.core.draft_style import plain_style
from app.infrastructure.db.models import (
    AiRun,
    ArticleDraft,
    AuditEvent,
    CandidateDecision,
    EvidencePackage,
    Fact,
    FeaturedImage,
    VerificationRun,
)


def recorded_model(session: Session, run_id: UUID | None, item_id: UUID, role: str) -> str:
    run = session.get(AiRun, run_id) if run_id else None
    if run is None or run.item_id != item_id or run.execution_role != role:
        return "モデルの記録なし"
    if run.provider == "mock":
        return "テスト用の模擬処理(実AIモデルの使用なし)"
    return run.model


def fact_signature(fact: Fact) -> tuple[str, ...]:
    """Match retained fact meaning, including price conditions and attribution."""
    fields = ("value", "unit", "currency", "date_precision", "region", "conditions", "attribution")
    return (fact.fact_type, *(plain_style(str(fact.value_json.get(k) or "")) for k in fields))


def extraction_model_names(session: Session, facts: list[Fact]) -> list[str]:
    """Include older successful AI extraction records whose facts remain in edited evidence.

    Older models are explicitly described as extraction history, not claimed to have
    produced the final manual edits. Unrelated, later and discarded runs are excluded.
    """
    used = {(f.evidence_package_id, f.item_id) for f in facts if f.extractor == "ai"}
    manual: dict[UUID, list[Fact]] = {}
    for fact in facts:
        if fact.extractor == "manual":
            manual.setdefault(fact.item_id, []).append(fact)
    for item_id, retained in manual.items():
        evidence = {
            e.id: e
            for e in session.scalars(
                select(EvidencePackage).where(EvidencePackage.item_id == item_id)
            )
        }
        earlier = session.scalars(
            select(Fact).where(Fact.item_id == item_id, Fact.extractor == "ai")
        )
        for prior in earlier:
            parent = evidence.get(prior.evidence_package_id) if prior.evidence_package_id else None
            if parent is None:
                continue
            if any(
                current.evidence_package_id in evidence
                and parent.revision < evidence[current.evidence_package_id].revision
                and fact_signature(prior) == fact_signature(current)
                for current in retained
            ):
                used.add((parent.id, item_id))
    names = []
    for evidence_id, item_id in sorted(used, key=lambda pair: str(pair[0])):
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
            if event.after_json and event.after_json.get("evidence_package_id") == str(evidence_id)
        ]
        run_id = linked[0].get("ai_run_id") if len(linked) == 1 else None
        run = session.get(AiRun, UUID(run_id)) if run_id else None
        if run is not None and run.validation_status not in {"valid", "valid_with_rejections"}:
            continue
        names.append(recorded_model(session, run.id if run else None, item_id, "facts"))
    return sorted(set(names))


def article_model_stages(
    session: Session, draft: ArticleDraft, verification: VerificationRun, package: ArticlePackageV1
) -> list[tuple[str, str]]:
    stages = []
    facts = list(session.scalars(select(Fact).where(Fact.id.in_(package.verified_fact_ids))))
    names = extraction_model_names(session, facts)
    edited = any(f.extractor == "manual" for f in facts)
    if names:
        description = "、".join(names)
        if edited:
            description += " (編集前の抽出履歴を含む。出典照合による編集を実施)"
        stages.append(("事実抽出", description))
    elif facts:
        stages.append(
            (
                "事実抽出",
                "出典照合による編集(抽出AIモデルの記録なし)"
                if edited
                else "ルール処理(AI使用なし)",
            )
        )
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
    audit = package.comparison_selection
    if audit is not None:
        stages.append(
            (
                "比較目的・項目の計画",
                recorded_model(session, audit.plan.ai_run_id, audit.item_id, "comparison_plan"),
            )
        )
        selected = set(audit.selected_product_keys)
        assessed = sorted(
            {
                recorded_model(session, entry.ai_run_id, audit.item_id, "comparison_assess")
                for entry in audit.evaluations
                if entry.product.product_key in selected
            }
        )
        stages.append(("比較資料・セルの評価", "、".join(assessed)))
        stages.append(
            (
                "比較適性の独立検証",
                recorded_model(
                    session, audit.independent_ai_run_id, audit.item_id, "comparison_verify"
                ),
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


def image_model_description(session: Session, image: FeaturedImage) -> str:
    """Show confirmed tool host software; never substitute media registration time."""
    markers = (" (モデル名未提供)", " (model undisclosed)")
    if not any(marker in image.model for marker in markers):
        return image.model
    model = image.model
    for marker in markers:
        model = model.replace(marker, "")
    if not image.content_hash:
        return model
    events = session.scalars(
        select(AuditEvent)
        .where(AuditEvent.action == "image.tool_software_identified")
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
    )
    for event in events:
        data = event.after_json or {}
        if data.get("content_hash") != image.content_hash:
            continue
        name, version = data.get("software_name"), data.get("software_version")
        if isinstance(name, str) and name.strip() and isinstance(version, str) and version.strip():
            return model + "\uff08組み込み先: " + name.strip() + " " + version.strip() + "\uff09"
    return model
