"""Search vocabulary only; independent of comparison axes and values."""

import re
import unicodedata
from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from app.contracts.base import ContractModel

SPEC_VERSION = "discovery-search-vocabulary-v2"
POLICY_VERSION = "discovery-search-vocabulary-v2.1"
SEARCH_POLICY = "discovery-vocabulary-nfkc-casefold-boundaries-v1"
ROLE = "discovery_vocabulary"
Text = Annotated[str, Field(min_length=1, strict=True)]
Term = Annotated[str, Field(min_length=1, max_length=24, strict=True)]
Layer = Literal["input", "mechanism", "output", "operations"]


def normalized_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def unique_text(values: tuple[str, ...], name: str) -> None:
    keys = [normalized_text(value) for value in values]
    if any(not key for key in keys) or len(keys) != len(set(keys)):
        raise ValueError(f"{name} must contain nonblank, unique text")


def unique_ids(values: tuple[str, ...], name: str) -> None:
    # IDs are opaque and case-sensitive; search normalization applies to names only.
    if any(not value.strip() for value in values) or len(values) != len(set(values)):
        raise ValueError(f"{name} must contain nonblank, unique IDs")


class DiscoveryArticle(ContractModel):
    article_id: Text
    title: Annotated[str, Field(strict=True)]
    body: Text

    @model_validator(mode="after")
    def nonblank(self) -> Self:
        if not self.article_id.strip() or not self.body.strip():
            raise ValueError("article_id and body must be nonblank")
        return self


class DiscoveryVocabularyInput(ContractModel):
    domain_hint: Annotated[str | None, Field(strict=True)] = None
    articles: tuple[DiscoveryArticle, ...] = Field(min_length=3, max_length=5)

    @model_validator(mode="after")
    def distinct_articles(self) -> Self:
        ids = [article.article_id for article in self.articles]
        if len(ids) != len(set(ids)):
            raise ValueError("article_id must be unique within input")
        return self


class SearchConcept(ContractModel):
    id: Text
    label: Term
    definition: Text
    aliases: tuple[Term, ...]
    layer: Layer
    priority: Literal["high", "normal"]
    origin: Literal["observed", "generalized", "domain_expansion"]
    source_article_ids: tuple[Text, ...]
    reason: Text

    @model_validator(mode="after")
    def concept_rules(self) -> Self:
        unique_text((self.label, *self.aliases), "label and aliases")
        unique_ids(self.source_article_ids, "source_article_ids")
        if any(not value.strip() for value in (self.id, self.definition, self.reason)):
            raise ValueError("id, definition and reason must be nonblank")
        if re.search(
            r"[()\[\]{}、,?\u300c-\u3011\u3014-\u301b]", unicodedata.normalize("NFKC", self.label)
        ):
            raise ValueError("label must be a basic noun without brackets, lists or questions")
        if any(value in self.label for value in ("の有無", "対応可否")):
            raise ValueError("label must not be a comparison question")
        if (self.origin == "domain_expansion") != (len(self.source_article_ids) == 0):
            raise ValueError("origin and source_article_ids are inconsistent")
        return self


class DiscoverySearchVocabularyV2(ContractModel):
    spec_version: Literal["discovery-search-vocabulary-v2"]
    domain_label: Annotated[str, Field(strict=True)]
    domain_terms: tuple[Text, ...]
    concepts: tuple[SearchConcept, ...]
    notes: tuple[Annotated[str, Field(strict=True)], ...]

    @model_validator(mode="after")
    def vocabulary_rules(self) -> Self:
        unique_text(self.domain_terms, "domain_terms")
        unique_ids(tuple(concept.id for concept in self.concepts), "concept IDs")
        unique_text(tuple(concept.label for concept in self.concepts), "concept labels")
        priorities = [concept.priority for concept in self.concepts]
        if "normal" in priorities and "high" in priorities[priorities.index("normal") :]:
            raise ValueError("high concepts must precede normal concepts")
        return self


class DiscoveryVocabularyRecord(ContractModel):
    run_id: UUID
    created_at: datetime
    policy_version: Literal["discovery-search-vocabulary-v2.1"]
    search_policy: Literal["discovery-vocabulary-nfkc-casefold-boundaries-v1"]
    input_hash: str
    output_hash: str | None
    profile_fingerprint: str
    provider: str
    model: str
    prompt_version: str
    contract_hash: str
    request: DiscoveryVocabularyInput
    vocabulary: DiscoverySearchVocabularyV2 | None
    ai_run_ids: tuple[UUID, ...]
    successful_ai_run_id: UUID | None
    status: Literal["ready", "failed"]
    error_code: str | None

    @model_validator(mode="after")
    def complete_record(self) -> Self:
        if self.status == "ready":
            if (
                self.vocabulary is None
                or self.output_hash is None
                or self.successful_ai_run_id is None
                or self.successful_ai_run_id not in self.ai_run_ids
                or self.error_code is not None
            ):
                raise ValueError("ready record requires vocabulary and successful AI run")
        elif (
            self.vocabulary is not None
            or self.error_code is None
            or self.output_hash is not None
            or self.successful_ai_run_id is not None
        ):
            raise ValueError("failed record requires error and no vocabulary")
        return self


class ConceptMatch(ContractModel):
    concept_id: str
    label: str
    matched_terms: tuple[str, ...]
    layer: Layer
    priority: Literal["high", "normal"]


class VocabularySearchHit(ContractModel):
    article_id: str
    title: str
    domain_matches: tuple[str, ...]
    matches: tuple[ConceptMatch, ...]
    concept_count: int
    layer_count: int
    high_priority_count: int
