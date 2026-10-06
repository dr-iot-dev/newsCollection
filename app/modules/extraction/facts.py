"""Pure fact extraction and evidence validation; no database or provider access."""

import re
from datetime import date

from app.contracts.content_v1 import NormalizedContentV1
from app.contracts.facts_v1 import ExtractedFactV1, FactsOutputV1
from app.core.editorial import INJECTION, EditorialError, numbers, personal_data

RULES = (
    ("organization", "organization", r"(?:企業名|メーカー|Company)[:\uff1a]\s*([^\n、。]{2,80})"),
    ("product", "product", r"(?:製品名|製品|Product)[:\uff1a]\s*([^\n、。]{2,80})"),
    (
        "hardware_spec",
        "specification",
        r"(?<![A-Za-z0-9,.])\d+(?:,\d{3})*(?:\.\d+)?\s*"
        r"(?:GHz|MHz|GB|MB|mAh|mW|W|mm|kg)(?![A-Za-z])",
    ),
    ("price", "price", r"(?<![A-Za-z0-9,.])(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?\s*円"),
    (
        "release_date",
        "date",
        r"(?:発売日|発売予定日|出荷開始日)[:\uff1a]\s*([0-9]{4}年[0-9]{1,2}月(?:[0-9]{1,2}日)?)",
    ),
)


def rule_facts(content: NormalizedContentV1) -> FactsOutputV1:
    facts: list[ExtractedFactV1] = []
    for kind, predicate, pattern in RULES:
        for match in re.finditer(pattern, content.body):
            start, end = match.span(1) if match.lastindex else match.span()
            text = content.body[start:end]
            unit = "円" if kind == "price" else None
            if kind == "hardware_spec":
                suffix = re.search(r"(?:GHz|MHz|GB|MB|mAh|mW|W|mm|kg)$", text)
                unit = suffix[0] if suffix else None
            precision = None
            if kind == "release_date":
                precision = "day" if text.endswith("日") else "month"
            facts.append(
                ExtractedFactV1(
                    fact_type=kind,
                    subject=text if kind in {"product", "organization"} else "発表内容",
                    predicate=predicate,
                    value=text,
                    unit=unit,
                    currency="JPY" if kind == "price" else None,
                    date_precision=precision,
                    evidence_text=text,
                    evidence_start=start,
                    evidence_end=end,
                    confidence=1,
                )
            )
            if len(facts) >= 100:
                break
        if len(facts) >= 100:
            break
    output = FactsOutputV1(facts=tuple(facts))
    validate_facts(content, output)
    return output


def anchor_evidence(content: NormalizedContentV1, output: FactsOutputV1) -> FactsOutputV1:
    """Anchor exact source quotes and pinpoint supported date literals within them."""
    anchored = []
    for index, fact in enumerate(output.facts):
        start = fact.evidence_start
        if content.body[start : fact.evidence_end] != fact.evidence_text:
            start = content.body.find(fact.evidence_text)
            if start < 0:
                raise EditorialError(
                    "FACT_EVIDENCE_MISMATCH", path=("facts", index, "evidence_text")
                )
            if content.body.find(fact.evidence_text, start + 1) >= 0:
                raise EditorialError(
                    "FACT_EVIDENCE_AMBIGUOUS", path=("facts", index, "evidence_text")
                )
        quote = fact.evidence_text
        if fact.date_precision is not None:
            matches = []
            pattern = (
                r"(?<![0-9])[0-9]{4}年(?:[0-9]{1,2}月)?(?:[0-9]{1,2}日)?|"
                r"(?<![0-9])[0-9]{4}(?:-[0-9]{2}){0,2}(?![0-9])"
            )
            for match in re.finditer(pattern, quote):
                raw = match[0]
                parts = re.fullmatch(r"(\d{4})年(?:(\d{1,2})月)?(?:(\d{1,2})日)?", raw)
                parts = parts or re.fullmatch(r"(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?", raw)
                assert parts is not None
                year, month, day = parts.groups()
                iso = (
                    year
                    + (f"-{int(month):02d}" if month else "")
                    + (f"-{int(day):02d}" if day else "")
                )
                precision = "day" if day else "month" if month else "year"
                if fact.value in {raw, iso} and fact.date_precision == precision:
                    matches.append(match)
            if len(matches) == 1:
                start += matches[0].start()
                quote = matches[0][0]
        anchored.append(
            fact.model_copy(
                update={
                    "evidence_start": start,
                    "evidence_end": start + len(quote),
                    "evidence_text": quote,
                }
            )
        )
    return output.model_copy(update={"facts": tuple(anchored)})


def supported_ai_facts(
    content: NormalizedContentV1, output: FactsOutputV1
) -> tuple[FactsOutputV1, tuple[EditorialError, ...]]:
    """Reject unsupported candidates individually; every retained fact passes full validation."""
    validate_facts(content, FactsOutputV1(facts=()))
    accepted: list[ExtractedFactV1] = []
    rejected: list[EditorialError] = []
    for index, fact in enumerate(output.facts):
        try:
            candidate = anchor_evidence(content, FactsOutputV1(facts=(fact,)))
            validate_facts(content, candidate)
        except EditorialError as exc:
            rejected.append(EditorialError(exc.code, path=("facts", index, *exc.path[2:])))
        else:
            accepted.extend(candidate.facts)
    if rejected and not accepted:
        raise rejected[0]
    uncertainties = tuple(
        dict.fromkeys(
            [
                *output.uncertainties,
                *("未検証の事実候補を除外しました: " + exc.code for exc in rejected),
            ]
        )
    )
    return output.model_copy(
        update={"facts": tuple(accepted), "uncertainties": uncertainties}
    ), tuple(rejected)


def evidence_passages(body: str) -> list[dict[str, str | int]]:
    """Expose exact paragraph offsets without modifying or duplicating the source body."""
    return [
        {"start": match.start(), "end": match.end(), "text": match[0]}
        for match in re.finditer(r"[^\n]+", body)
        if len(match[0]) <= 1000
    ]


def validate_facts(content: NormalizedContentV1, output: FactsOutputV1) -> None:
    if INJECTION.search(content.body):
        raise EditorialError("PROMPT_INJECTION_SUSPECTED")
    for index, fact in enumerate(output.facts):
        evidence = content.body[fact.evidence_start : fact.evidence_end]
        if fact.evidence_end > len(content.body) or evidence != fact.evidence_text:
            raise EditorialError("FACT_EVIDENCE_MISMATCH", path=("facts", index, "evidence_text"))
        if personal_data(evidence + fact.value + fact.subject):
            raise EditorialError("FACT_PERSONAL_DATA", path=("facts", index))
        if fact.subject != "発表内容" and fact.subject not in content.body:
            raise EditorialError("FACT_SUBJECT_UNSUPPORTED", path=("facts", index, "subject"))
        if fact.date_precision is None and not numbers(fact.value) <= numbers(evidence):
            raise EditorialError("FACT_NUMBER_UNSUPPORTED", path=("facts", index, "value"))
        if fact.date_precision is not None:
            parts = re.fullmatch(r"(\d{4})年(?:(\d{1,2})月)?(?:(\d{1,2})日)?", evidence)
            iso = re.fullmatch(r"(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?", evidence)
            parts = parts or iso
            if parts is None:
                raise EditorialError(
                    "FACT_DATE_UNSUPPORTED", path=("facts", index, "evidence_text")
                )
            year, month, day = parts.groups()
            precision = "day" if day else "month" if month else "year"
            expected = (
                year + (f"-{int(month):02d}" if month else "") + (f"-{int(day):02d}" if day else "")
            )
            try:
                date(int(year), int(month or 1), int(day or 1))
            except ValueError:
                raise EditorialError(
                    "FACT_DATE_INVALID", path=("facts", index, "evidence_text")
                ) from None
            if fact.date_precision != precision or fact.value not in {evidence, expected}:
                raise EditorialError(
                    "FACT_DATE_PRECISION_MISMATCH", path=("facts", index, "date_precision")
                )
        elif fact.fact_type in {"announcement_date", "release_date", "support_end_date"}:
            raise EditorialError(
                "FACT_DATE_PRECISION_REQUIRED", path=("facts", index, "date_precision")
            )
        elif fact.value not in evidence:
            raise EditorialError("FACT_VALUE_UNSUPPORTED", path=("facts", index, "value"))
        for field in ("unit", "region", "conditions", "attribution"):
            qualifier = getattr(fact, field)
            if qualifier and qualifier not in evidence:
                raise EditorialError("FACT_QUALIFIER_UNSUPPORTED", path=("facts", index, field))
        if fact.currency and not (
            (fact.currency == "JPY" and ("円" in evidence or "JPY" in evidence))
            or (fact.currency == "USD" and ("USD" in evidence or "$" in evidence))
            or (fact.currency == "EUR" and ("EUR" in evidence or "€" in evidence))
        ):
            raise EditorialError("FACT_CURRENCY_UNSUPPORTED", path=("facts", index, "currency"))
        if fact.fact_type in {"performance_claim", "security_claim"} and (
            not fact.attribution or not fact.conditions
        ):
            raise EditorialError("FACT_CLAIM_CONTEXT_MISSING", path=("facts", index, "conditions"))
