"""Write only from a supplied, self-contained article package."""

from typing import Any
from uuid import UUID, uuid5

from app.contracts.draft_v1 import ArticleDraftV1, ParagraphFactMapV1
from app.contracts.editorial_v1 import WritingOutputV1
from app.core.article_tables import (
    COMPARISON_PROSE_HEADING,
    render_comparison_table,
    render_source_list,
)
from app.modules.writing.service import normalize_writing_style, render_comparison, validate_writing

from ..common import Context, Outcome, StageInput, output, package_input, require_sources
from ..protocol import NAMESPACE, object_hash


def run(inputs: dict[str, StageInput], parameters: dict[str, Any], context: Context) -> Outcome:
    package, source = package_input(inputs)
    require_sources(package, int(parameters.get("minimum_sources", 3)))
    if parameters.get("article_id") and parameters["article_id"] != str(package.item_id):
        from ..protocol import ProtocolError

        raise ProtocolError("ARTICLE_SCOPE_MISMATCH")
    if "writing" in inputs:
        writing = WritingOutputV1.model_validate(inputs["writing"].payload)
        record = {"role": "writer", "model": "manual", "provider": "manual"}
    else:
        writing = context.generate(
            "writer", {"package": package.model_dump(mode="json")}, WritingOutputV1
        )
        record = context.records[-1]
    writing = normalize_writing_style(writing)
    validate_writing(writing, package)
    revision = int(parameters.get("revision", 1))
    identity = [str(package.item_id), object_hash(source["package"]), revision]
    draft_id = (
        UUID(parameters["draft_id"])
        if parameters.get("draft_id")
        else uuid5(NAMESPACE, str(identity))
    )
    body = render_comparison_table(package)
    if body:
        body += "\n\n" + COMPARISON_PROSE_HEADING
    body += "\n\n" + "\n\n".join(paragraph.text for paragraph in writing.paragraphs)
    body += render_comparison(writing, package)
    body += "\n\n## 出典\n\n" + render_source_list(package)
    draft = ArticleDraftV1(
        draft_id=draft_id,
        item_id=package.item_id,
        article_package_id=UUID(source["article_package_id"]),
        revision=revision,
        title=writing.title,
        lead=writing.lead,
        body_markdown=body,
        category_keys=writing.category_keys,
        risk_flags=writing.risk_flags,
        paragraph_facts=tuple(
            ParagraphFactMapV1(paragraph=i, fact_ids=p.fact_ids)
            for i, p in enumerate(writing.paragraphs)
        ),
        writer_profile_key=record["model"],
    )
    return output(
        "draft",
        "ArticleDraftV1",
        {
            "draft": draft.model_dump(mode="json"),
            "package_hash": object_hash(source["package"]),
            "writer": record,
            "created_at": source["created_at"],
            "provenance": source.get("provenance", []),
            "mode": source.get("mode", "production"),
        },
    )
