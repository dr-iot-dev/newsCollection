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


def validate_facts(content: NormalizedContentV1, output: FactsOutputV1) -> None:
    if INJECTION.search(content.body):
        raise EditorialError("PROMPT_INJECTION_SUSPECTED")
    for fact in output.facts:
        evidence = content.body[fact.evidence_start : fact.evidence_end]
        if fact.evidence_end > len(content.body) or evidence != fact.evidence_text:
            raise EditorialError("FACT_EVIDENCE_MISMATCH")
        if personal_data(evidence + fact.value + fact.subject):
            raise EditorialError("FACT_PERSONAL_DATA")
        if fact.subject != "発表内容" and fact.subject not in content.body:
            raise EditorialError("FACT_SUBJECT_UNSUPPORTED")
        if fact.date_precision is None and not numbers(fact.value) <= numbers(evidence):
            raise EditorialError("FACT_NUMBER_UNSUPPORTED")
        if fact.date_precision is not None:
            parts = re.fullmatch(r"(\d{4})年(?:(\d{1,2})月)?(?:(\d{1,2})日)?", evidence)
            iso = re.fullmatch(r"(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?", evidence)
            parts = parts or iso
            if parts is None:
                raise EditorialError("FACT_DATE_UNSUPPORTED")
            year, month, day = parts.groups()
            precision = "day" if day else "month" if month else "year"
            expected = (
                year + (f"-{int(month):02d}" if month else "") + (f"-{int(day):02d}" if day else "")
            )
            try:
                date(int(year), int(month or 1), int(day or 1))
            except ValueError:
                raise EditorialError("FACT_DATE_INVALID") from None
            if fact.date_precision != precision or fact.value not in {evidence, expected}:
                raise EditorialError("FACT_DATE_PRECISION_MISMATCH")
        elif fact.fact_type in {"announcement_date", "release_date", "support_end_date"}:
            raise EditorialError("FACT_DATE_PRECISION_REQUIRED")
        elif fact.value not in evidence:
            raise EditorialError("FACT_VALUE_UNSUPPORTED")
        for qualifier in (fact.unit, fact.region, fact.conditions, fact.attribution):
            if qualifier and qualifier not in evidence:
                raise EditorialError("FACT_QUALIFIER_UNSUPPORTED")
        if fact.currency and not (
            (fact.currency == "JPY" and ("円" in evidence or "JPY" in evidence))
            or (fact.currency == "USD" and ("USD" in evidence or "$" in evidence))
            or (fact.currency == "EUR" and ("EUR" in evidence or "€" in evidence))
        ):
            raise EditorialError("FACT_CURRENCY_UNSUPPORTED")
        if fact.fact_type in {"performance_claim", "security_claim"} and (
            not fact.attribution or not fact.conditions
        ):
            raise EditorialError("FACT_CLAIM_CONTEXT_MISSING")
