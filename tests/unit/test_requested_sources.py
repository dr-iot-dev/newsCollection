from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.extraction.service import extract_content, parse_date
from app.sources.config import WebSource, load_sources


def test_requested_sources_have_expected_urls_and_acquisition_status() -> None:
    config = load_sources(Path("config/sources.yaml"))
    sources = {source.key: source for source in config.sources}
    assert len(sources) == 3
    assert sources["prtimes-iot"].list_url == "https://prtimes.jp/topics/keywords/IoT"
    assert (
        sources["prtimes-electronics"].list_url
        == "https://prtimes.jp/topics/keywords/%E9%9B%BB%E5%AD%90%E5%B7%A5%E4%BD%9C"
    )
    assert sources["nikkei-topic-24032506"].list_url == "https://www.nikkei.com/topics/24032506"
    for key in ("prtimes-iot", "prtimes-electronics"):
        source = sources[key]
        source.assert_collectable(source.legal.terms_reviewed_at)
        assert source.legal.media_use == "none" and source.timezone_hint == "Asia/Tokyo"
        assert source.max_pages_per_run == 6 and source.min_delay_seconds == 5
    with pytest.raises(PermissionError):
        sources["nikkei-topic-24032506"].assert_collectable()
    assert sources["nikkei-topic-24032506"].legal.status == "pending"


def test_prtimes_naive_publication_time_is_interpreted_only_with_explicit_timezone() -> None:
    config = load_sources(Path("config/sources.yaml"))
    source = config.sources[0]
    content = extract_content(
        item_id=uuid4(),
        item_version=1,
        snapshot_id=uuid4(),
        url="https://prtimes.jp/main/html/rd/p/000000001.000000001.html",
        title="Untitled",
        body=Path("tests/fixtures/phase2/prtimes_structure.html").read_text(),
        published_at=None,
        language="ja",
        is_html=True,
        selectors=source.selectors,
        allowed_hosts=source.allowed_hosts,
        timezone_hint=source.timezone_hint,
    )
    assert content.title == "Example IoT release"
    assert content.published_at == datetime(2026, 9, 30, 6, 31, 35, tzinfo=UTC)
    assert content.modified_at == datetime(2026, 9, 30, 7, tzinfo=UTC)
    assert content.date_precision == "second" and content.quality_score >= 0.9
    assert "source_timezone:Asia/Tokyo" in content.quality_reasons
    assert "Footer excluded" not in content.body
    assert parse_date("2026-09-30 15:31:35") == (None, None, "unknown")
    raw = source.model_dump()
    raw["timezone_hint"] = "Unknown/Invalid"
    with pytest.raises(ValidationError, match="unknown publication timezone"):
        WebSource.model_validate(raw)


def test_disabled_nikkei_source_is_registered_without_any_network_request(
    acquisition_session,
) -> None:
    from sqlalchemy import select

    from app.infrastructure.db.models import LegalStatus, Source
    from app.modules.acquisition.service import collect_source
    from app.sources.service import sync_sources

    session = acquisition_session
    sync_sources(session, load_sources(Path("config/sources.yaml")), dry_run=False)
    session.commit()
    source = session.scalars(select(Source).where(Source.key == "nikkei-topic-24032506")).one()
    assert not source.enabled and source.legal_status == LegalStatus.PENDING

    def forbidden_network(_):
        pytest.fail("Nikkei must not make a network request while disabled")

    result = collect_source(session, source.key, force=True, http_factory=forbidden_network)
    assert result.status == "blocked" and result.error_code == "LEGAL_GATE_BLOCKED"
