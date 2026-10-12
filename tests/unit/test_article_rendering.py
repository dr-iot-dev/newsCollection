import pytest

from app.core.editorial import EditorialError
from app.modules.rendering.service import normalize_source_section, sanitize_html


def test_sanitizer_removes_active_content_media_and_unsafe_links():
    value = sanitize_html(
        '<p onclick="evil()" style="bad">Safe<strong>bold</strong></p>'
        '<script>secret()</script><iframe src="https://evil.example"></iframe>'
        '<svg><script>x</script></svg><img src="https://evil.example/pixel">'
        '<a href="javascript:evil()" onmouseover="bad">bad link</a>'
        '<a href="https://vendor.example/source" target="_blank">Source</a>'
        "<!-- secret -->"
    )
    assert "secret" not in value and "evil" not in value and "style=" not in value
    assert "<img" not in value and "onclick" not in value and "onmouseover" not in value
    assert "<a>bad link</a>" in value
    assert 'href="https://vendor.example/source"' in value and "noopener noreferrer" in value
    assert "<strong>bold</strong>" in value


@pytest.mark.parametrize(
    "content",
    [
        "<p>Article.</p>",
        "<p>Article.</p>\n<h2>出典</h2><ul><li>https://old.example/source</li></ul>",
        "<p>Article.</p>\n<h2>出典</h2><ul><li>https://vendor.example/source</li></ul>"
        '<h2>出典</h2><ul><li><a href="https://vendor.example/source">Source</a></li></ul>',
    ],
)
def test_source_section_is_single_linked_and_idempotent(content):
    urls = [
        "https://vendor.example/source",
        "https://other.example/source",
        "https://vendor.example/source",
    ]
    normalized = normalize_source_section(content, urls)
    assert normalized.count("<h2>出典</h2>") == 1
    assert normalized.count('href="https://vendor.example/source"') == 1
    assert normalized.count('href="https://other.example/source"') == 1
    assert "old.example" not in normalized
    assert "<p>Article.</p>" in normalized
    assert normalize_source_section(normalized, urls) == normalized


def test_source_normalization_preserves_article_sections_and_quoted_headings():
    value = (
        "<p>出典に基づく本文。</p>"
        "<pre><code>## 出典</code></pre>"
        "<blockquote><h2>出典</h2><p>Quoted heading.</p></blockquote>"
        "<h2><em>出典</em></h2><ul><li>Old source.</li></ul>"
        "<h3>Old source details</h3><p>Only part of old sources.</p>"
        "<h2>Article limitations</h2><p>Keep this article section.</p>"
    )
    normalized = normalize_source_section(value, ["https://vendor.example/source"])
    assert "<p>出典に基づく本文。</p>" in normalized
    assert "<pre><code>## 出典</code></pre>" in normalized
    assert "<blockquote><h2>出典</h2><p>Quoted heading.</p></blockquote>" in normalized
    assert "Old source" not in normalized and "Only part" not in normalized
    assert "<h2>Article limitations</h2><p>Keep this article section.</p>" in normalized
    assert normalized.endswith("</a></li></ul>")


@pytest.mark.parametrize(
    "urls", [[], ["http://vendor.example/source"], ["https://user:secret@vendor.example/source"]]
)
def test_source_normalization_requires_verified_safe_source_links(urls):
    with pytest.raises(EditorialError, match="WORDPRESS_SOURCE_LINK_REQUIRED"):
        normalize_source_section("<p>Article.</p>", urls)
