"""Move existing WordPress history to a renamed route; defaults to a dry run."""

import argparse
import json

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.infrastructure.wordpress import wordpress_target
from app.orchestration.wordpress_routes import migrate_wordpress_history


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    old = wordpress_target(settings.wordpress_base_url, "nc_news", "nc-news")
    new = wordpress_target(settings.wordpress_base_url, "news_weave", "news-weave")
    if args.rollback:
        old, new = new, old
    engine = create_engine(str(settings.database_url))
    with Session(engine) as session, session.begin():
        result = migrate_wordpress_history(session, old, new, apply=args.apply)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
