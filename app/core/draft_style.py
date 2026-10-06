"""Shared reader-facing editorial style constraints."""

from unicodedata import normalize


def title_has_comparison_suffix(title: str) -> bool:
    return normalize("NFKC", title).rstrip(" \t\n。.?!").endswith("を比較")
