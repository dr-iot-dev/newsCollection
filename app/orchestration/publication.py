"""Explicit human publication operations with durable intent before remote writes.

This service owns its commits. Call it with a plain Session, never inside session.begin().
An ambiguous create is only reconciled, never replayed, because WordPress has no atomic
idempotency-key API. Crashes in the commit/send gap intentionally require operator recovery.
"""

import hashlib
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.article_package_v1 import ArticlePackageV1
from app.contracts.draft_v1 import ArticleDraftV1
from app.contracts.editorial_v1 import ReviewChecklistV1
from app.contracts.envelope import ContractEnvelope, canonical_payload_hash
from app.contracts.publication_v1 import PublicationPackageV1
from app.contracts.wordpress_v1 import (
    PublishApprovalRequestV1,
    PublishRequestV1,
    WordPressPayloadV1,
    WordPressRequestV1,
)
from app.core.config import Settings
from app.core.editorial import EditorialError
from app.infrastructure.db.models import (
    ApiUser,
    ArticleDraft,
    ArticlePackage,
    FeaturedImage,
    Item,
    ItemStatus,
    Publication,
    PublishApproval,
    Review,
    VerificationRun,
)
from app.infrastructure.wordpress import WordPressClient, validate_base_url
from app.modules.publication.ports import PublicationPort
from app.modules.publication.service import (
    build_payload,
    idempotency_key,
    matches_payload,
    remote_hash,
)
from app.orchestration.editorial import (
    EditorialService,
    checked_payload,
    item_for_update,
    latest,
    touch,
)
from app.orchestration.source_sets import claim_source_set, package_source_set


class PublicationService:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        port: PublicationPort | None = None,
    ) -> None:
        self.session, self.settings = session, settings
        if not settings.wordpress_enabled:
            raise EditorialError("WORDPRESS_DISABLED", 503)
        self.base_url = validate_base_url(settings.wordpress_base_url)
        self.target = "wordpress:" + hashlib.sha256(self.base_url.encode()).hexdigest()
        if port is None:
            if settings.wordpress_application_password is None:
                raise EditorialError("WORDPRESS_CREDENTIALS_REQUIRED", 503)
            port = WordPressClient(
                self.base_url,
                settings.wordpress_username,
                settings.wordpress_application_password.get_secret_value(),
            )
        self.port = port
        self.editorial = EditorialService(session, settings)

    def actor(self, actor_id: UUID, role: str) -> ApiUser:
        user = self.session.get(ApiUser, actor_id, populate_existing=True)
        if user is None or not user.active or role not in user.roles:
            raise EditorialError("ROLE_REQUIRED", 403)
        return user

    def approved(
        self,
        item: Item,
        draft_id: UUID,
        *,
        require_human: bool = False,
    ) -> tuple[ArticleDraft, Review | VerificationRun, WordPressPayloadV1]:
        draft = latest(self.session, ArticleDraft, item.id)
        if draft is None or draft.id != draft_id:
            raise EditorialError("DRAFT_STALE")
        review = self.session.scalars(
            select(Review)
            .where(Review.item_id == item.id)
            .order_by(Review.created_at.desc(), Review.id.desc())
        ).first()
        approval: Review | VerificationRun
        if self.settings.review_required or require_human:
            if review is None or review.draft_id != draft.id or review.decision != "approve":
                raise EditorialError("HUMAN_APPROVAL_REQUIRED")
            checklist = ReviewChecklistV1.model_validate(review.checklist_json)
            if not all(v is True for v in checklist.model_dump().values()):
                raise EditorialError("REVIEW_CHECKLIST_INCOMPLETE")
            self.actor(review.reviewer_id, "reviewer")
            self.editorial.validate_for_approval(
                item, draft, review.reviewer_id, require_pending=False
            )
            approval = review
        else:
            if review is not None and review.draft_id == draft.id and review.decision != "approve":
                raise EditorialError("HUMAN_REVIEW_BLOCKED")
            approval = self.editorial.validate_for_approval(
                item, draft, None, require_pending=False
            )
        _, package = self.editorial.package(item)
        payload = build_payload(
            ArticleDraftV1.model_validate(draft.source_block["draft"]),
            package,
            self.target,
            self.settings.wordpress_category_map,
            self.settings.wordpress_tag_map,
        )
        return draft, approval, payload

    def publication(self, item: Item, publication_id: UUID) -> Publication:
        row = self.session.get(Publication, publication_id, populate_existing=True)
        if row is None or row.item_id != item.id or row.target != self.target:
            raise EditorialError("PUBLICATION_NOT_FOUND", 404)
        return row

    def validate_package(
        self,
        item: Item,
        row: Publication,
    ) -> tuple[Review | VerificationRun, WordPressPayloadV1]:
        if row.package_json is None or row.payload_json is None:
            raise EditorialError("PUBLICATION_LEGACY_REVIEW_REQUIRED")
        envelope = ContractEnvelope[PublicationPackageV1].model_validate(row.package_json)
        draft, review, payload = self.approved(
            item, row.draft_id, require_human=envelope.producer != "verification"
        )
        image = self.session.scalar(select(FeaturedImage).where(
            FeaturedImage.publication_id == row.id, FeaturedImage.state == "attached",
        ))
        if image is not None:
            if image.draft_id != row.draft_id or not image.remote_media_id:
                raise EditorialError("FEATURED_IMAGE_STALE")
            payload = payload.model_copy(update={"featured_media": int(image.remote_media_id)})
        approval_id = review.id
        if envelope.producer == "verification" and isinstance(review, Review):
            # A later switch to human review must not change the original AI provenance.
            approval_id = self.editorial.validate_for_approval(
                item, draft, None, require_pending=False
            ).id
        package = envelope.payload
        if (
            package.item_id != item.id
            or package.draft_id != row.draft_id
            or package.approval_id != approval_id
            or package.target != self.target
            or package.sanitized_content_hash
            != canonical_payload_hash({"content": payload.content})
            or package.cms_category_ids != payload.categories
            or package.cms_tag_ids != payload.tags
            or canonical_payload_hash(row.payload_json) != row.payload_hash
            or payload.model_dump(mode="json") != row.payload_json
        ):
            raise EditorialError("PUBLICATION_PACKAGE_STALE")
        return review, payload

    def fail(
        self, item: Item, row: Publication, exc: EditorialError, actor_id: UUID | None
    ) -> None:
        row.last_error = exc.code
        row.updated_at = datetime.now(UTC)
        touch(
            self.session,
            item,
            "wordpress.operation_failed",
            actor_id,
            publication_id=str(row.id),
            reason=exc.code,
        )
        self.session.commit()

    def accept_draft(
        self,
        item: Item,
        row: Publication,
        post: dict[str, Any],
        actor_id: UUID | None,
    ) -> None:
        if row.payload_json is None or not matches_payload(post, row.payload_json, "draft"):
            raise EditorialError("WORDPRESS_REMOTE_CONFLICT")
        row.remote_post_id = str(post["id"])
        row.remote_url, row.remote_status = post["link"], post["status"]
        row.remote_hash, row.state, row.last_error = remote_hash(post), "drafted", None
        touch(
            self.session,
            item,
            "wordpress.drafted",
            actor_id,
            ItemStatus.WP_DRAFTED,
            publication_id=str(row.id),
            remote_post_id=row.remote_post_id,
        )

    def checked_remote(self, row: Publication) -> dict[str, Any]:
        if not row.remote_post_id or not row.remote_hash:
            raise EditorialError("WORDPRESS_DRAFT_REQUIRED")
        post = self.port.get(row.remote_post_id)
        if str(post["id"]) != row.remote_post_id or remote_hash(post) != row.remote_hash:
            raise EditorialError("WORDPRESS_REMOTE_CONFLICT")
        if post["status"] != "draft":
            raise EditorialError("WORDPRESS_REMOTE_STATUS_CONFLICT")
        return post

    def create_draft(
        self,
        item_id: UUID,
        request: WordPressRequestV1,
        actor_id: UUID | None = None,
    ) -> Publication:
        if actor_id is not None:
            self.actor(actor_id, "editor")
        elif self.settings.review_required:
            raise EditorialError("HUMAN_APPROVAL_REQUIRED")
        item = item_for_update(self.session, item_id, request.expected_version)
        allowed = {ItemStatus.APPROVED, ItemStatus.WP_DRAFTED}
        if not self.settings.review_required:
            allowed.update({ItemStatus.VERIFIED, ItemStatus.REVIEW_PENDING})
        if item.status not in allowed:
            raise EditorialError("WORDPRESS_DRAFT_STATE_INVALID")
        draft, review, payload = self.approved(item, request.draft_id)
        key = idempotency_key(self.target, item.id, draft.revision)
        row = self.session.scalar(
            select(Publication).where(
                Publication.target == self.target, Publication.idempotency_key == key
            )
        )
        _, article_package = self.editorial.package(item)
        claim = claim_source_set(self.session, self.target, article_package, item.id)
        if claim.publication_id is not None and (row is None or claim.publication_id != row.id):
            raise EditorialError("WORDPRESS_SOURCE_SET_DUPLICATE")
        if row is not None and row.state in {"trashing", "trashed"}:
            raise EditorialError("WORDPRESS_DRAFT_TRASHED")
        if row is None:
            package = PublicationPackageV1(
                item_id=item.id,
                draft_id=draft.id,
                approval_id=review.id,
                sanitized_content_hash=canonical_payload_hash({"content": payload.content}),
                target=self.target,
                cms_category_ids=payload.categories,
                cms_tag_ids=payload.tags,
            )
            row = Publication(
                item_id=item.id,
                draft_id=draft.id,
                target=self.target,
                idempotency_key=key,
                payload_hash=canonical_payload_hash(payload.model_dump(mode="json")),
                payload_json=payload.model_dump(mode="json"),
                state="prepared",
                package_json=ContractEnvelope[PublicationPackageV1]
                .build(
                    package,
                    contract_type="PublicationPackageV1",
                    producer="review" if isinstance(review, Review) else "verification",
                    producer_version="0.4.0",
                )
                .model_dump(mode="json"),
            )
            self.session.add(row)
            self.session.flush()
        claim.publication_id, claim.draft_id = row.id, row.draft_id
        self.validate_package(item, row)
        try:
            if row.remote_post_id:
                self.checked_remote(row)
                self.session.commit()
                return row
            post = self.port.find(payload.slug)
            if post is not None:
                self.accept_draft(item, row, post, actor_id)
                self.session.commit()
                return row
            if row.state != "prepared":
                raise EditorialError("WORDPRESS_RECONCILIATION_PENDING")
            row.state = "creating"
            touch(
                self.session,
                item,
                "wordpress.create_intent",
                actor_id,
                publication_id=str(row.id),
                payload_hash=row.payload_hash,
            )
            expected = item.workflow_version
            row_id = row.id
            # Commit intent BEFORE POST. No subsequent request may repeat this create.
            self.session.commit()
            item = item_for_update(self.session, item_id, expected)
            if actor_id is not None:
                self.actor(actor_id, "editor")
            row = self.publication(item, row_id)
            self.validate_package(item, row)
            if row.state != "creating" or row.remote_post_id:
                raise EditorialError("WORDPRESS_RECONCILIATION_PENDING")
            post = self.port.create_draft(payload)
            self.accept_draft(item, row, post, actor_id)
            self.session.commit()
            return row
        except EditorialError as exc:
            self.fail(item, row, exc, actor_id)
            raise

    def approve_publish(
        self,
        item_id: UUID,
        request: PublishApprovalRequestV1,
        actor_id: UUID,
    ) -> PublishApproval:
        self.actor(actor_id, "publisher")
        if request.confirm_publish is not True:
            raise EditorialError("EXPLICIT_PUBLISH_CONFIRMATION_REQUIRED", 422)
        item = item_for_update(self.session, item_id, request.expected_version)
        if item.status not in {ItemStatus.WP_DRAFTED, ItemStatus.PUBLISH_APPROVED}:
            raise EditorialError("PUBLISH_APPROVAL_STATE_INVALID")
        row = self.publication(item, request.publication_id)
        if row.draft_id != request.draft_id:
            raise EditorialError("DRAFT_STALE")
        self.validate_package(item, row)
        _, review, _ = self.approved(item, row.draft_id, require_human=True)
        assert isinstance(review, Review)
        draft = self.session.get(ArticleDraft, row.draft_id)
        assert draft is not None
        if self.settings.review_require_four_eyes and draft.source_block.get("actor_id") == str(
            actor_id
        ):
            raise EditorialError("PUBLISH_FOUR_EYES_REQUIRED")
        self.checked_remote(row)
        approval = self.session.scalar(
            select(PublishApproval).where(PublishApproval.publication_id == row.id)
        )
        if approval is not None:
            self.validate_publish_approval(item, row, approval)
            return approval
        assert row.remote_hash is not None
        approval = PublishApproval(
            publication_id=row.id,
            review_id=review.id,
            publisher_id=actor_id,
            item_version=item.version,
            payload_hash=row.payload_hash,
            remote_hash=row.remote_hash,
        )
        self.session.add(approval)
        self.session.flush()
        row.state = "publish_approved"
        touch(
            self.session,
            item,
            "wordpress.publish_approved",
            actor_id,
            ItemStatus.PUBLISH_APPROVED,
            publication_id=str(row.id),
            publish_approval_id=str(approval.id),
        )
        self.session.commit()
        return approval

    def validate_publish_approval(
        self,
        item: Item,
        row: Publication,
        approval: PublishApproval,
    ) -> None:
        self.validate_package(item, row)
        _, review, _ = self.approved(item, row.draft_id, require_human=True)
        assert isinstance(review, Review)
        self.actor(approval.publisher_id, "publisher")
        if (
            approval.publication_id != row.id
            or approval.review_id != review.id
            or approval.item_version != item.version
            or approval.payload_hash != row.payload_hash
            or approval.remote_hash != row.remote_hash
        ):
            raise EditorialError("PUBLISH_APPROVAL_STALE")
        draft = self.session.get(ArticleDraft, row.draft_id)
        assert draft is not None
        if self.settings.review_require_four_eyes and draft.source_block.get("actor_id") == str(
            approval.publisher_id
        ):
            raise EditorialError("PUBLISH_FOUR_EYES_REQUIRED")

    def accept_published(
        self,
        item: Item,
        row: Publication,
        post: dict[str, Any],
        actor_id: UUID | None,
    ) -> None:
        if (
            str(post["id"]) != row.remote_post_id
            or row.payload_json is None
            or not matches_payload(post, row.payload_json, "publish")
        ):
            raise EditorialError("WORDPRESS_REMOTE_CONFLICT")
        row.remote_url, row.remote_status = post["link"], "publish"
        row.state, row.last_error, row.published_at = "published", None, datetime.now(UTC)
        touch(
            self.session,
            item,
            "wordpress.published",
            actor_id,
            ItemStatus.PUBLISHED,
            publication_id=str(row.id),
            remote_post_id=row.remote_post_id,
            remote_url=row.remote_url,
        )

    def publish(
        self,
        item_id: UUID,
        request: PublishRequestV1,
        actor_id: UUID,
    ) -> Publication:
        self.actor(actor_id, "publisher")
        item = item_for_update(self.session, item_id, request.expected_version)
        row = self.publication(item, request.publication_id)
        if row.draft_id != request.draft_id:
            raise EditorialError("DRAFT_STALE")
        if item.status == ItemStatus.PUBLISHED and row.state == "published":
            approval = self.session.get(PublishApproval, request.publish_approval_id)
            if approval is None or approval.publication_id != row.id:
                raise EditorialError("PUBLISH_APPROVAL_REQUIRED")
            return row
        if item.status != ItemStatus.PUBLISH_APPROVED:
            raise EditorialError("PUBLISH_APPROVAL_REQUIRED")
        approval = self.session.get(PublishApproval, request.publish_approval_id)
        if approval is None:
            raise EditorialError("PUBLISH_APPROVAL_REQUIRED")
        self.validate_publish_approval(item, row, approval)
        try:
            assert row.remote_post_id is not None
            if row.state == "publishing":
                post = self.port.get(row.remote_post_id)
                if post["status"] == "publish":
                    self.accept_published(item, row, post, actor_id)
                    self.session.commit()
                    return row
            self.checked_remote(row)
            row.state = "publishing"
            touch(
                self.session,
                item,
                "wordpress.publish_intent",
                actor_id,
                publication_id=str(row.id),
                publish_approval_id=str(approval.id),
            )
            expected = item.workflow_version
            row_id = row.id
            self.session.commit()
            item = item_for_update(self.session, item_id, expected)
            self.actor(actor_id, "publisher")
            row = self.publication(item, row_id)
            self.validate_publish_approval(item, row, approval)
            self.checked_remote(row)
            post = self.port.publish(row.remote_post_id or "")
            self.accept_published(item, row, post, actor_id)
            self.session.commit()
            return row
        except EditorialError as exc:
            self.fail(item, row, exc, actor_id)
            raise

    def accept_trashed(
        self, item: Item, row: Publication, post: dict[str, Any]
    ) -> None:
        if str(post["id"]) != row.remote_post_id or post["status"] != "trash":
            raise EditorialError("WORDPRESS_REMOTE_STATUS_CONFLICT")
        row.remote_status, row.state = "trash", "trashed"
        row.remote_hash, row.last_error = remote_hash(post), None
        touch(self.session, item, "wordpress.duplicate_trashed", publication_id=str(row.id))

    def trash_duplicate(self, publication_id: UUID, keep_id: UUID) -> Publication:
        """Explicit cleanup of an unmodified duplicate draft, with recoverable deletion."""
        row = self.session.get(Publication, publication_id)
        keep = self.session.get(Publication, keep_id)
        if row is None or keep is None or row.target != self.target or keep.target != self.target:
            raise EditorialError("PUBLICATION_NOT_FOUND", 404)
        if row.id == keep.id:
            raise EditorialError("WORDPRESS_DUPLICATE_REQUIRED")
        item = item_for_update(self.session, row.item_id)
        row = self.publication(item, row.id)
        if row.state == "trashed":
            self.session.commit()
            return row
        if row.state != "drafted" or keep.state not in {"drafted", "published"}:
            raise EditorialError("WORDPRESS_DRAFT_STATE_INVALID")

        def sources(publication: Publication) -> str:
            draft = self.session.get(ArticleDraft, publication.draft_id)
            if draft is None:
                raise EditorialError("DRAFT_NOT_FOUND")
            package = self.session.get(ArticlePackage, draft.article_package_id)
            if package is None:
                raise EditorialError("ARTICLE_PACKAGE_REQUIRED")
            return package_source_set(checked_payload(package, ArticlePackageV1))

        if sources(row) != sources(keep):
            raise EditorialError("WORDPRESS_DUPLICATE_REQUIRED")
        # Stop if an editor changed either post; never delete a published post.
        self.checked_remote(row)
        retained = self.port.get(keep.remote_post_id or "")
        if keep.payload_json is None or not matches_payload(
            retained, keep.payload_json, keep.remote_status or "draft"
        ):
            raise EditorialError("WORDPRESS_REMOTE_CONFLICT")
        row.state = "trashing"
        touch(
            self.session, item, "wordpress.duplicate_trash_intent",
            publication_id=str(row.id), retained_publication_id=str(keep.id),
        )
        expected, row_id = item.workflow_version, row.id
        self.session.commit()
        item = item_for_update(self.session, item.id, expected)
        row = self.publication(item, row_id)
        try:
            self.checked_remote(row)
            self.accept_trashed(item, row, self.port.trash(row.remote_post_id or ""))
            self.session.commit()
            return row
        except EditorialError as exc:
            self.fail(item, row, exc, None)
            raise

    def reconcile(self, publication_id: UUID, actor_id: UUID | None = None) -> Publication:
        row = self.session.get(Publication, publication_id)
        if row is None or row.target != self.target:
            raise EditorialError("PUBLICATION_NOT_FOUND", 404)
        item = item_for_update(self.session, row.item_id)
        row = self.publication(item, row.id)
        post: dict[str, Any] | None
        try:
            if row.state == "trashed":
                self.session.commit()
                return row
            if row.state == "trashing":
                post = self.port.get(row.remote_post_id or "")
                if post["status"] != "trash":
                    raise EditorialError("WORDPRESS_RECONCILIATION_PENDING")
                self.accept_trashed(item, row, post)
                self.session.commit()
                return row
            if row.state == "published":
                post = self.port.get(row.remote_post_id or "")
                if (
                    row.payload_json is None
                    or str(post["id"]) != row.remote_post_id
                    or not matches_payload(post, row.payload_json, "publish")
                ):
                    raise EditorialError("WORDPRESS_REMOTE_CONFLICT")
                row.updated_at = datetime.now(UTC)
                self.session.commit()
                return row
            self.validate_package(item, row)
            post = (
                self.port.get(row.remote_post_id)
                if row.remote_post_id
                else self.port.find((row.payload_json or {})["slug"])
            )
            if post is None:
                raise EditorialError("WORDPRESS_RECONCILIATION_PENDING")
            if row.state in {"prepared", "creating"}:
                allowed = {ItemStatus.APPROVED}
                if not self.settings.review_required:
                    allowed.update({ItemStatus.VERIFIED, ItemStatus.REVIEW_PENDING})
                if item.status not in allowed:
                    raise EditorialError("WORDPRESS_DRAFT_STATE_INVALID")
                self.accept_draft(item, row, post, actor_id)
            elif row.state == "publishing" and post["status"] == "publish":
                if item.status != ItemStatus.PUBLISH_APPROVED:
                    raise EditorialError("PUBLISH_APPROVAL_REQUIRED")
                approval = self.session.scalar(
                    select(PublishApproval).where(PublishApproval.publication_id == row.id)
                )
                if approval is None:
                    raise EditorialError("PUBLISH_APPROVAL_REQUIRED")
                self.validate_publish_approval(item, row, approval)
                self.accept_published(item, row, post, actor_id)
            else:
                self.checked_remote(row)
                row.last_error = None
                row.updated_at = datetime.now(UTC)
            self.session.commit()
            return row
        except EditorialError as exc:
            self.fail(item, row, exc, actor_id)
            raise


def process_verified_publications(
    session: Session,
    settings: Settings,
    limit: int = 10,
    port: PublicationPort | None = None,
) -> int:
    """Send AI-verified drafts using a plain Session; create_draft owns its commits."""
    if not settings.wordpress_enabled or settings.review_required:
        return 0
    service = PublicationService(session, settings, port)
    item_ids = list(
        session.scalars(
            select(Item.id)
            .where(
                Item.status.in_([ItemStatus.VERIFIED, ItemStatus.REVIEW_PENDING]),
                select(VerificationRun.id)
                .where(
                    VerificationRun.item_id == Item.id,
                    VerificationRun.overall_result == "pass",
                )
                .exists(),
            )
            .order_by(Item.created_at, Item.id)
            .limit(limit)
        )
    )
    sent = 0
    for item_id in item_ids:
        try:
            item = item_for_update(session, item_id)
            draft = latest(session, ArticleDraft, item.id)
            if draft is None:
                session.rollback()
                continue
            service.create_draft(
                item.id,
                WordPressRequestV1(expected_version=item.workflow_version, draft_id=draft.id),
            )
            sent += 1
        except EditorialError as exc:
            session.rollback()
            if exc.code == "WORDPRESS_SOURCE_SET_DUPLICATE":
                item = item_for_update(session, item_id)
                touch(
                    session, item, "wordpress.source_set_duplicate",
                    status=ItemStatus.NEEDS_CHANGES, reason=exc.code,
                )
                session.commit()
            structlog.get_logger().warning(
                "wordpress_auto_draft_blocked", item_id=str(item_id), error_code=exc.code
            )
    return sent
