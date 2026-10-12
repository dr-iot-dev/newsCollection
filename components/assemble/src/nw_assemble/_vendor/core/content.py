"""Pure normalization shared through the core, with no networking."""

import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFC", value.replace("\x00", "\ufffd"))
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[^\S\n]+", " ", line).strip() for line in value.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def normalize_url(value: str) -> str:
    parsed = urlsplit(value)
    host = (parsed.hostname or "").lower().encode("idna").decode()
    port = parsed.port
    authority = host if port in (None, 443) else f"{host}:{port}"
    query = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in {"gclid", "fbclid"}
    ]
    return urlunsplit((parsed.scheme.lower(), authority, parsed.path or "/", urlencode(query), ""))
