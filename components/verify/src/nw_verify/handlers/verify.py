"""Verify supplied draft, package, source text and actual writer model."""

import difflib
from typing import Any
from uuid import uuid5

from nw_verify._vendor.contracts.draft_v1 import ArticleDraftV1
from nw_verify._vendor.contracts.facts_v1 import ExtractedFactV1
from nw_verify._vendor.contracts.verification_v1 import CriterionResult, VerificationReportV1
from nw_verify._vendor.core.article_tables import comparison_prose
from nw_verify._vendor.modules.verification.service import REQUIRED_CRITERIA, rule_criteria, verification_policy

from ..common import Context, Outcome, StageInput, output, package_input, require_sources, required
from ..protocol import NAMESPACE, ProtocolError, object_hash


def run(inputs: dict[str, StageInput], parameters: dict[str, Any], context: Context) -> Outcome:
    package, source = package_input(inputs)
    supplied = required(inputs, "draft").payload
    draft = ArticleDraftV1.model_validate(supplied["draft"])
    require_sources(package, int(parameters.get("minimum_sources", 3)))
    if (
        supplied["package_hash"] != object_hash(source["package"])
        or str(draft.article_package_id) != source["article_package_id"]
        or draft.item_id != package.item_id
    ):
        raise ProtocolError("DRAFT_PACKAGE_STALE")
    writer = supplied.get("writer")
    sources = source.get("sources")
    if not writer or not sources or any("body" not in row for row in sources):
        return Outcome.needs("VERIFICATION_CONTEXT_REQUIRED")
    verifier_model = context.config.get("models", {}).get("verifier", "")
    if not verifier_model or (
        writer.get("provider") != "manual" and writer.get("model") == verifier_model
    ):
        raise ProtocolError("AI_MODELS_MUST_BE_DISTINCT")
    grounded = {}
    for record in sources:
        for fact_id, raw in record.get("anchors", {}).items():
            anchor = ExtractedFactV1.model_validate(raw)
            if record["body"][anchor.evidence_start : anchor.evidence_end] != anchor.evidence_text:
                raise ProtocolError("FACT_EVIDENCE_MISMATCH")
            if fact_id in grounded:
                raise ProtocolError("FACT_EVIDENCE_DUPLICATE")
            grounded[fact_id] = anchor
    for fact in package.facts:
        expected = grounded.get(str(fact.fact_id))
        if expected is None or any(
            getattr(fact, key) != getattr(expected, key)
            for key in (
                "fact_type",
                "subject",
                "predicate",
                "value",
                "unit",
                "currency",
                "date_precision",
                "region",
                "conditions",
                "attribution",
            )
        ):
            raise ProtocolError("FACT_EVIDENCE_MISMATCH")
    rules = {criterion.key: criterion for criterion in rule_criteria(draft, package)}
    _, prose = comparison_prose(draft.body_markdown, package)
    text = draft.title + "\n" + draft.lead + "\n" + prose
    if any(
        difflib.SequenceMatcher(None, row["body"], text, autojunk=False).find_longest_match().size
        >= 80
        for row in sources
    ):
        rules["original_expression"] = rules["original_expression"].model_copy(
            update={"result": CriterionResult.FAIL, "detail": "Long source expression copied"}
        )
    verification_id = uuid5(NAMESPACE, object_hash([supplied, source, verifier_model]))
    policy = verification_policy(package)
    data = {
        "draft": draft.model_dump(mode="json"),
        "package": package.model_dump(mode="json"),
        "sources": sources,
        "required_criteria": sorted(REQUIRED_CRITERIA),
        "verification_id": str(verification_id),
        "policy_version": policy,
        "verifier_profile_key": verifier_model,
    }
    report = context.generate("verifier", data, VerificationReportV1)
    if (
        report.draft_id != draft.draft_id
        or report.article_package_id != draft.article_package_id
        or report.verification_id != verification_id
        or report.policy_version != policy
        or report.verifier_profile_key != verifier_model
        or len(report.criteria) != len(REQUIRED_CRITERIA)
        or {c.key for c in report.criteria} != set(REQUIRED_CRITERIA)
        or any(not set(c.fact_ids) <= set(package.verified_fact_ids) for c in report.criteria)
    ):
        raise ProtocolError("VERIFIER_OUTPUT_SCOPE_INVALID")
    for criterion in report.criteria:
        if rules[criterion.key].result != CriterionResult.FAIL:
            rules[criterion.key] = criterion
    issues = [c.key for c in rules.values() if c.result != CriterionResult.PASSED]
    issues.extend(report.blocking_issues)
    report = report.model_copy(
        update={
            "draft_hash": object_hash(supplied["draft"]),
            "draft_revision": draft.revision,
            "article_package_hash": object_hash(source["package"]),
            "overall_result": "pass" if not issues and report.overall_result == "pass" else "fail",
            "criteria": tuple(rules.values()),
            "blocking_issues": tuple(issues),
        }
    )
    return output(
        "verification",
        "VerificationReportV1",
        {"report": report.model_dump(mode="json"), "verifier": context.records[-1]},
    )
