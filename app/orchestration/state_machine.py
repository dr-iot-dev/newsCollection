from app.infrastructure.db.models import ItemStatus

ALLOWED_TRANSITIONS: dict[ItemStatus, frozenset[ItemStatus]] = {
    ItemStatus.DISCOVERED: frozenset({ItemStatus.FETCHED}),
    ItemStatus.FETCHED: frozenset({ItemStatus.EXTRACTED}),
    ItemStatus.EXTRACTED: frozenset({ItemStatus.DEDUPED}),
    ItemStatus.DEDUPED: frozenset({ItemStatus.FACTS_READY}),
    ItemStatus.FACTS_READY: frozenset(
        {
            ItemStatus.CANDIDATE_SELECTED,
            ItemStatus.CANDIDATE_DEFERRED,
            ItemStatus.CANDIDATE_REJECTED,
        }
    ),
    ItemStatus.CANDIDATE_SELECTED: frozenset({ItemStatus.COMPARISON_READY}),
    ItemStatus.COMPARISON_READY: frozenset({ItemStatus.DRAFT_GENERATED}),
    ItemStatus.DRAFT_GENERATED: frozenset({ItemStatus.VERIFICATION_PENDING}),
    ItemStatus.VERIFICATION_PENDING: frozenset(
        {ItemStatus.VERIFIED, ItemStatus.VERIFICATION_FAILED}
    ),
    ItemStatus.VERIFICATION_FAILED: frozenset({ItemStatus.NEEDS_CHANGES}),
    ItemStatus.VERIFIED: frozenset({ItemStatus.REVIEW_PENDING}),
    ItemStatus.REVIEW_PENDING: frozenset(
        {
            ItemStatus.APPROVED,
            ItemStatus.NEEDS_CHANGES,
            ItemStatus.REJECTED,
            ItemStatus.BLOCKED_RIGHTS,
        }
    ),
    ItemStatus.NEEDS_CHANGES: frozenset({ItemStatus.DRAFT_GENERATED, ItemStatus.REVIEW_PENDING}),
    ItemStatus.APPROVED: frozenset({ItemStatus.WP_DRAFTED}),
    ItemStatus.WP_DRAFTED: frozenset({ItemStatus.PUBLISH_APPROVED}),
    ItemStatus.PUBLISH_APPROVED: frozenset({ItemStatus.PUBLISHED}),
}

FAILURE_STATES = frozenset(
    {
        ItemStatus.FAILED_RETRYABLE,
        ItemStatus.FAILED_FINAL,
        ItemStatus.REJECTED,
        ItemStatus.BLOCKED_RIGHTS,
    }
)


def validate_transition(current: ItemStatus, target: ItemStatus) -> None:
    if target in FAILURE_STATES:
        return
    if target not in ALLOWED_TRANSITIONS.get(current, frozenset()):
        raise ValueError(f"invalid item status transition: {current.value} -> {target.value}")
