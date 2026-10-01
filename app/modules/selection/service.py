from app.contracts.editorial_v1 import SelectionOutputV1
from app.contracts.evidence_v1 import EvidencePackageV1

POLICY_VERSION = "selection-v1"


def rule_selection(package: EvidencePackageV1) -> SelectionOutputV1:
    missing = []
    kinds = {f.fact_type for f in package.verified_facts}
    if package.rights_blocked:
        return SelectionOutputV1(decision="rejected", score=0, reason_codes=("RIGHTS_BLOCKED",))
    if package.quality_score < 0.6:
        missing.append("EXTRACTION_QUALITY")
    if any(
        sum(f.fact_type == kind for f in package.verified_facts) > 1
        for kind in ("organization", "product")
    ):
        missing.append("AMBIGUOUS_PRODUCT_IDENTITY")
    if not {"organization", "product"} <= kinds:
        missing.append("PRODUCT_AND_ORGANIZATION_EVIDENCE")
    if not kinds - {"organization", "product"}:
        missing.append("ANNOUNCEMENT_FACTS")
    return SelectionOutputV1(
        decision="deferred" if missing else "selected",
        score=0 if missing else 0.8,
        reason_codes=("PRIMARY_INFORMATION_INSUFFICIENT",)
        if missing
        else ("VERIFIED_PRIMARY_FACTS",),
        missing_requirements=tuple(missing),
    )
