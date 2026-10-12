"""Select comparable supplied evidence; request collection only when explicitly enabled."""

from datetime import date
from typing import Any, Literal
from uuid import UUID, uuid5

from nw_curate._vendor.contracts.article_package_v1 import ArticlePackageV1, SourceReferenceV1
from nw_curate._vendor.contracts.comparison_analysis_v1 import (
    ArticleTopicV1,
    CandidateAssessmentV1,
    ComparisonAnalysisV1,
)
from nw_curate._vendor.contracts.evidence_v1 import EvidencePackageV1
from nw_curate._vendor.contracts.facts_v1 import VerifiedFactV1
from nw_curate._vendor.core.article_tables import coverage_for_sources, require_comparison_coverage
from nw_curate._vendor.modules.comparison.analysis import compare_features
from nw_curate._vendor.modules.comparison.service import build_comparison, organization
from nw_curate._vendor.modules.research.service import (
    relation_reason,
    relevance_score,
    topic_checks,
    topic_reasons,
)
from nw_curate._vendor.modules.selection.service import rule_selection

from ..common import Context, Outcome, StageInput, output, required
from ..protocol import NAMESPACE, normalize_url, object_hash


def run(inputs: dict[str, StageInput], parameters: dict[str, Any], context: Context) -> Outcome:
    documents = required(inputs, "evidence").payload["documents"]
    if "corpus" in inputs:
        documents = documents + inputs["corpus"].payload["documents"]
    main_id = parameters.get(
        "main_item_id", documents[0]["evidence"]["item_id"] if documents else ""
    )
    main = next((row for row in documents if row["evidence"]["item_id"] == main_id), None)
    if main is None:
        return Outcome.needs("PRIMARY_EVIDENCE_REQUIRED")
    target = EvidencePackageV1.model_validate(main["evidence"])
    if rule_selection(target).decision != "selected":
        return Outcome.needs("PRIMARY_INFORMATION_INSUFFICIENT")
    target_topic = ArticleTopicV1.model_validate(main["topic"])
    selected, assessments, rejected, seen = (
        [main],
        [],
        [],
        {normalize_url(str(target.canonical_url))},
    )
    previous: list[VerifiedFactV1] = []
    competitors: list[VerifiedFactV1] = []
    for row in documents:
        candidate = EvidencePackageV1.model_validate(row["evidence"])
        url = normalize_url(str(candidate.canonical_url))
        if candidate.item_id == target.item_id or url in seen:
            continue
        seen.add(url)
        if rule_selection(candidate).decision != "selected":
            continue
        topic = ArticleTopicV1.model_validate(row["topic"])
        checks = topic_checks(target_topic, topic)
        reasons = list(topic_reasons(checks))
        relation: Literal["previous", "competitor"] = (
            "previous"
            if organization(target.verified_facts) == organization(candidate.verified_facts)
            else "competitor"
        )
        relevance = relevance_score(
            target, main["content"]["body"], candidate.title, row["content"]["body"]
        )
        reason = relation_reason(target, candidate, relation, relevance)
        if reason:
            reasons.append(reason)
        features = compare_features(target.verified_facts, candidate.verified_facts)
        shared = tuple(f.axis for f in features if f.target.values and f.candidate.values)
        if not shared:
            reasons.append("SHARED_FEATURES_UNCONFIRMED")
        if reasons:
            rejected.append({"item_id": str(candidate.item_id), "reasons": reasons})
            continue
        selected.append(row)
        (previous if relation == "previous" else competitors).extend(candidate.verified_facts)
        assessments.append(
            CandidateAssessmentV1(
                candidate_topic=topic,
                relation=relation,
                decision="eligible",
                reason_codes=("VERIFIED_TOPIC_FIT",),
                selection_checks=checks,
                shared_feature_axes=shared,
                features=features,
                score=len(shared),
            )
        )
        if len(selected) >= int(parameters.get("maximum_sources", 6)):
            break
    minimum = int(parameters.get("minimum_sources", 3))
    checkpoint = {
        "main_item_id": main_id,
        "input_hash": object_hash(documents),
        "rejected": rejected,
        "selected_item_ids": [row["evidence"]["item_id"] for row in selected],
    }
    if len(selected) < minimum:
        code = (
            "COMPARISON_SOURCES_REQUIRED"
            if context.allow_fetch(parameters)
            else "MISSING_SOURCE_FETCH_DISABLED"
        )
        result = Outcome.needs(code, required_sources=minimum, supplied_sources=len(selected))
        result.outputs["checkpoint"] = ("ResearchCheckpointV1", checkpoint, {})
        if context.allow_fetch(parameters):
            specs = parameters.get("approved_sources", [])
            result.outputs["plan"] = (
                "FetchPlanV1",
                {
                    "purpose": "missing_sources",
                    "sources": specs,
                    "query": target.title,
                    "target_item_id": main_id,
                    "target_hash": object_hash(main),
                    "maximum_attempts": int(parameters.get("maximum_attempts", 3)),
                },
                {},
            )
        return result
    revision = int(parameters.get("revision", 1))
    as_of = date.fromisoformat(main["fetched_at"][:10])
    comparison = build_comparison(
        target.item_id, revision, target.verified_facts, tuple(previous), tuple(competitors), as_of
    )
    comparison = comparison.model_copy(
        update={
            "analysis": ComparisonAnalysisV1(
                item_id=target.item_id,
                item_version=target.item_version,
                policy_version="comparison-v1",
                target_topic=target_topic,
                selection_criteria=("purpose", "environment", "function"),
                candidates=tuple(assessments),
                selected_item_ids=tuple(UUID(row["evidence"]["item_id"]) for row in selected[1:]),
            )
        }
    )
    facts: list[VerifiedFactV1] = []
    references: list[SourceReferenceV1] = []
    sources, provenance = [], []
    for row in selected:
        evidence = EvidencePackageV1.model_validate(row["evidence"])
        facts.extend(evidence.verified_facts)
        references.append(
            SourceReferenceV1(
                url=evidence.canonical_url,
                reference_id=evidence.package_id,
                fact_ids=tuple(f.fact_id for f in evidence.verified_facts),
            )
        )
        sources.append(
            {
                "url": str(evidence.canonical_url),
                "body": row["content"]["body"],
                "evidence": row["evidence"],
                "anchors": row["anchors"],
            }
        )
        provenance.extend(row.get("provenance", []))
    dataset_id = uuid5(NAMESPACE, object_hash(comparison.model_dump(mode="json")))
    coverage = coverage_for_sources(
        (
            str(row["evidence"]["canonical_url"]),
            EvidencePackageV1.model_validate(row["evidence"]).verified_facts,
        )
        for row in selected
    )
    package = ArticlePackageV1(
        item_id=target.item_id,
        revision=revision,
        topic=target.title,
        topic_profile=target_topic,
        item_version=target.item_version,
        facts=tuple(facts),
        comparison=comparison,
        verified_fact_ids=tuple(f.fact_id for f in facts),
        comparison_dataset_id=dataset_id,
        source_references=tuple(references),
        comparison_required_rows=tuple(row[0] for row in coverage.rows),
        uncertainties=target.uncertainties,
        writing_policy_version="writing-v7",
    )
    require_comparison_coverage(package)
    package_id = uuid5(NAMESPACE, object_hash(package.model_dump(mode="json")))
    return output(
        "package",
        "ArticlePackageV1",
        {
            "article_package_id": str(package_id),
            "package": package.model_dump(mode="json"),
            "sources": sources,
            "provenance": provenance,
            "created_at": main["fetched_at"],
            "mode": "shadow"
            if "shadow" in (parameters.get("mode"), context.config.get("comparison_selection_mode"))
            else "production",
        },
    )
