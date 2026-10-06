"""Persist append-only topic and comparison audit contracts without external AI calls."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal, cast
from uuid import UUID

from sqlalchemy import select

from app.contracts.comparison_analysis_v1 import (
    ArticleTopicV1,
    CandidateAssessmentV1,
    ComparisonAnalysisV1,
    SelectionCheckV1,
)
from app.contracts.content_v1 import NormalizedContentV1
from app.contracts.envelope import ContractEnvelope
from app.contracts.evidence_v1 import EvidencePackageV1
from app.core.editorial import EditorialError
from app.infrastructure.db.models import ExtractionResult, Item
from app.infrastructure.db.repositories.messages import ModuleMessageRepository
from app.modules.comparison.analysis import compare_features
from app.modules.research.service import (
    POLICY_VERSION,
    identity,
    relation_reason,
    topic_checks,
    topic_reasons,
    utc,
)
from app.modules.research.topics import classify_topic

if TYPE_CHECKING:
    from app.orchestration.editorial import EditorialService

SELECTION_CRITERIA = (
    "用途・利用環境・機能トピックを根拠付きで確認し、すべて共通する候補に限定する。",
    "同社旧製品は会社と公開日の前後関係、他社製品は会社の相違を確認する。",
    "単なるhardware_spec等の型一致ではなく、通信・検知等の具体的な共通比較軸を要求する。",
    "利用者・発表主題の違いも記録し、未記載を非対応や性能差と扱わない。",
    "登録済み一次情報内の探索であり、未確認候補を無理に採用しない。",
    "順位点は必須トピック一致数*100 + 両側で確認した比較軸数*10 + 利用者・発表主題一致数。",
    "事実確認前の順位点で探索し、同点は記事ID順。確認上限内で最初に適合した候補を採用する。",
)


def content_for_item(
    service: "EditorialService", item: Item
) -> tuple[ExtractionResult, NormalizedContentV1]:
    from app.orchestration.editorial import checked_payload

    row = service.session.scalar(
        select(ExtractionResult).where(
            ExtractionResult.item_id == item.id, ExtractionResult.revision == item.version
        )
    )
    if row is None:
        raise EditorialError("EXTRACTION_REQUIRED")
    return row, checked_payload(row, NormalizedContentV1)


def record_contract(
    service: "EditorialService", payload: ArticleTopicV1 | ComparisonAnalysisV1, consumer: str
) -> UUID:
    message = ModuleMessageRepository(service.session).enqueue_once(
        ContractEnvelope.build(
            payload,
            contract_type=type(payload).__name__,
            producer="comparison_analysis",
            producer_version="0.4.0",
        ),
        consumer=consumer,
        status="processed",
    )
    if message.processed_at is None:
        message.processed_at = datetime.now(UTC)
    return message.message_id


def topic_for_item(service: "EditorialService", item: Item) -> ArticleTopicV1:
    row, content = content_for_item(service, item)
    topic = classify_topic(content, row.payload_hash)
    record_contract(service, topic, "article_topic")
    return topic


def assess_candidate(
    service: "EditorialService",
    target: Item,
    target_evidence: EvidencePackageV1,
    target_topic: ArticleTopicV1,
    candidate: Item,
    relation: Literal["previous", "competitor"],
    candidate_evidence: EvidencePackageV1 | None = None,
) -> CandidateAssessmentV1:
    from app.orchestration.editorial import eligible

    eligible(service.session, candidate)
    candidate_topic = topic_for_item(service, candidate)
    checks = topic_checks(target_topic, candidate_topic)
    reasons = []
    evidence_row = None
    if candidate_evidence is None:
        try:
            evidence_row, candidate_evidence = service.evidence(candidate)
        except EditorialError as exc:
            if exc.code != "CURRENT_FACTS_REQUIRED":
                raise
    else:
        evidence_row, _ = service.evidence(candidate)
    features = compare_features(
        target_evidence.verified_facts,
        candidate_evidence.verified_facts if candidate_evidence else (),
    )
    shared = tuple(
        f.axis for f in features if f.target.values and f.candidate.values and f.axis != "price"
    )
    score = (
        100
        * sum(
            c.result == "pass"
            for c in checks
            if c.criterion in {"purpose", "environment", "function"}
        )
        + 10 * len(shared)
        + sum(c.result == "pass" for c in checks if c.criterion in {"audience", "article_focus"})
    )
    company = identity(target_evidence, "organization")
    other_company = identity(candidate_evidence, "organization") if candidate_evidence else None
    company_ok = bool(
        company
        and other_company
        and ((company == other_company) if relation == "previous" else (company != other_company))
    )
    extra = [
        SelectionCheckV1(
            criterion="company_relation",
            required=True,
            result="unknown"
            if not company or not other_company
            else "pass"
            if company_ok
            else "fail",
            target_values=(company,) if company else (),
            candidate_values=(other_company,) if other_company else (),
            explanation="同社旧製品は同じ会社、他社製品は別会社であることを要求する。",
        )
    ]
    if relation == "previous":
        date_ok = bool(
            target_evidence.published_at
            and candidate_evidence
            and candidate_evidence.published_at
            and utc(candidate_evidence.published_at) < utc(target_evidence.published_at)
        )
        extra.append(
            SelectionCheckV1(
                criterion="previous_publication_order",
                required=True,
                result="pass" if date_ok else "unknown",
                target_values=(target_evidence.published_at.isoformat(),)
                if target_evidence.published_at
                else (),
                candidate_values=(candidate_evidence.published_at.isoformat(),)
                if candidate_evidence and candidate_evidence.published_at
                else (),
                explanation="旧製品は元記事より前の公開日時を確認する。",
            )
        )
    extra.append(
        SelectionCheckV1(
            criterion="meaningful_feature_axes",
            required=True,
            result="pass" if shared else "unknown",
            target_values=tuple(f.axis for f in features if f.target.values),
            candidate_values=tuple(f.axis for f in features if f.candidate.values),
            explanation="検証済み事実から通信方式・検知対象等の具体的な比較軸が両側で確認できることを要求する。",
        )
    )
    checks = (*checks, *extra)
    if candidate_evidence is None:
        reasons.append("REFERENCE_FACTS_UNAVAILABLE")
    else:
        reason = relation_reason(target_evidence, candidate_evidence, relation, score)
        if reason:
            reasons.append(reason)
        if not shared:
            reasons.append("MEANINGFUL_COMPARISON_AXES_UNCONFIRMED")
    reasons.extend(topic_reasons(checks))
    return CandidateAssessmentV1(
        candidate_topic=candidate_topic,
        relation=relation,
        decision="rejected" if reasons else "eligible",
        reason_codes=tuple(reasons),
        selection_checks=checks,
        shared_feature_axes=shared,
        features=features,
        score=score,
        evidence_package_id=evidence_row.id if evidence_row else None,
        evidence_hash=evidence_row.payload_hash if evidence_row else None,
    )


def analysis_for_items(
    service: "EditorialService",
    target: Item,
    previous_ids: tuple[UUID, ...] = (),
    competitor_ids: tuple[UUID, ...] = (),
    *,
    enforce: bool = False,
) -> ComparisonAnalysisV1:
    from app.orchestration.editorial import eligible, item_for_update

    eligible(service.session, target)
    _, evidence = service.evidence(target)
    topic = topic_for_item(service, target)
    candidates = []
    for relation, ids in (("previous", previous_ids), ("competitor", competitor_ids)):
        for key in ids:
            if key == target.id:
                raise EditorialError("COMPARISON_SELF_REFERENCE")
            item = item_for_update(service.session, key)
            assessment = assess_candidate(
                service,
                target,
                evidence,
                topic,
                item,
                cast(Literal["previous", "competitor"], relation),
            )
            candidates.append(assessment)
    result = ComparisonAnalysisV1(
        item_id=target.id,
        item_version=target.version,
        policy_version=POLICY_VERSION,
        target_topic=topic,
        selection_criteria=SELECTION_CRITERIA,
        candidates=tuple(candidates),
        selected_item_ids=tuple(
            c.candidate_topic.item_id
            for c in candidates
            if enforce and all(value.decision == "eligible" for value in candidates)
        ),
    )
    record_contract(service, result, "comparison_audit")
    if enforce:
        for assessment in candidates:
            if assessment.decision != "eligible":
                raise EditorialError(assessment.reason_codes[0])
    return result
