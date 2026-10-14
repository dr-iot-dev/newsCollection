"""Read the publisher's release kind from public metadata, never infer it from prose."""

import re

from bs4 import BeautifulSoup

TYPE_URL = re.compile(r"^/main/html/searchrlp/release_type_id/(\d+)/?$")


def public_release_type(html: str) -> tuple[str, str] | None:
    page = BeautifulSoup(html, "html.parser")
    found: set[tuple[str, str]] = set()
    for anchor in page.select("a[href*='/main/html/searchrlp/release_type_id/']"):
        if anchor.find_parent(id="press-release-body") is not None:
            continue
        match = TYPE_URL.fullmatch(str(anchor.get("href", "")))
        if match and (name := anchor.get_text(" ", strip=True)):
            found.add((match.group(1).zfill(2), name))
    return next(iter(found)) if len(found) == 1 else None
