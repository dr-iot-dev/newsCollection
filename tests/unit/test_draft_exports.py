"""Generation-only export and delivery-history migration tests."""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.auth import create_user
from app.core.editorial import EditorialError
from app.infrastructure.db.models import DraftAsset, DraftExport, Publication
from app.infrastructure.db.session import get_db
from app.main import create_app
from app.orchestration.draft_exports import DraftExporter, process_draft_exports
from nw_generation.protocol import digest, read_bundle
from tests.unit.test_phase3 import prepared, review_request, settings


def setup_publication(session, tmp_path):
    """Historical test fixture name; prepares a local verified/reviewed draft only."""
    author, _ = create_user(session, "author", ["editor"])
    reviewer, _ = create_user(session, "reviewer", ["reviewer"])
    publisher, _ = create_user(session, "publisher", ["publisher"])
    session.commit()
    item, editorial, _ = prepared(session, author.id)
    draft = editorial.draft(item.id)
    editorial.verify(draft.id)
    editorial.review(item.id, review_request(item, draft), reviewer.id)
    session.commit()
    config = settings().model_copy(
        update={
            "draft_artifact_dir": tmp_path / "drafts",
            "featured_images_enabled": False,
            "review_required": False,
        }
    )
    return item, draft, author, reviewer, publisher, config, Mock(), editorial


def test_authenticated_api_has_export_permissions_and_no_cms_routes(acquisition_session, tmp_path):
    session = acquisition_session
    item, draft, _, _, _, config, _, _ = setup_publication(session, tmp_path)
    _, token = create_user(session, "reader", ["viewer"])
    _, etoken = create_user(session, "api-editor", ["editor"])
    session.commit()
    app = create_app()
    app.dependency_overrides[get_db] = lambda: session
    with (
        TestClient(app) as client,
        patch("app.api.routes.draft_exports.get_settings", return_value=config),
    ):
        assert client.post(f"/api/v1/items/{item.id}/wordpress/draft", json={}).status_code == 404
        url = f"/api/v1/items/{item.id}/draft-exports"
        body = {"draft_id": str(draft.id)}
        assert client.post(url, json=body).status_code == 401
        assert (
            client.post(url, headers={"Authorization": "Bearer " + token}, json=body).status_code
            == 403
        )
        response = client.post(url, headers={"Authorization": "Bearer " + etoken}, json=body)
        assert response.status_code == 200, response.text
        download = client.get(
            response.json()["download"], headers={"Authorization": "Bearer " + token}
        )
        assert download.status_code == 200
        assert download.headers["content-type"] == "application/zip"
        metadata, _ = read_bundle(download.content, draft=True)
        assert metadata["article_id"] == str(item.id)


def test_export_is_immutable_and_repairs_missing_shared_copy(acquisition_session, tmp_path):
    session = acquisition_session
    _, draft, _, _, _, config, _, _ = setup_publication(session, tmp_path)
    config = config.model_copy(update={"draft_transfer_dir": tmp_path / "transfer"})
    exporter = DraftExporter(session, config)
    first = exporter.export(draft.id)
    data = Path(first.file_path).read_bytes()
    shared = next((tmp_path / "transfer/ready").glob("*.nwdraft"))
    assert shared.read_bytes() == data
    shared.unlink()
    again = exporter.export(draft.id)
    assert again.id == first.id and shared.read_bytes() == data
    assert len(session.scalars(select(DraftExport)).all()) == 1
    assert session.scalars(select(Publication)).all() == []
    assert session.scalars(select(DraftAsset)).all() == []


def test_corrupt_local_artifact_blocks_export(acquisition_session, tmp_path):
    session = acquisition_session
    _, draft, _, _, _, config, _, _ = setup_publication(session, tmp_path)
    exporter = DraftExporter(session, config)
    row = exporter.export(draft.id)
    Path(row.file_path).write_bytes(b"broken")
    with pytest.raises(EditorialError, match="EXPORT_ARTIFACT_HASH_MISMATCH"):
        exporter.export(draft.id)


def test_shadow_never_creates_export_or_image_intent(acquisition_session, tmp_path):
    session = acquisition_session
    _, draft, _, _, _, config, _, _ = setup_publication(session, tmp_path)
    config = config.model_copy(update={"comparison_selection_mode": "shadow"})
    assert process_draft_exports(session, config) == 0
    with pytest.raises(EditorialError, match="SHADOW_EXPORT_DISABLED"):
        DraftExporter(session, config).export(draft.id)
    assert session.scalars(select(DraftExport)).all() == []


def test_image_ack_loss_preserves_draft_and_paid_attempt(acquisition_session, tmp_path):
    session = acquisition_session
    _, draft, _, _, _, config, _, _ = setup_publication(session, tmp_path)
    config = config.model_copy(update={"featured_images_enabled": True})
    provider = Mock()
    provider.generate.side_effect = RuntimeError("lost response")
    exporter = DraftExporter(session, config, provider)
    with pytest.raises(RuntimeError):
        exporter.export(draft.id)
    assert provider.generate.call_count == 1
    asset = session.scalar(select(DraftAsset))
    assert asset.state == "uncertain" and asset.attempt == 1
    with pytest.raises(EditorialError, match="AI_IMAGE_RECONCILIATION_PENDING"):
        exporter.export(draft.id)
    assert provider.generate.call_count == 1


def test_scheduler_republishes_cached_file_without_regeneration(acquisition_session, tmp_path):
    session = acquisition_session
    _, draft, _, _, _, config, _, _ = setup_publication(session, tmp_path)
    config = config.model_copy(update={"draft_transfer_dir": tmp_path / "transfer"})
    row = DraftExporter(session, config).export(draft.id)
    assert row.bundle_hash == digest(Path(row.file_path).read_bytes())
    assert process_draft_exports(session, config) == 0
    next((tmp_path / "transfer/ready").glob("*.nwdraft")).unlink()
    assert process_draft_exports(session, config) == 1


def test_history_export_is_read_only_and_retains_remote_identity(acquisition_session, tmp_path):
    from app.orchestration.delivery_history import export_history
    from nw_generation.protocol import load_json, object_hash

    session = acquisition_session
    item, draft, _, _, _, config, _, _ = setup_publication(session, tmp_path)
    target = "wordpress:" + "a" * 64
    payload = {
        "title": "Historical",
        "content": "<p>Saved</p>",
        "excerpt": "",
        "slug": "news-" + "b" * 64,
        "status": "draft",
        "categories": [3],
        "tags": [],
    }
    row = Publication(
        item_id=item.id,
        draft_id=draft.id,
        target=target,
        idempotency_key="b" * 64,
        remote_post_id="42",
        state="draft_created",
        remote_status="draft",
        payload_json=payload,
        payload_hash=object_hash(payload),
    )
    session.add(row)
    session.commit()
    destination = tmp_path / "history.json"
    assert export_history(session, config, target, destination) == 1
    record = load_json(destination.read_bytes())["deliveries"][0]
    assert record["remote_post_id"] == "42" and record["operation_key"] == "b" * 64
    assert record["article_id"] == str(item.id) and row.state == "draft_created"
    assert session.scalars(select(DraftExport)).all() == []
