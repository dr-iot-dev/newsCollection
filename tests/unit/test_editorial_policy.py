import pytest
from pydantic import ValidationError

from app.contracts.article_package_v1 import ArticlePackageV1
from app.core.config import Settings
from app.core.editorial import EditorialError
from app.orchestration.research import prepare_comparison
from tests.unit.test_comparison_research import add_article, prepared_root, seed_articles
from tests.unit.test_phase3 import settings


def config(**updates):
    return settings().model_copy(
        update={
            "comparison_min_sources": 3,
            "review_required": False,
            "fetch_missing_sources": False,
            "featured_images_enabled": False,
            **updates,
        }
    )


def prepared(session, **updates):
    target, _previous, _competitor = seed_articles(session)
    service = prepared_root(session, target, config(**updates))
    research = prepare_comparison(service, target.id)
    package = service.comparison(
        target.id, research.previous_ids, research.competitor_ids, request_missing=False
    )
    return target, service, package


def test_defaults_and_invalid_minimum(monkeypatch):
    monkeypatch.delenv("COMPARISON_MIN_SOURCES", raising=False)
    monkeypatch.delenv("REVIEW_REQUIRED", raising=False)
    defaults = Settings(_env_file=None)
    assert defaults.comparison_min_sources == 3
    assert defaults.review_required is False
    for value in (0, 22):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, comparison_min_sources=value)


def test_two_sources_block_generation_and_cannot_count_duplicate_urls(acquisition_session):
    session = acquisition_session
    target, _previous, competitor = seed_articles(session)
    service = prepared_root(session, target, config())
    service.facts(competitor.id)
    package = service.comparison(target.id, competitor_ids=(competitor.id,), request_missing=False)
    with pytest.raises(EditorialError, match="COMPARISON_MIN_SOURCES_REQUIRED"):
        service.draft(target.id)
    assert not service.runner.provider.calls
    dto = ArticlePackageV1.model_validate(package.payload_json)
    same = dto.source_references[-1].model_copy(
        update={"url": str(dto.source_references[-1].url) + "?utm_source=duplicate#section"}
    )
    with pytest.raises(EditorialError, match="COMPARISON_MIN_SOURCES_REQUIRED"):
        service.validate_source_count(
            dto.model_copy(update={"source_references": (*dto.source_references, same)})
        )
    service.settings = config(comparison_min_sources=2)
    assert service.draft(target.id) is not None


def test_multiple_competitors_meet_minimum_without_previous_article(acquisition_session):
    session = acquisition_session
    target = add_article(session, "target", "ExampleCorp", "ABC100", 8, "19,800", 30)
    first = add_article(session, "competitor", "OtherCorp", "XYZ200", 16, "29,800", 30)
    second = add_article(session, "alternative", "ThirdCorp", "DEF300", 32, "39,800", 29)
    service = prepared_root(session, target, config())
    research = prepare_comparison(service, target.id)
    assert not research.previous_ids
    assert set(research.competitor_ids) == {first.id, second.id}
    package = service.comparison(
        target.id, research.previous_ids, research.competitor_ids, request_missing=False
    )
    assert len(package.payload_json["source_references"]) == 3
    draft = service.draft(target.id)
    assert draft is not None
    assert service.verify(draft.id).overall_result == "pass"
