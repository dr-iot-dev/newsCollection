from uuid import uuid4

import pytest
from bs4 import BeautifulSoup

from app.contracts.article_package_v1 import ArticlePackageV1, SourceReferenceV1
from app.contracts.draft_v1 import ArticleDraftV1
from app.contracts.facts_v1 import VerifiedFactV1
from app.core.article_tables import comparison_prose, render_comparison_table, render_source_list
from app.modules.publication.service import build_payload
from app.modules.verification.service import rule_criteria
from tests.unit.test_comparison_research import prepared_root, seed_articles


def example_package():
    first, second = uuid4(), uuid4()
    facts = (
        VerifiedFactV1(
            fact_id=uuid4(),
            evidence_id=first,
            fact_type="product",
            subject="Alpha",
            predicate="product",
            value="Alpha",
        ),
        VerifiedFactV1(
            fact_id=uuid4(),
            evidence_id=first,
            fact_type="price",
            subject="Alpha",
            predicate="subsidy",
            value="1,000円",
            region="日本",
            conditions="補助適用後・対象世帯のみ",
        ),
        VerifiedFactV1(
            fact_id=uuid4(),
            evidence_id=first,
            fact_type="hardware_spec",
            subject="Alpha",
            predicate="spec",
            value="LTE | [bad](https://bad.example)",
            attribution="開発元",
        ),
        VerifiedFactV1(
            fact_id=uuid4(),
            evidence_id=second,
            fact_type="product",
            subject="Beta",
            predicate="product",
            value="Beta",
        ),
        VerifiedFactV1(
            fact_id=uuid4(),
            evidence_id=second,
            fact_type="price",
            subject="Beta",
            predicate="price",
            value="2,000円",
            region="米国",
            conditions="月額料金",
        ),
    )
    references = (
        SourceReferenceV1(
            url="https://z.example/main",
            reference_id=first,
            fact_ids=tuple(f.fact_id for f in facts if f.evidence_id == first),
        ),
        SourceReferenceV1(
            url="https://a.example/other",
            reference_id=second,
            fact_ids=tuple(f.fact_id for f in facts if f.evidence_id == second),
        ),
    )
    return ArticlePackageV1(
        item_id=uuid4(),
        revision=1,
        topic="比較",
        comparison_dataset_id=uuid4(),
        writing_policy_version="writing-v5",
        facts=facts,
        verified_fact_ids=tuple(f.fact_id for f in facts),
        source_references=references,
    )


def test_table_keeps_conditions_unknowns_and_reference_order_without_invented_links():
    package = example_package()
    table = render_comparison_table(package)
    assert "日本、補助適用後・対象世帯のみ" in table
    assert "米国、月額料金" in table
    assert "開発元によると" in table
    assert "資料で確認できず" in table and "非対応を意味しない" in table
    assert "[資料1](https://z.example/main)" in table
    assert "[資料2](https://a.example/other)" in table
    assert render_source_list(package).splitlines() == [
        "- 資料1: https://z.example/main",
        "- 資料2: https://a.example/other",
    ]
    draft = ArticleDraftV1(
        draft_id=uuid4(),
        item_id=package.item_id,
        article_package_id=uuid4(),
        revision=1,
        title="仕様比較",
        lead="確認済み資料",
        body_markdown=table + "\n\n## 出典\n\n" + render_source_list(package),
        category_keys=("iot_platform",),
        paragraph_facts=(),
        writer_profile_key="test",
    )
    payload = build_payload(draft, package, "cms", {"iot_platform": 1}, {})
    soup = BeautifulSoup(payload.content, "html.parser")
    anchors = soup.find("table").find_all("a")
    assert [(a.get_text(), a["href"]) for a in anchors] == [
        ("資料1", "https://z.example/main"),
        ("資料2", "https://a.example/other"),
    ]
    assert len(soup.find("tbody").find_all("tr")) == 2
    assert all(len(tr.find_all("td")) == 3 for tr in soup.find("tbody").find_all("tr"))
    assert soup.find("table").get_text().count("[bad](https://bad.example)") == 1
    source_rows = soup.find("h2", string="出典").find_next_sibling("ul").find_all("li")
    assert [li.get_text() for li in source_rows] == [
        "資料1: https://z.example/main",
        "資料2: https://a.example/other",
    ]


def test_repeated_source_uses_one_number_and_unverified_facts_do_not_enter_table():
    package = example_package()
    repeated = package.model_copy(
        update={"source_references": (*package.source_references, package.source_references[0])}
    )
    assert render_comparison_table(repeated) == render_comparison_table(package)
    assert render_source_list(repeated) == render_source_list(package)
    single = package.model_copy(update={"source_references": package.source_references[:1]})
    assert render_comparison_table(single) == ""
    limited = package.model_copy(
        update={
            "verified_fact_ids": tuple(
                f.fact_id for f in package.facts if f.fact_type != "hardware_spec"
            )
        }
    )
    assert "bad.example" not in render_comparison_table(limited)


@pytest.mark.parametrize(
    "fault", [None, "value", "source", "missing", "duplicate", "source_list", "prose_heading"],
)
def test_future_draft_generates_and_verifies_table_before_wordpress(acquisition_session, fault):
    session = acquisition_session
    target, previous, competitor = seed_articles(session)
    service = prepared_root(session, target)
    service.facts(previous.id)
    service.facts(competitor.id)
    service.comparison(target.id, (previous.id,), (competitor.id,), request_missing=False)
    draft = service.draft(target.id)
    assert draft
    _, package = service.package(target)
    dto = ArticleDraftV1.model_validate(draft.source_block["draft"])
    table = render_comparison_table(package)
    assert table and dto.body_markdown.count("## 比較表") == 1
    assert dto.body_markdown.count("## 比較の考察") == 1
    assert dto.body_markdown.split(table, 1)[1].startswith("\n\n## 比較の考察\n\n")
    assert dto.body_markdown.index("## 比較表") < dto.body_markdown.index("## 比較の考察")
    assert dto.body_markdown.index("## 比較の考察") < dto.body_markdown.index("## 出典")
    if fault:
        body = dto.body_markdown
        if fault == "value":
            body = body.replace("8GB", "999GB")
        elif fault == "source":
            body = body.replace("[資料1]", "[資料2]", 1)
        elif fault == "missing":
            body = body.replace(table, "", 1)
        elif fault == "duplicate":
            body = body.replace(table, table + table, 1)
        elif fault == "prose_heading":
            body = body.replace("## 比較の考察\n\n", "", 1)
        else:
            body = body.replace("- 資料1:", "- 資料9:", 1)
        dto = dto.model_copy(update={"body_markdown": body})
    criteria = {c.key: c.result for c in rule_criteria(dto, package)}
    if fault == "source_list":
        assert criteria["source_links"] == "fail"
    elif fault == "prose_heading":
        assert criteria["comparison_table"] == "fail"
    elif fault:
        assert criteria["comparison_table"] == criteria["fact_support"] == "fail"
    else:
        assert all(value == "pass" for value in criteria.values())
        assert service.verify(draft.id).overall_result == "pass"
        payload = build_payload(dto, package, "cms", {"edge_ai": 1}, {})
        soup = BeautifulSoup(payload.content, "html.parser")
        assert len(soup.find_all("table")) == 1
        assert [h.get_text() for h in soup.find_all("h2")] == ["比較表", "比較の考察", "出典"]
        anchors = soup.find("table").find_all("a")
        refs = [str(ref.url) for ref in package.source_references]
        assert [(a.get_text(), a["href"]) for a in anchors] == [
            (f"資料{i}", url) for i, url in enumerate(refs, 1)
        ]


def test_table_values_do_not_mask_copied_prose_or_allow_altered_tables():
    package = example_package()
    table = render_comparison_table(package)
    source_expression = "本文の独自表現は別に検証する。" * 10
    body = source_expression + table
    valid, prose = comparison_prose(body, package)
    assert valid and prose == source_expression
    changed = body.replace("1,000円", "99,999円")
    valid, prose = comparison_prose(changed, package)
    assert not valid and prose == changed
    valid, _ = comparison_prose(body + table, package)
    assert not valid


def test_majority_is_strict_counts_unique_sources_and_never_hides_deficient_rows():
    from app.core.article_tables import comparison_coverage, require_comparison_coverage
    from app.core.editorial import EditorialError

    package = example_package()
    audit = comparison_coverage(package)
    assert audit.source_count == 2 and audit.required == 2
    assert audit.deficient_rows == ("技術・機能仕様",)
    with pytest.raises(EditorialError, match="COMPARISON_ROW_MAJORITY_REQUIRED"):
        require_comparison_coverage(package)
    repeated = package.model_copy(update={
        "source_references": (*package.source_references, package.source_references[0]),
    })
    assert comparison_coverage(repeated) == audit
    assert "技術・機能仕様" in render_comparison_table(package)
    retained = package.model_copy(update={"comparison_required_rows": ("standard",)})
    assert "標準" in comparison_coverage(retained).deficient_rows
    assert "| 標準 | 資料で確認できず | 資料で確認できず |" in render_comparison_table(retained)


def test_majority_accepts_two_of_three_but_not_half_of_four():
    from app.core.article_tables import coverage_for_sources

    package = example_package()
    first = package.facts[:3]
    second = package.facts[3:]
    audit = coverage_for_sources([
        ("https://a.example/", first), ("https://b.example/", first),
        ("https://c.example/", second),
    ])
    assert audit.valid and audit.required == 2
    assert not coverage_for_sources([
        ("https://a.example/", first), ("https://b.example/", first),
        ("https://c.example/", second), ("https://d.example/", second),
    ]).valid


def test_comparison_prose_before_table_is_rejected(acquisition_session):
    session = acquisition_session
    target, previous, competitor = seed_articles(session)
    service = prepared_root(session, target)
    service.facts(previous.id)
    service.facts(competitor.id)
    service.comparison(target.id, (previous.id,), (competitor.id,), request_missing=False)
    draft = service.draft(target.id)
    _, package = service.package(target)
    dto = ArticleDraftV1.model_validate(draft.source_block["draft"])
    assert dto.body_markdown.lstrip().startswith("## 比較表")
    table = render_comparison_table(package)
    moved = dto.model_copy(update={"body_markdown": "先に本文。" + dto.body_markdown})
    assert {c.key: c.result for c in rule_criteria(moved, package)}["comparison_table"] == "fail"
    assert comparison_prose(moved.body_markdown, package)[0]
    assert table in moved.body_markdown


def test_manual_fact_corrections_preserve_history_and_reject_unquoted_values(acquisition_session):
    from app.contracts.facts_v1 import FactsOutputV1
    from app.core.editorial import EditorialError
    from app.modules.extraction.facts import rule_facts
    from app.orchestration.research import current_content

    target, _, _ = seed_articles(acquisition_session)
    service = prepared_root(acquisition_session, target)
    before, _ = service.evidence(target)
    output = rule_facts(current_content(acquisition_session, target))
    corrected = service.facts(target.id, manual=output)
    assert corrected.id != before.id and corrected.revision == before.revision + 1
    assert before.payload_json["verified_facts"]
    tampered = output.model_copy(update={"facts": (
        output.facts[0].model_copy(update={"value": "UNSUPPORTED"}),
    )})
    with pytest.raises(EditorialError, match="FACT_VALUE_UNSUPPORTED"):
        service.facts(target.id, manual=FactsOutputV1.model_validate(tampered.model_dump()))


def test_explicit_editorial_revision_can_rewrite_passed_draft_but_default_stays_idempotent(
    acquisition_session,
):
    from app.core.editorial import EditorialError

    target, previous, competitor = seed_articles(acquisition_session)
    service = prepared_root(acquisition_session, target)
    service.facts(previous.id)
    service.facts(competitor.id)
    service.comparison(target.id, (previous.id,), (competitor.id,), request_missing=False)
    first = service.draft(target.id)
    assert service.verify(first.id).overall_result == "pass"
    with pytest.raises(EditorialError, match="DRAFT_SOURCE_SET_DUPLICATE"):
        service.draft(target.id)
    second = service.draft(target.id, revision_reason="User requested source and layout correction")
    assert second.revision == first.revision + 1 and second.id != first.id
    assert first.body_markdown and service.verify(second.id).overall_result == "pass"


def test_joint_search_reselects_a_group_instead_of_omitting_low_coverage_axis(acquisition_session):
    from app.orchestration.research import prepare_comparison

    target, previous, competitor = seed_articles(acquisition_session)
    service = prepared_root(acquisition_session, target)
    prepared = prepare_comparison(service, target.id)
    assert prepared.previous_ids == (previous.id,)
    assert prepared.competitor_ids == (competitor.id,)
    package = service.comparison(
        target.id, prepared.previous_ids, prepared.competitor_ids, request_missing=False,
    )
    from app.core.article_tables import comparison_coverage
    assert comparison_coverage(ArticlePackageV1.model_validate(package.payload_json)).valid

def test_joint_search_uses_better_evidence_even_when_its_relevance_rank_is_lower(
    acquisition_session, monkeypatch,
):
    from sqlalchemy import select

    from app.infrastructure.db.models import ModuleMessage
    from app.orchestration.research import prepare_comparison, select_joint_sources
    from tests.unit.test_comparison_research import add_article

    target, previous, competitor = seed_articles(acquisition_session)
    alternative = add_article(
        acquisition_session, "alternative", "ThirdCorp", "DEF300", 16, "29,800", 30,
    )
    service = prepared_root(acquisition_session, target)
    for item in (previous, competitor, alternative):
        service.facts(item.id)
    prepared = prepare_comparison(service, target.id)
    original_evidence = service.evidence

    def richer_evidence(item):
        row, evidence = original_evidence(item)
        if item.id in {target.id, alternative.id}:
            template = next(
                fact for fact in evidence.verified_facts if fact.fact_type == "hardware_spec"
            )
            evidence = evidence.model_copy(update={"verified_facts": (
                *evidence.verified_facts,
                template.model_copy(update={
                    "fact_id": uuid4(), "fact_type": "software_requirement",
                }),
            )})
        return row, evidence

    monkeypatch.setattr(service, "evidence", richer_evidence)
    messages = list(acquisition_session.scalars(
        select(ModuleMessage).where(ModuleMessage.message_id.in_(prepared.request_ids))
    ))
    for message in messages:
        choices = (
            [{"item_id": str(previous.id), "score": 100}]
            if message.payload_json["relation"] == "previous"
            else [
                {"item_id": str(competitor.id), "score": 100},
                {"item_id": str(alternative.id), "score": 1},
            ]
        )
        message.result_json = {"coverage_candidates": choices}
    _, target_evidence = service.evidence(target)
    chosen = select_joint_sources(
        service, target_evidence,
        {"previous": (previous.id,), "competitor": (competitor.id,)},
        prepared.request_ids, {"previous": (), "competitor": ()},
    )
    assert chosen == {"previous": (previous.id,), "competitor": (alternative.id,)}

def test_reselection_retains_previous_axes_even_if_new_documents_lack_them(acquisition_session):
    from app.core.article_tables import comparison_coverage
    from app.core.editorial import EditorialError
    from app.modules.extraction.facts import rule_facts
    from app.orchestration.research import current_content

    target, previous, competitor = seed_articles(acquisition_session)
    service = prepared_root(acquisition_session, target)
    service.facts(previous.id)
    service.facts(competitor.id)
    original = service.comparison(
        target.id, (previous.id,), (competitor.id,), request_missing=False,
    )
    assert "price" in ArticlePackageV1.model_validate(
        original.payload_json
    ).comparison_required_rows
    for item in (target, previous, competitor):
        output = rule_facts(current_content(acquisition_session, item))
        service.facts(item.id, manual=output.model_copy(update={
            "facts": tuple(f for f in output.facts if f.fact_type != "price"),
        }))
    service.select(target.id)
    revised = service.comparison(
        target.id, (previous.id,), (competitor.id,), request_missing=False,
    )
    package = ArticlePackageV1.model_validate(revised.payload_json)
    assert "price" in package.comparison_required_rows
    assert ("price", "価格と適用条件", 0) in comparison_coverage(package).rows
    with pytest.raises(EditorialError, match="COMPARISON_ROW_MAJORITY_REQUIRED"):
        service.draft(target.id)
