import base64
import copy
import json
from email.parser import BytesParser
from email.policy import default
from io import BytesIO
from typing import get_args

import httpx
import pytest
from PIL import Image
from sqlalchemy import select

from app.ai.image_styles import CATEGORY_STYLES, image_style
from app.ai.images import OpenAIImageProvider, validate_image
from app.contracts.editorial_v1 import Category
from app.contracts.wordpress_v1 import WordPressRequestV1
from app.core.config import Settings
from app.core.editorial import EditorialError
from app.infrastructure.db.models import ArticleDraft, FeaturedImage
from app.orchestration.featured_images import (
    FeaturedImageService,
    image_prompt,
    process_featured_images,
)
from app.orchestration.publication import PublicationService
from tests.unit.test_phase4 import (
    CMS,
    approval_request,
    publish_request,
    setup_publication,
)


def jpeg(size="1536x1024"):
    width, height = map(int, size.split("x"))
    out = BytesIO()
    Image.new("RGB", (width, height), "teal").save(out, format="JPEG")
    return out.getvalue()


class ImageProvider:
    def __init__(self):
        self.calls = []
        self.error = None

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise EditorialError(self.error)
        return validate_image(jpeg(kwargs["size"]), kwargs["size"])


class MediaCMS(CMS):
    def __init__(self, post_type="post", rest_base="posts"):
        super().__init__(post_type, rest_base)
        self.media = {}
        self.upload_fault = None
        self.feature_fault = None
        self.upload_fields = []

    def handler(self, request):
        if "/media" in request.url.path:
            self.requests.append(request)
            key = request.url.path.rsplit("/", 1)[-1]
            if request.method == "GET":
                value = (
                    [m for m in self.media.values() if m["slug"] == request.url.params["slug"]]
                    if key == "media"
                    else self.media[int(key)]
                )
                return httpx.Response(200, json=value)
            if self.upload_fault == "before":
                raise httpx.ReadTimeout("upload uncertainty", request=request)
            message = BytesParser(policy=default).parsebytes(
                b"MIME-Version: 1.0\r\nContent-Type: "
                + request.headers["content-type"].encode()
                + b"\r\n\r\n"
                + request.content
            )
            fields = {
                part.get_param("name", header="content-disposition"): part.get_payload(decode=True)
                for part in message.iter_parts()
            }
            picture = validate_image(fields["file"], "1536x1024")
            text = {k: v.decode() for k, v in fields.items() if k != "file"}
            self.upload_fields.append(text)
            mid = 100 + len(self.media)
            media = {
                "id": mid,
                "slug": text["slug"],
                "type": "attachment",
                "media_type": "image",
                "mime_type": "image/jpeg",
                "source_url": f"https://cms.example/uploads/{mid}.jpg",
                "media_details": {"width": picture.width, "height": picture.height},
                "alt_text": text["alt_text"],
                "caption": {"raw": text["caption"]},
            }
            self.media[mid] = media
            if self.upload_fault == "after":
                raise httpx.ReadTimeout("upload uncertainty", request=request)
            return httpx.Response(201, json=media)
        if request.method == "POST" and request.content:
            data = json.loads(request.content)
            if "featured_media" in data:
                if self.feature_fault == "before":
                    self.requests.append(request)
                    return httpx.Response(503, json={})
                result = super().handler(request)
                if self.feature_fault == "after":
                    raise httpx.ReadTimeout("attachment uncertainty", request=request)
                return result
        return super().handler(request)

    @property
    def uploads(self):
        return [r for r in self.requests if r.method == "POST" and r.url.path.endswith("/media")]

    @property
    def attachments(self):
        return [
            r
            for r in self.requests
            if r.method == "POST"
            and not r.url.path.endswith("/media")
            and "featured_media" in json.loads(r.content)
        ]


def draft_for_images(session):
    item, draft, author, _reviewer, publisher, config, _cms, _svc = setup_publication(session)
    config = config.model_copy(update={"featured_images_enabled": True})
    cms = MediaCMS()
    publication = PublicationService(session, config, cms.client())
    row = publication.create_draft(
        item.id,
        WordPressRequestV1(
            expected_version=item.workflow_version,
            draft_id=draft.id,
        ),
        author.id,
    )
    provider = ImageProvider()
    return item, draft, publisher, config, row, cms, provider, publication


def test_adapter_uses_bounded_jpeg_generation_and_checks_dimensions():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(jpeg()).decode()}]})

    provider = OpenAIImageProvider("fixture-key", transport=httpx.MockTransport(handler))
    image = provider.generate(
        model="gpt-image-1.5",
        prompt="A generic sensor illustration",
        size="1536x1024",
        quality="medium",
    )
    assert (image.width, image.height) == (1536, 1024)
    assert len(calls) == 1 and calls[0].url.path == "/v1/images/generations"
    payload = json.loads(calls[0].content)
    assert payload["n"] == 1 and payload["output_format"] == "jpeg"
    assert payload["quality"] == "medium" and payload["background"] == "opaque"
    with pytest.raises(EditorialError, match="AI_IMAGE_DIMENSIONS_INVALID"):
        validate_image(jpeg("1024x1024"), "1536x1024")
    with pytest.raises(EditorialError, match="AI_IMAGE_INVALID"):
        validate_image(b"not a picture", "1536x1024")


@pytest.mark.parametrize("failure", ["network", "rejected", "malformed", "oversized"])
def test_provider_failures_never_retry_or_expose_key(failure):
    calls = []

    def handler(request):
        calls.append(request)
        if failure == "network":
            raise httpx.ReadTimeout("sensitive-response", request=request)
        if failure == "rejected":
            return httpx.Response(403, json={"error": "sensitive-response"})
        if failure == "oversized":
            return httpx.Response(200, content=b"x" * 12_000_001)
        return httpx.Response(200, json={"data": [{"b64_json": "invalid-base64"}]})

    provider = OpenAIImageProvider("fixture-key", transport=httpx.MockTransport(handler))
    with pytest.raises(EditorialError) as exc:
        provider.generate(model="gpt-image-1.5", prompt="Context", size="1536x1024", quality="low")
    assert len(calls) == 1
    assert "fixture-key" not in str(exc.value) and "sensitive-response" not in str(exc.value)


def test_image_is_attached_once_and_publication_validation_still_passes(acquisition_session):
    session = acquisition_session
    item, draft, _publisher, config, row, cms, provider, publication = draft_for_images(session)
    original = copy.deepcopy(cms.posts[int(row.remote_post_id)])
    assert process_featured_images(session, config, port=cms.client(), provider=provider) == 1
    image = session.scalars(select(FeaturedImage)).one()
    assert image.state == "attached" and image.image_bytes is not None
    assert len(provider.calls) == len(cms.uploads) == len(cms.attachments) == 1
    assert len(cms.posts) == 1 and cms.posts[1]["status"] == "draft"
    assert cms.posts[1]["featured_media"] == int(image.remote_media_id)
    assert cms.upload_fields[0]["alt_text"].startswith(draft.title)
    assert "AI生成" in cms.upload_fields[0]["caption"]
    assert "No text" in provider.calls[0]["prompt"]
    assert draft.title in provider.calls[0]["prompt"]
    assert not any(
        k in json.loads(cms.attachments[0].content) for k in ("title", "excerpt", "status")
    )
    assert cms.posts[1]["content"]["raw"].count("<h2>使用したAIモデル</h2>") == 1
    assert "画像生成: " + image.model in cms.posts[1]["content"]["raw"]
    assert (
        cms.posts[1]["content"]["raw"].split("<h2>使用したAIモデル</h2>")[0]
        == original["content"]["raw"].split("<h2>使用したAIモデル</h2>")[0]
    )
    for key in ("title", "excerpt", "slug", "categories", "tags"):
        assert cms.posts[1][key] == original[key]
    publication.validate_package(item, row)
    assert publication.checked_remote(row)["featured_media"] == int(image.remote_media_id)
    assert process_featured_images(session, config, port=cms.client(), provider=provider) == 0
    assert (
        FeaturedImageService(session, config, port=cms.client(), provider=provider)
        .ensure(
            row.id,
        )
        .id
        == image.id
    )
    assert len(provider.calls) == len(cms.uploads) == len(cms.attachments) == 1


@pytest.mark.parametrize("fault", ["before", "after"])
def test_upload_uncertainty_is_reconciled_without_duplicate_media(acquisition_session, fault):
    session = acquisition_session
    _item, _draft, _publisher, config, row, cms, provider, _publication = draft_for_images(session)
    service = FeaturedImageService(session, config, port=cms.client(), provider=provider)
    cms.upload_fault = fault
    with pytest.raises(EditorialError, match="WORDPRESS_NETWORK_UNCERTAIN"):
        service.ensure(row.id)
    image = session.scalars(select(FeaturedImage)).one()
    assert image.state == "uploading" and row.state == "drafted"
    cms.upload_fault = None
    if fault == "after":
        assert service.ensure(row.id).state == "attached"
    else:
        with pytest.raises(EditorialError, match="WORDPRESS_MEDIA_RECONCILIATION_PENDING"):
            service.ensure(row.id)
    assert len(provider.calls) == len(cms.uploads) == 1
    assert len(cms.media) == (1 if fault == "after" else 0)
    assert len(cms.posts) == 1


@pytest.mark.parametrize("fault", ["before", "after"])
def test_attachment_timeout_reconciles_without_regeneration_or_reupload(acquisition_session, fault):
    session = acquisition_session
    _item, _draft, _publisher, config, row, cms, provider, _publication = draft_for_images(session)
    service = FeaturedImageService(session, config, port=cms.client(), provider=provider)
    cms.feature_fault = fault
    with pytest.raises(EditorialError):
        service.ensure(row.id)
    assert session.scalars(select(FeaturedImage)).one().state == "attaching"
    cms.feature_fault = None
    assert service.ensure(row.id).state == "attached"
    assert len(provider.calls) == len(cms.uploads) == 1
    assert len(cms.attachments) == (1 if fault == "after" else 2)


@pytest.mark.parametrize("change", ["title", "content", "status", "featured_media"])
def test_human_changes_are_preserved_and_prevent_generation(acquisition_session, change):
    session = acquisition_session
    _item, _draft, _publisher, config, row, cms, provider, _publication = draft_for_images(session)
    cms.posts[1][change] = (
        {"raw": "Human edit"}
        if change in {"title", "content"}
        else "publish"
        if change == "status"
        else 999
    )
    before = copy.deepcopy(cms.posts)
    service = FeaturedImageService(session, config, port=cms.client(), provider=provider)
    if change == "featured_media":
        assert service.ensure(row.id).state == "skipped"
    else:
        with pytest.raises(EditorialError, match="WORDPRESS_REMOTE_CONFLICT"):
            service.ensure(row.id)
    assert cms.posts == before and not provider.calls and not cms.uploads


def test_generator_failure_does_not_lose_draft_or_repeat_billable_call(acquisition_session):
    session = acquisition_session
    _item, _draft, _publisher, config, row, cms, provider, _publication = draft_for_images(session)
    provider.error = "AI_IMAGE_NETWORK_UNCERTAIN"
    assert process_featured_images(session, config, port=cms.client(), provider=provider) == 0
    image = session.scalars(select(FeaturedImage)).one()
    assert image.state == "blocked" and row.state == "drafted"
    assert process_featured_images(session, config, port=cms.client(), provider=provider) == 0
    assert len(provider.calls) == 1 and not cms.uploads


def test_disabled_trashed_and_other_target_drafts_are_excluded(acquisition_session):
    session = acquisition_session
    _item, _draft, _publisher, config, row, cms, provider, _publication = draft_for_images(session)
    for disabled in (
        config.model_copy(update={"featured_images_enabled": False}),
        config.model_copy(update={"wordpress_enabled": False}),
        config.model_copy(update={"wordpress_base_url": "https://other.example"}),
    ):
        assert process_featured_images(session, disabled, port=cms.client(), provider=provider) == 0
    row.state = "trashed"
    session.commit()
    assert process_featured_images(session, config, port=cms.client(), provider=provider) == 0
    assert not provider.calls and not cms.uploads
    assert not session.scalars(select(FeaturedImage)).all()


@pytest.mark.parametrize("tamper", [False, True])
def test_featured_media_is_checked_before_human_publication(acquisition_session, tamper):
    session = acquisition_session
    item, draft, publisher, config, row, cms, provider, publication = draft_for_images(session)
    FeaturedImageService(session, config, port=cms.client(), provider=provider).ensure(row.id)
    approval = publication.approve_publish(
        item.id,
        approval_request(item, draft, row),
        publisher.id,
    )
    assert approval.payload_hash == row.payload_hash
    if tamper:
        cms.posts[1]["featured_media"] = 999
        with pytest.raises(EditorialError, match="WORDPRESS_REMOTE_CONFLICT"):
            publication.publish(item.id, publish_request(item, draft, row, approval), publisher.id)
        assert cms.posts[1]["status"] == "draft"
    else:
        publication.publish(item.id, publish_request(item, draft, row, approval), publisher.id)
        assert cms.posts[1]["status"] == "publish"
        assert cms.posts[1]["featured_media"] == int(
            session.scalars(select(FeaturedImage)).one().remote_media_id,
        )


def test_images_default_enabled_and_legacy_payload_remains_compatible(monkeypatch):
    from app.contracts.wordpress_v1 import WordPressPayloadV1
    from app.modules.publication.service import remote_payload

    monkeypatch.delenv("FEATURED_IMAGES_ENABLED", raising=False)
    assert Settings(_env_file=None).featured_images_enabled is True
    payload = WordPressPayloadV1(
        title="A", content="<p>B</p>", excerpt="C", slug="news-" + "a" * 64, categories=(1,)
    )
    assert "featured_media" not in payload.model_dump(mode="json")
    post = {
        **payload.model_dump(mode="json"),
        "featured_media": 0,
        **{k: {"raw": getattr(payload, k)} for k in ("title", "content", "excerpt")},
    }
    assert "featured_media" not in remote_payload(post)
    post["featured_media"] = 5
    assert remote_payload(post)["featured_media"] == 5
    with pytest.raises(EditorialError, match="WORDPRESS_RESPONSE_INVALID"):
        remote_payload({**post, "featured_media": True})


def prompt_draft(categories):
    return ArticleDraft(
        title="機器の接続と操作環境",
        lead="発表資料を比較する。",
        body_markdown="記事の本文である。",
        category_keys=categories,
    )


def test_all_supported_categories_have_distinct_whole_image_art_directions():
    # Adding a supported category requires a deliberately chosen visual identity.
    assert set(CATEGORY_STYLES) == set(get_args(Category))
    assert len({style.background for style in CATEGORY_STYLES.values()}) == len(CATEGORY_STYLES)
    for category, style in CATEGORY_STYLES.items():
        prompt = image_prompt(prompt_draft([category]))
        instructions, context = prompt.split("\n", 1)
        assert style.background in instructions and style.dominant in instructions
        assert "at least 70 percent" in instructions and "thumbnail size" in instructions
        assert "small badge, border, icon or tiny accent" in instructions
        assert "No text" in instructions and "unbranded" in instructions
        assert json.loads(context)["primary_category"] == category
    assert "restrained blue and teal with warm accents" not in image_prompt(
        prompt_draft(["edge_ai"])
    )


def test_primary_category_controls_palette_without_blending_secondary_categories():
    single = image_prompt(prompt_draft(["security"]))
    multiple = image_prompt(prompt_draft(["security", "iot_platform"]))
    assert single == multiple
    assert multiple != image_prompt(prompt_draft(["iot_platform", "security"]))


def test_future_unknown_category_has_stable_own_palette_and_empty_category_is_safe():
    assert image_style("future_health") == image_style("future_health")
    assert image_style("future_health") != image_style("future_energy")
    prompt = image_prompt(prompt_draft(["future_health"]))
    assert image_style("future_health").background in prompt
    assert json.loads(image_prompt(prompt_draft([])).split("\n", 1)[1])["primary_category"] == (
        "uncategorized"
    )


def test_existing_attached_image_is_not_regenerated_when_art_policy_changes(
    acquisition_session, monkeypatch
):
    session = acquisition_session
    _item, _draft, _publisher, config, row, cms, provider, _publication = draft_for_images(session)
    service = FeaturedImageService(session, config, port=cms.client(), provider=provider)
    original = service.ensure(row.id)
    recorded = (original.prompt, original.input_hash, original.remote_media_id)
    monkeypatch.setattr(
        "app.orchestration.featured_images.image_prompt", lambda draft: "New category art policy"
    )
    assert service.ensure(row.id).id == original.id
    assert (original.prompt, original.input_hash, original.remote_media_id) == recorded
    assert len(provider.calls) == len(cms.uploads) == len(cms.attachments) == 1


def test_untrusted_category_change_cannot_control_image_generation(acquisition_session):
    session = acquisition_session
    _item, draft, _publisher, config, row, cms, provider, _publication = draft_for_images(session)
    draft.category_keys = ["security"] if draft.category_keys != ["security"] else ["edge_ai"]
    session.commit()
    with pytest.raises(EditorialError, match="DRAFT_HASH_MISMATCH"):
        FeaturedImageService(session, config, port=cms.client(), provider=provider).ensure(row.id)
    assert not provider.calls and not cms.uploads
