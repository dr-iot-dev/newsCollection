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
    models = {
        "facts": FactsOutputV1,
        "selector": SelectionOutputV1,
        "writer": WritingOutputV1,
        "verifier": VerificationReportV1,
    }
    payload = {
        "format_version": 1,
        "description": "Public instructions and schema snapshot; no secrets or article data.",
        "policies": {
            "writing": WRITING_POLICY,
            "verification": VERIFICATION_POLICY,
            "research": RESEARCH_POLICY,
            "topics": TOPIC_POLICY,
        },
        "required_verification_criteria": sorted(REQUIRED_CRITERIA),
        "runtime_binding_required": {
            "writer": "Supply verified ArticlePackage plus allowed_numbers and allowed_entities.",
            "verifier": (
                "Bind verification_id, draft_id, article_package_id, policy_version, "
                "verifier_profile_key, criterion keys and fact IDs to the exact runtime input; "
                "see AIRunner.run and EditorialService.verify. This generic schema is incomplete "
                "without those bindings and deterministic validation."
            ),
        },
        "stage_inputs": {
            "facts": ["body (contacts masked with offsets preserved)",
                      "evidence_passages (text and character offsets)", "source_url"],
            "selector": ["EvidencePackageV1"],
            "writer": ["ArticlePackageV1", "allowed_numbers", "allowed_entities"],
            "verifier": ["ArticleDraftV1", "ArticlePackageV1", "required_criteria",
                         "verifier_profile_key", "verification_id", "policy_version", "policy"],
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
        "image_category_styles": {
            key: asdict(style) for key, style in CATEGORY_STYLES.items()
        },
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output == "-":
        print(rendered, end="")
    else:
        Path(args.output).write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    main()
