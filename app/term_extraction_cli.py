"""Import a domain corpus, then count Discovery candidate words with SQL."""

import csv
import json
import sqlite3
from pathlib import Path
from typing import Annotated, Any

import typer

from app.contracts.discovery_search_vocabulary_v2 import (
    DiscoveryArticle,
    DiscoverySearchVocabularyV2,
)
from app.core.term_extraction import (
    DOMAIN_FILTER_POLICY,
    DOMAIN_LEAD_CHARS,
    TITLE_FILTER_POLICY,
    article_domain_terms,
    title_exclusion_terms,
)
from app.infrastructure.term_corpus import TermCorpusStore

extraction_app = typer.Typer(no_args_is_help=True, pretty_exceptions_show_locals=False)


def failure(exc: Exception) -> None:
    typer.echo("extraction failed: " + type(exc).__name__, err=True)
    raise typer.Exit(1) from None


def markdown_table(rows: list[dict[str, Any]]) -> str:
    def escape(value: str) -> str:
        return value.replace("|", "\\|").replace("\n", " ").replace("\r", " ")

    lines = [
        "| 記事 | 分野 | 一致候補数 | 一致語数 | 含んでいる語 |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    for row in rows:
        article = escape(row["title"])
        if row["url"]:
            article = (
                "[" + article.replace("[", "\\[").replace("]", "\\]") + "](" + row["url"] + ")"
            )
        lines.append(
            "| "
            + " | ".join(
                (
                    article,
                    "、".join(row.get("domains", ())),
                    str(row["concept_count"]),
                    str(row["matched_term_count"]),
                    escape("、".join(row["matched_terms"])) or "—",
                )
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


@extraction_app.command("import")
def import_articles(
    database: Annotated[Path, typer.Option("--database")],
    corpus: Annotated[str, typer.Option("--corpus")],
    articles_file: Annotated[Path, typer.Option("--articles")],
    domain_label: Annotated[str, typer.Option("--domain-label")] = "",
) -> None:
    """Save extracted title/body articles to the database before searching."""
    try:
        payload = json.loads(articles_file.read_text(encoding="utf-8-sig"))
        if not isinstance(payload, list):
            raise ValueError("articles must be a JSON array")
        articles = []
        exclusions = []
        domain_exclusions = []
        for value in payload:
            title = value["title"]
            if not isinstance(title, str):
                raise ValueError("title must be a string")
            terms = title_exclusion_terms(title)
            if terms:
                article_id = value.get("article_id") or value.get("url") or value.get("item_id")
                if not isinstance(article_id, str) or not article_id.strip():
                    raise ValueError("article_id must be a nonblank string")
                exclusions.append((article_id, title, value.get("url", "")))
                continue
            body = value.get("body", "")
            if not isinstance(body, str):
                raise ValueError("body must be a string")
            if not article_domain_terms(title, body):
                article_id = value.get("article_id") or value.get("url") or value.get("item_id")
                if not isinstance(article_id, str) or not article_id.strip():
                    raise ValueError("article_id must be a nonblank string")
                domain_exclusions.append(
                    (article_id, title, body[:DOMAIN_LEAD_CHARS], value.get("url", ""))
                )
                continue
            articles.append(
                (
                    DiscoveryArticle.model_validate(
                        {
                            "article_id": value.get("article_id")
                            or value.get("url")
                            or value.get("item_id"),
                            "title": value["title"],
                            "body": value["body"],
                        }
                    ),
                    value.get("url", ""),
                )
            )
        ids = (
            [article.article_id for article, _ in articles]
            + [entry[0] for entry in exclusions]
            + [entry[0] for entry in domain_exclusions]
        )
        if len(ids) != len(set(ids)):
            raise ValueError("article_id must be unique within import")
        with TermCorpusStore(database) as store:
            store.create_corpus(corpus, domain_label or corpus)
            for article_id, title, url in exclusions:
                store.record_title_exclusion(corpus, article_id, title, url)
            for article_id, title, body, url in domain_exclusions:
                store.record_domain_screening(corpus, article_id, title, body, url)
            for article, url in articles:
                store.import_article(corpus, article, url)
            typer.echo(
                json.dumps(
                    {
                        "database": str(database),
                        "corpus": corpus,
                        "stored_articles": store.stored_article_count(corpus),
                        "eligible_articles": store.article_count(corpus),
                        "excluded_input_articles": len(exclusions) + len(domain_exclusions),
                        "title_excluded_input_articles": len(exclusions),
                        "domain_excluded_input_articles": len(domain_exclusions),
                        "title_filter_policy": TITLE_FILTER_POLICY,
                        "domain_filter_policy": DOMAIN_FILTER_POLICY,
                        "allowed_domains": ["AI", "IoT"],
                    },
                    ensure_ascii=False,
                )
            )
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
        failure(exc)


@extraction_app.command("count")
def count(
    database: Annotated[Path, typer.Option("--database")],
    corpus: Annotated[str, typer.Option("--corpus")],
    vocabulary_file: Annotated[Path, typer.Option("--vocabulary")],
    output: Annotated[Path | None, typer.Option("--output")] = None,
    minimum_articles: Annotated[int, typer.Option("--minimum-articles", min=1)] = 200,
) -> None:
    """Register vocabulary and count every stored article in SQL, including zero hits."""
    try:
        if not database.is_file():
            raise ValueError("import articles into the database first")
        vocabulary = DiscoverySearchVocabularyV2.model_validate_json(
            vocabulary_file.read_text(encoding="utf-8-sig")
        )
        with TermCorpusStore(database) as store:
            eligible_count = store.article_count(corpus)
            if eligible_count < minimum_articles:
                typer.echo(
                    f"extraction failed: eligible articles {eligible_count} "
                    f"< minimum {minimum_articles}",
                    err=True,
                )
                raise typer.Exit(1)
            vocabulary_hash = store.save_vocabulary(vocabulary)
            rows = store.count_candidates(corpus, vocabulary_hash)
            excluded = store.excluded_articles(corpus)
            stored_count = store.stored_article_count(corpus)
            domain_screenings = store.domain_screenings(corpus)
        table = markdown_table(rows)
        if output:
            output.mkdir(parents=True, exist_ok=True)
            (output / "counts.json").write_text(
                json.dumps(
                    {
                        "database": str(database),
                        "corpus": corpus,
                        "vocabulary_hash": vocabulary_hash,
                        "vocabulary_spec": vocabulary.spec_version,
                        "candidate_count": len(vocabulary.concepts),
                        "search_scope": "stored_title_and_body",
                        "execution": "database_sql",
                        "count_policy": (
                            "distinct_concept_ids; aliases_count_once; include_zero_hits"
                        ),
                        "article_count": len(rows),
                        "stored_article_count": stored_count,
                        "excluded_article_count": len(excluded),
                        "title_filter_policy": TITLE_FILTER_POLICY,
                        "domain_filter_policy": DOMAIN_FILTER_POLICY,
                        "allowed_domains": ["AI", "IoT"],
                        "articles": rows,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            (output / "counts.md").write_text(table, encoding="utf-8")
            (output / "excluded-articles.json").write_text(
                json.dumps(excluded, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            (output / "domain-screenings.json").write_text(
                json.dumps(domain_screenings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            with (output / "excluded-articles.csv").open(
                "w", encoding="utf-8-sig", newline=""
            ) as stream:
                writer = csv.writer(stream)
                writer.writerow(
                    (
                        "article_id",
                        "title",
                        "url",
                        "matched_exclusion_terms",
                        "exclusion_reason",
                        "policy",
                    )
                )
                for row in excluded:
                    writer.writerow(
                        (
                            row["article_id"],
                            row["title"],
                            row["url"],
                            "、".join(row["matched_exclusion_terms"]),
                            row["exclusion_reason"],
                            row["policy"],
                        )
                    )
            with (output / "counts.csv").open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(
                    (
                        "article_id",
                        "title",
                        "url",
                        "domains",
                        "candidate_count",
                        "matched_term_count",
                        "matched_terms",
                        "matched_candidates",
                    )
                )
                for row in rows:
                    writer.writerow(
                        (
                            row["article_id"],
                            row["title"],
                            row["url"],
                            "、".join(row["domains"]),
                            row["concept_count"],
                            row["matched_term_count"],
                            "、".join(row["matched_terms"]),
                            "、".join(match["label"] for match in row["matches"]),
                        )
                    )
        typer.echo(table)
    except (OSError, ValueError, sqlite3.Error) as exc:
        failure(exc)


@extraction_app.command("distances")
def distances(
    database: Annotated[Path, typer.Option("--database")],
    corpus: Annotated[str, typer.Option("--corpus")],
    counts_file: Annotated[Path, typer.Option("--counts")],
    output: Annotated[Path, typer.Option("--output")],
    model: Annotated[str, typer.Option("--model")] = "text-embedding-3-small",
    prepare_only: Annotated[bool, typer.Option("--prepare-only")] = False,
) -> None:
    """E -> F (candidate count > 4), per-article vectors, and all cosine-distance pairs."""
    from app.core.config import get_settings
    from app.infrastructure.extraction_embeddings import OpenAIEmbeddingBatchProvider
    from app.orchestration.extraction_distances import (
        calculate_distances,
        prepare_distance_analysis,
    )

    try:
        run = prepare_distance_analysis(database, corpus, counts_file, output, model)
        if prepare_only:
            typer.echo(
                json.dumps({k: v for k, v in run.items() if k != "articles"}, ensure_ascii=False)
            )
            return
        settings = get_settings()
        if settings.ai_api_key is None:
            raise ValueError("embedding API key not configured")
        result = calculate_distances(
            run,
            output,
            OpenAIEmbeddingBatchProvider(settings.ai_api_key.get_secret_value(), model),
            progress=lambda value: typer.echo(json.dumps(value)),
        )
        typer.echo(json.dumps(result, ensure_ascii=False))
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
        failure(exc)


@extraction_app.command("cores")
def cores(
    vectors_file: Annotated[Path, typer.Option("--vectors")],
    output: Annotated[Path, typer.Option("--output")],
    n_components: Annotated[int, typer.Option("--n-components", min=2)] = 15,
    n_neighbors: Annotated[int, typer.Option("--n-neighbors", min=2)] = 15,
    min_cluster_size: Annotated[int, typer.Option("--min-cluster-size", min=2)] = 5,
    min_samples: Annotated[int, typer.Option("--min-samples", min=1)] = 5,
    core_top_n: Annotated[int, typer.Option("--core-top-n", min=1)] = 3,
    core_min_probability: Annotated[
        float, typer.Option("--core-min-probability", min=0, max=1)
    ] = 0.9,
    random_state: Annotated[int, typer.Option("--random-state")] = 42,
    sensitivity: Annotated[bool, typer.Option("--sensitivity/--no-sensitivity")] = True,
    latest_per_organization: Annotated[bool, typer.Option("--latest-per-organization")] = False,
    audit_database: Annotated[Path | None, typer.Option("--audit-database")] = None,
) -> None:
    """Extract UMAP/HDBSCAN density cores locally from previously saved vectors."""
    from app.orchestration.extraction_cores import CoreParameters, extract_density_cores

    try:
        if latest_per_organization:
            from app.orchestration.extraction_organizations import select_latest_organizations

            if audit_database is None:
                raise ValueError("--latest-per-organization requires --audit-database")
            vectors_file = select_latest_organizations(
                vectors_file, audit_database, output / "selection"
            )
        result = extract_density_cores(
            vectors_file,
            output,
            CoreParameters(
                n_components=n_components,
                n_neighbors=n_neighbors,
                min_cluster_size=min_cluster_size,
                min_samples=min_samples,
                core_top_n=core_top_n,
                core_min_probability=core_min_probability,
                random_state=random_state,
            ),
            sensitivity=sensitivity,
            progress=lambda value: typer.echo(json.dumps(value)),
        )
        typer.echo(json.dumps(result, ensure_ascii=False))
    except ImportError:
        typer.echo("extraction failed: install news-weave[clustering] first", err=True)
        raise typer.Exit(1) from None
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
        failure(exc)


@extraction_app.command("embeddings")
def embeddings(
    database: Annotated[Path, typer.Option("--database")],
    corpus: Annotated[str, typer.Option("--corpus")],
    counts_file: Annotated[Path, typer.Option("--counts")],
    output: Annotated[Path, typer.Option("--output")],
    reuse_database: Annotated[Path | None, typer.Option("--reuse-database")] = None,
    minimum_articles: Annotated[int, typer.Option("--minimum-articles", min=1)] = 1000,
    prepare_only: Annotated[bool, typer.Option("--prepare-only")] = False,
) -> None:
    """Embed count > 4 articles, reusing old vectors and reporting actual-token costs."""
    from app.core.config import get_settings
    from app.core.editorial import EditorialError
    from app.infrastructure.extraction_embeddings import OpenAIEmbeddingBatchProvider
    from app.orchestration.extraction_distances import prepare_distance_analysis
    from app.orchestration.extraction_embedding_values import embed_article_values

    try:
        run = prepare_distance_analysis(database, corpus, counts_file, output)
        if run["F_count"] < minimum_articles:
            raise ValueError("not enough count > 4 articles for embedding")
        if prepare_only:
            typer.echo(
                json.dumps({k: v for k, v in run.items() if k != "articles"}, ensure_ascii=False)
            )
            return
        settings = get_settings()
        if settings.ai_api_key is None:
            raise ValueError("embedding API key not configured")
        result = embed_article_values(
            run,
            output,
            OpenAIEmbeddingBatchProvider(settings.ai_api_key.get_secret_value(), run["model"]),
            reuse_database,
            progress=lambda value: typer.echo(json.dumps(value)),
        )
        typer.echo(json.dumps(result, ensure_ascii=False))
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error, EditorialError) as exc:
        failure(exc)
