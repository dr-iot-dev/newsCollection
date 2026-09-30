from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.sources.config import load_sources

EXAMPLE = Path("config/sources.example.yaml")


def test_example_config_is_valid() -> None:
    config = load_sources(EXAMPLE)
    assert len(config.sources) == 3
    assert config.sources[0].key == "vendor-official-feed"


def test_non_approved_source_cannot_be_collected() -> None:
    source = load_sources(EXAMPLE).sources[2].model_copy(update={"enabled": True})
    with pytest.raises(PermissionError, match="legal status"):
        source.assert_collectable()


def test_expired_approval_cannot_be_collected() -> None:
    source = load_sources(EXAMPLE).sources[0]
    future = datetime.now(UTC) + timedelta(days=181)
    with pytest.raises(PermissionError, match="expired"):
        source.assert_collectable(future)


@pytest.mark.parametrize(
    ("needle", "replacement", "message"),
    [
        ("https://vendor.example/news/feed.xml", "http://vendor.example/feed", "HTTPS"),
        ('type: "rss"', 'type: "rss"\n    api_token: "secret"', "secret-like"),
        (
            'name: "Vendor Official News"',
            'name: "Vendor Official News"\n    unknown: true',
            "extra",
        ),
    ],
)
def test_unsafe_config_is_rejected(
    tmp_path: Path, needle: str, replacement: str, message: str
) -> None:
    content = EXAMPLE.read_text(encoding="utf-8").replace(needle, replacement, 1)
    path = tmp_path / "sources.yaml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises((ValueError, ValidationError), match=message):
        load_sources(path)
