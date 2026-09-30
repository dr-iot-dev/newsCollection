import pytest

from app.infrastructure.db.models import ItemStatus
from app.orchestration.state_machine import validate_transition


def test_expected_transition_is_allowed() -> None:
    validate_transition(ItemStatus.FACTS_READY, ItemStatus.CANDIDATE_SELECTED)


def test_skipping_verification_is_rejected() -> None:
    with pytest.raises(ValueError, match="invalid item status transition"):
        validate_transition(ItemStatus.DRAFT_GENERATED, ItemStatus.APPROVED)


def test_failure_state_is_available_from_any_state() -> None:
    validate_transition(ItemStatus.EXTRACTED, ItemStatus.FAILED_RETRYABLE)
