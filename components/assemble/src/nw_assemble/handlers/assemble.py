"""Deterministic, CMS-independent final assembly. No network or database."""

from typing import Any
from uuid import UUID

from bs4 import BeautifulSoup, Comment, Tag
from markdown_it import MarkdownIt

from nw_assemble._vendor.contracts.draft_v1 import ArticleDraftV1
from nw_assemble._vendor.contracts.verification_v1 import VerificationReportV1
from nw_assemble._vendor.modules.rendering.model_disclosure import append_model_disclosure

from ..common import Context, Outcome, StageInput, package_input, require_sources, required
from ..protocol import (
    ProtocolError,
    bundle_bytes,
    digest,
    normalize_url,
    object_hash,
    package_identity,
    source_hash,
)

ALLOWED = frozenset(
    {
        "p",
        "br",
        "h2",
        "h3",
        "h4",
        "ul",
        "ol",
        "li",
        "strong",
        "em",
        "a",
        "blockquote",
        "pre",
        "code",
        "table",
        "thead",
        "tbody",
        "tr",
        "th",
        "td",
        "hr",
    }
)


def sanitize(value: str) -> str:
    soup = BeautifulSoup(value, "html.parser")
    for node in list(soup.find_all(True)):
        if not isinstance(node, Tag) or node.parent is None:
            continue
        if node.name not in ALLOWED:
            node.decompose()
        else:
            href = node.get("href") if node.name == "a" else None
            node.attrs = {}
            if isinstance(href, str):
                normalize_url(href)
                node["href"] = href
                node["rel"] = "noopener noreferrer"
    for comment in soup.find_all(string=lambda s: isinstance(s, Comment)):
        comment.extract()
    return str(soup)


def run(inputs: dict[str, StageInput], parameters: dict[str, Any], context: Context) -> Outcome:
    package, package_source = package_input(inputs)
    source = required(inputs, "draft").payload
    draft = ArticleDraftV1.model_validate(source["draft"])
    verified = required(inputs, "verification").payload
    report = VerificationReportV1.model_validate(verified["report"])
    package_hash = object_hash(package_source["package"])
    draft_hash = object_hash(source["draft"])
    require_sources(package, int(parameters.get("minimum_sources", 3)))
    from nw_assemble._vendor.modules.verification.service import REQUIRED_CRITERIA

    if (
        report.blocking_issues
        or len(report.criteria) != len(REQUIRED_CRITERIA)
        or {c.key for c in report.criteria} != set(REQUIRED_CRITERIA)
        or any(c.result != "pass" for c in report.criteria)
    ):
        raise ProtocolError("VERIFICATION_REPORT_INVALID")
    if (
        report.overall_result != "pass"
        or report.draft_id != draft.draft_id
        or report.draft_hash != draft_hash
        or report.article_package_hash != package_hash
        or report.article_package_id != draft.article_package_id
        or report.draft_revision != draft.revision
        or source["package_hash"] != package_hash
    ):
        raise ProtocolError("VERIFICATION_BINDING_MISMATCH")
    if any(
        mode == "shadow"
        for mode in (
            parameters.get("mode"),
            context.config.get("comparison_selection_mode"),
            package_source.get("mode"),
            source.get("mode"),
        )
    ):
        raise ProtocolError("SHADOW_EXPORT_DISABLED")
    image_input = inputs.get("image")
    image = image_input.payload if image_input else None
    if image is not None and image["draft_hash"] != draft_hash:
        raise ProtocolError("FEATURED_IMAGE_STALE")
    if image is None and parameters.get("image_enabled", True):
        return Outcome.needs("FEATURED_IMAGE_REQUIRED")
    skip = image.get("skip_reason") if image else "disabled"
    if skip is not None and skip not in {"disabled", "manual_skip"}:
        raise ProtocolError("IMAGE_SKIP_REASON_INVALID")
    review_required = bool(
        context.config.get("review_required", False) or parameters.get("review_required", False)
    )
    approved = inputs.get("approval")
    decision = None
    if approved is not None:
        approval = approved.payload
        image_hash = image.get("asset_hash") if image else None
        if (
            approval.get("draft_hash") != draft_hash
            or approval.get("package_hash") != package_hash
            or approval.get("image_hash") != image_hash
            or not approval.get("actor_id")
        ):
            raise ProtocolError("REVIEW_BINDING_MISMATCH")
        decision = approval.get("decision")
        if (
            decision != "approve"
            or not approval.get("checklist")
            or not all(value is True for value in approval["checklist"].values())
        ):
            raise ProtocolError("REVIEW_CHECKLIST_INCOMPLETE")
    if review_required and decision != "approve":
        return Outcome.needs("HUMAN_APPROVAL_REQUIRED")
    md = (draft.lead + "\n\n" + draft.body_markdown).replace("\r\n", "\n").encode()
    html = sanitize(MarkdownIt("commonmark", {"html": False}).enable("table").render(md.decode()))
    names = {
        "facts": "事実抽出",
        "writer": "本文作成・編集",
        "verifier": "原稿のAI検証",
        "image": "画像生成",
    }
    stages = {}
    for record in source.get("provenance", []):
        stage = record.get("stage", names.get(record.get("role", ""), record.get("role")))
        if stage:
            stages[stage] = record.get("model", "モデルの記録なし")
    for role, record in (("writer", source.get("writer")), ("verifier", verified.get("verifier"))):
        if record:
            stages[names[role]] = record["model"]
    if image and not skip:
        stages["画像生成"] = image["model"]
    html = sanitize(append_model_disclosure(html, list(stages.items())))
    html_bytes = html.encode()
    files = {"article.md": md, "article.html": html_bytes}
    featured = None
    if image and not skip:
        assert image_input is not None
        raw = image_input.assets[image["path"]]
        if image["asset_hash"] != digest(raw):
            raise ProtocolError("IMAGE_HASH_MISMATCH")
        from nw_assemble._vendor.ai.images import validate_image

        validate_image(raw, f"{image['width']}x{image['height']}")
        files[image["path"]] = raw
        featured = {
            k: image[k] for k in ("path", "mime", "width", "height", "alt", "caption", "model")
        }
    meta = {
        "producer_id": str(UUID(parameters["producer_id"])),
        "article_id": str(draft.item_id),
        "draft_id": str(draft.draft_id),
        "revision": draft.revision,
        "artifact_revision": int(parameters.get("artifact_revision", 1)),
        "created_at": source["created_at"],
        "producer_version": "1.0.0",
        "title": draft.title,
        "excerpt": draft.lead,
        "category_keys": list(draft.category_keys),
        "tag_keys": list(draft.tags),
        "source_urls": [str(ref.url) for ref in package.source_references if ref.url],
        "source_normalization_version": "source-set-v1",
        "eligibility": {
            "verification": "pass",
            "draft_hash": draft_hash,
            "package_hash": package_hash,
            "html_hash": digest(html_bytes),
            "markdown_hash": digest(md),
            "render_binding": object_hash(
                [draft_hash, package_hash, "renderer-v1", digest(html_bytes)]
            ),
            "policy_version": report.policy_version,
            "mode": "production",
            "review_required": review_required,
            "review": decision,
            "minimum_sources": int(parameters.get("minimum_sources", 3)),
        },
        "provenance": [{"stage": stage, "model": model} for stage, model in stages.items()],
        "featured_image": featured,
        "image_skip_reason": skip,
    }
    meta["source_set_hash"] = source_hash(meta["source_urls"])
    meta["package_id"] = package_identity(meta)
    data = bundle_bytes(meta, files, draft=True)
    return Outcome(outputs={"bundle": ("DraftBundleV1", meta, {"bundle.nwdraft": data})})
