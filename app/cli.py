"""The only public entry point for the seven-stage system."""

import argparse
import json
from pathlib import Path

from sqlalchemy import select

from app.acquisition import Collector, exclusions_from, parse_article, save_article
from app.db import open_session, schema_sql
from app.model_client import OpenAI
from app.models import Run
from app.pipeline import Pipeline
from app.settings import Settings, database_url


def parser():
    root = argparse.ArgumentParser(description="News Weave seven-stage comparison pipeline")
    root.add_argument("--database", default=database_url())
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("init")
    ddl = commands.add_parser("schema")
    ddl.add_argument("--output", type=Path, required=True)
    ddl.add_argument("--dialect", choices=["sqlite", "postgresql"], default="postgresql")
    collect = commands.add_parser("collect")
    collect.add_argument("--urls", type=Path, help="one public release URL per line")
    collect.add_argument("--search-pages", type=int, default=1)
    collect.add_argument(
        "--exclude-titles", type=Path, default=Path(__file__).with_name("title-exclusions.txt")
    )
    ingest = commands.add_parser("import-html")
    ingest.add_argument("--input", type=Path, required=True, help="JSON list of {url, html}")
    ingest.add_argument(
        "--exclude-titles", type=Path, default=Path(__file__).with_name("title-exclusions.txt")
    )
    run = commands.add_parser("run")
    run.add_argument("--embedding-model", default=Settings.embedding_model)
    run.add_argument("--selection-model", default=Settings.selection_model)
    run.add_argument("--selection-candidate-limit", type=int, default=30)
    run.add_argument("--generation-model", default=Settings.generation_model)
    run.add_argument("--verification-model", default=Settings.verification_model)
    run.add_argument("--n-components", type=int, default=15)
    run.add_argument("--n-neighbors", type=int, default=15)
    run.add_argument("--min-cluster-size", type=int, default=5)
    run.add_argument("--min-samples", type=int, default=5)
    commands.add_parser("list")
    resume = commands.add_parser("resume")
    resume.add_argument("run_id")
    export = commands.add_parser("export")
    export.add_argument("run_id")
    export.add_argument("--output", type=Path, required=True)
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    if args.command == "schema":
        schema_sql(args.output, args.dialect)
        return 0
    provider = None
    collector = None
    try:
        with open_session(args.database) as session:
            if args.command == "init":
                result = {"initialized": True, "tables": 6}
            elif args.command == "collect":
                if args.search_pages < 1:
                    raise ValueError("search-pages must be positive")
                collector = Collector(exclusions_from(args.exclude_titles))
                urls = (
                    args.urls.read_text(encoding="utf-8-sig").splitlines()
                    if args.urls
                    else (collector.search(args.search_pages))
                )
                result = collector.collect(session, [u.strip() for u in urls if u.strip()])
            elif args.command == "import-html":
                accepted = 0
                for item in json.loads(args.input.read_text(encoding="utf-8-sig")):
                    data = parse_article(
                        item["url"], item["html"], exclusions_from(args.exclude_titles)
                    )
                    if data:
                        save_article(session, data)
                        session.commit()
                        accepted += 1
                result = {"accepted": accepted}
            elif args.command == "list":
                result = [
                    {"id": r.id, "step": r.step, "error": r.error}
                    for r in session.scalars(select(Run).order_by(Run.created_at))
                ]
            elif args.command == "export":
                result = Pipeline(session, None).export(args.run_id, args.output)
            else:
                provider = OpenAI()
                pipeline = Pipeline(session, provider)
                if args.command == "run":
                    settings = Settings(
                        **{field: getattr(args, field) for field in Settings.__dataclass_fields__}
                    )
                    run = pipeline.start(settings)
                    print(json.dumps({"run_id": run.id, "step": run.step}), flush=True)
                else:
                    run = session.get(Run, args.run_id)
                    if run is None:
                        raise ValueError("RUN_NOT_FOUND")
                run = pipeline.process(run.id)
                result = {"run_id": run.id, "step": run.step, "error": run.error}
            print(json.dumps(result, ensure_ascii=False))
    except (ValueError, OSError, KeyError) as exc:
        # Never print raw transport exceptions or provider response payloads.
        print(json.dumps({"error": type(exc).__name__}))
        return 1
    finally:
        if provider:
            provider.close()
        if collector:
            collector.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
