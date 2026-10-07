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


@pytest.mark.parametrize("fault", [None, "value", "source", "missing", "duplicate", "source_list"])
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
    assert dto.body_markdown.index("## 比較表") < dto.body_markdown.index("## 出典")
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
        else:
            body = body.replace("- 資料1:", "- 資料9:", 1)
        dto = dto.model_copy(update={"body_markdown": body})
    criteria = {c.key: c.result for c in rule_criteria(dto, package)}
    if fault == "source_list":
        assert criteria["source_links"] == "fail"
    elif fault:
        assert criteria["comparison_table"] == criteria["fact_support"] == "fail"
    else:
        assert all(value == "pass" for value in criteria.values())
        assert service.verify(draft.id).overall_result == "pass"
        payload = build_payload(dto, package, "cms", {"edge_ai": 1}, {})
        soup = BeautifulSoup(payload.content, "html.parser")
        assert len(soup.find_all("table")) == 1
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
