"""Snapshot verified drafts into immutable files. Never calls WordPress."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.content_v1 import NormalizedContentV1
from app.contracts.draft_v1 import ArticleDraftV1
from app.core.config import Settings
from app.core.editorial import EditorialError
from app.infrastructure.db.models import (
    AiRun,
    ArticleDraft,
    DraftAsset,
    DraftExport,
    ExtractionResult,
    FeaturedImage,
    Item,
    ItemStatus,
    Review,
)
from app.orchestration.editorial import EditorialService, checked_payload, latest
from app.orchestration.model_disclosure import article_model_stages, image_model_description
from nw_generation.common import Context, StageInput
from nw_generation.handlers.assemble import run as assemble
from nw_generation.handlers.illustrate import run as illustrate
from nw_generation.protocol import (
    atomic_write,
    canonical,
    digest,
    load_json,
    object_hash,
    process_lock,
)


def producer_identity(settings: Settings) -> str:
    if settings.draft_producer_id:
        return str(UUID(settings.draft_producer_id))
    from nw_generation.protocol import require_local

    directory = require_local(settings.draft_artifact_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "producer.json"
    with process_lock(directory / "producer.lock"):
        if not path.exists():
            atomic_write(path, canonical({"producer_id": str(uuid4())}), immutable=True)
        return str(UUID(load_json(path.read_bytes())["producer_id"]))


def stage(kind: str, payload: dict[str, Any], assets: dict[str, bytes] | None = None) -> StageInput:
    return StageInput({"contract_type": kind}, payload, assets or {})


def snapshot(session: Session, settings: Settings, draft: ArticleDraft) -> dict[str, Any]:
    item = session.get(Item, draft.item_id)
    if item is None:
        raise EditorialError("ITEM_NOT_FOUND")
    service = EditorialService(session, settings)
    row, package = service.package(item)
    current = latest(session, ArticleDraft, item.id)
    if current is None or current.id != draft.id:
        raise EditorialError("DRAFT_STALE")
    verification = service.validate_for_approval(item, draft, None, require_pending=False)
    approval = session.scalars(
        select(Review)
        .where(Review.draft_id == draft.id)
        .order_by(Review.created_at.desc(), Review.id.desc())
    ).first()
    if approval and approval.decision != "approve":
        raise EditorialError("HUMAN_REVIEW_BLOCKED")
    if settings.review_required:
        if approval is None or approval.decision != "approve":
            raise EditorialError("HUMAN_APPROVAL_REQUIRED")
        if not all(value is True for value in approval.checklist_json.values()):
            raise EditorialError("REVIEW_CHECKLIST_INCOMPLETE")
    dto = ArticleDraftV1.model_validate(draft.source_block["draft"])
    if object_hash(dto.model_dump(mode="json")) != draft.source_block["hash"]:
        raise EditorialError("DRAFT_HASH_MISMATCH")
    writer = session.get(AiRun, draft.ai_run_id) if draft.ai_run_id else None
    verifier = session.get(AiRun, verification.ai_run_id) if verification.ai_run_id else None
    if settings.ai_require_distinct_models and draft.created_by_type == "ai":
        if writer is None or verifier is None or writer.model == verifier.model:
            raise EditorialError("AI_MODELS_MUST_BE_DISTINCT")
    references = []
    for ref in package.source_references:
        if ref.url is None:
            continue
        # The saved package already validates the exact fact/source revisions.
        from app.infrastructure.db.models import Fact

        fact = session.get(Fact, ref.fact_ids[0]) if ref.fact_ids else None
        if fact is None:
            raise EditorialError("SOURCE_FACTS_REQUIRED")
        content = session.scalar(
            select(ExtractionResult).where(
                ExtractionResult.item_id == fact.item_id,
                ExtractionResult.revision == fact.item_version,
            )
        )
        if content is None:
            raise EditorialError("SOURCE_CONTENT_REQUIRED")
        normalized = checked_payload(content, NormalizedContentV1)
        references.append({"url": str(ref.url), "body": normalized.body})
    report = {
        "overall_result": verification.overall_result,
        "draft_revision": dto.revision,
        "draft_hash": object_hash(dto.model_dump(mode="json")),
        "article_package_hash": row.payload_hash,
        "verification_id": str(verification.id),
        "draft_id": str(dto.draft_id),
        "article_package_id": str(row.id),
        "policy_version": verification.policy_version,
        "verifier_profile_key": verifier.model_profile_key if verifier else "recorded-verification",
        "criteria": verification.criteria_json,
        "blocking_issues": verification.blocking_issues_json,
        "warnings": verification.warnings_json,
    }
    provenance = [
        {"stage": name, "model": model}
        for name, model in article_model_stages(session, draft, verification, package)
    ]
    result = {
        "package": {
            "article_package_id": str(row.id),
            "package": package.model_dump(mode="json"),
            "sources": references,
            "created_at": draft.created_at.isoformat(),
        },
        "draft": {
            "draft": dto.model_dump(mode="json"),
            "package_hash": row.payload_hash,
            "created_at": draft.created_at.isoformat(),
            "provenance": provenance,
            "writer": {
                "model": writer.model if writer else "手動編集",
                "provider": writer.provider if writer else "manual",
            },
        },
        "verification": {
            "report": report,
            "verifier": {"model": verifier.model if verifier else "モデルの記録なし"},
        },
    }
    if approval:
        result["approval"] = {
            "draft_hash": report["draft_hash"],
            "package_hash": row.payload_hash,
            "image_hash": None,
            "actor_id": str(approval.reviewer_id),
            "decision": approval.decision,
            "checklist": approval.checklist_json,
        }
    return result


class DraftExporter:
    """Owns commits for image intents/export; call with a plain Session."""

    def __init__(self, session: Session, settings: Settings, image_provider: Any = None):
        from nw_generation.protocol import require_local

        require_local(settings.draft_artifact_dir)
        self.session, self.settings = session, settings
        self.image_provider = image_provider

    def image(self, draft_id: UUID, saved: dict[str, Any]) -> StageInput:
        dto = saved["draft"]["draft"]
        if not self.settings.featured_images_enabled:
            return stage(
                "ImageAssetV1", {"draft_hash": object_hash(dto), "skip_reason": "disabled"}
            )
        asset = self.session.scalar(
            select(DraftAsset).where(DraftAsset.draft_id == draft_id).with_for_update()
        )
        if asset is None:
            imported = self.session.scalars(
                select(FeaturedImage)
                .where(FeaturedImage.draft_id == draft_id, FeaturedImage.image_bytes.is_not(None))
                .order_by(FeaturedImage.created_at.desc())
            ).first()
            asset = DraftAsset(
                draft_id=draft_id,
                input_hash=object_hash(dto),
                state="prepared",
                metadata_json={},
                attempt=0,
            )
            if imported is not None and imported.image_bytes is not None:
                asset.state = "generated"
                asset.image_bytes = imported.image_bytes
                asset.metadata_json = {
                    "draft_hash": object_hash(dto),
                    "path": "assets/featured.jpg",
                    "asset_hash": digest(imported.image_bytes),
                    "mime": "image/jpeg",
                    "width": imported.width,
                    "height": imported.height,
                    "alt": dto["title"],
                    "caption": (
                        "記事のテーマを表すAI生成のイメージイラストです。"
                        "製品の実物写真ではありません。"
                    ),
                    "model": image_model_description(self.session, imported),
                }
            self.session.add(asset)
            self.session.commit()
        if asset.input_hash != object_hash(dto):
            raise EditorialError("FEATURED_IMAGE_STALE")
        if asset.state == "generated" and asset.image_bytes:
            return stage(
                "ImageAssetV1",
                asset.metadata_json,
                {asset.metadata_json["path"]: asset.image_bytes},
            )
        if asset.attempt >= self.settings.ai_image_max_attempts:
            raise EditorialError("AI_IMAGE_ATTEMPT_BUDGET_EXHAUSTED")
        if asset.state != "prepared":
            raise EditorialError("AI_IMAGE_RECONCILIATION_PENDING")
        if self.image_provider is None and not self.settings.ai_api_key:
            raise EditorialError("AI_IMAGE_CREDENTIAL_REQUIRED")
        asset.state, asset.attempt = "generating", asset.attempt + 1
        self.session.commit()
        try:
            context = Context(
                config={
                    "models": {"image": self.settings.ai_image_model},
                    "image_size": self.settings.ai_image_size,
                    "image_quality": self.settings.ai_image_quality,
                },
                image_provider=self.image_provider,
            )
            # The independent adapter reads only its AI credential.
            if self.image_provider is None and self.settings.ai_api_key:
                from app.ai.images import OpenAIImageProvider

                context.image_provider = OpenAIImageProvider(
                    self.settings.ai_api_key.get_secret_value()
                )
            outcome = illustrate({"draft": stage("ArticleDraftV1", saved["draft"])}, {}, context)
            _, metadata, files = outcome.outputs["image"]
            asset = self.session.scalar(select(DraftAsset).where(DraftAsset.draft_id == draft_id))
            assert asset is not None
            asset.metadata_json, asset.image_bytes = metadata, files[metadata["path"]]
            asset.state, asset.last_error = "generated", None
            self.session.commit()
            return stage("ImageAssetV1", metadata, files)
        except Exception as exc:
            self.session.rollback()
            asset = self.session.scalar(select(DraftAsset).where(DraftAsset.draft_id == draft_id))
            assert asset is not None
            asset.state, asset.last_error = (
                "uncertain",
                getattr(exc, "code", "AI_IMAGE_RESULT_UNCERTAIN"),
            )
            self.session.commit()
            raise

    def export(self, draft_id: UUID, *, artifact_revision: int = 1) -> DraftExport:
        if self.settings.comparison_selection_mode == "shadow":
            raise EditorialError("SHADOW_EXPORT_DISABLED")
        draft = self.session.get(ArticleDraft, draft_id)
        if draft is None:
            raise EditorialError("DRAFT_NOT_FOUND")
        row = self.session.scalar(
            select(DraftExport)
            .where(
                DraftExport.draft_id == draft_id, DraftExport.artifact_revision == artifact_revision
            )
            .with_for_update()
        )
        if row is None:
            saved = snapshot(self.session, self.settings, draft)
            row = DraftExport(
                draft_id=draft_id,
                item_id=draft.item_id,
                artifact_revision=artifact_revision,
                snapshot_json=saved,
                state="prepared",
                producer_id=producer_identity(self.settings),
            )
            self.session.add(row)
            self.session.commit()
        # A delivered artifact is still checked and republished if the shared copy disappeared.
        if row.file_path and Path(row.file_path).exists():
            data = Path(row.file_path).read_bytes()
            if digest(data) != row.bundle_hash:
                raise EditorialError("EXPORT_ARTIFACT_HASH_MISMATCH")
        else:
            live = snapshot(self.session, self.settings, draft)
            if (
                live["draft"]["draft"] != row.snapshot_json["draft"]["draft"]
                or live["package"]["package"] != row.snapshot_json["package"]["package"]
                or live["verification"]["report"] != row.snapshot_json["verification"]["report"]
            ):
                raise EditorialError("EXPORT_SNAPSHOT_STALE")
            saved = row.snapshot_json
            image = self.image(draft_id, saved)
            inputs = {
                "package": stage("ArticlePackageV1", saved["package"]),
                "draft": stage("ArticleDraftV1", saved["draft"]),
                "verification": stage("VerificationReportV1", saved["verification"]),
                "image": image,
            }
            if "approval" in saved:
                approval = dict(saved["approval"])
                # Bind image approval only if the stored review explicitly included that asset.
                approval["image_hash"] = saved["approval"].get("image_hash")
                if (
                    image.payload.get("asset_hash")
                    and self.settings.review_required
                    and approval["image_hash"] != image.payload["asset_hash"]
                ):
                    raise EditorialError("IMAGE_REVIEW_REQUIRED")
                if approval["image_hash"] == image.payload.get("asset_hash"):
                    inputs["approval"] = stage("ApprovalRecordV1", approval)
            outcome = assemble(
                inputs,
                {
                    "producer_id": row.producer_id,
                    "artifact_revision": artifact_revision,
                    "minimum_sources": self.settings.comparison_min_sources,
                    "image_enabled": self.settings.featured_images_enabled,
                    "review_required": self.settings.review_required,
                },
                Context(),
            )
            if outcome.outcome != "success":
                raise EditorialError(outcome.issues[0]["code"])
            data = outcome.outputs["bundle"][2]["bundle.nwdraft"]
            path = self.settings.draft_artifact_dir / "ready" / (digest(data)[7:] + ".nwdraft")
            atomic_write(path, data, immutable=True)
            row.file_path, row.bundle_hash, row.state, row.last_error = (
                str(path),
                digest(data),
                "ready",
                None,
            )
            self.session.commit()
        if self.settings.draft_transfer_dir:
            destination = (
                self.settings.draft_transfer_dir / "ready" / (digest(data)[7:] + ".nwdraft")
            )
            atomic_write(destination, data, immutable=True)
            row.state = "delivered"
            self.session.commit()
        return row


def process_draft_exports(session: Session, settings: Settings, limit: int = 10) -> int:
    if not settings.draft_export_enabled or settings.comparison_selection_mode == "shadow":
        return 0
    ids = session.scalars(
        select(Item.id)
        .where(
            Item.status.in_([ItemStatus.VERIFIED, ItemStatus.REVIEW_PENDING, ItemStatus.APPROVED])
        )
        .order_by(Item.created_at, Item.id)
    ).all()
    count = 0
    for item_id in ids:
        draft = latest(session, ArticleDraft, item_id)
        if draft is None:
            continue
        existing = session.scalar(
            select(DraftExport).where(
                DraftExport.draft_id == draft.id, DraftExport.artifact_revision == 1
            )
        )
        if (
            existing
            and existing.bundle_hash
            and existing.file_path
            and Path(existing.file_path).exists()
        ):
            if (
                not settings.draft_transfer_dir
                or (
                    settings.draft_transfer_dir / "ready" / (existing.bundle_hash[7:] + ".nwdraft")
                ).exists()
            ):
                continue
        if count >= limit:
            break
        try:
            DraftExporter(session, settings).export(draft.id)
            count += 1
        except Exception as exc:
            session.rollback()
            import structlog

            structlog.get_logger().warning(
                "draft_export_pending",
                draft_id=str(draft.id),
                error_code=getattr(exc, "code", "EXPORT_FAILED"),
            )
    return count


def approve_export_image(
    session: Session, settings: Settings, export_id: UUID, reviewer_id: UUID, expected_hash: str
) -> DraftExport:
    from app.infrastructure.db.models import ApiUser
    from app.orchestration.editorial import touch

    row = session.scalar(select(DraftExport).where(DraftExport.id == export_id).with_for_update())
    if row is None or row.file_path is not None:
        raise EditorialError("IMAGE_APPROVAL_STATE_INVALID")
    user = session.get(ApiUser, reviewer_id)
    if user is None or not user.active or "reviewer" not in user.roles:
        raise EditorialError("ROLE_REQUIRED", 403)
    draft = session.get(ArticleDraft, row.draft_id)
    current = latest(session, ArticleDraft, row.item_id)
    if draft is None or current is None or current.id != draft.id:
        raise EditorialError("DRAFT_STALE")
    if settings.review_require_four_eyes and draft.source_block.get("actor_id") == str(reviewer_id):
        raise EditorialError("REVIEW_FOUR_EYES_REQUIRED")
    asset = session.scalar(select(DraftAsset).where(DraftAsset.draft_id == row.draft_id))
    if (
        asset is None
        or asset.state != "generated"
        or not asset.image_bytes
        or asset.metadata_json.get("asset_hash") != expected_hash
        or digest(asset.image_bytes) != expected_hash
    ):
        raise EditorialError("FEATURED_IMAGE_STALE")
    saved = dict(row.snapshot_json)
    if "approval" not in saved or saved["approval"]["decision"] != "approve":
        raise EditorialError("HUMAN_APPROVAL_REQUIRED")
    record = dict(saved["approval"])
    record.update(
        image_hash=expected_hash,
        text_actor_id=record["actor_id"],
        actor_id=str(reviewer_id),
        image_reviewed_at=datetime.now(UTC).isoformat(),
    )
    saved["approval"] = record
    row.snapshot_json = saved
    item = session.get(Item, row.item_id)
    assert item is not None
    touch(
        session,
        item,
        "draft.image_reviewed",
        reviewer_id,
        export_id=str(row.id),
        image_hash=expected_hash,
    )
    session.commit()
    return row
