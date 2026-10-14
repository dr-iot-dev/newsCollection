"""A self-contained, compact, searchable table of all article pairs."""

import json
from pathlib import Path
from typing import Any


def distance_report_html(
    summary: dict[str, Any], articles: list[dict[str, Any]], pairs: list[dict[str, Any]]
) -> str:
    payload = (
        json.dumps(
            {
                "summary": summary,
                "articles": [{k: v for k, v in a.items() if k != "value"} for a in articles],
                "pairs": [[p["left_id"], p["right_id"], p["distance"]] for p in pairs],
            },
            ensure_ascii=False,
        )
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
    return TEMPLATE.replace("__DATA__", payload)


TEMPLATE = (Path(__file__).parent / "templates/extraction-distances.html").read_text(
    encoding="utf-8"
)
