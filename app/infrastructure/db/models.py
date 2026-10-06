import enum
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

JSON_STORAGE = JSON().with_variant(JSONB(), "postgresql")


def enum_values(enum_class: type[enum.Enum]) -> list[str]:
    return [str(member.value) for member in enum_class]


class Base(DeclarativeBase):
    pass


class SourceType(enum.StrEnum):
    RSS = "rss"
    GITHUB_RELEASES = "github_releases"
    WEB = "web"


class LegalStatus(enum.StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    BLOCKED = "blocked"
    EXPIRED = "expired"


class ItemStatus(enum.StrEnum):
    DISCOVERED = "DISCOVERED"
    FETCHED = "FETCHED"
    EXTRACTED = "EXTRACTED"
    DEDUPED = "DEDUPED"
    FACTS_READY = "FACTS_READY"
    CANDIDATE_SELECTED = "CANDIDATE_SELECTED"
    CANDIDATE_DEFERRED = "CANDIDATE_DEFERRED"
    CANDIDATE_REJECTED = "CANDIDATE_REJECTED"
    COMPARISON_READY = "COMPARISON_READY"
    DRAFT_GENERATED = "DRAFT_GENERATED"
    VERIFICATION_PENDING = "VERIFICATION_PENDING"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    VERIFIED = "VERIFIED"
    REVIEW_PENDING = "REVIEW_PENDING"
    NEEDS_CHANGES = "NEEDS_CHANGES"
    APPROVED = "APPROVED"
    WP_DRAFTED = "WP_DRAFTED"
    PUBLISH_APPROVED = "PUBLISH_APPROVED"
    PUBLISHED = "PUBLISHED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_FINAL = "FAILED_FINAL"
    REJECTED = "REJECTED"
    BLOCKED_RIGHTS = "BLOCKED_RIGHTS"


class CreatedUpdatedMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Source(CreatedUpdatedMixin, Base):
    __tablename__ = "sources"
    __table_args__ = (Index("ix_sources_legal_enabled", "enabled", "legal_status"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    type: Mapped[SourceType] = mapped_column(
        Enum(SourceType, name="source_type", values_callable=enum_values), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSON_STORAGE, default=dict, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    legal_status: Mapped[LegalStatus] = mapped_column(
        Enum(LegalStatus, name="legal_status", values_callable=enum_values),
        default=LegalStatus.PENDING,
        nullable=False,
    )
    terms_url: Mapped[str | None] = mapped_column(Text)
    terms_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SourceCursor(Base):
    __tablename__ = "source_cursors"

    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), primary_key=True
    )
    etag: Mapped[str | None] = mapped_column(Text)
    last_modified: Mapped[str | None] = mapped_column(Text)
    last_external_id: Mapped[str | None] = mapped_column(Text)
    cursor_json: Mapped[dict[str, Any]] = mapped_column(JSON_STORAGE, default=dict, nullable=False)
    robots_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("robots_snapshots.id"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class RawSnapshot(Base):
    __tablename__ = "raw_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id"), nullable=False)
    requested_url: Mapped[str] = mapped_column(Text, nullable=False)
    final_url: Mapped[str] = mapped_column(Text, nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    response_headers: Mapped[dict[str, str]] = mapped_column(
        JSON_STORAGE, default=dict, nullable=False
    )
    content_type: Mapped[str] = mapped_column(Text, nullable=False)
    body_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    body_text: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retention_until: Mapped[date] = mapped_column(Date, nullable=False)


class Item(CreatedUpdatedMixin, Base):
    __tablename__ = "items"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_item_source_external"),
        UniqueConstraint(
            "source_id", "canonical_url", "content_sha256", name="uq_item_source_url_content"
        ),
        Index("ix_items_status_published", "status", "published_at"),
        Index("ix_items_canonical_url", "canonical_url"),
        Index("ix_items_content_sha", "content_sha256"),
        Index(
            "ix_items_duplicate",
            "duplicate_of_id",
            postgresql_where=text("duplicate_of_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id"), nullable=False)
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    title_original: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    language: Mapped[str] = mapped_column(String(10), nullable=False)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    simhash64: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[ItemStatus] = mapped_column(
        Enum(ItemStatus, name="item_status", values_callable=enum_values),
        default=ItemStatus.DISCOVERED,
        nullable=False,
    )
    duplicate_of_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("items.id"))
    workflow_version: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class ItemVersion(Base):
    __tablename__ = "item_versions"
    __table_args__ = (UniqueConstraint("item_id", "version_no"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id"), nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("raw_snapshots.id"), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Fact(Base):
    __tablename__ = "facts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id"), nullable=False)
    item_version: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )
    evidence_id: Mapped[uuid.UUID | None] = mapped_column(unique=True)
    evidence_package_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("evidence_packages.id", name="fk_facts_evidence_package")
    )
    fact_type: Mapped[str] = mapped_column(String(50), nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    predicate: Mapped[str] = mapped_column(Text, nullable=False)
    value_json: Mapped[dict[str, Any]] = mapped_column(JSON_STORAGE, nullable=False)
    normalized_value: Mapped[str | None] = mapped_column(Text)
    evidence_text: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_start: Mapped[int | None] = mapped_column(Integer)
    evidence_end: Mapped[int | None] = mapped_column(Integer)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    extractor: Mapped[str] = mapped_column(String(20), nullable=False)
    verified_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True)


class AiRun(Base):
    __tablename__ = "ai_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("items.id"))
    task_type: Mapped[str] = mapped_column(String(50), nullable=False)
    execution_role: Mapped[str] = mapped_column(String(20), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    model_profile_key: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(50), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(71), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(255))
    output_json: Mapped[dict[str, Any] | None] = mapped_column(JSON_STORAGE)
    validation_status: Mapped[str] = mapped_column(String(30), nullable=False)
    validation_errors_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON_STORAGE)
    token_in: Mapped[int | None] = mapped_column(Integer)
    token_out: Mapped[int | None] = mapped_column(Integer)
    cost_estimate: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AiModelProfile(CreatedUpdatedMixin, Base):
    __tablename__ = "ai_model_profiles"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    execution_role: Mapped[str] = mapped_column(String(20), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    parameters_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_STORAGE, default=dict, nullable=False
    )
    secret_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class CandidateDecision(Base):
    __tablename__ = "candidate_decisions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id"), nullable=False)
    evidence_package_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    score: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(JSON_STORAGE, nullable=False)
    missing_requirements: Mapped[list[str]] = mapped_column(
        JSON_STORAGE, default=list, nullable=False
    )
    policy_version: Mapped[str] = mapped_column(String(50), nullable=False)
    ai_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ai_runs.id"))
    input_hash: Mapped[str] = mapped_column(String(71), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class VersionedPayloadMixin:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id"), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON_STORAGE, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(71), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ComparisonDataset(VersionedPayloadMixin, Base):
    __tablename__ = "comparison_datasets"
    __table_args__ = (UniqueConstraint("item_id", "revision"),)


class ArticlePackage(VersionedPayloadMixin, Base):
    __tablename__ = "article_packages"
    __table_args__ = (UniqueConstraint("item_id", "revision"),)


class ArticleDraft(Base):
    __tablename__ = "article_drafts"
    __table_args__ = (UniqueConstraint("item_id", "revision"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id"), nullable=False)
    article_package_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("article_packages.id"), nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    lead: Mapped[str] = mapped_column(Text, nullable=False)
    body_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    category_keys: Mapped[list[str]] = mapped_column(JSON_STORAGE, nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSON_STORAGE, default=list, nullable=False)
    source_block: Mapped[dict[str, Any]] = mapped_column(JSON_STORAGE, nullable=False)
    risk_flags: Mapped[list[str]] = mapped_column(JSON_STORAGE, default=list, nullable=False)
    created_by_type: Mapped[str] = mapped_column(String(20), nullable=False)
    ai_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ai_runs.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class VerificationRun(Base):
    __tablename__ = "verification_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id"), nullable=False)
    draft_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("article_drafts.id"), nullable=False)
    ai_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ai_runs.id"), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(50), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(71), nullable=False)
    overall_result: Mapped[str] = mapped_column(String(20), nullable=False)
    criteria_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON_STORAGE, nullable=False)
    comparison_checks_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_STORAGE, nullable=False
    )
    blocking_issues_json: Mapped[list[str]] = mapped_column(JSON_STORAGE, nullable=False)
    warnings_json: Mapped[list[str]] = mapped_column(JSON_STORAGE, nullable=False)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id"), nullable=False)
    draft_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("article_drafts.id"), nullable=False)
    reviewer_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    decision: Mapped[str] = mapped_column(String(30), nullable=False)
    checklist_json: Mapped[dict[str, bool]] = mapped_column(JSON_STORAGE, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )


class Publication(CreatedUpdatedMixin, Base):
    __tablename__ = "publications"
    __table_args__ = (UniqueConstraint("target", "idempotency_key"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id"), nullable=False)
    draft_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("article_drafts.id"), nullable=False)
    target: Mapped[str] = mapped_column(String(100), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    remote_post_id: Mapped[str | None] = mapped_column(String(255))
    remote_url: Mapped[str | None] = mapped_column(Text)
    remote_status: Mapped[str | None] = mapped_column(String(30))
    payload_hash: Mapped[str] = mapped_column(String(71), nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    package_json: Mapped[dict[str, Any] | None] = mapped_column(JSON_STORAGE)
    payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSON_STORAGE)
    remote_hash: Mapped[str | None] = mapped_column(String(71))
    state: Mapped[str] = mapped_column(
        String(30), default="prepared", server_default="legacy", nullable=False
    )


class FeaturedImage(CreatedUpdatedMixin, Base):
    __tablename__ = "featured_images"
    __table_args__ = (UniqueConstraint("publication_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    publication_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("publications.id"), nullable=False)
    draft_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("article_drafts.id"), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    input_hash: Mapped[str] = mapped_column(String(71), nullable=False)
    state: Mapped[str] = mapped_column(String(30), nullable=False, default="prepared")
    image_bytes: Mapped[bytes | None] = mapped_column(LargeBinary)
    content_hash: Mapped[str | None] = mapped_column(String(71))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    remote_media_id: Mapped[str | None] = mapped_column(String(255))
    remote_url: Mapped[str | None] = mapped_column(Text)
    last_error: Mapped[str | None] = mapped_column(String(100))


class SourceSetClaim(CreatedUpdatedMixin, Base):
    __tablename__ = "source_set_claims"
    __table_args__ = (UniqueConstraint("scope", "source_set_hash"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    scope: Mapped[str] = mapped_column(String(100), nullable=False)
    source_set_hash: Mapped[str] = mapped_column(String(71), nullable=False)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id"), nullable=False)
    draft_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("article_drafts.id"))
    publication_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("publications.id"))


class PublishApproval(Base):
    __tablename__ = "publish_approvals"
    __table_args__ = (UniqueConstraint("publication_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    publication_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("publications.id"), nullable=False)
    review_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reviews.id"), nullable=False)
    publisher_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("api_users.id"), nullable=False)
    item_version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(71), nullable=False)
    remote_hash: Mapped[str] = mapped_column(String(71), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class JobRun(Base):
    __tablename__ = "job_runs"
    __table_args__ = (
        UniqueConstraint("idempotency_key"),
        Index("ix_job_runs_source_started", "source_id", "started_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    job_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sources.id"))
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    stats_json: Mapped[dict[str, Any]] = mapped_column(JSON_STORAGE, default=dict, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)


class ModuleMessage(Base):
    __tablename__ = "module_messages"
    __table_args__ = (UniqueConstraint("consumer", "payload_hash"),)

    message_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    contract_type: Mapped[str] = mapped_column(String(100), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(20), nullable=False)
    correlation_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    producer: Mapped[str] = mapped_column(String(50), nullable=False)
    consumer: Mapped[str] = mapped_column(String(50), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON_STORAGE, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(71), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_json: Mapped[dict[str, Any] | None] = mapped_column(JSON_STORAGE)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON_STORAGE)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RobotsSnapshot(Base):
    __tablename__ = "robots_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    origin: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    body_hash: Mapped[str | None] = mapped_column(String(71))
    decision: Mapped[str] = mapped_column(String(30), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TermsSnapshot(Base):
    __tablename__ = "terms_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id"), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    body_hash: Mapped[str | None] = mapped_column(String(71))
    decision: Mapped[str] = mapped_column(String(30), nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_entity", "entity_type", "entity_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    actor_type: Mapped[str] = mapped_column(String(30), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(255), nullable=False)
    before_json: Mapped[dict[str, Any] | None] = mapped_column(JSON_STORAGE)
    after_json: Mapped[dict[str, Any] | None] = mapped_column(JSON_STORAGE)
    trace_id: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ExtractionResult(VersionedPayloadMixin, Base):
    __tablename__ = "extraction_results"
    __table_args__ = (
        UniqueConstraint("item_id", "revision"),
        Index("ix_extraction_body_sha", "body_sha256"),
        Index("ix_extraction_url", "canonical_url"),
    )
    snapshot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("raw_snapshots.id"), nullable=False)
    body_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)


class DuplicateDecision(Base):
    __tablename__ = "duplicate_decisions"
    __table_args__ = (UniqueConstraint("item_id", "revision", "candidate_id"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id"), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    candidate_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("items.id"))
    candidate_revision: Mapped[int | None] = mapped_column(Integer)
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    score: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    reasons: Mapped[dict[str, Any]] = mapped_column(JSON_STORAGE, nullable=False)
    policy_version: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class EvidencePackage(VersionedPayloadMixin, Base):
    __tablename__ = "evidence_packages"
    __table_args__ = (
        UniqueConstraint("item_id", "revision"),
        UniqueConstraint("item_id", "input_hash"),
    )
    item_version: Mapped[int] = mapped_column(Integer, nullable=False)
    input_hash: Mapped[str] = mapped_column(String(71), nullable=False)


class ApiUser(CreatedUpdatedMixin, Base):
    __tablename__ = "api_users"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    roles: Mapped[list[str]] = mapped_column(JSON_STORAGE, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
