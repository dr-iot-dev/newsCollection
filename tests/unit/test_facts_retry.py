from decimal import Decimal

import pytest
from sqlalchemy import delete

from app.core.editorial import EditorialError
from app.infrastructure.db.models import DuplicateDecision, ItemStatus
from tests.unit.test_comparison_research import prepared_root, seed_articles


@pytest.mark.parametrize("decision", ["separate", "review", "duplicate", None])
def test_first_fact_extraction_retry_requires_current_unambiguous_deduplication(
    acquisition_session, decision
):
    session = acquisition_session
    target, candidate, _ = seed_articles(session)
    service = prepared_root(session, target)
    candidate.status = ItemStatus.REVIEW_PENDING
    session.execute(delete(DuplicateDecision).where(DuplicateDecision.item_id == candidate.id))
    if decision:
        session.add(
            DuplicateDecision(
                item_id=candidate.id,
                revision=candidate.version,
                candidate_id=None,
                decision=decision,
                score=Decimal("0"),
                reasons={},
                policy_version="fixture",
            )
        )
    session.flush()
    if decision == "separate":
        evidence = service.facts(candidate.id)
        assert evidence is not None and evidence.payload_json["verified_facts"]
        assert candidate.status == ItemStatus.FACTS_READY
    else:
        with pytest.raises(EditorialError, match="DEDUPLICATION_REQUIRED"):
            service.facts(candidate.id)
