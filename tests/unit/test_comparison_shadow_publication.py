import pytest

from app.ai.diagnostics import validation_diagnostics
from app.contracts.comparison_selection_v1 import CandidateSuitabilityV1
from app.core.editorial import EditorialError


@pytest.mark.parametrize(
    "code",
    [
        "COMPARISON_GROUNDING_INVALID",
        "COMPARISON_OTHER_PRODUCT_GROUNDING",
        "COMPARISON_CELL_CONDITION_LOST",
        "COMPARISON_REQUIRED_CONDITION_FAILED",
    ],
)
def test_comparison_repair_has_specific_safe_diagnostics(code):
    diagnostic = validation_diagnostics(EditorialError(code), CandidateSuitabilityV1, 1)
    assert diagnostic[0]["code"] == code
    assert "AI_VALIDATION_ERROR" not in str(diagnostic)
