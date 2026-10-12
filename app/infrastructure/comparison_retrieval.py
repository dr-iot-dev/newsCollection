"""Deterministic Japanese keyword retrieval and exact, model-separated vectors."""

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations
from unicodedata import normalize
from uuid import UUID


def terms(text: str) -> set[str]:
    text = normalize("NFKC", text).casefold()
    tokens = set(re.findall(r"[a-z0-9][a-z0-9_+.-]*", text))
    for phrase in re.findall(r"[\u3040-\u30ff\u3400-\u9fff]+", text):
        tokens.update(phrase[i : i + 2] for i in range(len(phrase) - 1))
    return tokens


def keyword_score(query: str, text: str) -> float:
    left, right = terms(query), terms(text)
    return len(left & right) / math.sqrt(len(left) * len(right)) if left and right else 0.0


@dataclass(frozen=True)
class Embedding:
    provider: str
    model: str
    revision: str
    values: tuple[float, ...]


def cosine(left: Embedding, right: Embedding) -> float:
    if (left.provider, left.model, left.revision, len(left.values)) != (
        right.provider,
        right.model,
        right.revision,
        len(right.values),
    ):
        raise ValueError("Incompatible embedding model or dimensions")
    if not left.values or not all(math.isfinite(v) for v in (*left.values, *right.values)):
        raise ValueError("Empty or non-finite embedding")
    a_scale, b_scale = max(abs(v) for v in left.values), max(abs(v) for v in right.values)
    if not a_scale or not b_scale:
        raise ValueError("Zero embedding")
    a_values = tuple(v / a_scale for v in left.values)
    b_values = tuple(v / b_scale for v in right.values)
    a_norm, b_norm = math.hypot(*a_values), math.hypot(*b_values)
    return max(
        -1.0,
        min(
            1.0,
            math.fsum((x / a_norm) * (y / b_norm) for x, y in zip(a_values, b_values, strict=True)),
        ),
    )


def reciprocal_rank_fusion(*rankings: Sequence[UUID]) -> dict[UUID, float]:
    result: dict[UUID, float] = {}
    for ranking in rankings:
        for rank, key in enumerate(dict.fromkeys(ranking), 1):
            result[key] = result.get(key, 0.0) + 1 / (60 + rank)
    return result


def rank_candidates(
    seed: UUID,
    texts: Mapping[UUID, str],
    intent: str | None = None,
    embeddings: Mapping[UUID, Embedding] | None = None,
) -> tuple[tuple[UUID, ...], dict[UUID, float]]:
    query = texts[seed] + (" " + intent if intent else "")
    scores = {key: keyword_score(query, value) for key, value in texts.items()}
    keyword = sorted(texts, key=lambda key: (-scores[key], str(key)))
    if embeddings is not None:
        if set(embeddings) != set(texts):
            raise ValueError("Embedding coverage must match the retrieval snapshot")
        similarities = {key: cosine(embeddings[seed], embeddings[key]) for key in texts}
        vector = sorted(texts, key=lambda key: (-similarities[key], str(key)))
        scores = reciprocal_rank_fusion(keyword, vector)
    ranked = sorted(texts, key=lambda key: (-scores[key], str(key)))
    # The article anchor is always retained, even when the purpose ranks it lower.
    return (seed, *(key for key in ranked if key != seed)), scores


@dataclass(frozen=True)
class GroupRetrievalScore:
    item_ids: tuple[UUID, UUID, UUID]
    relatedness: float
    redundancy: float
    selection_score: float


def rank_seeded_groups(
    seed: UUID,
    detailed: Sequence[UUID],
    texts: Mapping[UUID, str],
) -> tuple[GroupRetrievalScore, ...]:
    """MMR over non-seed members; relevance remains a discovery hint, never approval."""
    if seed not in detailed or len(set(detailed)) != len(detailed):
        raise ValueError("A distinct detailed pool containing the seed is required")
    pairs = tuple(combinations((key for key in detailed if key != seed), 2))
    relatedness = {
        pair: min(
            keyword_score(texts[seed], texts[pair[0]]),
            keyword_score(texts[seed], texts[pair[1]]),
            keyword_score(texts[pair[0]], texts[pair[1]]),
        )
        for pair in pairs
    }
    maximum = max(relatedness.values(), default=0.0)
    remaining = set(pairs)
    selected: list[tuple[UUID, UUID]] = []
    results = []
    while remaining:

        def score(pair: tuple[UUID, UUID]) -> tuple[float, float]:
            redundancy = max((len(set(pair) & set(prior)) / 2 for prior in selected), default=0.0)
            relevance = relatedness[pair] / maximum if maximum else 0.0
            return 0.7 * relevance - 0.3 * redundancy, redundancy

        chosen = min(remaining, key=lambda pair: (-score(pair)[0], str(pair[0]), str(pair[1])))
        value, redundancy = score(chosen)
        results.append(GroupRetrievalScore((seed, *chosen), relatedness[chosen], redundancy, value))
        selected.append(chosen)
        remaining.remove(chosen)
    return tuple(results)
