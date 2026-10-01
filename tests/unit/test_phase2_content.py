import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from app.core.content import normalize_text, normalize_url
from app.modules.acquisition.robots import RobotsPolicy
from app.modules.deduplication.service import compare
from app.modules.extraction.service import extract_content, parse_date
from app.sources.config import WebSelectors

FIXTURE = Path("tests/fixtures/phase2")
SELECTORS = WebSelectors(
    list_links="main a.news-card",
    title="h1",
    published_at="time[datetime]",
    body="article .content",
)


def extract(body: str, **options):
    return extract_content(
        item_id=uuid4(),
        item_version=1,
        snapshot_id=uuid4(),
        url="https://vendor.example/news/2026/x1",
        title="Fallback",
        body=body,
        published_at=None,
        language="und",
        is_html=True,
        **options,
    )


def test_selector_extraction_keeps_heading_and_lists_removes_boilerplate() -> None:
    content = extract((FIXTURE / "article.html").read_text(), selectors=SELECTORS)
    assert content.title == "Acme X1 gateway released"
    assert content.body.startswith("Connectivity\n")
    assert "Local data processing\n" in content.body
    for forbidden in (
        "Navigation",
        "evil.example",
        "previous instructions",
        "Enable JS",
        "Accept all cookies",
        "All rights reserved",
    ):
        assert forbidden not in content.body
    assert content.quality_score == 1
    assert content.date_precision == "second"
    assert content.published_at == datetime(2026, 9, 29, 23, tzinfo=UTC)
    assert content.modified_at == datetime(2026, 10, 1, 1, tzinfo=UTC)
    assert content.language == "en"
    assert content.language_confidence == 0.95
    assert str(content.canonical_url) == "https://vendor.example/news/2026/x1"


def test_jsonld_graph_and_open_graph_fallback() -> None:
    body = "A documented product release with official installation information. " * 8
    document = (
        '<html><head><meta property="og:title" content="OG title">'
        '<script type="application/ld+json">'
        + json.dumps(
            {
                "@graph": [
                    {
                        "@type": ["NewsArticle"],
                        "headline": "Structured title",
                        "articleBody": body,
                        "datePublished": "2026-09-30",
                    }
                ]
            }
        )
        + "</script></head><body><p>Other text</p></body></html>"
    )
    content = extract(document)
    assert content.title == "Structured title"
    assert content.extraction_method == "json_ld"
    assert content.date_precision == "date" and content.published_at is None
    assert content.published_date.isoformat() == "2026-09-30"
    content = extract(
        '<meta property="og:title" content="OG title"><article><p>' + body + "</p></article>"
    )
    assert content.title == "OG title" and content.extraction_method == "semantic_html"


def test_unstructured_or_short_pages_require_review_and_canonical_is_checked() -> None:
    content = extract(
        '<link rel="canonical" href="https://evil.example/secret"><h1>Title</h1><div>Short</div>'
    )
    assert content.quality_score < 0.6
    assert "canonical_rejected" in content.quality_reasons
    assert str(content.canonical_url).startswith("https://vendor.example/")
    assert (
        extract("<h1>Title</h1><div>" + ("Long unstructured text. " * 50) + "</div>").quality_score
        < 0.6
    )


@pytest.mark.parametrize("value", ["2026-09-30T09:00:00", "not a date", "2026-02-31", ""])
def test_unknown_timezone_or_invalid_date_never_gets_invented_time(value: str) -> None:
    assert parse_date(value) == (None, None, "unknown")


def test_normalization_preserves_semantic_query_and_path() -> None:
    assert normalize_text("Cafe\u0301  test\r\n\r\n\r\nnext") == "Caf\u00e9 test\n\nnext"
    assert (
        normalize_url("https://VENDOR.example:443/news/?id=2&utm_source=x&gclid=x#top")
        == "https://vendor.example/news/?id=2"
    )
    assert normalize_url("https://vendor.example/news") != normalize_url(
        "https://vendor.example/news/"
    )


@pytest.mark.parametrize(
    ("path", "allowed"),
    [
        ("/private", False),
        ("/private/open", True),
        ("/private/open/hidden", False),
        ("/news/a.pdf", False),
        ("/news/a.pdf?download=1", True),
        ("/public", True),
    ],
)
def test_robots_longest_match_wildcard_anchor_and_combined_groups(path: str, allowed: bool) -> None:
    policy = RobotsPolicy(
        "User-agent: TestNewsBot\nDisallow: /private\nAllow: /private/open\n"
        "Disallow: /*.pdf$\n\nUser-agent: TestNewsBot\nDisallow: /private/open/hidden\n"
        "\nUser-agent: *\nDisallow: /",
        "TestNewsBot/1.0",
    )
    assert policy.allowed("https://vendor.example" + path) is allowed


def test_robots_octets_and_allow_on_equal_specificity() -> None:
    policy = RobotsPolicy(
        "User-agent: *\nDisallow: /caf%C3%A9\nDisallow: /same\nAllow: /same\nDisallow: /private\n",
        "TestNewsBot/1.0",
    )
    assert not policy.allowed("https://vendor.example/caf\u00e9")
    assert not policy.allowed("https://vendor.example/%70rivate")
    assert policy.allowed("https://vendor.example/same")


def pair_content(value):
    return extract_content(
        item_id=uuid4(),
        item_version=1,
        snapshot_id=uuid4(),
        url=value["url"],
        title=value["title"],
        body=value["body"],
        published_at=datetime.fromisoformat(value["date"]).replace(tzinfo=UTC),
        language="en",
        is_html=False,
    )


def test_labeled_duplicate_fixture_precision_at_least_99_percent() -> None:
    pairs = json.loads((FIXTURE / "duplicate_pairs.json").read_text())
    true_positive = false_positive = positive = 0
    for pair in pairs:
        match = compare(pair_content(pair["left"]), pair_content(pair["right"]))
        if pair["duplicate"]:
            positive += 1
        if match.decision == "duplicate":
            if pair["duplicate"]:
                true_positive += 1
            else:
                false_positive += 1
        if not pair["duplicate"]:
            assert match.decision != "duplicate", pair["name"]
    assert len(pairs) == 56 and positive == 24
    assert true_positive >= 20
    assert true_positive / (true_positive + false_positive) >= 0.99


def test_unknown_dates_and_changed_numeric_specs_only_get_review_candidates() -> None:
    pairs = json.loads((FIXTURE / "duplicate_pairs.json").read_text())
    pair = next(p for p in pairs if p["name"] == "X1-changed_spec")
    left, right = pair_content(pair["left"]), pair_content(pair["right"])
    assert compare(left, right).decision == "review"
    right = right.model_copy(update={"published_date": None, "published_at": None})
    assert compare(left, right).decision != "duplicate"


def test_public_ip_literals_are_rejected_before_network_access() -> None:
    from app.modules.acquisition.http import CollectionError, URLPolicy

    with pytest.raises(CollectionError, match="URL_BLOCKED"):
        URLPolicy(["93.184.216.34"]).validate("https://93.184.216.34/news")


def test_copied_template_with_different_manufacturer_requires_review() -> None:
    values = json.loads((FIXTURE / "duplicate_pairs.json").read_text())[0]
    left, right = pair_content(values["left"]), pair_content(values["right"])
    right = right.model_copy(update={"title": "Zenith X1 gateway released"})
    assert compare(left, right).decision == "review"


def test_invalid_css_selectors_and_missing_web_approval_are_configuration_errors() -> None:
    from pydantic import ValidationError

    from app.sources.config import load_sources

    config = load_sources(Path("config/sources.example.yaml"))
    web = next(s for s in config.sources if s.type == "web")
    raw = web.model_dump()
    raw["selectors"]["body"] = "article["
    with pytest.raises(ValidationError, match="invalid CSS selector"):
        type(web).model_validate(raw)
    raw = web.model_dump()
    raw["allow_url_patterns"] = ["["]
    with pytest.raises(ValidationError, match="invalid URL pattern"):
        type(web).model_validate(raw)
    raw = web.model_dump()
    raw["legal"].update(status="approved", approved_by="test", terms_reviewed_at=datetime.now(UTC))
    with pytest.raises(ValidationError, match="robots_reviewed_at"):
        type(web).model_validate(raw)
