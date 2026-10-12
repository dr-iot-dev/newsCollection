"""Standalone discovery, versioned history and exports; no comparison extraction."""

import csv
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.runner import AIRunner
from app.contracts.base import ContractModel
from app.contracts.discovery_search_vocabulary_v2 import (
    POLICY_VERSION,
    ROLE,
    SEARCH_POLICY,
    DiscoveryArticle,
    DiscoverySearchVocabularyV2,
    DiscoveryVocabularyInput,
    DiscoveryVocabularyRecord,
)
from app.contracts.envelope import ContractEnvelope, canonical_payload_hash
from app.core.config import Settings
from app.core.discovery_search_vocabulary import validate_vocabulary
from app.core.editorial import EditorialError
from app.infrastructure.db.models import (
    AiRun,
    ExtractionResult,
    Item,
    LegalStatus,
    ModuleMessage,
    Source,
)
from app.infrastructure.db.repositories.messages import ModuleMessageRepository

CONSUMER = "discovery_search_vocabulary"


class HistoryInput(ContractModel):
    request: DiscoveryVocabularyInput
    profile_fingerprint: str
    contract_hash: str
    policy_version: str
    search_policy: str


def history_payload(
    request: DiscoveryVocabularyInput, fingerprint: str, contract_hash: str
) -> dict[str, Any]:
    return {
        "request": request.model_dump(mode="json"),
        "profile_fingerprint": fingerprint,
        "contract_hash": contract_hash,
        "policy_version": POLICY_VERSION,
        "search_policy": SEARCH_POLICY,
    }


class DiscoveryVocabularyService:
    def __init__(
        self, session: Session, settings: Settings, runner: AIRunner | None = None
    ) -> None:
        self.session = session
        self.runner = runner or AIRunner(session, settings)

    def discover(
        self, request: DiscoveryVocabularyInput, *, call_budget: int = 2
    ) -> DiscoveryVocabularyRecord:
        if call_budget not in (1, 2):
            raise ValueError("call_budget must be 1 or 2 (one optional repair)")
        profile = self.runner.profile(ROLE)
        contract_hash = canonical_payload_hash(DiscoverySearchVocabularyV2.model_json_schema())
        payload = history_payload(request, profile.fingerprint, contract_hash)
        identity = canonical_payload_hash(payload)
        # The history key includes full input, prompt, model, schema and both policies.
        history = ContractEnvelope.build(
            HistoryInput.model_validate(payload),
            contract_type="discovery_search_vocabulary_request",
            producer=CONSUMER,
            producer_version=POLICY_VERSION,
            schema_version="2.0",
        )
        row = ModuleMessageRepository(self.session).enqueue_once(history, consumer=CONSUMER)
        row = self.session.scalars(
            select(ModuleMessage)
            .where(ModuleMessage.message_id == row.message_id)
            .with_for_update()
        ).one()
        previous = load_record(self.session, row.message_id) if row.result_json else None
        if previous is not None and previous.status == "ready":
            self.session.commit()
            return previous
        start = len(self.runner.run_ids)
        result = None
        successful_id = None
        error_code = None
        try:
            result, successful_id = self.runner.run(
                ROLE,
                None,
                request.model_dump(mode="json"),
                DiscoverySearchVocabularyV2,
                validate=partial(validate_vocabulary, request=request),
                repair=call_budget == 2,
            )
            if result is None:
                error_code = "VOCABULARY_AI_OUTPUT_INVALID"
                successful_id = None
        except EditorialError as exc:
            error_code = exc.code
        previous_ids = previous.ai_run_ids if previous else ()
        record = DiscoveryVocabularyRecord(
            run_id=row.message_id,
            created_at=previous.created_at if previous else datetime.now(UTC),
            policy_version=POLICY_VERSION,
            search_policy=SEARCH_POLICY,
            input_hash=identity,
            output_hash=canonical_payload_hash(result.model_dump(mode="json")) if result else None,
            profile_fingerprint=profile.fingerprint,
            provider=profile.provider,
            model=profile.model,
            prompt_version=profile.prompt_version,
            contract_hash=contract_hash,
            request=request,
            vocabulary=result,
            ai_run_ids=tuple(dict.fromkeys((*previous_ids, *self.runner.run_ids[start:]))),
            successful_ai_run_id=successful_id,
            status="ready" if result is not None else "failed",
            error_code=error_code,
        )
        row.result_json = record.model_dump(mode="json")
        row.status = "processed" if result else "failed"
        row.attempt += 1
        row.processed_at = datetime.now(UTC)
        self.session.commit()
        return record


def load_record(session: Session, run_id: UUID) -> DiscoveryVocabularyRecord:
    row = session.get(ModuleMessage, run_id)
    if row is None or row.consumer != CONSUMER or not row.result_json:
        raise EditorialError("VOCABULARY_RUN_NOT_FOUND")
    try:
        record = DiscoveryVocabularyRecord.model_validate(row.result_json)
    except ValueError:
        raise EditorialError("VOCABULARY_HISTORY_INVALID") from None
    payload = history_payload(record.request, record.profile_fingerprint, record.contract_hash)
    if (
        record.run_id != row.message_id
        or row.payload_json != payload
        or row.payload_hash != canonical_payload_hash(payload)
        or record.input_hash != row.payload_hash
        or record.contract_hash
        != canonical_payload_hash(DiscoverySearchVocabularyV2.model_json_schema())
    ):
        raise EditorialError("VOCABULARY_HISTORY_INVALID")
    if record.vocabulary is not None:
        validate_vocabulary(record.vocabulary, record.request)
        run = session.get(AiRun, record.successful_ai_run_id)
        input_hashes = {
            canonical_payload_hash(
                {
                    "data": record.request.model_dump(mode="json"),
                    "profile": record.profile_fingerprint,
                    "attempt": attempt,
                }
            )
            for attempt in (0, 1)
        }
        output = record.vocabulary.model_dump(mode="json")
        if (
            record.output_hash != canonical_payload_hash(output)
            or run is None
            or run.execution_role != ROLE
            or run.validation_status != "valid"
            or run.input_hash not in input_hashes
            or run.model != record.model
            or run.provider != record.provider
            or run.prompt_version != record.prompt_version
            or run.output_json != output
        ):
            raise EditorialError("VOCABULARY_AI_CACHE_INVALID")
    return record


def registered_articles(
    session: Session, item_ids: tuple[UUID, ...] | None = None
) -> Iterator[DiscoveryArticle]:
    query = (
        select(Item, ExtractionResult)
        .join(Source, Source.id == Item.source_id)
        .join(
            ExtractionResult,
            (ExtractionResult.item_id == Item.id) & (ExtractionResult.revision == Item.version),
        )
        .where(
            Source.enabled.is_(True),
            Source.legal_status == LegalStatus.APPROVED,
            Item.duplicate_of_id.is_(None),
        )
        .order_by(Item.id)
    )
    if item_ids is not None:
        query = query.where(Item.id.in_(item_ids))
    for item, extraction in session.execute(query):
        yield DiscoveryArticle(
            article_id=str(item.id),
            title=extraction.payload_json["title"],
            body=extraction.payload_json["body"],
        )


def load_input(
    session: Session, item_ids: tuple[UUID, ...], domain_hint: str | None = None
) -> DiscoveryVocabularyInput:
    if not 3 <= len(item_ids) <= 5 or len(set(item_ids)) != len(item_ids):
        raise ValueError("supply three to five unique item IDs")
    wanted = {str(item_id) for item_id in item_ids}
    found = {
        article.article_id: article
        for article in registered_articles(session, item_ids)
        if article.article_id in wanted
    }
    if set(found) != wanted:
        raise EditorialError("VOCABULARY_APPROVED_EXTRACTION_REQUIRED")
    return DiscoveryVocabularyInput(
        domain_hint=domain_hint, articles=tuple(found[str(item_id)] for item_id in item_ids)
    )


def export_record(record: DiscoveryVocabularyRecord, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "audit.json").write_text(record.model_dump_json(indent=2) + "\n", encoding="utf-8")
    if record.vocabulary is None:
        return
    (directory / "vocabulary.json").write_text(
        record.vocabulary.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    with (directory / "candidates.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            (
                "id",
                "label",
                "aliases",
                "layer",
                "priority",
                "origin",
                "definition",
                "source_article_ids",
                "reason",
            )
        )
        for concept in record.vocabulary.concepts:
            writer.writerow(
                (
                    concept.id,
                    concept.label,
                    json.dumps(concept.aliases, ensure_ascii=False),
                    concept.layer,
                    concept.priority,
                    concept.origin,
                    concept.definition,
                    json.dumps(concept.source_article_ids, ensure_ascii=False),
                    concept.reason,
                )
            )
