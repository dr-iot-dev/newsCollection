"""Conservative duplicate scoring. Similarity never deletes an article."""

import hashlib
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from urllib.parse import urlsplit

from app.contracts.content_v1 import NormalizedContentV1
from app.core.content import normalize_url

POLICY_VERSION = "dedup-v1"
STOP_WORDS = {
    "the",
    "a",
    "an",
    "new",
    "announces",
    "launches",
    "release",
    "released",
    "introduces",
    "and",
    "with",
    "for",
    "update",
}


def tokens(value: str) -> list[str]:
    words = re.findall(r"[\w-]+", value.casefold())
    # Character shingles also distinguish Japanese text without whitespace.
    if len(words) <= 3 and re.search(r"[\u3040-\u9fff]", value):
        text = re.sub(r"\s+", "", value.casefold())
        return [text[i : i + 3] for i in range(max(1, len(text) - 2))]
    return words


def simhash(value: str) -> int:
    vector = [0] * 64
    for token in tokens(value[:20_000]):
        digest = int.from_bytes(hashlib.sha256(token.encode()).digest()[:8], "big")
        for bit in range(64):
            vector[bit] += 1 if digest & (1 << bit) else -1
    return sum(1 << bit for bit, weight in enumerate(vector) if weight > 0)


def identity(title: str) -> set[str]:
    words = tokens(title)
    # Manufacturer/subject anchor plus explicit model/version numbers; no LLM entity guesses.
    anchors = [word for word in words if word not in STOP_WORDS]
    return ({anchors[0]} if anchors else set()) | {
        word for word in words if any(c.isdigit() for c in word)
    }


@dataclass(frozen=True)
class Match:
    decision: str
    score: float
    reasons: dict[str, float | bool | str]


def compare(left: NormalizedContentV1, right: NormalizedContentV1) -> Match:
    url_match = normalize_url(str(left.canonical_url)) == normalize_url(str(right.canonical_url))
    hash_match = left.body_sha256 == right.body_sha256 and len(left.body) >= 300
    date_compatible = (
        left.published_date is None
        or right.published_date is None
        or abs((left.published_date - right.published_date).days) <= 2
    )
    body_identity_safe = identity(left.title) == identity(right.title) and date_compatible
    if url_match or hash_match:
        return Match(
            "duplicate" if url_match or body_identity_safe else "review",
            1.0,
            {
                "canonical_url_equal": url_match,
                "normalized_body_equal": hash_match,
                "identity_compatible": body_identity_safe,
            },
        )
    title = SequenceMatcher(
        None, left.title.casefold(), right.title.casefold(), autojunk=False
    ).ratio()
    similarity = (
        1
        - (
            simhash(left.title + "\n" + left.body) ^ simhash(right.title + "\n" + right.body)
        ).bit_count()
        / 64
    )
    a, b = identity(left.title), identity(right.title)
    entity = len(a & b) / max(1, len(a | b))
    dates = left.published_date is not None and right.published_date is not None
    days = (
        abs((left.published_date - right.published_date).days)
        if dates and left.published_date and right.published_date
        else None
    )
    date_score = 1.0 if days is not None and days <= 2 else 0.0
    related = (
        urlsplit(str(left.canonical_url)).hostname == urlsplit(str(right.canonical_url)).hostname
    )
    score = round(
        0.45 * title + 0.25 * similarity + 0.15 * entity + 0.10 * date_score + 0.05 * related, 3
    )
    # Different makers/models and unknown dates cannot be automatically grouped.
    numeric_match = {w for w in tokens(left.body) if any(c.isdigit() for c in w)} == {
        w for w in tokens(right.body) if any(c.isdigit() for c in w)
    }
    technical_match = set(re.findall(r"\b[A-Z][A-Z0-9]{1,}\b", left.body)) == set(
        re.findall(r"\b[A-Z][A-Z0-9]{1,}\b", right.body)
    )
    strong = (
        title >= 0.98
        and similarity >= 0.95
        and bool(a)
        and a == b
        and date_score == 1
        and numeric_match
        and technical_match
    )
    decision = (
        "duplicate" if score >= 0.92 and strong else "review" if score >= 0.80 else "separate"
    )
    return Match(
        decision,
        score,
        {
            "title_similarity": round(title, 4),
            "simhash_similarity": similarity,
            "entity_similarity": entity,
            "date_similarity": date_score,
            "same_host": related,
            "strong_identity_match": strong,
            "numeric_details_match": numeric_match,
            "technical_terms_match": technical_match,
        },
    )
