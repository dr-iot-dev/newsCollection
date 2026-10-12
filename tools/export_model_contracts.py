"""Export public model instructions and schemas without settings, DB, or API access.

Run from the repository root: python -m tools.export_model_contracts --output PATH
Use --output - when executing via stdin in a read-only container.
"""

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from app.ai.image_styles import CATEGORY_STYLES
from app.ai.provider import strict_schema
from app.ai.runner import PROMPTS
from app.contracts.article_package_v1 import ArticlePackageV1
from app.contracts.base import ContractModel
from app.contracts.comparison_discovery_v2 import (
    POLICY_VERSION as COMPARISON_DISCOVERY_POLICY,
)
from app.contracts.comparison_discovery_v2 import (
    ComparisonGroupProposalV2,
    DiscoveryEvidenceInventoryV2,
    DiscoveryGroupSelectionV2,
    DiscoveryReviewV2,
    DiscoverySemanticProfilesV2,
)
from app.contracts.comparison_dynamic_axes_v1 import POLICY as DYNAMIC_AXES_POLICY
from app.contracts.comparison_dynamic_axes_v1 import (
    AxisCandidatesRef,
    AxisReview,
    AxisSelection,
    AxisValuesRef,
)
from app.contracts.comparison_pair_discovery_v3 import (
    ACQUISITION_POLICY,
    KEYWORD_POLICY,
    KEYWORD_TARGET,
    SEARCH_POLICY,
    SEARCH_RESULTS_PER_KEYWORD,
    CategoryKeywords,
    DocumentFeatures,
    PairPlan,
    TripleReview,
)
from app.contracts.comparison_pair_discovery_v3 import (
    POLICY as PAIR_DISCOVERY_POLICY,
)
from app.contracts.comparison_selection_ai_v1 import (
    CandidateSuitabilityAIOutputV1,
    ComparisonPlanAIOutputV1,
)
from app.contracts.comparison_selection_v1 import (
    POLICY_VERSION as COMPARISON_SELECTION_POLICY,
)
from app.contracts.comparison_selection_v1 import (
    ComparisonSuitabilityOutputV1,
)
from app.contracts.discovery_search_vocabulary_v2 import (
    POLICY_VERSION as VOCABULARY_POLICY,
)
from app.contracts.discovery_search_vocabulary_v2 import (
    DiscoverySearchVocabularyV2,
)
from app.contracts.draft_v1 import ArticleDraftV1
from app.contracts.editorial_v1 import SelectionOutputV1, WritingOutputV1
from app.contracts.evidence_v1 import EvidencePackageV1
from app.contracts.facts_v1 import FactsOutputV1
from app.contracts.verification_v1 import VerificationReportV1
from app.modules.research.service import POLICY_VERSION as RESEARCH_POLICY
from app.modules.research.topics import POLICY_VERSION as TOPIC_POLICY
from app.modules.verification.service import POLICY_VERSION as VERIFICATION_POLICY
from app.modules.verification.service import REQUIRED_CRITERIA
from app.modules.writing.service import POLICY_VERSION as WRITING_POLICY


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="docs/model-contracts.json")
    args = parser.parse_args()
    models: dict[str, type[ContractModel]] = {
        "facts": FactsOutputV1,
        "discovery_vocabulary": DiscoverySearchVocabularyV2,
        "axis_discover": AxisCandidatesRef,
        "axis_extract": AxisValuesRef,
        "axis_repair": AxisValuesRef,
        "axis_select": AxisSelection,
        "axis_review": AxisReview,
        "pair_keywords": CategoryKeywords,
        "pair_category": CategoryKeywords,
        "pair_plan": PairPlan,
        "pair_cells": DocumentFeatures,
        "pair_review": TripleReview,
        "comparison_plan": ComparisonPlanAIOutputV1,
        "comparison_assess": CandidateSuitabilityAIOutputV1,
        "comparison_verify": ComparisonSuitabilityOutputV1,
        "discovery_plan": ComparisonGroupProposalV2,
        "discovery_groups": DiscoveryGroupSelectionV2,
        "discovery_profiles": DiscoverySemanticProfilesV2,
        "discovery_inventory": DiscoveryEvidenceInventoryV2,
        "discovery_assess": CandidateSuitabilityAIOutputV1,
        "discovery_review": DiscoveryReviewV2,
        "selector": SelectionOutputV1,
        "writer": WritingOutputV1,
        "verifier": VerificationReportV1,
    }
    payload = {
        "format_version": 1,
        "description": "Public instructions and schema snapshot; no secrets or article data.",
        "policies": {
            "discovery_search_vocabulary": VOCABULARY_POLICY,
            "comparison_dynamic_axes": DYNAMIC_AXES_POLICY,
            "comparison_selection": COMPARISON_SELECTION_POLICY,
            "comparison_pair_discovery": PAIR_DISCOVERY_POLICY,
            "comparison_pair_keywords": KEYWORD_POLICY,
            "comparison_pair_search": SEARCH_POLICY,
            "comparison_pair_acquisition": ACQUISITION_POLICY,
            "comparison_discovery": COMPARISON_DISCOVERY_POLICY,
            "writing": WRITING_POLICY,
            "verification": VERIFICATION_POLICY,
            "verification_with_selection": VERIFICATION_POLICY + "+selection-v1",
            "research": RESEARCH_POLICY,
            "topics": TOPIC_POLICY,
        },
        "required_verification_criteria": sorted(REQUIRED_CRITERIA),
        "runtime_binding_required": {
            "discovery_vocabulary": (
                "Validate unique IDs and labels, origin/source references, "
                "basic labels and aliases. "
                "Do not require frequency, literal quotes or shared-source coverage. "
                "Keep domain terms separate; "
                "search label/alias OR matches with NFKC, case folding "
                "and Latin boundaries, without AI. "
                "Record prompt, model, schema and policy versions; never reuse DynamicAxis caches."
            ),
            "dynamic_axes": (
                "Shadow analysis of three to five supplied documents. "
                "Discover candidate questions only; extract each source independently. "
                "Bind passage IDs to exact original paragraphs and item IDs to supplied sources. "
                "Bind extraction, assessment and review counts and axis IDs to the input axes. "
                "Compute strict majority after extraction, reject duplicate products, and "
                "require independent review before exporting selection-only comparison material."
            ),
            "pair_discovery": (
                "Category source selection only. "
                f"Target {KEYWORD_TARGET} distinctive grounded keywords. "
                "Search each keyword independently for up to "
                f"{SEARCH_RESULTS_PER_KEYWORD} unique article IDs; "
                "count distinct keyword IDs per article, never repetitions, and acquire candidates "
                "with at least three search hits for body validation. "
                "Category tags are not required. Exclude survey, case study, report and other "
                "non-product release titles from both initial documents and search candidates, "
                "and record matched title exclusion terms. "
                "Bind exact document hashes and quote offsets, "
                "freeze each pair plan, search only within group A, require two of three "
                "sources for at least three axes and independent review. Exhaustion requires "
                "ten completed unsuccessful pairs; interruptions never consume a pair. "
                "Selection does not approve a draft or publication."
            ),
            "discovery": (
                "Shadow only. Bind each fact ID and source context to its own product, "
                "validate dynamic major questions and announcement/product majorities, "
                "then require all six independent checks. V2 audit is not V1 selection approval."
            ),
            "writer": "Supply verified ArticlePackage plus allowed_numbers and allowed_entities.",
            "verifier": (
                "Bind verification_id, draft_id, article_package_id, policy_version, "
                "verifier_profile_key, criterion keys and fact IDs to the exact runtime input; "
                "see AIRunner.run and EditorialService.verify. This generic schema is incomplete "
                "without those bindings and deterministic validation."
            ),
        },
        "stage_inputs": {
            "discovery_vocabulary": [
                "optional domain_hint and three to five articles "
                "with article_id, title and extracted body"
            ],
            "axis_discover": ["three to five source bodies; axes and related passages only"],
            "axis_extract": ["one source and frozen candidate axes"],
            "axis_repair": ["one source, frozen candidates, previous values and review feedback"],
            "axis_select": ["candidate axes, extracted values and computed majority coverage"],
            "axis_review": ["selected axes, extracted values and original sources"],
            "pair_keywords": [
                "one registered source body with contacts masked, offsets preserved",
                "category_context: fixed category, generic exclusions, keyword target and policy",
                "each keyword requires its distinction_reason within the category",
            ],
            "pair_category": [
                "initial document keywords with validated original quotes",
                "category_context and document_frequency; distinction precedes frequency",
                "target approximately 50 distinct grounded labels; "
                "explain evidence shortfalls without padding",
                "complete grounded labels and equivalent quoted aliases only",
            ],
            "pair_plan": ["two registered source bodies and hashes, exact quote grounding"],
            "pair_cells": ["frozen pair plan and one candidate source body"],
            "pair_review": ["frozen axes, three grounded products and cells, majority coverage"],
            "discovery_profiles": [
                "eligible distinct product catalog with own verified facts and publication dates",
                "derived retrieval metadata only; not facts, user intent or comparison approval",
            ],
            "discovery_groups": [
                "eligible distinct product catalog with verified facts and publication dates",
                "seed item, optional editorial intent, group and detailed pool limits",
                "coarse proposal only; requires subsequent three-source planning and validation",
            ],
            "facts": [
                "body (contacts masked with offsets preserved)",
                "evidence_passages (text and character offsets)",
                "source_url",
            ],
            "comparison_plan": ["registered document", "verified facts", "exact fact grounding"],
            "comparison_assess": [
                "fixed ComparisonPlanV1",
                "candidate source",
                "fact_constraints (literal qualifiers and conditional status requirements)",
                "exclusion baseline",
            ],
            "comparison_verify": [
                "fixed ComparisonPlanV1",
                "selected product group",
                "grounded cells",
            ],
            "discovery_plan": [
                "three registered sources and verified facts",
                "bounded source context with contacts masked",
                "optional editorial_intent and maximum_hypotheses",
                "optional unapproved grounded evidence inventory, not fixed mandatory rows",
            ],
            "discovery_inventory": [
                "three registered sources, own verified facts and bounded masked context",
                "optional editorial intent and tentative group hint",
                "provisional questions and one grounded or unknown answer per source",
            ],
            "discovery_assess": [
                "joint hypothesis with frozen questions",
                "candidate source and condition constraints",
                "bounded source context with contacts masked",
            ],
            "discovery_review": [
                "joint hypothesis and all three grounded product evaluations",
                "all three sources with masked context and publication dates",
                "actual editorial intent only; no tentative inventories, "
                "group hints or superseded proposals",
            ],
            "selector": ["EvidencePackageV1"],
            "writer": ["ArticlePackageV1", "allowed_numbers", "allowed_entities"],
            "verifier": [
                "ArticleDraftV1",
                "ArticlePackageV1",
                "required_criteria",
                "verifier_profile_key",
                "verification_id",
                "policy_version",
                "policy",
            ],
        },
        "evidence_package_schema": EvidencePackageV1.model_json_schema(),
        "article_package_schema": ArticlePackageV1.model_json_schema(),
        "article_draft_schema": ArticleDraftV1.model_json_schema(),
        "stages": {
            role: {
                "instructions": PROMPTS[role],
                "output_schema": model.model_json_schema(),
                "provider_strict_schema": strict_schema(model.model_json_schema()),
            }
            for role, model in models.items()
        },
        "image_category_styles": {key: asdict(style) for key, style in CATEGORY_STYLES.items()},
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output == "-":
        print(rendered, end="")
    else:
        Path(args.output).write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    main()
