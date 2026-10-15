"""Copy immutable source articles into a separate database with the AI-selection schema."""

import argparse
import json
import sqlite3
from pathlib import Path
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.engine import make_url

from app.db import open_session
from app.models import Article, Run


def readonly_uri(source: Path) -> str:
    name = source.as_posix()
    # Four slashes preserve a Windows UNC path without a non-local URI authority.
    return "file:" + ("//" if name.startswith("//") else "") + quote(name, safe="/:") + "?mode=ro"


def migrate(source: Path, database: str) -> int:
    source = source.resolve(strict=True)
    target = make_url(database)
    if target.get_backend_name() == "sqlite" and target.database:
        if Path(target.database).resolve() == source:
            raise ValueError("MIGRATION_REQUIRES_SEPARATE_DATABASE")
    columns = [c.name for c in Article.__table__.columns]
    # All identifiers come from the fixed ORM schema, never from user input.
    query = "SELECT " + ", ".join('"' + c + '"' for c in columns) + " FROM articles"  # noqa: S608
    with sqlite3.connect(readonly_uri(source), uri=True) as original:
        original.row_factory = sqlite3.Row
        with open_session(database) as session:
            occupied = session.scalar(select(Article.id).limit(1)) or session.scalar(
                select(Run.id).limit(1)
            )
            if occupied:
                raise ValueError("MIGRATION_TARGET_NOT_EMPTY")
            count = 0
            for row in original.execute(query):
                data = dict(row)
                if isinstance(data["domains"], str):
                    data["domains"] = json.loads(data["domains"])
                session.add(Article(**data))
                count += 1
            session.commit()
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--database", required=True)
    args = parser.parse_args()
    print(json.dumps({"copied_articles": migrate(args.source, args.database)}))


if __name__ == "__main__":
    main()
