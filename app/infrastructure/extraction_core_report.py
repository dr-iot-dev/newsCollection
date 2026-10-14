"""Small, self-contained report for density clusters and their core articles."""

import json
from pathlib import Path
from typing import Any


def core_report_html(
    summary: dict[str, Any],
    clusters: list[dict[str, Any]],
    articles: list[dict[str, Any]],
    variants: list[dict[str, Any]],
) -> str:
    data = (
        json.dumps(
            {
                "summary": summary,
                "clusters": [
                    {k: v for k, v in c.items() if k != "centroid_value"} for c in clusters
                ],
                "articles": articles,
                "variants": [{k: v for k, v in r.items() if k != "labels"} for r in variants],
            },
            ensure_ascii=False,
            allow_nan=False,
        )
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
    template = Path(__file__).with_name("templates") / "extraction-cores.html"
    return template.read_text(encoding="utf-8").replace("__CORE_DATA__", data)
