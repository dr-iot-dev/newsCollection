"""Checkpointed category search and ten-pair exploration. No publication approval."""

import csv
import io
import json
from collections.abc import Callable, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any, Protocol, TypeVar
from urllib.parse import unquote, urlsplit
from uuid import UUID

from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from app.ai.runner import AIRunner
from app.contracts.base import ContractModel
from app.contracts.comparison_pair_discovery_v3 import (
    ACQUISITION_POLICY,
    KEYWORD_POLICY,
    KEYWORD_TARGET,
    POLICY,
    PREPROCESSING,
    SEARCH_POLICY,
    SEARCH_RESULTS_PER_KEYWORD,
    CategoryKeywords,
    DocumentFeatures,
    PairDiscoveryRequest,
    PairDiscoveryState,
    PairDocument,
    PairEvent,
    PairPlan,
    TripleReview,
)
from app.contracts.envelope import ContractEnvelope, canonical_payload_hash
from app.core.comparison_pair_discovery import (
    CATEGORY_GENERIC,
    TITLE_EXCLUSION_TERMS,
    aggregate_vectors,
    bind_quote_offsets,
    coverage,
    distinctive_keywords,
    embedding_text,
    excluded_title_terms,
    keyword_match,
    matching_terms,
    norm,
    product_key,
    ranked_pairs,
    text_hash,
    third_ranking,
    validate_distinction,
    validate_features,
    validate_plan,
    validate_terms,
)
from app.core.config import Settings
from app.core.editorial import EditorialError, redact_contacts
from app.infrastructure.comparison_embeddings import (
    EmbeddingResponse,
    OpenAIEmbeddings,
    embedding_chunks,
)
from app.infrastructure.comparison_retrieval import Embedding, cosine
from app.infrastructure.db.models import AiRun, ModuleMessage, Source
from app.infrastructure.db.repositories.messages import ModuleMessageRepository
from app.infrastructure.prtimes_pair_acquisition import PRTimesPairAcquisition
from app.modules.acquisition.http import CollectionError
from app.modules.extraction.facts import evidence_passages

T = TypeVar("T", bound=ContractModel)
RUN_CONSUMER = "comparison_pair_run"
EVENT_CONSUMER = "comparison_pair_event"


class AcquisitionPort(Protocol):
    def initial(self, progress: dict[str, Any], count: int) -> tuple[PairDocument, ...]: ...
    def search(
        self, progress: dict[str, Any], keywords: CategoryKeywords, count: int
    ) -> tuple[PairDocument, ...]: ...
    def close(self) -> None: ...


class EmbeddingPort(Protocol):
    def embed(self, text: str) -> EmbeddingResponse: ...


class PairDiscoveryService:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        runner: AIRunner | None = None,
        acquisition: AcquisitionPort | None = None,
        embedder: EmbeddingPort | None = None,
        *,
        checkpoint: bool = True,
    ) -> None:
        self.session, self.settings = session, settings
        self.runner = runner or AIRunner(session, settings)
        self.acquisition, self.embedder = acquisition, embedder
        self.owns_acquisition = acquisition is None
        self.checkpoint = checkpoint
        self.state: PairDiscoveryState | None = None
        self.row: ModuleMessage | None = None
        self.calls_left = 0

    def fingerprint(self, request: PairDiscoveryRequest) -> str:
        source = self.session.scalar(select(Source).where(Source.key == request.source_key))
        return canonical_payload_hash(
            {
                "source_configuration": source.config if source else None,
                "policy": POLICY,
                "preprocessing": PREPROCESSING,
                "keyword_policy": KEYWORD_POLICY,
                "keyword_target": KEYWORD_TARGET,
                "keyword_max_input_chars": self.settings.ai_pair_keyword_max_input_chars,
                "keyword_max_output_tokens": self.settings.ai_pair_keyword_max_output_tokens,
                "search_policy": SEARCH_POLICY,
                "acquisition_policy": ACQUISITION_POLICY,
                "title_exclusion_terms": TITLE_EXCLUSION_TERMS,
                "search_results_per_keyword": SEARCH_RESULTS_PER_KEYWORD,
                "embedding_model": self.settings.ai_embedding_model,
                "embedding_revision": self.settings.ai_embedding_revision,
                "source_config_path": str(self.settings.sources_config_path),
                "profiles": {
                    role: self.runner.profile(role).fingerprint
                    for role in (
                        "pair_keywords",
                        "pair_category",
                        "pair_plan",
                        "pair_cells",
                        "pair_review",
                    )
                },
            }
        )

    def save(self, **changes: Any) -> None:
        assert self.state is not None and self.row is not None
        self.state = PairDiscoveryState.model_validate(
            {
                **self.state.model_dump(mode="python"),
                **changes,
            }
        )
        self.row.result_json = self.state.model_dump(mode="json")
        self.row.status = (
            "processed"
            if self.state.status in {"selection_passed", "exhausted"}
            else "pair_checkpoint"
        )
        self.row.processed_at = datetime.now(UTC)
        self.session.flush()
        if self.checkpoint:
            self.session.commit()

    def event(self, step: int, **data: Any) -> None:
        assert self.state is not None
        sequence = self.state.sequence + 1
        event = PairEvent(run_id=self.state.request.run_id, sequence=sequence, step=step, data=data)
        ModuleMessageRepository(self.session).enqueue_once(
            ContractEnvelope.build(
                event,
                contract_type="PairDiscoveryEvent",
                schema_version="3.0",
                producer="comparison_pair",
                producer_version="0.4.0",
                correlation_id=self.state.request.run_id,
            ),
            consumer=EVENT_CONSUMER,
            status="processed",
        )
        self.save(sequence=sequence)

    def reserve(self, *, ai: bool = False) -> None:
        assert self.state is not None
        if self.calls_left <= 0:
            raise EditorialError("PAIR_CALL_BUDGET")
        self.calls_left -= 1
        self.save(
            external_calls=self.state.external_calls + 1, ai_calls=self.state.ai_calls + int(ai)
        )

    def acquisition_checkpoint(self, progress: dict[str, Any]) -> None:
        self.save(acquisition=progress)

    def stage(
        self,
        role: str,
        documents: Sequence[PairDocument],
        data: dict[str, Any],
        model: type[T],
        validate: Callable[[T], None],
    ) -> T:
        assert self.state is not None
        identity = canonical_payload_hash(
            {
                "data": data,
                "profile": self.runner.profile(role).fingerprint,
                "schema": model.model_json_schema(),
                "policy": POLICY,
                "keyword_policy": KEYWORD_POLICY,
            }
        )
        cached = self.state.stages.get(identity)
        if cached is not None:
            run = self.session.get(AiRun, UUID(cached["ai_run_id"]))
            if (
                run is None
                or run.validation_status != "valid"
                or run.execution_role != role
                or run.model != self.runner.profile(role).model
                or run.output_json != cached["output"]
            ):
                raise EditorialError("PAIR_AI_CACHE_INVALID")
            cached_result = model.model_validate(cached["output"])
            validate(cached_result)
            return cached_result
        normalization: dict[str, Any] = (
            {"category_context": data.get("category_context", {})}
            if role in {"pair_keywords", "pair_category"}
            else {}
        )
        if role == "pair_category":
            normalization["document_frequency"] = data.get("document_frequency", [])

        def normalize_output(value: T) -> T:
            # An explicit negative comparison does not assert any product/axis facts.
            if isinstance(value, PairPlan) and not value.comparable:
                normalization.update(policy="negative_plan_has_no_adoptable_products_or_axes")
                return type(value).model_validate(
                    value.model_copy(update={"products": (), "axes": ()}).model_dump(mode="json")
                )
            bound = bind_quote_offsets(value, {d.item_id: d for d in documents})
            if isinstance(bound, CategoryKeywords):
                context = data.get("category_context", {})
                cleaned, decisions = distinctive_keywords(bound, context.get("category", ""))
                normalization.update(
                    original_terms=len(bound.terms),
                    retained_terms=len(cleaned.terms),
                    policy=KEYWORD_POLICY,
                    decisions=decisions,
                )
                return type(value).model_validate(cleaned.model_dump(mode="json"))
            return bound

        first_attempt = len(self.runner.run_ids)
        try:
            result, run_id = self.runner.run(
                role,
                documents[0].item_id,
                data,
                model,
                validate=validate,
                normalize=normalize_output,
                repair=True,
                before_call=lambda: self.reserve(ai=True),
            )
        finally:
            attempts = self.runner.run_ids[first_attempt:]
            if attempts:
                self.save(
                    ai_attempt_ids=tuple(dict.fromkeys((*self.state.ai_attempt_ids, *attempts)))
                )
        self.session.flush()
        if result is None or run_id is None:
            self.save()
            raise EditorialError("PAIR_AI_OUTPUT_INVALID", 503)
        stages = {
            **self.state.stages,
            identity: {
                "role": role,
                "ai_run_id": str(run_id),
                "output": result.model_dump(mode="json"),
                "normalization": normalization,
            },
        }
        self.save(stages=stages)
        return result

    @staticmethod
    def document_data(document: PairDocument) -> dict[str, Any]:
        return {
            "item_id": str(document.item_id),
            "title": document.title,
            "body": redact_contacts(document.body),
            "evidence_passages": evidence_passages(redact_contacts(document.body)),
            "item_version": document.item_version,
            "body_hash": document.body_hash,
        }

    def keywords(self, initial: Sequence[PairDocument]) -> CategoryKeywords:
        extracted = []
        docs = {doc.item_id: doc for doc in initial}
        source = (
            self.session.scalar(select(Source).where(Source.key == self.state.request.source_key))
            if self.state
            else None
        )
        category_url = str(source.config.get("list_url", "")) if source else ""
        if not category_url and initial:
            category_url = initial[0].category_proof
        category = unquote(urlsplit(category_url).path.rsplit("/", 1)[-1])
        context = {
            "category": category,
            "policy": KEYWORD_POLICY,
            "keyword_target": KEYWORD_TARGET,
            "excluded_generic_forms": sorted(CATEGORY_GENERIC | {category}),
        }
        for doc in initial:

            def check_keywords(value: CategoryKeywords, doc: PairDocument = doc) -> None:
                validate_terms(value.terms, {doc.item_id: doc})
                validate_distinction(value)

            value = self.stage(
                "pair_keywords",
                (doc,),
                {"source": self.document_data(doc), "category_context": context},
                CategoryKeywords,
                check_keywords,
            )
            extracted.append({"item_id": str(doc.item_id), **value.model_dump(mode="json")})
        # Keep complete specific forms; generic substrings cannot replace the source concepts.
        originals = [term for entry in extracted for term in entry["terms"]]
        refs = [ref for term in originals for ref in term["evidence"]]
        forms = {form for term in originals for form in (term["label"], *term["aliases"])}

        def check_category(value: CategoryKeywords) -> None:
            validate_terms(value.terms, docs)
            validate_distinction(value)
            if any(
                any(
                    not any(norm(original) == norm(form) for original in forms)
                    for form in (term.label, *term.aliases)
                )
                or any(
                    not any(
                        str(ref.item_id) == original["item_id"]
                        and original["start"] <= ref.start < ref.end <= original["end"]
                        for original in refs
                    )
                    for ref in term.evidence
                )
                for term in value.terms
            ):
                raise EditorialError("PAIR_CATEGORY_NOT_GROUNDED")

        result = self.stage(
            "pair_category",
            initial,
            {
                "source_key": self.state.request.source_key if self.state else "",
                "category_context": context,
                "grounded_keywords": extracted,
                "document_frequency": [
                    {
                        "key": term["key"],
                        "label": term["label"],
                        "aliases": term["aliases"],
                        "document_count": sum(
                            bool(
                                matching_terms(
                                    embedding_text(doc)[0],
                                    (
                                        CategoryKeywords.model_validate(
                                            {"terms": [term], "reason": "frequency"}
                                        ).terms[0],
                                    ),
                                )
                            )
                            for doc in initial
                        ),
                    }
                    for entry in extracted
                    for term in entry["terms"]
                ],
            },
            CategoryKeywords,
            check_category,
        )
        self.event(
            2,
            keyword_target=KEYWORD_TARGET,
            keyword_count=len(result.terms),
            shortfall=max(0, KEYWORD_TARGET - len(result.terms)),
            reason=result.reason,
        )
        return result

    def vectors(self) -> dict[UUID, Embedding]:
        assert self.state is not None and self.embedder is not None
        vectors: dict[UUID, Embedding] = {}
        for doc in self.state.group_a:
            clean, removed = embedding_text(doc)
            chunks = embedding_chunks(clean)
            saved = dict(self.state.embeddings.get(str(doc.item_id), {}))
            if saved and saved.get("input_hash") != text_hash(clean):
                raise EditorialError("PAIR_EMBEDDING_CACHE_MISMATCH")
            parts = list(saved.get("chunks", []))
            for chunk in chunks[len(parts) :]:
                self.reserve()
                response = self.embedder.embed(chunk)
                candidate = Embedding(
                    "openai", response.model, self.settings.ai_embedding_revision, response.values
                )
                cosine(candidate, candidate)
                if parts and (
                    parts[0]["model"] != response.model
                    or len(parts[0]["values"]) != len(response.values)
                ):
                    raise EditorialError("PAIR_EMBEDDING_MODEL_MISMATCH")
                parts.append(
                    {
                        **asdict(response),
                        "input_hash": text_hash(chunk),
                        "weight": len(chunk.encode()),
                    }
                )
                saved.update(
                    input_hash=text_hash(clean),
                    preprocessing=PREPROCESSING,
                    removed=list(removed),
                    chunks=parts,
                )
                self.save(embeddings={**self.state.embeddings, str(doc.item_id): saved})
            if len(parts) != len(chunks) or any(
                part["input_hash"] != text_hash(chunk)
                for part, chunk in zip(parts, chunks, strict=True)
            ):
                raise EditorialError("PAIR_EMBEDDING_CHUNKS_MISMATCH")
            merged = aggregate_vectors(
                [part["values"] for part in parts], [part["weight"] for part in parts]
            )
            vectors[doc.item_id] = Embedding(
                "openai",
                parts[0]["model"],
                self.settings.ai_embedding_revision,
                merged,
            )
            saved["vector"] = list(merged)
            self.save(embeddings={**self.state.embeddings, str(doc.item_id): saved})
            self.event(
                4,
                item_id=str(doc.item_id),
                input_hash=text_hash(clean),
                chunks=len(parts),
                dimensions=len(merged),
                removed=len(removed),
            )
        return vectors

    def features(self, document: PairDocument, plan: PairPlan) -> DocumentFeatures:
        return self.stage(
            "pair_cells",
            (document,),
            {
                "source": self.document_data(document),
                "purpose": plan.purpose,
                "axes": [a.model_dump(mode="json") for a in plan.axes],
            },
            DocumentFeatures,
            lambda value: validate_features(value, document, plan.axes),
        )

    def explore(self, vectors: dict[UUID, Embedding]) -> None:
        assert self.state is not None
        docs = {d.item_id: d for d in self.state.group_a}
        for pair in self.state.distances[self.state.completed_pairs : 10]:
            pair_docs = (docs[pair.left], docs[pair.right])
            self.event(
                6, pair=pair.model_dump(mode="json"), completed_pairs=self.state.completed_pairs
            )
            plan = self.stage(
                "pair_plan",
                pair_docs,
                {"sources": [self.document_data(doc) for doc in pair_docs]},
                PairPlan,
                partial(validate_plan, documents={d.item_id: d for d in pair_docs}),
            )
            result: dict[str, Any] = {
                "pair": pair.model_dump(mode="json"),
                "plan": plan.model_dump(mode="json"),
                "trials": [],
                "reason": "",
            }
            # Trials for an interrupted pair are retained in a checkpoint stage slot.
            progress_key = "pair-progress:" + str(pair.rank)
            result = self.state.stages.get(progress_key, result)
            if not plan.comparable or len(plan.axes) < 3:
                result["reason"] = "pair_not_comparable_or_axes_insufficient"
            elif len({product_key(p) for p in plan.products}) < 2:
                result["reason"] = "pair_products_not_distinct"
            else:
                group_b = [
                    doc
                    for doc in self.state.group_a
                    if len(matching_terms(embedding_text(doc)[0], plan.axes)) >= 3
                ]
                ranking = third_ranking(pair, [d.item_id for d in group_b], vectors)
                result.update(group_b=[str(d.item_id) for d in group_b], ranking=list(ranking))
                self.event(
                    7,
                    pair_rank=pair.rank,
                    group_b=result["group_b"],
                    count=len(group_b),
                    third_candidates=len(ranking),
                )
                self.save(stages={**self.state.stages, progress_key: result})
                completed = {trial["third_item_id"] for trial in result["trials"]}
                for candidate in ranking:
                    third_id = UUID(str(candidate["item_id"]))
                    if str(third_id) in completed:
                        continue
                    self.event(8, pair_rank=pair.rank, **candidate)
                    selected = (*pair_docs, docs[third_id])
                    features = tuple(self.features(doc, plan) for doc in selected)
                    # A product mismatch relative to the frozen pair plan is invalid AI output.
                    if any(
                        product_key(f.product) != product_key(p)
                        for f, p in zip(features[:2], plan.products, strict=True)
                    ):
                        # Pair products can be returned in either order.
                        expected = {p.item_id: product_key(p) for p in plan.products}
                        if any(
                            product_key(f.product) != expected[f.product.item_id]
                            for f in features[:2]
                        ):
                            raise EditorialError("PAIR_PRODUCT_CHANGED")
                    try:
                        counts = coverage(features, plan.axes)
                        supported = tuple(key for key, count in counts.items() if count >= 2)
                        duplicate = False
                    except EditorialError as exc:
                        if exc.code != "PAIR_DUPLICATE_PRODUCT":
                            raise
                        counts, supported, duplicate = {}, (), True
                    review = None
                    if len(supported) >= 3:

                        def validate_review(
                            value: TripleReview, supported: tuple[str, ...] = supported
                        ) -> None:
                            if len(set(value.valid_axis_keys)) != len(
                                value.valid_axis_keys
                            ) or not set(value.valid_axis_keys) <= set(supported):
                                raise EditorialError("PAIR_REVIEW_AXES_INVALID")

                        review = self.stage(
                            "pair_review",
                            selected,
                            {
                                "purpose": plan.purpose,
                                "axes": [a.model_dump(mode="json") for a in plan.axes],
                                "features": [f.model_dump(mode="json") for f in features],
                                "coverage": counts,
                            },
                            TripleReview,
                            validate_review,
                        )
                    passed = bool(
                        review
                        and review.same_selection_task
                        and review.evidence_valid
                        and review.conditions_preserved
                        and len(review.valid_axis_keys) >= 3
                    )
                    trial = {
                        "third_item_id": str(third_id),
                        "distances": candidate,
                        "features": [f.model_dump(mode="json") for f in features],
                        "coverage": counts,
                        "supported_axes": list(supported),
                        "review": review.model_dump(mode="json") if review else None,
                        "passed": passed,
                        "reason": (
                            "duplicate_product"
                            if duplicate
                            else "passed"
                            if passed
                            else "insufficient_coverage_or_review_failed"
                        ),
                    }
                    result["trials"] = [*result["trials"], trial]
                    self.save(stages={**self.state.stages, progress_key: result})
                    self.event(
                        9,
                        pair_rank=pair.rank,
                        third_item_id=str(third_id),
                        coverage=counts,
                        passed=passed,
                        reason=trial["reason"],
                    )
                    if passed:
                        selected_payload = {
                            "item_ids": [str(d.item_id) for d in selected],
                            "documents": [d.model_dump(mode="json") for d in selected],
                            "plan": plan.model_dump(mode="json"),
                            "trial": trial,
                            "selection_only": True,
                        }
                        selected_payload["frozen_hash"] = canonical_payload_hash(selected_payload)
                        result["reason"] = "passed"
                        self.save(
                            completed_pairs=self.state.completed_pairs + 1,
                            pair_results=(*self.state.pair_results, result),
                            status="selection_passed",
                            selected=selected_payload,
                            reason="at_least_three_axes_with_two_of_three_sources",
                        )
                        return
                    self.event(
                        10, pair_rank=pair.rank, remaining=len(ranking) - len(result["trials"])
                    )
                result["reason"] = (
                    "all_third_candidates_failed" if ranking else "no_third_candidates"
                )
            self.save(
                completed_pairs=self.state.completed_pairs + 1,
                pair_results=(*self.state.pair_results, result),
            )
            self.event(11, completed_pairs=self.state.completed_pairs, reason=result["reason"])
        if self.state.completed_pairs == 10:
            self.save(status="exhausted", reason="ten_pairs_completed_without_comparison")
        else:
            self.save(
                status="insufficient_pairs",
                reason="fewer_than_ten_pairs_available_not_search_exhaustion",
            )

    def run(self, request: PairDiscoveryRequest, *, call_budget: int = 100) -> PairDiscoveryState:
        if call_budget < 1:
            raise EditorialError("PAIR_INVALID_BUDGET")
        self.calls_left = call_budget
        lock_key = int.from_bytes(request.run_id.bytes[:8], "big", signed=True)
        bind = self.session.get_bind()
        lock_connection = None
        if bind.dialect.name == "postgresql":
            if not isinstance(bind, Engine):
                raise EditorialError("PAIR_DEDICATED_ENGINE_REQUIRED")
            lock_connection = bind.connect()
            if not lock_connection.scalar(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": lock_key}
            ):
                lock_connection.close()
                raise EditorialError("PAIR_RUN_ALREADY_ACTIVE")
        try:
            return self._run(request)
        finally:
            if self.acquisition is not None:
                self.acquisition.close()
                if self.owns_acquisition:
                    self.acquisition = None
            if lock_connection is not None:
                try:
                    lock_connection.execute(
                        text("SELECT pg_advisory_unlock(:key)"), {"key": lock_key}
                    )
                    lock_connection.commit()
                finally:
                    lock_connection.close()

    def _run(self, request: PairDiscoveryRequest) -> PairDiscoveryState:
        fingerprint = self.fingerprint(request)
        row = self.session.get(ModuleMessage, request.run_id)
        if row is None:
            envelope = ContractEnvelope.build(
                request,
                contract_type="PairDiscoveryRequest",
                schema_version="3.0",
                producer="comparison_pair",
                producer_version="0.4.0",
                correlation_id=request.run_id,
            ).model_copy(update={"message_id": request.run_id})
            row = ModuleMessageRepository(self.session).enqueue_once(
                envelope, consumer=RUN_CONSUMER
            )
        if (
            row.consumer != RUN_CONSUMER
            or row.payload_hash != canonical_payload_hash(row.payload_json)
            or row.payload_hash != canonical_payload_hash(request.model_dump(mode="json"))
        ):
            raise EditorialError("PAIR_RUN_REQUEST_MISMATCH")
        self.row = row
        self.state = (
            PairDiscoveryState.model_validate(row.result_json)
            if row.result_json
            else PairDiscoveryState(request=request, fingerprint=fingerprint)
        )
        if self.state.fingerprint != fingerprint or self.state.policy != POLICY:
            raise EditorialError("PAIR_RESUME_CONFIGURATION_CHANGED")
        if self.state.status in {"selection_passed", "exhausted"}:
            return self.state
        self.save(status="running", reason="")
        try:
            models = [
                self.runner.profile(role).model
                for role in ("pair_plan", "pair_cells", "pair_review")
            ]
            if not all(models) or models[2] in models[:2]:
                raise EditorialError("PAIR_INDEPENDENT_MODEL_REQUIRED")
            if not self.settings.ai_embedding_model or not self.settings.ai_embedding_revision:
                raise EditorialError("PAIR_EMBEDDING_MODEL_REQUIRED")
            if self.acquisition is None:
                self.acquisition = PRTimesPairAcquisition(
                    self.session,
                    request.source_key,
                    self.acquisition_checkpoint,
                    lambda: self.reserve(),
                )
            if self.embedder is None:
                if self.settings.ai_provider != "openai" or self.settings.ai_api_key is None:
                    raise EditorialError("PAIR_AI_NOT_CONFIGURED")
                self.embedder = OpenAIEmbeddings(
                    self.settings.ai_api_key.get_secret_value(), self.settings.ai_embedding_model
                )
            if not self.state.initial:
                initial = self.acquisition.initial(
                    dict(self.state.acquisition), request.initial_count
                )
                if any(excluded_title_terms(doc.title) for doc in initial):
                    raise EditorialError("PAIR_INITIAL_TITLE_EXCLUDED")
                self.save(initial=initial)
                self.event(1, item_ids=[str(d.item_id) for d in initial], count=len(initial))
            if len(self.state.initial) < 3:
                self.save(status="insufficient_sources", reason="initial_sample_below_three")
                return self.state
            if self.state.keywords is None:
                self.save(keywords=self.keywords(self.state.initial))
                self.event(
                    2,
                    keywords=self.state.keywords.model_dump(mode="json")
                    if self.state.keywords
                    else {},
                )
            assert self.state.keywords is not None
            if len(self.state.keywords.terms) < 3:
                self.save(
                    status="insufficient_keywords", reason="fewer_than_three_category_keywords"
                )
                return self.state
            if not self.state.acquisition.get("search_complete"):
                group = self.acquisition.search(
                    dict(self.state.acquisition), self.state.keywords, request.maximum_documents
                )
                initial_source_ids = {d.source_id for d in self.state.initial}
                ids, hashes = set(), set()
                for doc in group:
                    if (
                        doc.source_id not in initial_source_ids
                        or excluded_title_terms(doc.title)
                        or len(keyword_match(doc, self.state.keywords)) < 3
                        or doc.item_id in ids
                        or doc.body_hash in hashes
                    ):
                        raise EditorialError("PAIR_GROUP_A_INVALID")
                    ids.add(doc.item_id)
                    hashes.add(doc.body_hash)
                if len(group) > request.maximum_documents:
                    raise EditorialError("PAIR_GROUP_A_LIMIT")
                self.save(group_a=group)
                self.event(
                    3,
                    item_ids=[str(d.item_id) for d in group],
                    count=len(group),
                    search_policy=SEARCH_POLICY,
                    keyword_count=len(self.state.keywords.terms),
                    results_per_keyword=SEARCH_RESULTS_PER_KEYWORD,
                    unique_search_articles=self.state.acquisition.get("search_unique_articles"),
                    three_keyword_candidates=self.state.acquisition.get(
                        "search_candidates_three_keywords"
                    ),
                )
            elif not self.state.group_a:
                self.save(
                    group_a=tuple(
                        PairDocument.model_validate(d)
                        for d in self.state.acquisition.get("accepted", [])
                    )
                )
            if len(self.state.group_a) < 3:
                self.save(status="insufficient_sources", reason="group_a_below_three")
                return self.state
            vectors = self.vectors()
            distances = ranked_pairs(vectors)
            if self.state.distances and distances != self.state.distances:
                raise EditorialError("PAIR_DISTANCE_SNAPSHOT_CHANGED")
            if not self.state.distances:
                self.save(distances=distances)
                self.event(
                    5,
                    document_count=len(vectors),
                    pair_count=len(distances),
                    metric="one_minus_cosine",
                )
            self.explore(vectors)
        except (EditorialError, CollectionError, ValueError) as exc:
            code = (
                exc.code
                if isinstance(exc, (EditorialError, CollectionError))
                else "PAIR_INPUT_INVALID"
            )
            status = (
                "paused_budget"
                if code in {"PAIR_CALL_BUDGET", "PAGE_LIMIT"}
                else "failed_configuration"
                if code
                in {
                    "PAIR_INDEPENDENT_MODEL_REQUIRED",
                    "PAIR_EMBEDDING_MODEL_REQUIRED",
                    "PAIR_AI_NOT_CONFIGURED",
                    "AI_NOT_CONFIGURED",
                    "PAIR_SOURCE_NOT_FOUND",
                    "PAIR_PRTIMES_SOURCE_REQUIRED",
                    "PAIR_KEYWORD_CATEGORY_REQUIRED",
                }
                else "waiting_retry"
            )
            self.save(status=status, reason=code)
            self.event(12, status=status, reason=code, completed_pairs=self.state.completed_pairs)
        assert self.state is not None
        self.event(
            12,
            status=self.state.status,
            completed_pairs=self.state.completed_pairs,
            selected=self.state.selected["item_ids"] if self.state.selected else [],
        )
        return self.state


def load_pair_request(session: Session, run_id: UUID) -> PairDiscoveryRequest:
    row = session.get(ModuleMessage, run_id)
    if row is None or row.consumer != RUN_CONSUMER:
        raise EditorialError("PAIR_RUN_NOT_FOUND")
    if row.payload_hash != canonical_payload_hash(row.payload_json):
        raise EditorialError("PAIR_RUN_HASH_INVALID")
    return PairDiscoveryRequest.model_validate(row.payload_json)


def export_pair_run(session: Session, run_id: UUID, directory: Path) -> None:
    request = load_pair_request(session, run_id)
    row = session.get(ModuleMessage, run_id)
    assert row is not None and row.result_json is not None
    state = PairDiscoveryState.model_validate(row.result_json)
    events = list(
        session.scalars(
            select(ModuleMessage)
            .where(ModuleMessage.consumer == EVENT_CONSUMER, ModuleMessage.correlation_id == run_id)
            .order_by(ModuleMessage.created_at, ModuleMessage.message_id)
        )
    )
    event_values = sorted((event.payload_json for event in events), key=lambda e: e["sequence"])
    directory.mkdir(parents=True, exist_ok=True)
    attempt_ids = set(state.ai_attempt_ids)
    attempt_ids.update(
        UUID(stage["ai_run_id"]) for stage in state.stages.values() if "ai_run_id" in stage
    )
    ai_runs = [session.get(AiRun, run_id) for run_id in sorted(attempt_ids, key=str)]
    provenance = [
        {
            "ai_run_id": str(run.id),
            "role": run.execution_role,
            "model": run.model,
            "prompt_version": run.prompt_version,
            "input_hash": run.input_hash,
            "validation_status": run.validation_status,
            "validation_errors": run.validation_errors_json,
            "token_in": run.token_in,
            "token_out": run.token_out,
            "cost_estimate": str(run.cost_estimate) if run.cost_estimate is not None else None,
            "latency_ms": run.latency_ms,
        }
        for run in ai_runs
        if run is not None
    ]
    keyword_frequency = [
        {
            "key": term.key,
            "label": term.label,
            "document_count": len(matched),
            "item_ids": matched,
            "basis": "derived_from_frozen_initial_documents",
        }
        for term in (state.keywords.terms if state.keywords else ())
        for matched in [
            [
                str(doc.item_id)
                for doc in state.initial
                if term.key in matching_terms(embedding_text(doc)[0], (term,))
            ]
        ]
    ]
    audit = {
        "state": state.model_dump(mode="json"),
        "events": event_values,
        "ai_runs": provenance,
        "keyword_document_frequency": keyword_frequency,
    }
    (directory / "ai-runs.json").write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (directory / "audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        (
            "keyword_key",
            "label",
            "query",
            "page",
            "rank",
            "article_id",
            "url",
            "title",
            "snapshot_id",
        )
    )
    keyword_results = state.acquisition.get("keyword_results", {})
    for search in keyword_results.values():
        for result in search["results"]:
            writer.writerow(
                (
                    search["keyword_key"],
                    search["label"],
                    search["query"],
                    result["page"],
                    result["rank"],
                    result["article_id"],
                    result["url"],
                    result["title"],
                    result["snapshot_id"],
                )
            )
    (directory / "keyword-search-results.csv").write_text(buffer.getvalue(), encoding="utf-8-sig")
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(("keyword_key", "label", "saved_count", "target", "complete", "end_reason"))
    for search in keyword_results.values():
        writer.writerow(
            (
                search["keyword_key"],
                search["label"],
                len(search["results"]),
                state.acquisition.get("results_per_keyword"),
                search["complete"],
                search["end_reason"],
            )
        )
    (directory / "keyword-search-summary.csv").write_text(buffer.getvalue(), encoding="utf-8-sig")
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        (
            "article_id",
            "url",
            "title",
            "keyword_count",
            "keyword_keys",
            "labels",
            "body_keyword_count",
            "rejection",
            "title_exclusion_terms",
            "candidate_eligible",
        )
    )
    terms = {term.key: term.label for term in state.keywords.terms} if state.keywords else {}
    checked = {row["url"]: row for row in state.acquisition.get("results", [])}
    for article in sorted(
        state.acquisition.get("article_keyword_counts", {}).values(),
        key=lambda row: (-row["keyword_count"], row["article_id"]),
    ):
        check = checked.get(article["url"])
        writer.writerow(
            (
                article["article_id"],
                article["url"],
                article["title"],
                article["keyword_count"],
                ";".join(article["keyword_keys"]),
                ";".join(terms[key] for key in article["keyword_keys"]),
                len(check["hits"]) if check and check.get("item_id") else "",
                check["rejection"]
                if check
                else ("title_excluded" if article.get("title_exclusion_terms") else "not_fetched"),
                ";".join(
                    dict.fromkeys(
                        [
                            *article.get("title_exclusion_terms", []),
                            *(check or {}).get("acquisition", {}).get("title_exclusion_terms", []),
                        ]
                    )
                ),
                article.get("candidate_eligible", ""),
            )
        )
    (directory / "article-keyword-counts.csv").write_text(buffer.getvalue(), encoding="utf-8-sig")
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(("rank", "url", "title", "item_id", "rejection", "title_exclusion_terms"))
    for result in state.acquisition.get("initial_results", []):
        acquisition = result.get("acquisition", {})
        writer.writerow(
            (
                result["rank"],
                result["url"],
                acquisition.get("title", ""),
                result.get("item_id"),
                result.get("rejection"),
                ";".join(acquisition.get("title_exclusion_terms", [])),
            )
        )
    (directory / "initial-selection.csv").write_text(buffer.getvalue(), encoding="utf-8-sig")
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(("rank", "left_item_id", "right_item_id", "distance"))
    for pair in state.distances:
        writer.writerow((pair.rank, pair.left, pair.right, pair.distance))
    (directory / "pair-distances.csv").write_text(buffer.getvalue(), encoding="utf-8-sig")
    results = list(state.pair_results)
    current = state.stages.get("pair-progress:" + str(state.completed_pairs + 1))
    if current:
        results.append(current)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ("pair_rank", "third_item_id", "left_distance", "right_distance", "mean_distance")
    )
    for result in results:
        for candidate in result.get("ranking", []):
            writer.writerow(
                (
                    result["pair"]["rank"],
                    candidate["item_id"],
                    candidate["left_distance"],
                    candidate["right_distance"],
                    candidate["distance"],
                )
            )
    (directory / "third-distances.csv").write_text(buffer.getvalue(), encoding="utf-8-sig")
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(("pair_rank", "third_item_id", "axis", "source_count", "passed"))
    for result in results:
        for trial in result["trials"]:
            for axis, count in trial["coverage"].items():
                writer.writerow(
                    (result["pair"]["rank"], trial["third_item_id"], axis, count, trial["passed"])
                )
    (directory / "coverage.csv").write_text(buffer.getvalue(), encoding="utf-8-sig")
    summary = [
        f"# 比較資料探索 {request.run_id}",
        "",
        f"- 収集元: {request.source_key}",
        f"- 状態: {state.status}",
        f"- 理由: {state.reason}",
        f"- 初期資料: {len(state.initial)}",
        f"- 特徴語: {len(state.keywords.terms) if state.keywords else 0} / 目標 {KEYWORD_TARGET}",
        f"- 検索結果保存目標: 1語につき{SEARCH_RESULTS_PER_KEYWORD}件",
        f"- 検索で発見した異なる記事: {state.acquisition.get('search_unique_articles', 0)}",
        f"- 検索3語以上・タイトル除外後の候補: "
        f"{state.acquisition.get('search_candidates_three_keywords', 0)}",
        f"- 検索3語以上からタイトルで除外: "
        f"{len(state.acquisition.get('candidate_exclusions', []))}",
        f"- 資料群A(確定): {len(state.group_a)}",
        f"- 資料群A(取得途中の採用候補): {len(state.acquisition.get('accepted', []))}",
        f"- 完了ペア: {state.completed_pairs}/10",
        f"- 外部呼出し: {state.external_calls}(AI生成: {state.ai_calls})",
        "",
        "## 工程履歴",
        "",
    ]
    for event in event_values:
        summary.append(
            f"- ステップ{event['step']} / 記録{event['sequence']}: "
            + json.dumps(event["data"], ensure_ascii=False)
        )
    if state.selected:
        frozen = {k: v for k, v in state.selected.items() if k != "frozen_hash"}
        if canonical_payload_hash(frozen) != state.selected["frozen_hash"]:
            raise EditorialError("PAIR_SELECTION_HASH_INVALID")
        (directory / "selection.json").write_text(
            json.dumps(state.selected, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

        def table_text(value: str) -> str:
            return value.replace("|", r"\|").replace("\n", "<br>")

        features = state.selected["trial"]["features"]
        valid_axes = set(state.selected["trial"]["review"]["valid_axis_keys"])
        comparison = [
            "# 比較記事用の資料表",
            "",
            state.selected["plan"]["purpose"],
            "",
            "| 比較項目 | " + " | ".join(table_text(f["product"]["name"]) for f in features) + " |",
            "| --- | " + " | ".join("---" for _ in features) + " |",
        ]
        for axis in state.selected["plan"]["axes"]:
            if axis["key"] not in valid_axes:
                continue
            cells = []
            for feature in features:
                cell = next(c for c in feature["cells"] if c["axis_key"] == axis["key"])
                answer = (
                    cell["answer"]
                    if cell["status"] not in {"unknown", "incomparable"}
                    else "資料から確認できず"
                )
                if cell["conditions"]:
                    answer += "(" + cell["conditions"] + ")"
                cells.append(table_text(answer))
            comparison.append(
                "| " + table_text(axis["question"]) + " | " + " | ".join(cells) + " |"
            )
        comparison.extend(("", "## 出典", ""))
        comparison.extend(f"- [{d['title']}]({d['url']})" for d in state.selected["documents"])
        comparison.extend(("", "記事作成用の資料表。原稿の検証・公開承認は別工程。"))
        (directory / "comparison.md").write_text("\n".join(comparison) + "\n", encoding="utf-8")
        summary.extend(
            (
                "",
                "## 採用資料",
                "",
                *(f"- [{d['title']}]({d['url']})" for d in state.selected["documents"]),
                "",
                "選択合格のみ。記事の公開・送信承認とは別の結果です。",
            )
        )
    (directory / "report.md").write_text("\n".join(summary) + "\n", encoding="utf-8")
