# ruff: noqa: RUF001
"""Regression tests for the seven requested stages and the minimal schema."""

import json
import sqlite3

import httpx
import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.acquisition import Collector, parse_article, save_article
from app.cli import main
from app.clustering import cluster, select_three
from app.db import engine_for, initialize, schema_sql
from app.model_client import GENERATION_SCHEMA, SELECTION_SCHEMA, VERIFICATION_SCHEMA, OpenAI
from app.models import Article, Comparison, Draft, RunArticle, Verification
from app.pipeline import Pipeline
from app.settings import Settings


def release(company=1, release_id=1, title="IoT 新製品", kind="01", body="IoT 機能の説明"):
    url = f"https://prtimes.jp/main/html/rd/p/{release_id:09d}.{company:09d}.html"
    metadata = {
        "@type": "NewsArticle",
        "headline": title,
        "datePublished": f"2026-10-{release_id:02d} 09:00:00",
        "dateModified": "2099-01-01",
        "author": {"@type": "Organization", "name": "同じ社名"},
    }
    html = (
        '<script type="application/ld+json">'
        + json.dumps(metadata, ensure_ascii=False)
        + "</script>"
        f'<h1>{title}</h1><div id="press-release-body">{body}</div>'
        f'<a href="/main/html/searchrlp/company_id/{company}">企業</a>'
        f'<dl><dt>種類</dt><dd><a href="/main/html/searchrlp/release_type_id/{kind}/">'
        + ("商品サービス" if kind == "01" else "経営情報")
        + "</a></dd></dl>"
    )
    return url, html


@pytest.fixture
def session(tmp_path):
    engine = engine_for("sqlite:///" + (tmp_path / "pipeline.sqlite").as_posix())
    initialize(engine)
    with Session(engine, expire_on_commit=False) as db:
        yield db
    engine.dispose()


def add(session, company=1, release_id=1, **kwargs):
    article = save_article(session, parse_article(*release(company, release_id, **kwargs), []))
    session.commit()
    return article


class Provider:
    def __init__(self, status="eligible", score=98):
        self.calls = []
        self.status, self.score = status, score
        self.prompts = []

    def embed(self, model, texts):
        self.calls.append(("embed", model, list(texts)))
        return [[1.0, 0.2] for _ in texts]

    def complete(self, model, prompt, data, schema):
        self.calls.append((schema, model, data))
        self.prompts.append((schema, prompt))
        if schema == SELECTION_SCHEMA:
            return {
                "selection_status": "ONE_SET",
                "primary_article_ids": [x["article_id"] for x in data["candidates"][:3]],
                "reserve_article_ids": [],
                "reason": "3つの共通軸と2つの有意差を本文から確認。",
            }
        if schema == GENERATION_SCHEMA:
            return generation("# 比較記事\n\n3件の原資料に基づく比較である。")
        return {"status": self.status, "score": self.score, "reason": "個別の原資料に基づく評価"}


def generation(text):
    rejected = isinstance(text, str) and text.lstrip().startswith("# 比較不適")
    return {
        "status": "INAPPROPRIATE" if rejected else "APPROPRIATE",
        "reason": text if rejected else "G1〜G6の本文根拠を確認した。",
        "article_markdown": "" if rejected else text,
    }


def labels(values, settings):
    return [0] * len(values)


def test_acquisition_requires_product_domain_and_title_conditions():
    assert parse_article(*release(body="IoT"), [])  # One domain term is sufficient.
    assert parse_article(*release(kind="02"), []) is None
    assert parse_article(*release(title="一般製品", body="概要のみ"), []) is None
    assert parse_article(*release(title="IoT 展示の案内"), ["展示"]) is None
    assert parse_article(*release(title="一般製品", body="rapidapi と会社概要 AI"), []) is None


def test_latest_before_embedding_and_distinct_company_ids(session):
    old = add(session, 1, 1)
    newest = add(session, 1, 2)
    other = add(session, 2, 1)
    third = add(session, 3, 1)
    provider = Provider()
    pipeline = Pipeline(session, provider, labels)
    run = pipeline.start(Settings())
    ids = {row.article_id for row in session.scalars(select(RunArticle))}
    assert ids == {newest.id, other.id, third.id} and old.id not in ids
    assert not provider.calls
    pipeline.process(run.id)
    assert len([call for call in provider.calls if call[0] == "embed"]) == 3
    assert len(session.scalars(select(Article)).all()) == 4


def test_full_pipeline_individual_verification_exact_inputs_and_export(session, tmp_path):
    for company in range(1, 7):
        add(session, company)
    provider = Provider()
    pipeline = Pipeline(session, provider, lambda v, _: [0, 0, 0, 1, 1, 1])
    run = pipeline.start(Settings())
    assert pipeline.process(run.id).step == "complete"
    calls = [c for c in provider.calls if c[0] == VERIFICATION_SCHEMA]
    assert len(calls) == 2
    for _schema, model, data in calls:
        assert model == Settings.verification_model
        assert set(data) == {"article_markdown", "sources", "generation_instructions"}
        assert data["generation_instructions"] == run.settings["prompts"]["generation"]
        assert len(data["sources"]) == 3
        assert all(
            set(source) == {"title", "url", "published_at", "text"} for source in data["sources"]
        )
    before = len(provider.calls)
    pipeline.process(run.id)
    assert len(provider.calls) == before
    result = pipeline.export(run.id, tmp_path / "export")
    assert len(result["articles"]) == 2
    assert all(r["status"] == "eligible" and r["score"] == 98 for r in result["articles"])


def test_high_score_never_changes_ineligible_status(session):
    for company in range(1, 4):
        add(session, company)
    provider = Provider("ineligible", 99)
    pipeline = Pipeline(session, provider, labels)
    pipeline.process(pipeline.start(Settings()).id)
    results = session.scalars(select(Verification)).all()
    assert len(results) == 2
    assert all((result.status, result.score) == ("ineligible", 99) for result in results)


def test_verification_receives_actual_frozen_generation_instruction(session, tmp_path, monkeypatch):
    from app.settings import prompt_dir

    temporary = tmp_path / "prompts"
    temporary.mkdir()
    for name in ("selection", "generation", "verification"):
        (temporary / (name + ".txt")).write_text(
            (prompt_dir() / (name + ".txt")).read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    monkeypatch.setattr("app.pipeline.prompt_dir", lambda: temporary)
    for company in range(1, 4):
        add(session, company)
    provider = Provider()
    pipeline = Pipeline(session, provider, labels)
    run = pipeline.start(Settings())
    (temporary / "generation.txt").write_text("Changed after the run started", encoding="utf-8")
    pipeline.process(run.id)
    generation_prompt = next(p for schema, p in provider.prompts if schema == GENERATION_SCHEMA)
    verification_prompt = next(p for schema, p in provider.prompts if schema == VERIFICATION_SCHEMA)
    verification_input = next(
        data for schema, _, data in provider.calls if schema == VERIFICATION_SCHEMA
    )
    assert verification_input["generation_instructions"] == generation_prompt
    assert generation_prompt != "Changed after the run started"
    assert "generation_instructions" in verification_prompt
    assert "80点以上" in verification_prompt and "50点以下" in verification_prompt


def test_uncertain_article_mark_cannot_be_saved_as_eligible(session):
    for company in range(1, 4):
        add(session, company)
    provider = Provider()
    original = provider.complete

    def contradictory(model, prompt, data, schema):
        if schema == SELECTION_SCHEMA:
            return original(model, prompt, data, schema)
        if schema == GENERATION_SCHEMA:
            return generation("# 要確認（公開不可）\n\n原資料に重大な疑義がある。")
        return original(model, prompt, data, schema)

    provider.complete = contradictory
    pipeline = Pipeline(session, provider, labels)
    run = pipeline.start(Settings())
    with pytest.raises(ValueError, match="VERDICT_CONTRADICTS_ARTICLE_MARK"):
        pipeline.process(run.id)
    assert run.step == "verify"
    assert not session.scalars(select(Verification)).all()


def test_generation_ineligible_is_final_without_verification_or_repair(session, tmp_path):
    for company in range(1, 4):
        add(session, company)
    provider = Provider()
    original = provider.complete

    def unsuitable(model, prompt, data, schema):
        if schema == SELECTION_SCHEMA:
            return original(model, prompt, data, schema)
        assert schema == GENERATION_SCHEMA
        original(model, prompt, data, schema)
        return generation("\n# 比較不適（公開不可）  \n\n対象が重複している。")

    provider.complete = unsuitable
    pipeline = Pipeline(session, provider, labels)
    run = pipeline.process(pipeline.start(Settings()).id)
    assert run.step == "complete"
    assert [c[0] for c in provider.calls if c[0] not in ("embed", SELECTION_SCHEMA)] == [
        GENERATION_SCHEMA
    ]
    assert len(session.scalars(select(Draft)).all()) == 1
    row = pipeline.export(run.id, tmp_path / "export")["articles"][0]
    assert row["status"] == "ineligible" and row["score"] is None
    assert "評価モデルは未実行" in row["reason"]
    before = len(provider.calls)
    pipeline.process(run.id)
    assert len(provider.calls) == before


def test_generation_rejection_saved_before_next_cluster_generation_fails(session):
    for company in range(1, 7):
        add(session, company)
    provider = Provider()
    original = provider.complete
    generated = 0

    def interrupted(model, prompt, data, schema):
        nonlocal generated
        if schema == SELECTION_SCHEMA:
            return original(model, prompt, data, schema)
        assert schema == GENERATION_SCHEMA
        generated += 1
        if generated == 2:
            raise ValueError("NEXT_CLUSTER_FAILURE")
        original(model, prompt, data, schema)
        return generation("# 比較不適（公開不可）\n\n対象が重複している。")

    provider.complete = interrupted
    pipeline = Pipeline(session, provider, lambda v, _: [0, 0, 0, 1, 1, 1])
    run = pipeline.start(Settings())
    with pytest.raises(ValueError, match="NEXT_CLUSTER_FAILURE"):
        pipeline.process(run.id)
    assert run.step == "generate"
    final = session.scalar(select(Verification))
    assert final.status == "ineligible" and final.score is None


@pytest.mark.parametrize("initial_status", ["ineligible", "needs_confirmation"])
@pytest.mark.parametrize("final_status", ["eligible", "ineligible", "needs_confirmation"])
def test_exactly_one_repair_and_latest_verdict_is_final(
    session, tmp_path, initial_status, final_status
):
    for company in range(1, 4):
        add(session, company)
    provider = Provider(initial_status, 45)
    original = provider.complete
    checks = 0
    feedback = "タイトルが62字あるため60字以内に直すこと。"
    initial_text = "# 初稿\n\n修正前の記事。"
    revised_text = "# 修正版\n\n修正した記事。"

    def responding(model, prompt, data, schema):
        nonlocal checks
        if schema == SELECTION_SCHEMA:
            return original(model, prompt, data, schema)
        original(model, prompt, data, schema)
        if schema == GENERATION_SCHEMA:
            return generation(revised_text if "feedback" in data else initial_text)
        checks += 1
        if checks == 1:
            return {"status": initial_status, "score": 45, "reason": feedback}
        return {"status": final_status, "score": 91, "reason": "修正版の最終判定"}

    provider.complete = responding
    pipeline = Pipeline(session, provider, labels)
    run = pipeline.process(pipeline.start(Settings()).id)
    calls = [c for c in provider.calls if c[0] not in ("embed", SELECTION_SCHEMA)]
    assert [c[0] for c in calls] == [
        GENERATION_SCHEMA,
        VERIFICATION_SCHEMA,
        GENERATION_SCHEMA,
        VERIFICATION_SCHEMA,
    ]
    assert calls[0][1] == calls[2][1] == Settings.generation_model
    assert calls[1][1] == calls[3][1] == Settings.verification_model
    assert calls[2][2] == {
        "sources": calls[0][2]["sources"],
        "article_markdown": initial_text,
        "feedback": feedback,
    }
    assert calls[1][2]["article_markdown"] == initial_text
    assert calls[3][2]["article_markdown"] == revised_text
    assert calls[1][2]["sources"] == calls[3][2]["sources"] == calls[0][2]["sources"]
    assert calls[1][2]["generation_instructions"] == calls[3][2]["generation_instructions"]
    assert all(
        prompt == run.settings["prompts"]["generation"]
        for schema, prompt in provider.prompts
        if schema == GENERATION_SCHEMA
    )
    drafts = session.scalars(select(Draft).order_by(Draft.revision)).all()
    assert [(d.revision, d.markdown) for d in drafts] == [(0, initial_text), (1, revised_text)]
    assert session.get(Verification, drafts[0].id).reason == feedback
    assert session.get(Verification, drafts[1].id).status == final_status
    output = tmp_path / "export"
    row = pipeline.export(run.id, output)["articles"][0]
    assert (row["revision"], row["status"], row["score"]) == (1, final_status, 91)
    assert (output / row["article"]).read_text(encoding="utf-8") == revised_text
    before = len(provider.calls)
    # Even resuming inside the verification stage must not restart the repair.
    run.step = "verify"
    session.commit()
    assert pipeline.process(run.id).step == "complete"
    assert len(provider.calls) == before


def test_repair_may_conclude_comparison_is_ineligible_without_second_verification(session):
    for company in range(1, 4):
        add(session, company)
    provider = Provider("ineligible", 25)
    original = provider.complete

    def responding(model, prompt, data, schema):
        if schema == SELECTION_SCHEMA:
            return original(model, prompt, data, schema)
        result = original(model, prompt, data, schema)
        if schema == GENERATION_SCHEMA and "feedback" in data:
            return generation("# 比較不適（公開不可）\n\n対象が重複している。")
        return result

    provider.complete = responding
    pipeline = Pipeline(session, provider, labels)
    run = pipeline.process(pipeline.start(Settings()).id)
    revised = session.scalar(select(Draft).where(Draft.revision == 1))
    final = session.get(Verification, revised.id)
    assert run.step == "complete" and final.status == "ineligible" and final.score is None
    assert [c[0] for c in provider.calls if c[0] not in ("embed", SELECTION_SCHEMA)] == [
        GENERATION_SCHEMA,
        VERIFICATION_SCHEMA,
        GENERATION_SCHEMA,
    ]


def test_resume_after_repaired_text_saved_only_retries_verification(session, tmp_path):
    for company in range(1, 4):
        add(session, company)
    provider = Provider("ineligible", 35)
    original = provider.complete
    checks = 0

    def interrupted(model, prompt, data, schema):
        nonlocal checks
        if schema == SELECTION_SCHEMA:
            return original(model, prompt, data, schema)
        if schema == VERIFICATION_SCHEMA:
            checks += 1
            if checks == 2:
                raise ValueError("SIMULATED_VERIFICATION_FAILURE")
        return original(model, prompt, data, schema)

    provider.complete = interrupted
    pipeline = Pipeline(session, provider, labels)
    run = pipeline.start(Settings())
    with pytest.raises(ValueError, match="SIMULATED_VERIFICATION_FAILURE"):
        pipeline.process(run.id)
    assert len(session.scalars(select(Draft)).all()) == 2
    assert len(session.scalars(select(Verification)).all()) == 1
    row = pipeline.export(run.id, tmp_path / "export")["articles"][0]
    assert row["revision"] == 1 and row["status"] is None and row["score"] is None
    provider.status, provider.score = "eligible", 92
    provider.complete = original
    pipeline.process(run.id)
    assert len([c for c in provider.calls if c[0] == GENERATION_SCHEMA]) == 2
    assert len([c for c in provider.calls if c[0] == VERIFICATION_SCHEMA]) == 2
    final = pipeline.export(run.id, tmp_path / "export")["articles"][0]
    assert (final["status"], final["score"]) == ("eligible", 92)


@pytest.mark.parametrize("failure", ["transport", "empty", "invalid"])
def test_failed_repair_never_sends_another_repair_on_resume(session, tmp_path, failure):
    for company in range(1, 4):
        add(session, company)
    provider = Provider("needs_confirmation", 55)
    original = provider.complete

    def interrupted(model, prompt, data, schema):
        if schema == SELECTION_SCHEMA:
            return original(model, prompt, data, schema)
        result = original(model, prompt, data, schema)
        if schema == GENERATION_SCHEMA and "feedback" in data:
            if failure == "transport":
                raise ValueError("SIMULATED_REPAIR_FAILURE")
            return generation("" if failure == "empty" else 123)
        return result

    provider.complete = interrupted
    pipeline = Pipeline(session, provider, labels)
    run = pipeline.start(Settings())
    with pytest.raises(ValueError):
        pipeline.process(run.id)
    revised = session.scalar(select(Draft).where(Draft.revision == 1))
    assert revised.markdown is None and run.step == "verify"
    row = pipeline.export(run.id, tmp_path / "export")["articles"][0]
    assert row["article"] is None and row["status"] is None and row["score"] is None
    before = len(provider.calls)
    # Reopen the database, rather than relying on process-local counters.
    with Session(session.bind, expire_on_commit=False) as reopened:
        with pytest.raises(ValueError, match="REPAIR_RESULT_UNAVAILABLE"):
            Pipeline(reopened, provider, labels).process(run.id)
    assert len(provider.calls) == before


def test_no_cross_run_embedding_reuse(session):
    for company in range(1, 4):
        add(session, company)
    provider = Provider()
    pipeline = Pipeline(session, provider, labels)
    for _ in range(2):
        pipeline.process(pipeline.start(Settings()).id)
    assert len([c for c in provider.calls if c[0] == "embed"]) == 6


def test_resume_persisted_embeddings_and_generated_article(session):
    for company in range(1, 7):
        add(session, company)
    provider = Provider()
    original = provider.complete
    count = 0

    def interrupted(*args):
        nonlocal count
        if args[3] == SELECTION_SCHEMA:
            return original(*args)
        count += 1
        if count == 2:
            raise ValueError("SIMULATED_INTERRUPTION")
        return original(*args)

    provider.complete = interrupted
    pipeline = Pipeline(session, provider, lambda v, _: [0, 0, 0, 1, 1, 1])
    run = pipeline.start(Settings())
    with pytest.raises(ValueError, match="SIMULATED_INTERRUPTION"):
        pipeline.process(run.id)
    assert run.step == "generate" and run.error == "ValueError"
    assert len(session.scalars(select(Draft)).all()) == 1
    provider.complete = original
    pipeline.process(run.id)
    assert len([c for c in provider.calls if c[0] == "embed"]) == 6
    assert len([c for c in provider.calls if c[0] == GENERATION_SCHEMA]) == 2
    assert len([c for c in provider.calls if c[0] == VERIFICATION_SCHEMA]) == 2


def test_three_articles_are_nearest_to_original_space_centroid():
    candidates = [
        ("a", "url-a", [10.0, 0.0]),
        ("b", "url-b", [1.0, 0.1]),
        ("c", "url-c", [1.0, -0.1]),
        ("d", "url-d", [0.0, 1.0]),
        ("e", "url-e", [-1.0, 0.0]),
    ]
    assert select_three(candidates) == ["b", "a", "c"]
    assert select_three(list(reversed(candidates))) == ["b", "a", "c"]


def test_small_cluster_does_not_produce_three_sources():
    assert select_three([("a", "url-a", [1.0, 0.0]), ("b", "url-b", [0.0, 1.0])]) == []


def test_selection_api_skips_noise_and_small_clusters(session):
    for company in range(1, 8):
        add(session, company)
    provider = Provider()
    pipeline = Pipeline(session, provider, lambda v, _: [0, 0, 1, 1, 1, -1, -1])
    run = pipeline.start(Settings())
    pipeline.process(run.id)
    choices = session.scalars(select(Comparison)).all()
    assert len(choices) == 1 and choices[0].cluster_id == 1
    assert [c[0] for c in provider.calls if c[0] not in ("embed", SELECTION_SCHEMA)] == [
        GENERATION_SCHEMA,
        VERIFICATION_SCHEMA,
    ]
    assert set(run.settings["prompts"]) == {"selection", "generation", "verification"}
    assert run.settings["selection_model"] == Settings.selection_model
    assert len([c for c in provider.calls if c[0] == SELECTION_SCHEMA]) == 1


def test_minimal_schema_and_incompatible_database_guard(session, tmp_path):
    initialize(session.bind)  # An already initialized current schema remains usable.
    assert set(inspect(session.bind).get_table_names()) == {
        "articles",
        "runs",
        "run_articles",
        "comparisons",
        "drafts",
        "verifications",
    }
    engine = engine_for("sqlite:///" + (tmp_path / "incompatible.sqlite").as_posix())
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE unexpected_table (id INTEGER)")
    with pytest.raises(ValueError, match="DATABASE_SCHEMA_MISMATCH"):
        initialize(engine)
    assert inspect(engine).get_table_names() == ["unexpected_table"]
    path = tmp_path / "schema.sql"
    schema_sql(path, "sqlite")
    with sqlite3.connect(":memory:") as database:
        database.executescript(path.read_text(encoding="utf-8"))
        assert (
            len(database.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall())
            == 6
        )


def test_previous_draft_schema_is_rejected_without_modifying_database(tmp_path):
    engine = engine_for("sqlite:///" + (tmp_path / "previous.sqlite").as_posix())
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE drafts (id VARCHAR(36) PRIMARY KEY NOT NULL, "
            "comparison_id VARCHAR(36) NOT NULL UNIQUE, markdown VARCHAR NOT NULL, "
            "created_at VARCHAR NOT NULL)"
        )
    with pytest.raises(ValueError, match="DATABASE_SCHEMA_MISMATCH"):
        initialize(engine)
    assert inspect(engine).get_table_names() == ["drafts"]
    assert "revision" not in {c["name"] for c in inspect(engine).get_columns("drafts")}
    engine.dispose()


def test_schema_limits_comparison_to_initial_and_one_revision(session):
    for company in range(1, 4):
        add(session, company)
    pipeline = Pipeline(session, Provider("ineligible", 40), labels)
    pipeline.process(pipeline.start(Settings()).id)
    comparison = session.scalar(select(Comparison))
    for revision in (1, 2):
        session.add(Draft(comparison_id=comparison.id, revision=revision, markdown="# 修正版"))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
    assert len(session.scalars(select(Draft)).all()) == 2


def test_schema_rejects_invalid_verification_score(session):
    for company in range(1, 4):
        add(session, company)
    pipeline = Pipeline(session, Provider(), labels)
    pipeline.process(pipeline.start(Settings()).id)
    result = session.scalar(select(Verification))
    result.score = 101
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_same_generation_verification_model_refused():
    with pytest.raises(ValueError, match="different models"):
        Settings(generation_model="same", verification_model="same").validate()


def test_response_api_verification_context_and_schema():
    seen = []

    def handler(request):
        payload = json.loads(request.content)
        seen.append(payload)
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(
                                    {"status": "ineligible", "score": 5, "reason": "対象が重複"}
                                ),
                            }
                        ]
                    }
                ],
            },
        )

    api = OpenAI("test-key", httpx.MockTransport(handler))
    result = api.complete(
        "model",
        "prompt",
        {"article_markdown": "text", "sources": [], "generation_instructions": "generation prompt"},
        VERIFICATION_SCHEMA,
    )
    api.close()
    assert result["status"] == "ineligible"
    assert seen[0]["store"] is False
    assert set(json.loads(seen[0]["input"])) == {
        "article_markdown",
        "sources",
        "generation_instructions",
    }


def test_embedding_chunks_do_not_truncate_full_text():
    seen = []

    def handler(request):
        data = json.loads(request.content)
        seen.extend(data["input"])
        return httpx.Response(
            200,
            json={
                "data": [{"index": i, "embedding": [3.0, 4.0]} for i in range(len(data["input"]))]
            },
        )

    text = "長い記事。" * 5000
    api = OpenAI("test-key", httpx.MockTransport(handler))
    value = api.embed("model", [text])[0]
    api.close()
    assert "".join(seen) == text
    assert all(len(c.encode()) <= 6000 for c in seen)
    assert value == pytest.approx([0.6, 0.8])


def test_real_clustering_preserves_separated_groups():
    import numpy as np

    rng = np.random.default_rng(23)
    vectors = np.vstack([np.eye(8)[group] + rng.normal(0, 0.025, (20, 8)) for group in range(3)])
    result = cluster(vectors.tolist(), Settings(n_components=3, n_neighbors=10, min_cluster_size=6))
    assert len(result) == 60
    assert len(set(result) - {-1}) >= 3
    for label in set(result) - {-1}:
        assert len({i // 20 for i, value in enumerate(result) if value == label}) == 1


def test_search_parses_public_response_and_honors_title_exclusion():
    class Client:
        min_delay_seconds = 0

        def get(self, url, **kwargs):
            class Response:
                status_code = 200
                body = (
                    b"User-agent: *\nAllow: /"
                    if url.endswith("robots.txt")
                    else json.dumps(
                        {
                            "status": 200,
                            "data": {
                                "current_page": 1,
                                "last_page": 1,
                                "release_list": [
                                    {
                                        "title": "IoT 新製品",
                                        "release_url": "/main/html/rd/p/000000001.000000001.html",
                                    }
                                ],
                            },
                        }
                    ).encode()
                )

            return Response()

    collector = Collector([], Client())
    assert collector.search(1) == [release()[0]]
    assert Collector(["新製品"], Client()).search(1) == []


def test_cli_import_and_list_without_external_api(tmp_path, capsys):
    url, html = release(body="IoT")
    source = tmp_path / "input.json"
    source.write_text(json.dumps([{"url": url, "html": html}]), encoding="utf-8")
    database = "sqlite:///" + (tmp_path / "cli.sqlite").as_posix()
    assert main(["--database", database, "import-html", "--input", str(source)]) == 0
    assert json.loads(capsys.readouterr().out)["accepted"] == 1
    assert main(["--database", database, "list"]) == 0
    assert json.loads(capsys.readouterr().out) == []


def two_sets(data):
    ids = [x["article_id"] for x in data["candidates"]]
    return {
        "selection_status": "TWO_SETS",
        "primary_article_ids": ids[:3],
        "reserve_article_ids": ids[1:4],
        "reason": "本命と予備についてG1〜G6、共通軸3つと有意差2つを確認。",
    }


@pytest.mark.parametrize("limit", [0, 2, 31, True])
def test_selection_limit_is_a_hard_cap(limit):
    with pytest.raises(ValueError, match="between 3 and 30"):
        Settings(selection_candidate_limit=limit).validate()


def test_selection_receives_at_most_30_full_articles(session):
    for company in range(1, 36):
        add(session, company, body="IoT 本文を省略しない。" * 50)
    provider = Provider()
    pipeline = Pipeline(session, provider, labels)
    run = pipeline.process(pipeline.start(Settings()).id)
    calls = [c for c in provider.calls if c[0] == SELECTION_SCHEMA]
    assert len(calls) == 1 and calls[0][1] == Settings.selection_model
    candidates = calls[0][2]["candidates"]
    assert len(candidates) == 30
    assert [c["centroid_rank"] for c in candidates] == list(range(1, 31))
    for item in candidates:
        assert item["text"] == session.get(Article, item["article_id"]).body
    comparison = session.scalar(select(Comparison))
    assert comparison.candidate_article_ids == [c["article_id"] for c in candidates]
    assert run.settings["selection_candidate_limit"] == 30


@pytest.mark.parametrize("reject_reserve", [False, True])
def test_primary_rejection_uses_reserve_and_only_appropriate_is_verified(
    session, tmp_path, reject_reserve
):
    for company in range(1, 5):
        add(session, company)
    provider = Provider()
    original = provider.complete
    generated = []

    def responding(model, prompt, data, schema):
        result = original(model, prompt, data, schema)
        if schema == SELECTION_SCHEMA:
            return two_sets(data)
        if schema == GENERATION_SCHEMA:
            generated.append(data["sources"])
            if len(generated) == 1 or reject_reserve:
                return generation("# 比較不適（公開不可）\n\nG2：比較単位が異なる。")
        return result

    provider.complete = responding
    pipeline = Pipeline(session, provider, labels)
    run = pipeline.process(pipeline.start(Settings()).id)
    assert len(generated) == 2 and generated[0] != generated[1]
    verified = [c for c in provider.calls if c[0] == VERIFICATION_SCHEMA]
    assert len(verified) == (0 if reject_reserve else 1)
    if verified:
        assert verified[0][1] != Settings.generation_model
        assert verified[0][2]["sources"] == generated[1]
        assert verified[0][2]["generation_instructions"] == run.settings["prompts"]["generation"]
    row = pipeline.export(run.id, tmp_path / "export")["articles"][0]
    assert row["set_role"] == "RESERVE" and len(row["attempts"]) == 2
    assert row["status"] == ("ineligible" if reject_reserve else "eligible")
    assert row["score"] == (None if reject_reserve else 98)
    assert (row["article"] is None) == reject_reserve
    assert (row["inappropriate_report"] is not None) == reject_reserve
    before = len(provider.calls)
    run.step = "generate"
    session.commit()
    pipeline.process(run.id)
    assert len(provider.calls) == before


def test_no_set_is_saved_and_not_generated_or_selected_again(session, tmp_path):
    for company in range(1, 4):
        add(session, company)
    provider = Provider()
    original = provider.complete

    def no_set(model, prompt, data, schema):
        original(model, prompt, data, schema)
        assert schema == SELECTION_SCHEMA
        return {
            "selection_status": "NO_SET",
            "primary_article_ids": [],
            "reserve_article_ids": [],
            "reason": "G2：カテゴリが不一致。",
        }

    provider.complete = no_set
    pipeline = Pipeline(session, provider, labels)
    run = pipeline.process(pipeline.start(Settings()).id)
    assert run.step == "complete" and not session.scalars(select(Draft)).all()
    assert not session.scalars(select(Verification)).all()
    assert session.scalar(select(Comparison)).source_ids() == []
    row = pipeline.export(run.id, tmp_path / "export")["articles"][0]
    assert row["status"] == "not_selected" and row["score"] is None
    before = len(provider.calls)
    run.step = "select"
    session.commit()
    pipeline.process(run.id)
    assert len(provider.calls) == before


@pytest.mark.parametrize("defect", ["outside", "duplicate", "same_set", "status"])
def test_invalid_selection_stops_before_generation(session, defect):
    for company in range(1, 5):
        add(session, company)
    provider = Provider()
    original = provider.complete

    def invalid(model, prompt, data, schema):
        original(model, prompt, data, schema)
        assert schema == SELECTION_SCHEMA
        result = two_sets(data)
        if defect == "outside":
            result["primary_article_ids"][0] = "not-in-the-candidate-pool"
        elif defect == "duplicate":
            result["primary_article_ids"][0] = result["primary_article_ids"][1]
        elif defect == "same_set":
            result["reserve_article_ids"] = list(reversed(result["primary_article_ids"]))
        else:
            result["selection_status"] = "NO_SET"
        return result

    provider.complete = invalid
    pipeline = Pipeline(session, provider, labels)
    run = pipeline.start(Settings())
    with pytest.raises(ValueError):
        pipeline.process(run.id)
    assert run.step == "select" and not session.scalars(select(Comparison)).all()
    assert not session.scalars(select(Draft)).all()


def test_reserve_failure_resumes_without_repeating_primary_or_selection(session, tmp_path):
    for company in range(1, 5):
        add(session, company)
    provider = Provider()
    original = provider.complete
    generated = 0

    def responding(model, prompt, data, schema):
        nonlocal generated
        result = original(model, prompt, data, schema)
        if schema == SELECTION_SCHEMA:
            return two_sets(data)
        if schema == GENERATION_SCHEMA:
            generated += 1
            if generated == 1:
                return generation("# 比較不適（公開不可）\n\nG4：根拠不足。")
            if generated == 2:
                raise ValueError("RESERVE_TRANSPORT_FAILURE")
        return result

    provider.complete = responding
    pipeline = Pipeline(session, provider, labels)
    run = pipeline.start(Settings())
    with pytest.raises(ValueError, match="RESERVE_TRANSPORT_FAILURE"):
        pipeline.process(run.id)
    pending = pipeline.export(run.id, tmp_path / "export")["articles"][0]
    assert pending["set_role"] == "RESERVE" and pending["status"] is None
    with Session(session.bind, expire_on_commit=False) as reopened:
        Pipeline(reopened, provider, labels).process(run.id)
    assert len([c for c in provider.calls if c[0] == SELECTION_SCHEMA]) == 1
    assert generated == 3


def test_primary_appropriate_does_not_generate_reserve_even_after_verification_rejection(session):
    for company in range(1, 5):
        add(session, company)
    provider = Provider("ineligible", 40)
    original = provider.complete

    def responding(model, prompt, data, schema):
        result = original(model, prompt, data, schema)
        return two_sets(data) if schema == SELECTION_SCHEMA else result

    provider.complete = responding
    pipeline = Pipeline(session, provider, labels)
    pipeline.process(pipeline.start(Settings()).id)
    drafts = session.scalars(select(Draft)).all()
    assert len(drafts) == 2 and all(d.set_role == "PRIMARY" for d in drafts)
    assert len([c for c in provider.calls if c[0] == VERIFICATION_SCHEMA]) == 2


@pytest.mark.parametrize(
    "status,text",
    [
        ("APPROPRIATE", ""),
        ("APPROPRIATE", "# 比較不適（公開不可）"),
        ("INAPPROPRIATE", "# 比較記事を返してはいけない"),
    ],
)
def test_inconsistent_generation_is_not_a_normal_rejection(session, status, text):
    for company in range(1, 4):
        add(session, company)
    provider = Provider()
    original = provider.complete

    def invalid(model, prompt, data, schema):
        result = original(model, prompt, data, schema)
        if schema == GENERATION_SCHEMA:
            return {"status": status, "reason": "判定の理由。", "article_markdown": text}
        return result

    provider.complete = invalid
    pipeline = Pipeline(session, provider, labels)
    with pytest.raises(ValueError):
        pipeline.process(pipeline.start(Settings()).id)
    assert not session.scalars(select(Draft)).all()
    assert not session.scalars(select(Verification)).all()


def test_sol_request_includes_reasoning_and_explicit_generation_status():
    payloads = []

    def handler(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {
                        "content": [
                            {"type": "output_text", "text": json.dumps(generation("# 比較記事"))}
                        ]
                    }
                ],
            },
        )

    api = OpenAI("test-key", httpx.MockTransport(handler))
    api.complete("gpt-6.1-sol", "prompt", {"sources": []}, GENERATION_SCHEMA)
    api.close()
    assert payloads[0]["reasoning"] == {"effort": "medium"}
    assert payloads[0]["store"] is False
    assert "temperature" not in payloads[0]


def test_source_migration_preserves_original_database_and_ids(session, tmp_path):
    from maintenance.migrate_ai_selection import migrate

    original = add(session, 1)
    source = tmp_path / "pipeline.sqlite"
    before = source.read_bytes()
    target = "sqlite:///" + (tmp_path / "ai-selection.sqlite").as_posix()
    assert migrate(source, target) == 1
    assert source.read_bytes() == before
    with Session(engine_for(target)) as copied:
        article = copied.get(Article, original.id)
        assert (article.body, article.snapshot_hash) == (original.body, original.snapshot_hash)
        assert copied.scalars(select(Comparison)).all() == []
    with pytest.raises(ValueError, match="TARGET_NOT_EMPTY"):
        migrate(source, target)
    with pytest.raises(ValueError, match="SEPARATE_DATABASE"):
        migrate(source, "sqlite:///" + source.as_posix())


def test_selection_ranking_is_stable_and_uses_full_cluster_centroid():
    from app.clustering import selection_candidates

    candidates = [("a", "a", [1.0, 0.0]), ("b", "b", [0.0, 1.0])]
    candidates += [(f"z{i:02d}", "z", [0.0, 1.0]) for i in range(35)]
    ids = selection_candidates(candidates)
    assert len(ids) == 30 and "a" not in ids
    assert ids == selection_candidates(list(reversed(candidates)))


def test_migration_readonly_uri_supports_unc_paths():
    from pathlib import PureWindowsPath

    from maintenance.migrate_ai_selection import readonly_uri

    uri = readonly_uri(PureWindowsPath("//server/share/news articles.sqlite"))
    assert uri == "file:////server/share/news%20articles.sqlite?mode=ro"


def test_successful_cluster_selection_is_not_repeated_after_next_selection_fails(session):
    for company in range(1, 7):
        add(session, company)
    provider = Provider()
    original = provider.complete
    selected = []

    def interrupted(model, prompt, data, schema):
        if schema == SELECTION_SCHEMA:
            selected.append(data["cluster_id"])
            if len(selected) == 2:
                raise ValueError("SELECTION_TRANSPORT_FAILURE")
        return original(model, prompt, data, schema)

    provider.complete = interrupted
    pipeline = Pipeline(session, provider, lambda v, _: [0, 0, 0, 1, 1, 1])
    run = pipeline.start(Settings())
    with pytest.raises(ValueError, match="SELECTION_TRANSPORT_FAILURE"):
        pipeline.process(run.id)
    assert run.step == "select" and len(session.scalars(select(Comparison)).all()) == 1
    pipeline.process(run.id)
    assert selected == [0, 1, 1]
