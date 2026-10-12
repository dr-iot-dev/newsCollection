# ruff: noqa: RUF001
"""Acceptance regressions for the standalone vocabulary contract and held-out search."""

import json
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from typer.testing import CliRunner

from app.ai.provider import AIResponse
from app.ai.runner import PROMPTS, AIRunner
from app.ai.search_vocabulary_prompts import DISCOVER
from app.cli import app
from app.contracts.discovery_search_vocabulary_v2 import (
    POLICY_VERSION,
    ROLE,
    SPEC_VERSION,
    DiscoveryArticle,
    DiscoverySearchVocabularyV2,
    DiscoveryVocabularyInput,
)
from app.core.config import Settings
from app.core.discovery_search_vocabulary import search_articles, term_matches, validate_vocabulary
from app.core.editorial import EditorialError
from app.infrastructure.db.models import AiRun, ArticleDraft, ModuleMessage, Publication
from app.orchestration.discovery_search_vocabulary import (
    CONSUMER,
    DiscoveryVocabularyService,
    export_record,
    load_record,
)


def seeds():
    return DiscoveryVocabularyInput.model_validate(
        {
            "domain_hint": "IoT製品・サービス",
            "articles": [
                {
                    "article_id": "A",
                    "title": "設備監視サービス",
                    "body": (
                        "クラウド監視・遠隔監視で監視対象データを取り込むIoTサービス。価格を公開。"
                    ),
                },
                {
                    "article_id": "B",
                    "title": "機器のモニタリング基盤",
                    "body": "IoT基盤。モニタリングと可視化。APIを提供。通信はLTE。",
                },
                {
                    "article_id": "C",
                    "title": "既存設備へのIoT導入",
                    "body": "遠隔管理と外部連携。データ保存期間を指定。メール通知。見積を提供。",
                },
            ],
        }
    )


def concept(label="監視", aliases=("モニタリング",), **changes):
    return {
        "id": label,
        "label": label,
        "definition": "対象の状態を確認する機能。",
        "aliases": list(aliases),
        "layer": "output",
        "priority": "high",
        "origin": "generalized",
        "source_article_ids": ["A", "B"],
        "reason": "出力層の中心的な機能を記述する別製品の記事を検索できる。",
        **changes,
    }


def vocabulary_payload():
    return {
        "spec_version": SPEC_VERSION,
        "domain_label": "IoT製品・サービス",
        "domain_terms": ["IoT"],
        "concepts": [
            concept(),
            concept("管理", ()),
            concept("連携", ()),
            concept("データ", (), layer="input", definition="入力として扱うデータ。"),
            concept("通信", (), layer="mechanism", origin="observed", source_article_ids=["B"]),
            concept(
                "価格",
                ("値段",),
                layer="operations",
                origin="observed",
                source_article_ids=["A"],
                definition="購入や利用のための金額。",
            ),
            concept("API", (), origin="observed", source_article_ids=["B"]),
            concept(
                "認証",
                (),
                layer="mechanism",
                origin="domain_expansion",
                source_article_ids=[],
                definition="利用主体を確認する仕組み。",
            ),
            concept(
                "契約", (), layer="operations", origin="domain_expansion", source_article_ids=[]
            ),
        ],
        "notes": [],
    }


def vocabulary():
    result = DiscoverySearchVocabularyV2.model_validate(vocabulary_payload())
    validate_vocabulary(result, seeds())
    return result


class Provider:
    def __init__(self, outputs=None):
        self.outputs = outputs or [vocabulary_payload()]
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        return AIResponse(self.outputs[min(len(self.calls) - 1, len(self.outputs) - 1)])


def settings(model="test-vocabulary-model"):
    return Settings(_env_file=None, ai_discovery_vocabulary_model=model)


def service(session, provider, config=None):
    config = config or settings()
    return DiscoveryVocabularyService(session, config, AIRunner(session, config, provider))


@pytest.mark.parametrize("size", [0, 1, 29, 51, 70])
def test_no_concept_count_quota_or_layer_quota(size):
    payload = vocabulary_payload()
    payload["concepts"] = [concept(f"概念{index}", ()) for index in range(size)]
    value = DiscoverySearchVocabularyV2.model_validate(payload)
    validate_vocabulary(value, seeds())
    assert len(value.concepts) == size
    assert "minItems" not in value.model_json_schema()["properties"]["concepts"]
    assert "maxItems" not in value.model_json_schema()["properties"]["concepts"]


def test_broad_terms_single_article_and_unobserved_terms_survive():
    value = vocabulary()
    by_label = {entry.label: entry for entry in value.concepts}
    assert by_label["価格"].source_article_ids == ("A",)
    assert by_label["価格"].aliases == ("値段",)
    assert by_label["認証"].source_article_ids == ()
    assert by_label["データ"].layer == "input"
    assert {by_label[label].id for label in ("監視", "管理", "連携")} == {"監視", "管理", "連携"}


@pytest.mark.parametrize(
    "label", ["クラウド監視", "遠隔監視", "遠隔管理", "外部連携", "監視対象データ"]
)
def test_modified_labels_are_repaired_instead_of_added_as_separate_axes(label):
    payload = vocabulary_payload()
    payload["concepts"] = [concept(label, ())]
    with pytest.raises(EditorialError, match="VOCABULARY_MODIFIED_LABEL"):
        validate_vocabulary(DiscoverySearchVocabularyV2.model_validate(payload), seeds())


@pytest.mark.parametrize(
    "label,alias",
    [
        ("監視", "管理"),
        ("監視", "連携"),
        ("管理", "監視"),
        ("管理", "連携"),
        ("連携", "監視"),
        ("連携", "管理"),
        ("保存", "データ保存期間"),
        ("データ保存", "データ保存期間"),
        ("通信", "LTE"),
        ("通知", "メール"),
        ("価格", "見積"),
    ],
)
def test_related_attributes_methods_and_values_are_not_synonyms(label, alias):
    payload = vocabulary_payload()
    payload["concepts"] = [concept(label, (alias,))]
    with pytest.raises(EditorialError, match="VOCABULARY_RELATED_ALIAS"):
        validate_vocabulary(DiscoverySearchVocabularyV2.model_validate(payload), seeds())


@pytest.mark.parametrize(
    "change",
    [
        {"label": "価格（セット別）"},
        {"label": "価格の有無"},
        {"label": "対応可否"},
        {"label": "a" * 25},
        {"label": " "},
        {"aliases": ["監視"]},
        {"aliases": ["API", "ＡＰＩ"]},
        {"aliases": [1]},
        {"layer": "other"},
        {"priority": "low"},
        {"source_article_ids": []},
        {"origin": "domain_expansion"},
        {"reason": ""},
        {"id": 5},
        {"definition": 5},
        {"unexpected": "value"},
    ],
)
def test_contract_rejects_bad_fields(change):
    payload = vocabulary_payload()
    payload["concepts"] = [concept(**change)]
    with pytest.raises(ValidationError):
        DiscoverySearchVocabularyV2.model_validate(payload)


@pytest.mark.parametrize("field", ["id", "label"])
def test_duplicate_ids_and_names_rejected(field):
    payload = vocabulary_payload()
    payload["concepts"][1][field] = payload["concepts"][0][field]
    with pytest.raises(ValidationError):
        DiscoverySearchVocabularyV2.model_validate(payload)


def test_unknown_source_and_priority_order_rejected():
    payload = vocabulary_payload()
    payload["concepts"][0]["source_article_ids"] = ["unprovided"]
    with pytest.raises(EditorialError, match="VOCABULARY_UNKNOWN_ARTICLE"):
        validate_vocabulary(DiscoverySearchVocabularyV2.model_validate(payload), seeds())
    payload = vocabulary_payload()
    payload["concepts"][0]["priority"] = "normal"
    with pytest.raises(ValidationError):
        DiscoverySearchVocabularyV2.model_validate(payload)


@pytest.mark.parametrize("size", [2, 6])
def test_seed_count_is_three_to_five(size):
    payload = seeds().model_dump(mode="json")
    payload["articles"] = [
        {"article_id": str(i), "title": "title", "body": "body"} for i in range(size)
    ]
    with pytest.raises(ValidationError):
        DiscoveryVocabularyInput.model_validate(payload)


def test_duplicate_seed_ids_rejected():
    payload = seeds().model_dump(mode="json")
    payload["articles"][1]["article_id"] = "A"
    with pytest.raises(ValidationError):
        DiscoveryVocabularyInput.model_validate(payload)


@pytest.mark.parametrize(
    "term,text,expected",
    [
        ("API", "ａｐｉ", True),
        ("API", "api連携", True),
        ("API", "rapidapi", False),
        ("API", "apis", False),
        ("IoT", "ＩｏＴ製品", True),
        ("IoT", "biotech", False),
        ("監視", "遠隔監視サービス", True),
        ("データ", "監視対象データ", True),
        ("C++", "C++実装", True),
        ("C++", "abc++", False),
    ],
)
def test_nfkc_casefold_latin_boundaries_and_japanese_compounds(term, text, expected):
    from app.contracts.discovery_search_vocabulary_v2 import normalized_text

    assert term_matches(term, normalized_text(text)) is expected


def held_out_articles():
    # Explanation-only releases for products outside the seed corpus, with relevance labels.
    return tuple(
        DiscoveryArticle(article_id=key, title=title, body=body)
        for key, title, body in [
            (
                "D",
                "別製品Delta",
                "ＩｏＴ機器。監視とモニタリングでデータを扱う。値段と認証を説明。",
            ),
            ("E", "別サービスEcho", "iotサービス。モニタリングとAPI連携。契約を説明。"),
            ("F", "別製品Foxtrot", "IoTセンサーの価格を説明。"),
            ("X", "別分野", "金融サービスの価格と管理。"),
            ("Y", "企業紹介", "IoT企業の設立と沿革について。"),
            ("Z", "境界による誤一致", "Biotech製品。RapidAPIの登録について。"),
        ]
    )


def test_held_out_search_precision_recall_and_concept_deduplication():
    hits = search_articles(vocabulary(), held_out_articles())
    relevant = {"D", "E", "F"}
    retrieved = {hit.article_id for hit in hits}
    precision = len(retrieved & relevant) / len(retrieved)
    recall = len(retrieved & relevant) / len(relevant)
    assert precision == recall == 1
    monitoring = next(match for match in hits[0].matches if match.label == "監視")
    assert monitoring.matched_terms == ("監視", "モニタリング")
    assert hits[0].concept_count == 4
    assert hits[0].layer_count == 4
    assert hits[0].high_priority_count == 4
    assert "監視対象データ" not in vocabulary().model_dump_json()
    assert all(hit.article_id not in {"A", "B", "C"} for hit in hits)


def test_domain_filter_is_separate_and_seeds_can_be_excluded():
    hits = search_articles(
        vocabulary(),
        (*seeds().articles, *held_out_articles()),
        require_domain=False,
        excluded_article_ids=["A", "B", "C"],
    )
    assert "X" in {hit.article_id for hit in hits}
    assert not {"A", "B", "C"} & {hit.article_id for hit in hits}
    assert all("IoT" not in match.matched_terms for hit in hits for match in hit.matches)


def test_discover_history_cache_export_and_no_value_extraction(acquisition_session, tmp_path):
    session = acquisition_session
    provider = Provider()
    runner_service = service(session, provider)
    record = runner_service.discover(seeds())
    assert record.status == "ready"
    assert record.vocabulary == vocabulary()
    assert record.policy_version == POLICY_VERSION
    assert provider.calls[0]["instructions"] == DISCOVER
    assert provider.calls[0]["data"] == seeds().model_dump(mode="json")
    assert provider.calls[0]["max_output_tokens"] == 16000
    assert len(provider.calls) == 1
    assert runner_service.discover(seeds()) == record
    assert load_record(session, record.run_id) == record
    export_record(record, tmp_path)
    assert (
        DiscoverySearchVocabularyV2.model_validate_json((tmp_path / "vocabulary.json").read_text())
        == vocabulary()
    )
    assert "label,aliases,layer,priority,origin" in (tmp_path / "candidates.csv").read_text(
        "utf-8-sig"
    )
    assert session.scalars(select(AiRun.execution_role)).all() == [ROLE]
    assert not session.scalars(select(ArticleDraft)).all()
    assert not session.scalars(select(Publication)).all()


def test_model_prompt_input_and_legacy_caches_are_separate(acquisition_session, monkeypatch):
    session = acquisition_session
    provider = Provider()
    first = service(session, provider).discover(seeds())
    changed_model = service(session, provider, settings("another-model")).discover(seeds())
    assert changed_model.run_id != first.run_id
    monkeypatch.setitem(PROMPTS, ROLE, DISCOVER + "\nPolicy revision.")
    changed_prompt = service(session, provider).discover(seeds())
    assert changed_prompt.run_id != first.run_id
    changed_input = seeds().model_copy(update={"domain_hint": "IoT monitoring"})
    assert service(session, provider).discover(changed_input).run_id != changed_prompt.run_id
    assert len(provider.calls) == 4
    assert all(row.consumer == CONSUMER for row in session.scalars(select(ModuleMessage)))


def test_invalid_semantics_are_repaired_once_and_invalid_attempt_is_saved(acquisition_session):
    bad = vocabulary_payload()
    bad["concepts"][0]["aliases"] = ["管理"]
    provider = Provider([bad, vocabulary_payload()])
    record = service(acquisition_session, provider).discover(seeds())
    assert record.status == "ready"
    assert len(provider.calls) == len(record.ai_run_ids) == 2
    assert "Repair once" in provider.calls[1]["instructions"]
    runs = [acquisition_session.get(AiRun, key) for key in record.ai_run_ids]
    assert [run.validation_status for run in runs] == ["invalid", "valid"]


def test_failed_attempt_can_resume_without_accepting_old_output(acquisition_session):
    bad = vocabulary_payload()
    bad["spec_version"] = "old-policy"
    provider = Provider([bad, vocabulary_payload()])
    runner_service = service(acquisition_session, provider)
    failed = runner_service.discover(seeds(), call_budget=1)
    assert failed.status == "failed" and failed.vocabulary is None
    assert len(provider.calls) == 1
    resumed = runner_service.discover(seeds(), call_budget=1)
    assert resumed.run_id == failed.run_id and resumed.status == "ready"
    assert len(resumed.ai_run_ids) == 2


def test_cache_tampering_is_rejected(acquisition_session):
    session = acquisition_session
    provider = Provider()
    record = service(session, provider).discover(seeds())
    run = session.get(AiRun, record.successful_ai_run_id)
    run.prompt_version = "legacy"
    session.commit()
    with pytest.raises(EditorialError, match="VOCABULARY_AI_CACHE_INVALID"):
        service(session, provider).discover(seeds())
    assert len(provider.calls) == 1


def test_missing_history_returns_explicit_error(acquisition_session):
    with pytest.raises(EditorialError, match="VOCABULARY_RUN_NOT_FOUND"):
        load_record(acquisition_session, uuid4())


def test_cli_search_files_has_no_database_or_ai_dependency(tmp_path, monkeypatch):
    import app.discovery_vocabulary_cli as cli

    def unavailable():
        raise AssertionError("offline search must not open DB")

    monkeypatch.setattr(cli, "SessionLocal", unavailable)
    vocab_file, articles_file = tmp_path / "vocabulary.json", tmp_path / "articles.json"
    vocab_file.write_text(vocabulary().model_dump_json(), encoding="utf-8")
    articles_file.write_text(
        json.dumps([article.model_dump() for article in held_out_articles()]), encoding="utf-8"
    )
    result = CliRunner().invoke(
        app,
        [
            "discovery-vocabulary",
            "search",
            "--vocabulary",
            str(vocab_file),
            "--articles",
            str(articles_file),
        ],
    )
    assert result.exit_code == 0, result.output
    assert {hit["article_id"] for hit in json.loads(result.output)} == {"D", "E", "F"}


def test_cli_discovery_and_show(acquisition_session, tmp_path, monkeypatch):
    import app.discovery_vocabulary_cli as cli

    session = acquisition_session
    provider = Provider()
    monkeypatch.setattr(cli, "SessionLocal", lambda: session)
    monkeypatch.setattr(cli, "get_settings", settings)
    monkeypatch.setattr(
        cli,
        "DiscoveryVocabularyService",
        lambda session, config: service(session, provider, config),
    )
    path = tmp_path / "seeds.json"
    path.write_text(seeds().model_dump_json(), encoding="utf-8")
    result = CliRunner().invoke(
        app,
        [
            "discovery-vocabulary",
            "discover",
            "--input",
            str(path),
            "--output",
            str(tmp_path / "export"),
        ],
    )
    assert result.exit_code == 0, result.output
    record_id = json.loads(result.output)["run_id"]
    result = CliRunner().invoke(app, ["discovery-vocabulary", "show", record_id])
    assert result.exit_code == 0, result.output
    assert "label\taliases\tlayer\tpriority\torigin" in result.output
    assert "価格\t値段\toperations\thigh\tobserved" in result.output
    assert len(provider.calls) == 1


def test_opaque_article_and_concept_ids_are_case_sensitive():
    payload = seeds().model_dump(mode="json")
    payload["articles"][1]["article_id"] = "a"
    request = DiscoveryVocabularyInput.model_validate(payload)
    output = vocabulary_payload()
    output["concepts"] = [
        concept("監視", (), id="X", source_article_ids=["A", "a"]),
        concept("管理", (), id="x", source_article_ids=["a"]),
    ]
    validate_vocabulary(DiscoverySearchVocabularyV2.model_validate(output), request)


def test_duplicate_alias_ownership_rejected():
    output = vocabulary_payload()
    output["concepts"] = [
        concept("監視", ("モニタリング",)),
        concept("状態確認", ("モニタリング",)),
    ]
    with pytest.raises(EditorialError, match="VOCABULARY_DUPLICATE_CONCEPT"):
        validate_vocabulary(DiscoverySearchVocabularyV2.model_validate(output), seeds())


@pytest.mark.parametrize(
    "change",
    [
        {"policy_version": "legacy-policy"},
        {"contract_hash": "sha256:" + "0" * 64},
        {"output_hash": "sha256:" + "0" * 64},
        {"model": "legacy-model"},
    ],
)
def test_old_policy_schema_or_modified_history_is_not_a_vocabulary_cache(
    acquisition_session, change
):
    session = acquisition_session
    provider = Provider()
    record = service(session, provider).discover(seeds())
    row = session.get(ModuleMessage, record.run_id)
    row.result_json = {**row.result_json, **change}
    session.commit()
    with pytest.raises(EditorialError):
        service(session, provider).discover(seeds())
    assert len(provider.calls) == 1


def test_registered_input_uses_current_approved_extracted_bodies(acquisition_session):
    from app.infrastructure.db.models import ExtractionResult, Item, RawSnapshot, Source
    from app.orchestration.discovery_search_vocabulary import load_input, registered_articles
    from tests.unit.test_comparison_dynamic_axes import documents

    session = acquisition_session
    docs = documents(session)
    from datetime import UTC, datetime, timedelta

    for doc in docs:
        session.add(
            RawSnapshot(
                id=doc.snapshot_id,
                source_id=doc.source_id,
                requested_url=doc.url,
                final_url=doc.url,
                status_code=200,
                response_headers={},
                content_type="text/plain",
                body_sha256="0" * 64,
                body_text=doc.body,
                fetched_at=datetime.now(UTC),
                retention_until=(datetime.now(UTC) + timedelta(days=365)).date(),
            )
        )
        session.flush()
        session.add(
            ExtractionResult(
                item_id=doc.item_id,
                revision=doc.item_version,
                payload_json={"title": doc.title, "body": doc.body},
                snapshot_id=doc.snapshot_id,
                body_sha256="0" * 64,
                canonical_url=doc.url,
                payload_hash="sha256:" + "0" * 64,
            )
        )
    session.commit()
    request = load_input(session, tuple(doc.item_id for doc in docs), "IoT")
    assert tuple(article.body for article in request.articles) == tuple(doc.body for doc in docs)
    assert len(tuple(registered_articles(session))) == 3
    item = session.get(Item, docs[0].item_id)
    item.version += 1
    session.commit()
    with pytest.raises(EditorialError, match="VOCABULARY_APPROVED_EXTRACTION_REQUIRED"):
        load_input(session, tuple(doc.item_id for doc in docs))
    item.version -= 1
    source = session.get(Source, item.source_id)
    source.enabled = False
    session.commit()
    with pytest.raises(EditorialError, match="VOCABULARY_APPROVED_EXTRACTION_REQUIRED"):
        load_input(session, tuple(doc.item_id for doc in docs))
