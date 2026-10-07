from uuid import uuid4

import pytest

from app.contracts.draft_v1 import ArticleDraftV1
from app.contracts.editorial_v1 import WritingOutputV1
from app.core.article_tables import fact_text, render_comparison_table
from app.core.draft_style import has_polite_ending, plain_style
from app.modules.verification.service import rule_criteria
from app.modules.writing.service import normalize_writing_style
from tests.unit.test_article_tables import example_package
from tests.unit.test_comparison_research import prepared_root, seed_articles


@pytest.mark.parametrize(
    ("polite", "plain"),
    [
        ("資料を整理しました。非対応を意味しません。", "資料を整理した。非対応を意味しない。"),
        ("方式が異なりますが、用途は共通しています。", "方式が異なるが、用途は共通している。"),
        (
            "対象世帯のみ利用できます。一般価格ではありません。",
            "対象世帯のみ利用できる。一般価格ではない。",
        ),
        ("製品は『便利です。』と説明しています。", "製品は『便利です。』と説明している。"),
        ("「ますます便利」は製品名です。", "「ますます便利」は製品名である。"),
    ],
)
def test_plain_style_keeps_meaning_and_literal_quotes(polite, plain):
    assert plain_style(polite) == plain
    assert not has_polite_ending(plain)
    assert plain_style(plain) == plain


def test_table_and_writer_use_plain_style_without_changing_evidence():
    package = example_package()
    fact = package.facts[2].model_copy(update={"value": "LTEを利用できます。"})
    assert fact_text(fact) == "開発元によると、LTEを利用できる。"
    assert fact.value == "LTEを利用できます。"
    assert not has_polite_ending(render_comparison_table(package))
    output = WritingOutputV1(
        title="仕様の比較",
        lead="仕様を整理します。",
        paragraphs=({"text": "価格は1,000円です。", "fact_ids": (uuid4(),)},),
        category_keys=("iot_platform",),
        importance=3,
    )
    normalized = normalize_writing_style(output)
    assert normalized.lead == "仕様を整理する。"
    assert normalized.paragraphs[0].text == "価格は1,000円である。"
    assert normalized.paragraphs[0].fact_ids == output.paragraphs[0].fact_ids


def test_future_article_style_is_consistent_and_mixed_style_is_rejected(acquisition_session):
    session = acquisition_session
    target, previous, competitor = seed_articles(session)
    service = prepared_root(session, target)
    service.facts(previous.id)
    service.facts(competitor.id)
    service.comparison(target.id, (previous.id,), (competitor.id,), request_missing=False)
    draft = service.draft(target.id)
    _, package = service.package(target)
    dto = ArticleDraftV1.model_validate(draft.source_block["draft"])
    assert not has_polite_ending(dto.lead + dto.body_markdown)
    assert service.verify(draft.id).overall_result == "pass"
    changed = dto.model_copy(update={"lead": dto.lead + "仕様を紹介します。"})
    criteria = {c.key: c.result for c in rule_criteria(changed, package)}
    assert criteria["editorial_conciseness"] == "fail"
