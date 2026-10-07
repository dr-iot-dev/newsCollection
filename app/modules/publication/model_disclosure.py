"""Reader-facing AI provenance, rendered from trusted execution records."""

from html import escape

from bs4 import BeautifulSoup, Tag

HEADING = "使用したAIモデル"
IMAGE_STAGE = "画像生成"


def append_model_disclosure(content: str, stages: list[tuple[str, str]]) -> str:
    soup = BeautifulSoup(content, "html.parser")
    for heading in list(soup.find_all("h2", recursive=False)):
        if heading.get_text(strip=True) != HEADING:
            continue
        sibling = heading.next_sibling
        heading.decompose()
        while sibling is not None:
            if isinstance(sibling, Tag) and sibling.name in {"h1", "h2"}:
                break
            following = sibling.next_sibling
            sibling.extract()
            sibling = following
    section = (
        "<h2>"
        + HEADING
        + "</h2><ul>"
        + "".join(f"<li>{escape(stage)}: {escape(value)}</li>" for stage, value in stages)
        + (
            "</ul><p>モデル名は記事に紐づく実行記録に基づく。"
            "AI検証は正確性や権利上の問題がないことを保証するものではない。</p>"
        )
    )
    return str(soup).rstrip() + "\n" + section


def with_image_model(content: str, model: str) -> str:
    """Add the actual generated image model without replacing article text."""
    soup = BeautifulSoup(content, "html.parser")
    heading = next(
        (h for h in soup.find_all("h2", recursive=False) if h.get_text(strip=True) == HEADING), None
    )
    if heading is None:
        # Older drafts can still be decorated, without guessing their writing model.
        return append_model_disclosure(
            content, [("本文作成・編集", "AI執筆モデルの記録なし"), (IMAGE_STAGE, model)]
        )
    listing = heading.find_next_sibling("ul")
    if listing is None:
        raise ValueError("AI model disclosure list is missing")
    for row in list(listing.find_all("li", recursive=False)):
        if row.get_text().startswith(IMAGE_STAGE + ": "):
            row.decompose()
    entry = soup.new_tag("li")
    entry.string = IMAGE_STAGE + ": " + model
    listing.append(entry)
    return str(soup)
