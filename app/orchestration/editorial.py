"""Revision-aware Phase 3 application services; modules exchange validated DTOs only."""

import difflib
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal, cast
from uuid import UUID, uuid4

import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.diagnostics import validation_diagnostics
from app.ai.runner import AIRunner
from app.contracts.article_package_v1 import ArticlePackageV1, SourceReferenceV1
from app.contracts.base import ContractModel
from app.contracts.candidate_v1 import CandidateDecisionV1
from app.contracts.content_v1 import NormalizedContentV1
from app.contracts.draft_v1 import ArticleDraftV1, ParagraphFactMapV1
from app.contracts.editorial_v1 import (
    ResearchRequestV1,
    ReviewRequestV1,
    SelectionOutputV1,
    WritingOutputV1,
)
from app.contracts.envelope import ContractEnvelope, canonical_payload_hash
from app.contracts.evidence_v1 import EvidencePackageV1, FactReferenceV1
from app.contracts.facts_v1 import FactsOutputV1, VerifiedFactV1
from app.contracts.verification_v1 import (
    CriterionResult,
    VerificationCriterionV1,
    VerificationReportV1,
)
from app.core.config import Settings
from app.core.editorial import INJECTION, EditorialError, numbers, redact_contacts
from app.core.evidence_support import supported_text
from app.infrastructure.db.models import (
    AiRun,
    ArticleDraft,
    ArticlePackage,
    CandidateDecision,
    ComparisonDataset,
    EvidencePackage,
    ExtractionResult,
    Fact,
    Item,
    ItemStatus,
    LegalStatus,
    ModuleMessage,
    Review,
    Source,
    VerificationRun,
)
from app.infrastructure.db.repositories.audit import AuditEventWriter
from app.infrastructure.db.repositories.messages import ModuleMessageRepository
from app.infrastructure.research_requests import QueuedResearchAcquisition
from app.modules.acquisition.ports import ResearchAcquisitionPort
from app.modules.acquisition.service import source_config
from app.modules.comparison.service import build_comparison
from app.modules.extraction.facts import (
    evidence_passages,
    rule_facts,
    supported_ai_facts,
    validate_facts,
)
from app.modules.review.service import validate_checklist
from app.modules.selection.service import POLICY_VERSION as SELECTION_POLICY
from app.modules.selection.service import rule_selection
from app.modules.verification.service import POLICY_VERSION as VERIFICATION_POLICY
from app.modules.verification.service import REQUIRED_CRITERIA, rule_criteria
from app.modules.writing.service import POLICY_VERSION as WRITING_POLICY
from app.modules.writing.service import render_comparison, validate_writing
from app.orchestration.phase2 import lock_item


def checked_payload(row: Any, model: type[Any]) -> Any:
    if row.payload_hash != canonical_payload_hash(row.payload_json):
        raise EditorialError("PAYLOAD_HASH_MISMATCH")
    return model.model_validate(row.payload_json)


def latest(session: Session, model: Any, item_id: UUID) -> Any:
    return session.scalars(
        select(model).where(model.item_id == item_id).order_by(model.revision.desc())
    ).first()


def touch(
    session: Session,
    item: Item,
    action: str,
    actor_id: UUID | None = None,
    status: ItemStatus | None = None,
    **details: Any,
) -> None:
    before = {"status": item.status.value, "workflow_version": item.workflow_version}
    if status is not None:
        item.status = status
    item.workflow_version += 1
    AuditEventWriter(session).append(
        actor_type="user" if actor_id else "system",
        actor_id=str(actor_id or "phase3"),
        action=action,
        entity_type="item",
        entity_id=str(item.id),
        trace_id=str(uuid4()),
        before=before,
        after={"status": item.status.value, "workflow_version": item.workflow_version, **details},
    )


def eligible(session: Session, item: Item) -> Source:
    source = session.get(Source, item.source_id)
    assert source is not None
    config = source_config(source)
    if (
        not source.enabled
        or source.legal_status != LegalStatus.APPROVED
        or config.legal.effective_status() != "approved"
    ):
        raise EditorialError("SOURCE_RIGHTS_BLOCKED")
    if item.status in {ItemStatus.REJECTED, ItemStatus.BLOCKED_RIGHTS, ItemStatus.PUBLISHED}:
        raise EditorialError("ITEM_REJECTED")
    if item.duplicate_of_id:
        raise EditorialError("DUPLICATE_ITEM")
    return source


def item_for_update(session: Session, item_id: UUID, expected_version: int | None = None) -> Item:
    item = lock_item(session, item_id)
    if item is None:
        raise EditorialError("ITEM_NOT_FOUND", 404)
    if expected_version is not None and expected_version != item.workflow_version:
        raise EditorialError("VERSION_CONFLICT")
    return item


class EditorialService:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        runner: AIRunner | None = None,
        actor_id: UUID | None = None,
    ):
        self.session, self.settings = session, settings
        self.runner = runner or AIRunner(session, settings)
        self.actor_id = actor_id
        self.research_job_id: UUID | None = None
        self.research_port: ResearchAcquisitionPort = QueuedResearchAcquisition(session)

    def enqueue(
        self, payload: ContractModel, contract_type: str, consumer: str, producer: str
    ) -> ModuleMessage:
        return ModuleMessageRepository(self.session).enqueue_once(
            ContractEnvelope.build(
                payload, contract_type=contract_type, producer=producer, producer_version="0.3.0"
            ),
            consumer=consumer,
        )

    def facts(
        self, item_id: UUID, mode: Literal["rules", "ai"] = "rules"
    ) -> EvidencePackage | None:
        item = item_for_update(self.session, item_id)
        eligible(self.session, item)
        extracted = self.session.scalar(
            select(ExtractionResult).where(
                ExtractionResult.item_id == item.id, ExtractionResult.revision == item.version
            )
        )
        if extracted is None:
            raise EditorialError("EXTRACTION_REQUIRED")
        content = checked_payload(extracted, NormalizedContentV1)
        if content.quality_score < 0.6 or INJECTION.search(content.body):
            touch(
                self.session,
                item,
                "facts.blocked",
                self.actor_id,
                ItemStatus.REVIEW_PENDING,
                reason="EXTRACTION_QUALITY_OR_INJECTION",
            )
            return None
        from app.orchestration.comparison_analysis import topic_for_item

        topic_for_item(self, item)
        identity = canonical_payload_hash(
            {
                "extraction": extracted.payload_hash,
                "mode": mode,
                "profile": self.runner.profile("facts").fingerprint
                if mode == "ai"
                else "facts-rules-v1",
            }
        )
        existing = self.session.scalar(
            select(EvidencePackage).where(
                EvidencePackage.item_id == item.id, EvidencePackage.input_hash == identity
            )
        )
        if existing:
            return existing
        if item.status in {ItemStatus.REJECTED, ItemStatus.BLOCKED_RIGHTS}:
            raise EditorialError("ITEM_REJECTED")
        if (
            latest(self.session, EvidencePackage, item.id) is None
            and item.status != ItemStatus.DEDUPED
        ):
            raise EditorialError("DEDUPLICATION_REQUIRED")
        if mode == "ai":
            omitted: tuple[EditorialError, ...] = ()
            normalize_attempt = 0

            def normalize(value: FactsOutputV1) -> FactsOutputV1:
                nonlocal omitted, normalize_attempt
                normalize_attempt += 1
                retained, omitted = supported_ai_facts(content, value)
                return retained

            output, run_id = self.runner.run(
                "facts",
                item.id,
                {
                    "body": redact_contacts(content.body),
                    "evidence_passages": evidence_passages(redact_contacts(content.body)),
                    "source_url": str(content.canonical_url),
                },
                FactsOutputV1,
                normalize=normalize,
                validate=lambda value: validate_facts(content, value),
                repair=True,
            )
            if output is None:
                touch(self.session, item, "facts.invalid", self.actor_id, ItemStatus.REVIEW_PENDING)
                return None
            if omitted:
                run = self.session.get(AiRun, run_id)
                assert run is not None
                run.validation_status = "valid_with_rejections"
                run.validation_errors_json = [
                    diagnostic
                    for exc in omitted
                    for diagnostic in validation_diagnostics(exc, FactsOutputV1, normalize_attempt)
                ]
                structlog.get_logger().warning(
                    "ai_fact_candidates_rejected",
                    ai_run_id=str(run.id),
                    item_id=str(item.id),
                    retained_fact_count=len(output.facts),
                    validation_errors=run.validation_errors_json,
                )
        else:
            try:
                output = rule_facts(content)
            except EditorialError as exc:
                touch(
                    self.session,
                    item,
                    "facts.invalid",
                    self.actor_id,
                    ItemStatus.REVIEW_PENDING,
                    reason=exc.code,
                )
                return None
        revision = (
            self.session.scalar(
                select(func.max(EvidencePackage.revision)).where(EvidencePackage.item_id == item.id)
            )
            or 0
        ) + 1
        record = EvidencePackage(
            id=uuid4(),
            item_id=item.id,
            revision=revision,
            item_version=item.version,
            input_hash=identity,
            payload_json={},
            payload_hash="",
        )
        self.session.add(record)
        self.session.flush()
        verified = []
        references = []
        for value in output.facts:
            fact = Fact(
                id=uuid4(),
                evidence_id=uuid4(),
                evidence_package_id=record.id,
                item_id=item.id,
                item_version=item.version,
                fact_type=value.fact_type,
                subject=value.subject,
                predicate=value.predicate,
                value_json=value.model_dump(mode="json"),
                normalized_value=value.value,
                evidence_text=value.evidence_text,
                evidence_start=value.evidence_start,
                evidence_end=value.evidence_end,
                source_url=str(content.canonical_url),
                confidence=Decimal(str(value.confidence)),
                extractor=mode,
            )
            self.session.add(fact)
            safe = {
                key: value.model_dump()[key]
                for key in VerifiedFactV1.model_fields
                if key not in {"fact_id", "evidence_id"}
            }
            verified.append(VerifiedFactV1(fact_id=fact.id, evidence_id=fact.evidence_id, **safe))
            references.append(
                FactReferenceV1(
                    fact_id=fact.id, evidence_id=fact.evidence_id, fact_type=fact.fact_type
                )
            )
        payload = EvidencePackageV1(
            package_id=record.id,
            revision=revision,
            item_id=item.id,
            item_version=item.version,
            canonical_url=content.canonical_url,
            title=content.title,
            published_at=content.published_at,
            language=content.language,
            facts=tuple(references),
            verified_facts=tuple(verified),
            uncertainties=output.uncertainties,
            quality_score=content.quality_score,
        )
        record.payload_json = payload.model_dump(mode="json")
        record.payload_hash = canonical_payload_hash(record.payload_json)
        touch(
            self.session,
            item,
            "facts.extracted",
            self.actor_id,
            ItemStatus.FACTS_READY if verified else ItemStatus.REVIEW_PENDING,
            facts=len(verified),
        )
        if verified:
            self.enqueue(payload, "EvidencePackage", "selection", "extraction")
        self.session.flush()
        return record

    def evidence(self, item: Item) -> tuple[EvidencePackage, EvidencePackageV1]:
        row = latest(self.session, EvidencePackage, item.id)
        if row is None or row.item_version != item.version:
            raise EditorialError("CURRENT_FACTS_REQUIRED")
        return row, checked_payload(row, EvidencePackageV1)

    def select(self, item_id: UUID) -> CandidateDecision:
        item = item_for_update(self.session, item_id)
        eligible(self.session, item)
        row, evidence = self.evidence(item)
        decision = rule_selection(evidence)
        profile = self.runner.profile("selector")
        identity = canonical_payload_hash(
            {
                "package": row.payload_hash,
                "policy": SELECTION_POLICY,
                "profile": profile.fingerprint,
            }
        )
        existing = self.session.scalar(
            select(CandidateDecision).where(
                CandidateDecision.item_id == item.id, CandidateDecision.input_hash == identity
            )
        )
        if existing:
            return existing
        if decision.decision == "selected" and profile.model:
            result, run_id = self.runner.run(
                "selector", item.id, evidence.model_dump(mode="json"), SelectionOutputV1
            )
            if result is None:
                decision = SelectionOutputV1(
                    decision="deferred", score=0, reason_codes=("AI_SELECTION_INVALID",)
                )
            else:
                decision = result
        else:
            run_id = None
        record = CandidateDecision(
            item_id=item.id,
            evidence_package_id=row.id,
            decision=decision.decision,
            score=Decimal(str(decision.score)),
            reason_codes=list(decision.reason_codes),
            missing_requirements=list(decision.missing_requirements),
            policy_version=SELECTION_POLICY,
            ai_run_id=run_id,
            input_hash=identity,
        )
        self.session.add(record)
        self.session.flush()
        status = {
            "selected": ItemStatus.CANDIDATE_SELECTED,
            "deferred": ItemStatus.CANDIDATE_DEFERRED,
            "rejected": ItemStatus.CANDIDATE_REJECTED,
        }[record.decision]
        touch(
            self.session, item, "candidate.decided", self.actor_id, status, decision=record.decision
        )
        self.enqueue(
            CandidateDecisionV1(
                item_id=item.id,
                evidence_package_id=row.id,
                decision=record.decision,
                score=float(record.score),
                reason_codes=tuple(record.reason_codes),
                missing_requirements=tuple(record.missing_requirements),
                policy_version=SELECTION_POLICY,
            ),
            "CandidateDecision",
            "comparison" if record.decision == "selected" else "selection_history",
            "selection",
        )
        return record

    def comparison(
        self,
        item_id: UUID,
        previous_ids: tuple[UUID, ...] = (),
        competitor_ids: tuple[UUID, ...] = (),
        *,
        request_missing: bool = True,
    ) -> ArticlePackage:
        item = item_for_update(self.session, item_id)
        eligible(self.session, item)
        evidence_row, evidence = self.evidence(item)
        candidate = self.session.scalars(
            select(CandidateDecision)
            .where(CandidateDecision.item_id == item.id)
            .order_by(CandidateDecision.created_at.desc(), CandidateDecision.id.desc())
        ).first()
        if (
            candidate is None
            or candidate.decision != "selected"
            or candidate.evidence_package_id != evidence_row.id
        ):
            raise EditorialError("SELECTED_CANDIDATE_REQUIRED")
        references = [
            SourceReferenceV1(
                reference_id=item.id,
                url=evidence.canonical_url,
                fact_ids=tuple(f.fact_id for f in evidence.verified_facts),
            )
        ]
        all_facts = list(evidence.verified_facts)
        previous: list[VerifiedFactV1] = []
        competitors: list[VerifiedFactV1] = []
        evidence_hashes = [evidence_row.payload_hash]
        for ids, destination in ((previous_ids, previous), (competitor_ids, competitors)):
            for reference_id in ids:
                if reference_id == item.id:
                    raise EditorialError("COMPARISON_SELF_REFERENCE")
                other = self.session.get(Item, reference_id)
                if other is None:
                    raise EditorialError("COMPARISON_ITEM_NOT_FOUND")
                eligible(self.session, other)
                other_row, other_evidence = self.evidence(other)
                if destination is previous and (
                    not evidence.published_at
                    or not other_evidence.published_at
                    or other_evidence.published_at >= evidence.published_at
                ):
                    raise EditorialError("PREVIOUS_PRODUCT_DATE_UNCONFIRMED")
                destination.extend(other_evidence.verified_facts)
                all_facts.extend(other_evidence.verified_facts)
                evidence_hashes.append(other_row.payload_hash)
                references.append(
                    SourceReferenceV1(
                        reference_id=other.id,
                        url=other_evidence.canonical_url,
                        fact_ids=tuple(f.fact_id for f in other_evidence.verified_facts),
                    )
                )
        from app.modules.research.service import POLICY_VERSION as RESEARCH_POLICY
        from app.orchestration.comparison_analysis import analysis_for_items

        analysis = analysis_for_items(self, item, previous_ids, competitor_ids, enforce=True)
        identity = canonical_payload_hash(
            {
                "candidate": str(candidate.id),
                "evidence": evidence_hashes,
                "previous": [str(i) for i in previous_ids],
                "competitor": [str(i) for i in competitor_ids],
                "policy": WRITING_POLICY,
                "research_policy": RESEARCH_POLICY,
                "analysis": canonical_payload_hash(analysis.model_dump(mode="json")),
            }
        )
        existing = latest(self.session, ArticlePackage, item.id)
        if existing and existing.payload_json.get("request_hash") == identity:
            return cast(ArticlePackage, existing)
        revision = (existing.revision if existing else 0) + 1
        comparison = build_comparison(
            item.id,
            revision,
            evidence.verified_facts,
            tuple(previous),
            tuple(competitors),
            datetime.now(UTC).date(),
        )
        comparison = comparison.model_copy(update={"analysis": analysis})
        dataset = ComparisonDataset(
            item_id=item.id,
            revision=revision,
            payload_json=comparison.model_dump(mode="json"),
            payload_hash=canonical_payload_hash(comparison.model_dump(mode="json")),
        )
        self.session.add(dataset)
        self.session.flush()
        package = ArticlePackageV1(
            item_id=item.id,
            item_version=item.version,
            revision=revision,
            candidate_id=candidate.id,
            request_hash=identity,
            topic=analysis.target_topic.topic_label,
            topic_profile=analysis.target_topic,
            facts=tuple(all_facts),
            verified_fact_ids=tuple(f.fact_id for f in all_facts),
            comparison_dataset_id=dataset.id,
            comparison=comparison,
            source_references=tuple(references),
            uncertainties=evidence.uncertainties,
            writing_policy_version=WRITING_POLICY,
        )
        result = ArticlePackage(
            item_id=item.id,
            revision=revision,
            payload_json=package.model_dump(mode="json"),
            payload_hash=canonical_payload_hash(package.model_dump(mode="json")),
        )
        self.session.add(result)
        self.session.flush()
        for relation, values in (("previous", previous), ("competitor", competitors)):
            if not values and request_missing:
                approved = tuple(
                    self.session.scalars(
                        select(Source.key)
                        .where(
                            Source.enabled.is_(True), Source.legal_status == LegalStatus.APPROVED
                        )
                        .order_by(Source.key)
                    )
                )
                self.research_port.request_search(
                    ResearchRequestV1(
                        item_id=item.id,
                        item_version=item.version,
                        relation=relation,
                        query=evidence.title,
                        approved_source_keys=approved,
                        evidence_package_id=evidence_row.id,
                        evidence_hash=evidence_row.payload_hash,
                        expected_workflow_version=item.workflow_version + 1,
                        job_id=self.research_job_id,
                    )
                )
        self.enqueue(package, "ArticlePackage", "writing", "comparison")
        touch(
            self.session,
            item,
            "comparison.packaged",
            self.actor_id,
            ItemStatus.COMPARISON_READY,
            article_package_id=str(result.id),
        )
        return result

    def package(self, item: Item) -> tuple[ArticlePackage, ArticlePackageV1]:
        row = latest(self.session, ArticlePackage, item.id)
        if row is None:
            raise EditorialError("ARTICLE_PACKAGE_REQUIRED")
        package = checked_payload(row, ArticlePackageV1)
        if package.item_version != item.version:
            raise EditorialError("ARTICLE_PACKAGE_STALE")
        evidence_row, _ = self.evidence(item)
        candidate = (
            self.session.get(CandidateDecision, package.candidate_id)
            if package.candidate_id
            else None
        )
        if candidate is None or candidate.evidence_package_id != evidence_row.id:
            raise EditorialError("ARTICLE_PACKAGE_FACTS_STALE")
        for fact_id in package.verified_fact_ids:
            fact = self.session.get(Fact, fact_id)
            if fact is None:
                raise EditorialError("ARTICLE_PACKAGE_FACT_REFERENCE_INVALID")
            parent = self.session.get(Item, fact.item_id)
            if parent is None or parent.version != fact.item_version:
                raise EditorialError("COMPARISON_FACTS_STALE")
            eligible(self.session, parent)
            current = latest(self.session, EvidencePackage, parent.id)
            if current is None or current.id != fact.evidence_package_id:
                raise EditorialError("COMPARISON_FACTS_STALE")
        return row, package

    def draft(self, item_id: UUID, manual: WritingOutputV1 | None = None) -> ArticleDraft | None:
        item = item_for_update(self.session, item_id)
        eligible(self.session, item)
        if item.status in {ItemStatus.REJECTED, ItemStatus.BLOCKED_RIGHTS, ItemStatus.PUBLISHED}:
            raise EditorialError("ITEM_REJECTED")
        row, package = self.package(item)
        output: WritingOutputV1 | None
        if manual is not None:
            validate_writing(manual, package)
            output, run_id = manual, None
        else:
            supported = supported_text(package)
            data = {
                **package.model_dump(mode="json"),
                "allowed_numbers": sorted(numbers(supported)),
                "allowed_entities": sorted(
                    set(re.findall(r"(?<![A-Za-z0-9_-])[A-Z][A-Za-z0-9_-]{2,}", supported))
                    | {f.value for f in package.facts if f.fact_type in {"organization", "product"}}
                ),
            }
            output, run_id = self.runner.run(
                "writer",
                item.id,
                data,
                WritingOutputV1,
                validate=lambda value: validate_writing(value, package),
                repair=True,
            )
        if output is None:
            touch(self.session, item, "draft.invalid", self.actor_id, ItemStatus.NEEDS_CHANGES)
            return None
        prior = latest(self.session, ArticleDraft, item.id)
        revision = (prior.revision if prior else 0) + 1
        sources = "\n".join("- " + str(ref.url) for ref in package.source_references)
        body = "\n\n".join(p.text for p in output.paragraphs)
        body += render_comparison(output, package)
        body += "\n\n## 出典\n\n" + sources
        draft_id = uuid4()
        payload = ArticleDraftV1(
            draft_id=draft_id,
            item_id=item.id,
            article_package_id=row.id,
            revision=revision,
            title=output.title,
            lead=output.lead,
            body_markdown=body,
            category_keys=output.category_keys,
            risk_flags=output.risk_flags,
            paragraph_facts=tuple(
                ParagraphFactMapV1(paragraph=i, fact_ids=p.fact_ids)
                for i, p in enumerate(output.paragraphs)
            ),
            writer_profile_key=self.runner.profile("writer").key,
        )
        result = ArticleDraft(
            id=draft_id,
            item_id=item.id,
            article_package_id=row.id,
            revision=revision,
            title=payload.title,
            lead=payload.lead,
            body_markdown=body,
            category_keys=list(payload.category_keys),
            tags=[],
            risk_flags=list(payload.risk_flags),
            source_block={
                "draft": payload.model_dump(mode="json"),
                "actor_id": str(self.actor_id) if self.actor_id else None,
                "hash": canonical_payload_hash(payload.model_dump(mode="json")),
                "importance": output.importance,
                "audiences": list(output.audiences),
            },
            created_by_type="user" if manual is not None else "ai",
            ai_run_id=run_id,
        )
        self.session.add(result)
        self.session.flush()
        touch(
            self.session,
            item,
            "draft.created",
            self.actor_id,
            ItemStatus.DRAFT_GENERATED,
            draft_id=str(result.id),
            revision=revision,
        )
        self.enqueue(payload, "ArticleDraft", "verification", "writing")
        return result

    def verify(self, draft_id: UUID) -> VerificationRun:
        draft = self.session.get(ArticleDraft, draft_id)
        if draft is None:
            raise EditorialError("DRAFT_NOT_FOUND", 404)
        item = item_for_update(self.session, draft.item_id)
        eligible(self.session, item)
        newest = latest(self.session, ArticleDraft, item.id)
        if newest is None or newest.id != draft.id:
            raise EditorialError("DRAFT_STALE")
        row, package = self.package(item)
        if draft.article_package_id != row.id:
            raise EditorialError("DRAFT_PACKAGE_STALE")
        dto = ArticleDraftV1.model_validate(draft.source_block["draft"])
        draft_hash = canonical_payload_hash(dto.model_dump(mode="json"))
        if draft_hash != draft.source_block["hash"]:
            raise EditorialError("DRAFT_HASH_MISMATCH")
        rules = {c.key: c for c in rule_criteria(dto, package)}
        original = self.session.scalar(
            select(ExtractionResult).where(
                ExtractionResult.item_id == item.id, ExtractionResult.revision == item.version
            )
        )
        assert original is not None
        body = checked_payload(original, NormalizedContentV1).body
        text = dto.title + "\n" + dto.lead + "\n" + dto.body_markdown
        copied = (
            difflib.SequenceMatcher(None, body, text, autojunk=False).find_longest_match().size
            >= 80
        )
        if copied:
            rules["original_expression"] = VerificationCriterionV1(
                key="original_expression",
                result=CriterionResult.FAIL,
                detail="Long source expression copied",
            )
        if self.settings.ai_require_distinct_models:
            writer_run = self.session.get(AiRun, draft.ai_run_id) if draft.ai_run_id else None
            if (draft.created_by_type == "ai" and writer_run is None) or (
                writer_run is not None and writer_run.model == self.runner.profile("verifier").model
            ):
                raise EditorialError("AI_MODELS_MUST_BE_DISTINCT")
        data = {
            "draft": dto.model_dump(mode="json"),
            "package": package.model_dump(mode="json"),
            "required_criteria": sorted(REQUIRED_CRITERIA),
            "verifier_profile_key": self.runner.profile("verifier").key,
            "verification_id": str(uuid4()),
            "policy_version": VERIFICATION_POLICY,
            "policy": VERIFICATION_POLICY,
        }

        def validate(report: VerificationReportV1) -> None:
            for field, expected in (
                ("draft_id", dto.draft_id),
                ("article_package_id", row.id),
                ("policy_version", VERIFICATION_POLICY),
                ("verifier_profile_key", self.runner.profile("verifier").key),
            ):
                if getattr(report, field) != expected:
                    raise EditorialError("VERIFIER_OUTPUT_SCOPE_INVALID", path=(field,))
            if (
                len(report.criteria) != len(REQUIRED_CRITERIA)
                or {c.key for c in report.criteria} != REQUIRED_CRITERIA
            ):
                raise EditorialError("VERIFIER_OUTPUT_SCOPE_INVALID", path=("criteria",))
            for index, criterion in enumerate(report.criteria):
                if not set(criterion.fact_ids) <= set(package.verified_fact_ids):
                    raise EditorialError(
                        "VERIFIER_OUTPUT_SCOPE_INVALID", path=("criteria", index, "fact_ids")
                    )

        report, run_id = self.runner.run(
            "verifier", item.id, data, VerificationReportV1, validate=validate
        )
        assert run_id is not None
        criteria = dict(rules)
        if report is not None:
            for criterion in report.criteria:
                if rules[criterion.key].result != CriterionResult.FAIL:
                    criteria[criterion.key] = criterion
        issues = [c.key for c in criteria.values() if c.result != CriterionResult.PASSED]
        if report is None:
            issues.append("AI_VERIFICATION_INVALID")
        elif report.blocking_issues:
            issues.extend(report.blocking_issues)
        overall = (
            "error"
            if report is None
            else "fail"
            if issues or report.overall_result != "pass"
            else "pass"
        )
        fingerprint = self.runner.profile("verifier").fingerprint
        result = VerificationRun(
            item_id=item.id,
            draft_id=draft.id,
            ai_run_id=run_id,
            policy_version=VERIFICATION_POLICY,
            input_hash=canonical_payload_hash(data),
            overall_result=overall,
            criteria_json=[c.model_dump(mode="json") for c in criteria.values()],
            comparison_checks_json=[
                {
                    "draft_hash": draft_hash,
                    "package_hash": row.payload_hash,
                    "verifier_fingerprint": fingerprint,
                    "require_distinct_models": self.settings.ai_require_distinct_models,
                }
            ],
            blocking_issues_json=issues,
            warnings_json=list(report.warnings) if report else [],
            verified_at=datetime.now(UTC),
        )
        self.session.add(result)
        self.session.flush()
        touch(
            self.session,
            item,
            "draft.verified",
            self.actor_id,
            ItemStatus.REVIEW_PENDING if overall == "pass" else ItemStatus.VERIFICATION_FAILED,
            verification_id=str(result.id),
            result=overall,
        )
        return result

    def validate_for_approval(
        self, item: Item, draft: ArticleDraft, reviewer_id: UUID, *, require_pending: bool = True
    ) -> None:
        """Recheck revision, rights, independent verification and four-eyes at every send."""
        current = latest(self.session, ArticleDraft, item.id)
        if current is None or current.id != draft.id:
            raise EditorialError("DRAFT_STALE")
        dto = ArticleDraftV1.model_validate(draft.source_block["draft"])
        if (
            dto.draft_id != draft.id
            or dto.item_id != item.id
            or dto.title != draft.title
            or dto.lead != draft.lead
            or dto.body_markdown != draft.body_markdown
            or list(dto.category_keys) != draft.category_keys
            or list(dto.tags) != draft.tags
            or dto.article_package_id != draft.article_package_id
            or dto.revision != draft.revision
            or canonical_payload_hash(dto.model_dump(mode="json")) != draft.source_block["hash"]
        ):
            raise EditorialError("DRAFT_HASH_MISMATCH")
        eligible(self.session, item)
        package_row, _ = self.package(item)
        if (
            require_pending and item.status != ItemStatus.REVIEW_PENDING
        ) or draft.article_package_id != package_row.id:
            raise EditorialError("REVIEW_STATE_INVALID")
        if self.settings.review_require_four_eyes and draft.source_block.get("actor_id") == str(
            reviewer_id
        ):
            raise EditorialError("REVIEW_FOUR_EYES_REQUIRED")
        verification = self.session.scalars(
            select(VerificationRun)
            .where(VerificationRun.draft_id == draft.id)
            .order_by(VerificationRun.verified_at.desc(), VerificationRun.id.desc())
        ).first()
        if verification is None or verification.overall_result != "pass":
            raise EditorialError("LATEST_VERIFICATION_REQUIRED")
        meta = verification.comparison_checks_json[0]
        current_hash = canonical_payload_hash(
            ArticleDraftV1.model_validate(draft.source_block["draft"]).model_dump(mode="json")
        )
        if (
            verification.policy_version != VERIFICATION_POLICY
            or meta.get("require_distinct_models") != self.settings.ai_require_distinct_models
            or meta["verifier_fingerprint"] != self.runner.profile("verifier").fingerprint
            or meta["draft_hash"] != current_hash
            or meta["package_hash"] != package_row.payload_hash
        ):
            raise EditorialError("VERIFICATION_STALE")

    def review(self, item_id: UUID, request: ReviewRequestV1, reviewer_id: UUID) -> Review:
        item = item_for_update(self.session, item_id, request.expected_version)
        draft = latest(self.session, ArticleDraft, item_id)
        if draft is None or draft.id != request.draft_id:
            raise EditorialError("DRAFT_STALE")
        validate_checklist(request)
        if request.decision == "approve":
            self.validate_for_approval(item, draft, reviewer_id)
        result = Review(
            item_id=item.id,
            draft_id=draft.id,
            reviewer_id=reviewer_id,
            decision=request.decision,
            checklist_json=request.checklist.model_dump(),
            comment=request.comment,
        )
        self.session.add(result)
        self.session.flush()
        status = {
            "approve": ItemStatus.APPROVED,
            "needs_changes": ItemStatus.NEEDS_CHANGES,
            "reject": ItemStatus.REJECTED,
        }[request.decision]
        touch(
            self.session,
            item,
            "review." + request.decision,
            reviewer_id,
            status,
            draft_id=str(draft.id),
            review_id=str(result.id),
        )
        return result


def process_facts_outbox(session: Session, settings: Settings, limit: int = 100) -> int:
    count = 0
    messages = list(
        session.scalars(
            select(ModuleMessage)
            .where(ModuleMessage.consumer == "facts", ModuleMessage.status == "pending")
            .order_by(ModuleMessage.created_at)
            .limit(limit)
        )
    )
    for message in messages:
        if canonical_payload_hash(message.payload_json) != message.payload_hash:
            raise EditorialError("OUTBOX_HASH_MISMATCH")
        payload = EvidencePackageV1.model_validate(message.payload_json)
        item = item_for_update(session, payload.item_id)
        if item.version == payload.item_version and item.status == ItemStatus.DEDUPED:
            try:
                EditorialService(session, settings).facts(item.id)
                count += 1
            except EditorialError as exc:
                touch(
                    session,
                    item,
                    "facts.blocked",
                    status=ItemStatus.REVIEW_PENDING,
                    reason=exc.code,
                )
                message.status, message.processed_at = "blocked", datetime.now(UTC)
                continue
        message.status, message.processed_at = "processed", datetime.now(UTC)
    session.flush()
    return count


def process_editorial_outbox(
    session: Session, settings: Settings, consumer: str, limit: int = 10
) -> int:
    if consumer in {"writing", "verification"} and settings.ai_provider == "disabled":
        return 0
    if consumer == "writing" and not settings.ai_writer_model:
        return 0
    if consumer == "verification" and not settings.ai_verifier_model:
        return 0
    service = EditorialService(session, settings)
    records = list(
        session.scalars(
            select(ModuleMessage)
            .where(
                ModuleMessage.consumer == consumer,
                ModuleMessage.status == "pending",
                ModuleMessage.available_at <= datetime.now(UTC),
            )
            .order_by(ModuleMessage.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    )
    for record in records:
        if canonical_payload_hash(record.payload_json) != record.payload_hash:
            raise EditorialError("OUTBOX_HASH_MISMATCH")
        item = item_for_update(session, UUID(record.payload_json["item_id"]))
        try:
            if consumer == "selection":
                payload = EvidencePackageV1.model_validate(record.payload_json)
                evidence = latest(session, EvidencePackage, item.id)
                if (
                    evidence
                    and evidence.id == payload.package_id
                    and payload.item_version == item.version
                ):
                    service.select(item.id)
            elif consumer == "comparison":
                from app.orchestration.research import has_active_comparison_job

                if has_active_comparison_job(session, item.id):
                    record.available_at = datetime.now(UTC) + timedelta(
                        seconds=settings.research_retry_seconds
                    )
                    continue
                decision = CandidateDecisionV1.model_validate(record.payload_json)
                evidence = latest(session, EvidencePackage, item.id)
                if (
                    evidence
                    and evidence.id == decision.evidence_package_id
                    and evidence.item_version == item.version
                ):
                    # Do not replace an already prepared manual/automatic comparison package.
                    existing_package = latest(session, ArticlePackage, item.id)
                    try:
                        if existing_package is not None:
                            service.package(item)
                            prepared_package = True
                        else:
                            prepared_package = False
                    except EditorialError:
                        prepared_package = False
                    if not prepared_package:
                        from app.orchestration.research import prepare_comparison, record_package

                        if service.runner.provider is None and settings.comparison_auto_research:
                            service.comparison(item.id)
                            record.status, record.processed_at = "processed", datetime.now(UTC)
                            continue
                        prepared = prepare_comparison(service, item.id)
                        if prepared.pending:
                            record.available_at = datetime.now(UTC) + timedelta(
                                seconds=settings.research_retry_seconds
                            )
                            continue
                        package = service.comparison(
                            item.id,
                            prepared.previous_ids,
                            prepared.competitor_ids,
                            request_missing=not settings.comparison_auto_research,
                        )
                        record_package(service, prepared.request_ids, package.id)
            elif consumer == "writing":
                if settings.comparison_auto_research:
                    active_research = session.scalar(
                        select(ModuleMessage.message_id)
                        .where(
                            ModuleMessage.consumer == "acquisition_research",
                            ModuleMessage.status == "pending",
                            ModuleMessage.payload_json["item_id"].as_string() == str(item.id),
                            ModuleMessage.payload_json["item_version"].as_integer() == item.version,
                        )
                        .limit(1)
                    )
                    if active_research is not None:
                        continue
                ArticlePackageV1.model_validate(record.payload_json)
                latest_package = latest(session, ArticlePackage, item.id)
                draft = latest(session, ArticleDraft, item.id)
                if (
                    latest_package
                    and latest_package.payload_hash == record.payload_hash
                    and (draft is None or draft.article_package_id != latest_package.id)
                ):
                    service.draft(item.id)
            elif consumer == "verification":
                payload_draft = ArticleDraftV1.model_validate(record.payload_json)
                draft = latest(session, ArticleDraft, item.id)
                existing = session.scalar(
                    select(VerificationRun.id).where(
                        VerificationRun.draft_id == payload_draft.draft_id
                    )
                )
                if draft and draft.id == payload_draft.draft_id and existing is None:
                    service.verify(draft.id)
            else:
                raise EditorialError("UNKNOWN_CONSUMER")
        except EditorialError as exc:
            record.status = "blocked"
            touch(session, item, "editorial.blocked", reason=exc.code)
        else:
            record.status = "processed"
        record.processed_at = datetime.now(UTC)
    session.flush()
    return len(records)
