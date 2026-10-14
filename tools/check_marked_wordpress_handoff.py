# ruff: noqa: E402
"""Import prepared handoff files with the real WPuploader, without CMS access."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / "WPuploader"))
sys.path.insert(0, str(ROOT))
from wpuploader.content import validate_draft
from wpuploader.protocol import read_bundle
from wpuploader.service import Uploader
from wpuploader.settings import Settings
from wpuploader.store import Store

from nw_generation.protocol import atomic_write, canonical

OUT = ROOT / ".local/comparison-A-wordpress-20261014-v7"


class NoNetwork:
    def __getattr__(self, name):
        raise AssertionError("Remote CMS access is forbidden in this check: " + name)


def main():
    settings = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8-sig").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            if key in {
                "WORDPRESS_BASE_URL",
                "WORDPRESS_CATEGORY_MAP",
                "WORDPRESS_POST_TYPE",
                "WORDPRESS_REST_BASE",
            }:
                settings[key] = value.strip().strip('"').strip("'")
    handoff = json.loads((OUT / "handoff.json").read_text(encoding="utf-8"))
    if not handoff["drafts"]:
        raise RuntimeError("NO_ELIGIBLE_DRAFTS")
    result = []
    with tempfile.TemporaryDirectory(prefix="newsweave-A-handoff-") as local:
        store = Store(Path(local), initialize=True)
        try:
            config = Settings(
                state_dir=Path(local),
                enabled=False,
                base_url=settings.get("WORDPRESS_BASE_URL", "https://example.test"),
                category_map=json.loads(settings.get("WORDPRESS_CATEGORY_MAP", "{}")),
                post_type=settings.get("WORDPRESS_POST_TYPE", "news_weave"),
                rest_base=settings.get("WORDPRESS_REST_BASE", "news-weave"),
            )
            uploader = Uploader(store, config, port=NoNetwork())
            for draft in handoff["drafts"]:
                path = Path(draft["path"])
                meta, files = read_bundle(path, draft=True)
                validate_draft(meta, files)
                assert meta["eligibility"]["policy_version"] == "marked-comparison-A-wordpress-v7"
                package = uploader.import_file(path)
                assert uploader.import_file(path) == package
                result.append(
                    {
                        "id": draft["id"],
                        "package_id": package,
                        "title": meta["title"],
                        "category_keys": meta["category_keys"],
                        "hash_checks": "pass",
                    }
                )
            uploader.prepare()
            rows = [
                dict(r)
                for r in store.db.execute("SELECT package_id,payload,state,error FROM deliveries")
            ]
            assert len(rows) == len(result)
            for row in rows:
                payload = json.loads(row["payload"])
                assert row["state"] == "prepared" and row["error"] is None
                assert payload["status"] == "draft"
            atomic_write(
                OUT / "uploader-dry-run.json",
                canonical(
                    {
                        "passed": True,
                        "uploader_implementation": "existing sibling WPuploader",
                        "files": result,
                        "deliveries": rows,
                        "remote_requests": 0,
                        "duplicate_import_created_extra_rows": False,
                        "state": "isolated temporary local SQLite",
                    }
                ),
            )
        finally:
            store.close()
    print(
        json.dumps(
            {"passed": True, "drafts": len(result), "remote_requests": 0}, ensure_ascii=False
        )
    )


if __name__ == "__main__":
    main()
