from uuid import uuid4

import pytest

from app.contracts.comparison_selection_ai_v1 import ComparisonPlanAIOutputV1
from app.core.comparison_selection import bind_plan, validate_plan
from app.core.editorial import EditorialError
from tests.unit.test_comparison_selection import plan, source


def reference_plan(intent):
    data = intent.model_dump(mode="json")
    for key in ("product", "product_kind", "role", "audience", "environment", "purpose"):
        judgment = data[key]
        judgment["fact_ids"] = [e["fact_id"] for e in judgment.pop("evidence")]
    return ComparisonPlanAIOutputV1.model_validate(data)


def test_quotes_and_offsets_come_from_source_records_not_ai_text():
    original = source()
    intent = plan(original)
    refs = reference_plan(intent)
    bound = bind_plan(refs, original)
    assert bound == intent
    assert "evidence" not in refs.product.model_dump()
    assert bound.product.evidence[0] == original.anchors[refs.product.fact_ids[0]]
    validate_plan(bound, original)


def test_binding_cannot_replace_a_missing_reference_with_another_fact():
    original = source()
    refs = reference_plan(plan(original))
    refs = refs.model_copy(
        update={"purpose": refs.purpose.model_copy(update={"fact_ids": (uuid4(),)})}
    )
    with pytest.raises(EditorialError, match="COMPARISON_GROUNDING_INVALID"):
        bind_plan(refs, original)
