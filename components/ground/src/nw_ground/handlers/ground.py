"""Normalize supplied bytes and bind all retained facts to their original source."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid5

from nw_ground._vendor.contracts.content_v1 import NormalizedContentV1
from nw_ground._vendor.contracts.evidence_v1 import EvidencePackageV1, FactReferenceV1
from nw_ground._vendor.contracts.facts_v1 import FactsOutputV1, VerifiedFactV1
from nw_ground._vendor.core.editorial import INJECTION
from nw_ground._vendor.modules.acquisition.connectors import decode_text
from nw_ground._vendor.modules.acquisition.http import FetchResponse
from nw_ground._vendor.modules.deduplication.service import compare
from nw_ground._vendor.modules.extraction.facts import rule_facts, supported_ai_facts, validate_facts
from nw_ground._vendor.modules.extraction.service import extract_content
from nw_ground._vendor.modules.research.topics import classify_topic
from nw_ground._vendor.sources.config import WebSelectors

from ..common import Context, Outcome, StageInput, output, required
from ..protocol import NAMESPACE, ProtocolError, digest, object_hash


def run(inputs: dict[str, StageInput], parameters: dict[str, Any], context: Context) -> Outcome:
    batch = required(inputs, "sources")
    documents, issues = [], []
    baseline = inputs.get("baseline")
    prior = (
        [
            NormalizedContentV1.model_validate(row["content"])
            for row in baseline.payload.get("documents", [])
        ]
        if baseline
        else []
    )
    for row in batch.payload["documents"]:
        raw = batch.assets[row["path"]]
        if digest(raw) != row["sha256"]:
            raise ProtocolError("SOURCE_CONTENT_HASH_MISMATCH")
        if row.get("rights_approved") is not True:
            issues.append(
                {"code": "SOURCE_RIGHTS_BLOCKED", "item_id": row["item_id"], "retryable": False}
            )
            continue
        content = extract_content(
            item_id=UUID(row["item_id"]),
            item_version=int(row.get("item_version", 1)),
            snapshot_id=UUID(row["snapshot_id"]),
            url=row["url"],
            title=row["title"],
            body=decode_text(
                FetchResponse(
                    row["url"],
                    row["url"],
                    200,
                    row.get("headers", {}),
                    raw,
                    datetime.fromisoformat(row["fetched_at"]),
                )
            ),
            published_at=datetime.fromisoformat(row["published_at"])
            if row.get("published_at")
            else None,
            language=row["language"],
            is_html=row["is_html"],
            selectors=WebSelectors.model_validate(row["selectors"])
            if row.get("selectors")
            else None,
            allowed_hosts=row.get("allowed_hosts"),
            timezone_hint=row.get("timezone_hint"),
        )
        if content.quality_score < 0.6 or INJECTION.search(content.body):
            issues.append(
                {"code": "SOURCE_QUALITY_BLOCKED", "item_id": row["item_id"], "retryable": False}
            )
            continue
        matches = [compare(content, other) for other in prior]
        if any(match.decision != "separate" for match in matches):
            issues.append(
                {
                    "code": "DUPLICATE_OR_AMBIGUOUS_SOURCE",
                    "item_id": row["item_id"],
                    "retryable": False,
                }
            )
            continue
        if parameters.get("facts_mode", "rules") == "ai":
            facts_output = context.generate("facts", content.model_dump(mode="json"), FactsOutputV1)
            facts_output, _omitted = supported_ai_facts(content, facts_output)
            record = context.records[-1]
        else:
            facts_output = rule_facts(content)
            record = {"role": "facts", "model": "rules", "provider": "rules"}
        validate_facts(content, facts_output)
        evidence_id = uuid5(
            NAMESPACE,
            object_hash([content.model_dump(mode="json"), facts_output.model_dump(mode="json")]),
        )
        facts, anchors = [], {}
        for index, fact in enumerate(facts_output.facts):
            fact_id = uuid5(
                NAMESPACE, object_hash([str(evidence_id), index, fact.model_dump(mode="json")])
            )
            retained = VerifiedFactV1(
                fact_id=fact_id,
                evidence_id=evidence_id,
                **{
                    key: value
                    for key, value in fact.model_dump().items()
                    if key in VerifiedFactV1.model_fields and key not in {"fact_id", "evidence_id"}
                },
            )
            facts.append(retained)
            anchors[str(fact_id)] = fact.model_dump(mode="json")
        evidence = EvidencePackageV1(
            package_id=evidence_id,
            item_id=content.item_id,
            canonical_url=content.canonical_url,
            title=content.title,
            published_at=content.published_at,
            language=content.language,
            item_version=content.item_version,
            verified_facts=tuple(facts),
            facts=tuple(
                FactReferenceV1(fact_id=f.fact_id, evidence_id=evidence_id, fact_type=f.fact_type)
                for f in facts
            ),
            quality_score=content.quality_score,
            uncertainties=facts_output.uncertainties,
        )
        topic = classify_topic(
            content,
            object_hash(content.model_dump(mode="json")),
            tuple(f.value for f in facts if f.fact_type == "product"),
        )
        documents.append(
            {
                "content": content.model_dump(mode="json"),
                "evidence": evidence.model_dump(mode="json"),
                "anchors": anchors,
                "topic": topic.model_dump(mode="json"),
                "provenance": [record],
                "fetched_at": row["fetched_at"],
                "source_key": row.get("source_key"),
            }
        )
        prior.append(content)
    if not documents:
        return Outcome(
            "needs_input",
            issues=issues or [{"code": "GROUNDED_DOCUMENTS_REQUIRED", "retryable": False}],
        )
    result = output("evidence", "EvidenceBatchV1", {"documents": documents})
    result.issues = issues
    return result
