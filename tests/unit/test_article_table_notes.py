from uuid import uuid4

import pytest

from app.contracts.article_package_v1 import ArticlePackageV1, SourceReferenceV1
from app.contracts.facts_v1 import VerifiedFactV1
from app.core.article_tables import UNKNOWN, render_comparison_table


@pytest.mark.parametrize("missing_price", [None, 0, 1])
def test_unknown_note_is_shown_only_when_comparison_table_has_unknown_cells(missing_price):
    facts, references = [], []
    for index, product in enumerate(("Alpha", "Beta")):
        evidence_id = uuid4()
        source_facts = [
            VerifiedFactV1(
                fact_id=uuid4(),
                evidence_id=evidence_id,
                fact_type="product",
                subject=product,
                predicate="name",
                value=product,
            ),
        ]
        if index != missing_price:
            source_facts.append(
                VerifiedFactV1(
                    fact_id=uuid4(),
                    evidence_id=evidence_id,
                    fact_type="price",
                    subject=product,
                    predicate="price",
                    value="1,000円",
                ),
            )
        facts.extend(source_facts)
        references.append(
            SourceReferenceV1(
                url=f"https://vendor.example/{index}",
                reference_id=evidence_id,
                fact_ids=tuple(f.fact_id for f in source_facts),
            ),
        )
    package = ArticlePackageV1(
        item_id=uuid4(),
        revision=1,
        topic="比較",
        comparison_dataset_id=uuid4(),
        writing_policy_version="writing-v6",
        facts=tuple(facts),
        verified_fact_ids=tuple(f.fact_id for f in facts),
        source_references=tuple(references),
    )
    table = render_comparison_table(package)
    cells = "\n".join(line for line in table.splitlines() if line.startswith("|"))
    note = f"「{UNKNOWN}」は非対応を意味しない。"
    assert (UNKNOWN in cells) == (missing_price is not None)
    assert (note in table) == (missing_price is not None)
    assert "記載された条件での比較であり、性能や価格の優劣を示すものではない。" in table
