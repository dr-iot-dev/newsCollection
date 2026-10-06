"""Version 1 identity of an unordered set of source article URLs."""

import hashlib
import json
from collections.abc import Iterable

from app.core.content import normalize_url


def source_set_hash(urls: Iterable[str]) -> str:
    normalized = sorted({normalize_url(url) for url in urls})
    return "sha256:" + hashlib.sha256(
        json.dumps(normalized, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
