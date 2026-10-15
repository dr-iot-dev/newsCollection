"""One-time article import; no legacy filtering, embeddings or evaluations are migrated."""

import argparse
import json
import sqlite3
from pathlib import Path
from urllib.parse import quote

from sqlalchemy.orm import Session

from app.acquisition import exclusions_from, parse_article, save_article
from app.db import open_session


def readonly(path: Path):
    name = path.resolve().as_posix()
    return sqlite3.connect(
        "file:" + ("//" if name.startswith("//") else "") + quote(name, safe="/:") + "?mode=ro",
        uri=True,
    )


def import_legacy_sources(
    session: Session, corpus: Path, snapshots: Path, exclusions: list[str]
) -> dict:
    accepted, excluded, missing = 0, 0, 0
    with readonly(corpus) as old, readonly(snapshots) as audit:
        old.row_factory = sqlite3.Row
        for row in old.execute("SELECT DISTINCT article_id,url FROM term_articles"):
            url = row["url"] or row["article_id"]
            snapshot = audit.execute(
                "SELECT body_text FROM raw_snapshots WHERE final_url=? "
                "ORDER BY fetched_at DESC LIMIT 1",
                (url,),
            ).fetchone()
            if snapshot is None:
                missing += 1
                continue
            data = parse_article(url, snapshot[0], exclusions)
            if data is None:
                excluded += 1
                continue
            save_article(session, data)
            session.commit()
            accepted += 1
    return {"accepted": accepted, "excluded": excluded, "missing_snapshot": missing}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="One-time migration of saved source HTML")
    parser.add_argument("--database", required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--snapshots", type=Path, required=True)
    parser.add_argument(
        "--exclude-titles",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "app/title-exclusions.txt",
    )
    args = parser.parse_args()
    with open_session(args.database) as session:
        print(
            json.dumps(
                import_legacy_sources(
                    session,
                    args.corpus,
                    args.snapshots,
                    exclusions_from(args.exclude_titles),
                ),
                ensure_ascii=False,
            )
        )
