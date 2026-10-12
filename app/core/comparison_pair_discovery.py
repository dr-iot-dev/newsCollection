"""Pure text matching, grounding, coverage and stable pair ordering."""

import hashlib
import math
import re
from collections.abc import Mapping, Sequence
from itertools import combinations
from unicodedata import normalize
from uuid import UUID

from app.contracts.base import ContractModel
from app.contracts.comparison_pair_discovery_v3 import (
    CategoryKeywords,
    ComparisonAxis,
    DocumentFeatures,
    PairDistance,
    PairDocument,
    PairPlan,
    PairProduct,
    SearchTerm,
    SourceQuote,
)
from app.core.content import normalize_text
from app.core.editorial import EMAIL, PHONE, EditorialError, numbers
from app.infrastructure.comparison_retrieval import Embedding, cosine

URL = re.compile(r"https?://[^\s<>「」『』\uff08\uff09()]+", re.I)
CONTACT = re.compile(
    r"^(?:お問い合わせ(?:先|について|[:\uff1a\s]|$)|問い合わせ先(?:[:\uff1a\s]|$)|"
    r"報道関係者(?:の皆様|向け|のお問い合わせ)?(?:[:\uff1a\s]|$)|"
    r"広報担当(?:[:\uff1a\s]|$)|TEL[:\uff1a]|FAX[:\uff1a])"
)
GENERIC = frozenset({"プレスリリース", "ニュースリリース", "株式会社", "PR TIMES"})
TITLE_EXCLUSION_TERMS = (
    "調査",
    "事例",
    "アンケート",
    "ランキング",
    "レポート",
    "ホワイトペーパー",
    "白書",
    "セミナー",
    "ウェビナー",
    "勉強会",
    "講演",
    "対談",
    "インタビュー",
    "イベント開催",
    "展示会",
    "書籍",
    "出版",
    "刊行",
    "受賞",
    "ベストセラー",
    "取材",
    "登壇",
    "交流会",
    "トークシリーズ",
    "開催",
    "大会",
    "決算",
    "増収",
    "増益",
    "声を公開",
    "説明会",
    "コラム",
    "論文",
    "論考",
    "ガイドブック",
    "寄稿",
    "出展",
    "設立",
    "事業重点化",
    "スポンサー契約",
)
KEYWORD_CLAUSE = re.compile(r"[。\uff01\uff1f]|を|から|できない|どう|組み込む|まとめる|に読み取り$")
CATEGORY_GENERIC = GENERIC | frozenset(
    {
        "AI",
        "API",
        "プロンプト",
        "組織図",
        "時系列整理",
        "整合性確認",
        "影響確認",
        "修正案の作成",
        "人工知能",
        "要件定義",
        "判断",
        "承認",
        "確認",
        "資料",
        "社内資料",
        "質問",
        "スライド",
        "LP",
        "ランディングページ",
        "配置",
        "色",
        "形",
        "設計",
        "実装",
        "運用",
        "業務",
        "効率化",
        "自動化",
        "データ",
        "ツール",
        "サービス",
        "定点調査",
        "継続調査",
        "計測ツール",
        "更新履歴",
        "リアルタイム",
        "自動突合",
        "所有者情報",
        "ページ順",
        "無料相談窓口",
        "非エンジニア向け",
        "初回無料",
        "月5件まで",
        "エビデンス",
        "情報源",
        "日本語",
        "英語",
        "明示",
        "モバイルアプリ",
        "閾値",
        "一次判定",
        "判定根拠",
    }
)


def norm(text: str) -> str:
    return normalize("NFKC", text).casefold().strip()


def excluded_title_terms(title: str) -> tuple[str, ...]:
    """Exclude non-product releases by explicit, auditable title substrings."""
    # decode_text replaces storage-incompatible NUL with U+FFFD. An inserted
    # separator must not turn 調査 into 調�査 and bypass the release-type filter.
    value = norm(title).replace("\x00", "").replace("\ufffd", "")
    return tuple(term for term in TITLE_EXCLUSION_TERMS if norm(term) in value)


def embedding_text(document: PairDocument) -> tuple[str, tuple[dict[str, object], ...]]:
    parts = [URL.sub("", document.title).strip()]
    removed: list[dict[str, object]] = []
    offset = 0
    for line in document.body.splitlines(keepends=True):
        stripped = line.strip()
        if CONTACT.search(stripped):
            removed.append({"start": offset, "end": offset + len(line), "reason": "contact"})
        else:
            clean = line
            patterns = [(EMAIL, "email"), (PHONE, "phone")]
            if not re.search(
                r"対象URL|URL形式|診断対象|エンドポイント|ドメイン|endpoint|domain", line, re.I
            ):
                patterns.insert(0, (URL, "url"))
            for pattern, reason in patterns:
                for match in pattern.finditer(line):
                    removed.append(
                        {
                            "start": offset + match.start(),
                            "end": offset + match.end(),
                            "reason": reason,
                        }
                    )
                clean = pattern.sub("", clean)
            if clean.strip():
                parts.append(clean.strip())
        offset += len(line)
    text = normalize_text("\n".join(parts))
    if not text:
        raise EditorialError("PAIR_EMBEDDING_INPUT_EMPTY")
    return text, tuple(removed)


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def bind_quote_offsets[T: ContractModel](value: T, documents: Mapping[UUID, PairDocument]) -> T:
    """Bind a verbatim quote to its unique occurrence; never edit or widen its text."""
    data = value.model_dump(mode="json")

    def visit(node: object) -> None:
        if isinstance(node, dict):
            if {"item_id", "start", "end", "quote"} <= node.keys():
                document = documents.get(UUID(node["item_id"]))
                if document is None:
                    raise EditorialError("PAIR_GROUNDING_INVALID")
                quote = node["quote"]
                if document.body[node["start"] : node["end"]] != quote:
                    start = document.body.find(quote)
                    if start < 0:
                        raise EditorialError("PAIR_GROUNDING_INVALID")
                    if document.body.find(quote, start + 1) >= 0:
                        raise EditorialError("PAIR_GROUNDING_AMBIGUOUS")
                    node["start"], node["end"] = start, start + len(quote)
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(data)
    return type(value).model_validate(data)


def validate_quotes(quotes: Sequence[SourceQuote], documents: Mapping[UUID, PairDocument]) -> None:
    for ref in quotes:
        doc = documents.get(ref.item_id)
        if doc is None or doc.body[ref.start : ref.end] != ref.quote or ref.end <= ref.start:
            raise EditorialError("PAIR_GROUNDING_INVALID")


def validate_terms(terms: Sequence[SearchTerm], documents: Mapping[UUID, PairDocument]) -> None:
    if len({term.key for term in terms}) != len(terms):
        raise EditorialError("PAIR_DUPLICATE_TERM")
    aliases: set[str] = set()
    for index, term in enumerate(terms):
        forms = {norm(form) for form in (term.label, *term.aliases)}
        if "" in forms or any(form in {norm(g) for g in GENERIC} for form in forms):
            raise EditorialError("PAIR_GENERIC_TERM")
        if aliases & forms:
            raise EditorialError("PAIR_OVERLAPPING_TERMS")
        aliases |= forms
        validate_quotes(term.evidence, documents)
        if not any(contains(ref.quote, form) for form in forms for ref in term.evidence):
            raise EditorialError("PAIR_TERM_NOT_GROUNDED", path=("terms", index, "label"))


def distinct_grounded_keywords(value: CategoryKeywords) -> CategoryKeywords:
    """Keep quoted search forms and merge concepts that share the same form."""
    terms: list[SearchTerm] = []
    for term in value.terms:
        forms = {norm(form) for form in (term.label, *term.aliases)}
        if not any(contains(ref.quote, form) for ref in term.evidence for form in forms):
            continue
        matches = [
            index
            for index, old in enumerate(terms)
            if forms & {norm(form) for form in (old.label, *old.aliases)}
        ]
        if not matches:
            terms.append(term)
            continue
        combined = [terms[index] for index in matches] + [term]
        first = combined[0]
        aliases = tuple(
            dict.fromkeys(
                form
                for old in combined
                for form in (old.label, *old.aliases)
                if norm(form) != norm(first.label)
            )
        )[:12]
        evidence = tuple(
            {
                (ref.item_id, ref.start, ref.end, ref.quote): ref
                for old in combined
                for ref in old.evidence
            }.values()
        )
        terms = [old for index, old in enumerate(terms) if index not in matches]
        terms.insert(
            matches[0], first.model_copy(update={"aliases": aliases, "evidence": evidence})
        )
    return value.model_copy(update={"terms": tuple(terms)})


def distinctive_keywords(
    value: CategoryKeywords, category: str
) -> tuple[CategoryKeywords, tuple[dict[str, object], ...]]:
    """Exclude broad forms without stripping specificity from compound labels.

    Semantic distinction and alias equivalence are assessed by the AI from the
    category context; this guard rejects known generic forms and unquoted forms.
    Every decision is returned for the checkpoint audit, including alias removals.
    """
    excluded = {norm(form) for form in CATEGORY_GENERIC} | {norm(category)}
    terms: list[SearchTerm] = []
    decisions: list[dict[str, object]] = []
    for term in value.terms:
        reason = ""
        if norm(term.label) in excluded:
            reason = "category_or_generic_label"
        elif KEYWORD_CLAUSE.search(term.label):
            reason = "explanatory_clause_not_keyword"
        elif not any(contains(ref.quote, term.label) for ref in term.evidence):
            reason = "label_not_quoted"
        aliases = tuple(
            alias
            for alias in term.aliases
            if norm(alias) not in excluded
            and not KEYWORD_CLAUSE.search(alias)
            and any(contains(ref.quote, alias) for ref in term.evidence)
        )
        decisions.append(
            {
                "key": term.key,
                "label": term.label,
                "retained": not reason,
                "reason": reason or "distinctive_grounded_proposal",
                "distinction_reason": term.distinction_reason,
                "removed_aliases": [alias for alias in term.aliases if alias not in aliases],
            }
        )
        if not reason:
            terms.append(term.model_copy(update={"aliases": aliases}))
    filtered = distinct_grounded_keywords(value.model_copy(update={"terms": tuple(terms)}))
    return filtered, tuple(decisions)


def validate_distinction(value: CategoryKeywords) -> None:
    for index, term in enumerate(value.terms):
        if not term.distinction_reason.strip():
            raise EditorialError("PAIR_KEYWORD_DISTINCTION_REQUIRED", path=("terms", index))


def contains(text: str, word: str) -> bool:
    text, word = norm(text), norm(word)
    if not word:
        return False
    if re.fullmatch(r"[a-z0-9_+.-]+", word):
        return bool(re.search(r"(?<![a-z0-9_])" + re.escape(word) + r"(?![a-z0-9_])", text))
    return word in text


def matching_terms(text: str, terms: Sequence[SearchTerm]) -> tuple[str, ...]:
    return tuple(
        term.key
        for term in terms
        if any(contains(text, form) for form in (term.label, *term.aliases))
    )


def keyword_match(document: PairDocument, keywords: CategoryKeywords) -> tuple[str, ...]:
    clean, _ = embedding_text(document)
    return matching_terms(clean, keywords.terms)


def ranked_pairs(embeddings: Mapping[UUID, Embedding]) -> tuple[PairDistance, ...]:
    ids = sorted(embeddings, key=str)
    values = [
        (left, right, 1 - cosine(embeddings[left], embeddings[right]))
        for left, right in combinations(ids, 2)
    ]
    values.sort(key=lambda row: (row[2], str(row[0]), str(row[1])))
    return tuple(
        PairDistance(left=a, right=b, distance=d, rank=i) for i, (a, b, d) in enumerate(values, 1)
    )


def third_ranking(
    pair: PairDistance, candidates: Sequence[UUID], embeddings: Mapping[UUID, Embedding]
) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for key in set(candidates) - {pair.left, pair.right}:
        a = 1 - cosine(embeddings[key], embeddings[pair.left])
        b = 1 - cosine(embeddings[key], embeddings[pair.right])
        rows.append(
            {
                "item_id": str(key),
                "left_distance": a,
                "right_distance": b,
                "distance": (a + b) / 2,
                "maximum": max(a, b),
            }
        )
    rows.sort(key=lambda row: (row["distance"], row["maximum"], row["item_id"]))
    return tuple(rows)


def product_key(product: PairProduct) -> str:
    return norm(product.organization + ":" + product.name)


def validate_product(product: PairProduct, document: PairDocument) -> None:
    if product.item_id != document.item_id:
        raise EditorialError("PAIR_FOREIGN_PRODUCT")
    validate_quotes(product.evidence, {document.item_id: document})
    evidence = " ".join(ref.quote for ref in product.evidence)
    if product.name not in evidence or product.organization not in evidence:
        raise EditorialError("PAIR_PRODUCT_UNGROUNDED")


def validate_plan(plan: PairPlan, documents: Mapping[UUID, PairDocument]) -> None:
    if not plan.comparable and not plan.products and not plan.axes:
        return
    if set(p.item_id for p in plan.products) != set(documents) or len(plan.products) != 2:
        raise EditorialError("PAIR_PRODUCTS_REQUIRED")
    for product in plan.products:
        validate_product(product, documents[product.item_id])
    validate_terms(plan.axes, documents)
    if len({norm(axis.question) for axis in plan.axes}) != len(plan.axes):
        raise EditorialError("PAIR_DUPLICATE_QUESTION")


def validate_features(
    value: DocumentFeatures, document: PairDocument, axes: Sequence[ComparisonAxis]
) -> None:
    validate_product(value.product, document)
    if len(value.cells) != len(axes) or {c.axis_key for c in value.cells} != {a.key for a in axes}:
        raise EditorialError("PAIR_CELL_COVERAGE_INVALID")
    for cell in value.cells:
        if cell.item_id != document.item_id:
            raise EditorialError("PAIR_FOREIGN_CELL")
        validate_quotes(cell.evidence, {document.item_id: document})
        if cell.status in {"unknown", "incomparable"}:
            if cell.evidence and cell.status == "unknown":
                raise EditorialError("PAIR_UNKNOWN_WITH_EVIDENCE")
            continue
        if not cell.evidence or not cell.answer.strip():
            raise EditorialError("PAIR_CELL_UNGROUNDED")
        raw = " ".join(ref.quote for ref in cell.evidence)
        if not numbers(cell.answer + " " + cell.conditions) <= numbers(raw):
            raise EditorialError("PAIR_UNSUPPORTED_NUMBER")


def coverage(
    features: Sequence[DocumentFeatures], axes: Sequence[ComparisonAxis]
) -> dict[str, int]:
    if len(features) != 3 or len({f.product.item_id for f in features}) != 3:
        raise EditorialError("PAIR_THREE_DISTINCT_DOCUMENTS_REQUIRED")
    if len({product_key(f.product) for f in features}) != 3:
        raise EditorialError("PAIR_DUPLICATE_PRODUCT")
    return {
        axis.key: sum(
            any(
                c.axis_key == axis.key
                and c.evidence
                and c.status not in {"unknown", "incomparable"}
                for c in f.cells
            )
            for f in features
        )
        for axis in axes
    }


def aggregate_vectors(
    vectors: Sequence[Sequence[float]], weights: Sequence[int]
) -> tuple[float, ...]:
    if not vectors or len(vectors) != len(weights):
        raise EditorialError("PAIR_EMBEDDING_INVALID")
    dimensions = len(vectors[0])
    if not dimensions or any(len(v) != dimensions for v in vectors):
        raise EditorialError("PAIR_EMBEDDING_DIMENSIONS")
    if any(not math.isfinite(n) for v in vectors for n in v) or any(w <= 0 for w in weights):
        raise EditorialError("PAIR_EMBEDDING_INVALID")
    total = sum(weights)
    merged = tuple(
        math.fsum(v[d] * w / total for v, w in zip(vectors, weights, strict=True))
        for d in range(dimensions)
    )
    length = math.hypot(*merged)
    if not length:
        raise EditorialError("PAIR_ZERO_EMBEDDING")
    return tuple(n / length for n in merged)
