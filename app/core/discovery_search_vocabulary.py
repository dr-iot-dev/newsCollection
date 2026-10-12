"""Deterministic vocabulary acceptance and ordinary phrase search, without AI."""

import re
from collections.abc import Iterable

from app.contracts.discovery_search_vocabulary_v2 import (
    ConceptMatch,
    DiscoveryArticle,
    DiscoverySearchVocabularyV2,
    DiscoveryVocabularyInput,
    VocabularySearchHit,
    normalized_text,
)
from app.core.editorial import EditorialError

# Explicit spec examples, not a domain vocabulary or generic-word stoplist.
_BASIC_LABELS = {"クラウド監視", "遠隔監視", "遠隔管理", "外部連携", "監視対象データ"}
_NON_SYNONYMS = (
    {"監視", "管理", "連携"},
    {"保存", "データ保存", "データ保存期間", "保存期間"},
    {"通信", "lte"},
    {"通知", "メール"},
    {"価格", "見積", "見積もり", "見積り"},
)


def validate_vocabulary(
    value: DiscoverySearchVocabularyV2, request: DiscoveryVocabularyInput
) -> None:
    article_ids = {article.article_id for article in request.articles}
    labels = {normalized_text(concept.label) for concept in value.concepts}
    owners: dict[str, str] = {}
    for index, concept in enumerate(value.concepts):
        path = ("concepts", index)
        if not set(concept.source_article_ids) <= article_ids:
            raise EditorialError("VOCABULARY_UNKNOWN_ARTICLE", path=(*path, "source_article_ids"))
        if normalized_text(concept.label) in _BASIC_LABELS:
            raise EditorialError("VOCABULARY_MODIFIED_LABEL", path=(*path, "label"))
        own_label = normalized_text(concept.label)
        aliases = {normalized_text(alias) for alias in concept.aliases}
        if aliases & (labels - {own_label}):
            raise EditorialError("VOCABULARY_DUPLICATE_CONCEPT", path=(*path, "aliases"))
        for term in (own_label, *aliases):
            if term in owners and owners[term] != concept.id:
                raise EditorialError("VOCABULARY_DUPLICATE_CONCEPT", path=(*path, "aliases"))
            owners[term] = concept.id
        for group in _NON_SYNONYMS:
            if own_label in group:
                forbidden = group - {own_label}
                if own_label in {"保存", "データ保存"}:
                    forbidden = {"データ保存期間", "保存期間"}
                if aliases & forbidden:
                    raise EditorialError("VOCABULARY_RELATED_ALIAS", path=(*path, "aliases"))


def term_matches(term: str, normalized: str) -> bool:
    """Japanese compound substrings are allowed; Latin words have Latin boundaries."""
    needle = normalized_text(term)
    if not needle:
        return False
    left = r"(?<![a-z0-9_])" if needle[0].isascii() and needle[0].isalnum() else ""
    right = r"(?![a-z0-9_])" if needle[-1].isascii() and needle[-1].isalnum() else ""
    return re.search(left + re.escape(needle) + right, normalized) is not None


def search_articles(
    vocabulary: DiscoverySearchVocabularyV2,
    articles: Iterable[DiscoveryArticle],
    *,
    require_domain: bool = True,
    excluded_article_ids: Iterable[str] = (),
) -> tuple[VocabularySearchHit, ...]:
    """Domain OR filter AND at least one concept's label/alias OR match."""
    excluded = set(excluded_article_ids)
    seen: set[str] = set()
    hits = []
    for article in articles:
        if article.article_id in seen:
            raise ValueError("search article_id must be unique")
        seen.add(article.article_id)
        if article.article_id in excluded:
            continue
        texts = (normalized_text(article.title), normalized_text(article.body))

        def matches(term: str, texts: tuple[str, str] = texts) -> bool:
            return any(term_matches(term, text) for text in texts)

        domain_matches = tuple(term for term in vocabulary.domain_terms if matches(term))
        if require_domain and vocabulary.domain_terms and not domain_matches:
            continue
        concept_matches = []
        for concept in vocabulary.concepts:
            matched_terms = tuple(
                term for term in (concept.label, *concept.aliases) if matches(term)
            )
            if matched_terms:
                concept_matches.append(
                    ConceptMatch(
                        concept_id=concept.id,
                        label=concept.label,
                        matched_terms=matched_terms,
                        layer=concept.layer,
                        priority=concept.priority,
                    )
                )
        if concept_matches:
            hits.append(
                VocabularySearchHit(
                    article_id=article.article_id,
                    title=article.title,
                    domain_matches=domain_matches,
                    matches=tuple(concept_matches),
                    concept_count=len(concept_matches),
                    layer_count=len({match.layer for match in concept_matches}),
                    high_priority_count=sum(match.priority == "high" for match in concept_matches),
                )
            )
    return tuple(
        sorted(
            hits,
            key=lambda hit: (
                -hit.high_priority_count,
                -hit.layer_count,
                -hit.concept_count,
                hit.article_id,
            ),
        )
    )
