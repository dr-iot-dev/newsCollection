# ruff: noqa: RUF001
"""One orchestration path for latest → embed → cluster → select → generate → verify."""

import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clustering import cluster, select_three
from app.model_client import (
    GENERATION_SCHEMA,
    VERIFICATION_SCHEMA,
    validate_result,
)
from app.models import Article, Comparison, Draft, Run, RunArticle, Verification
from app.settings import Settings, prompt_dir


def sources(articles: list[Article]) -> list[dict]:
    return [
        {
            "title": a.title,
            "url": a.url,
            "published_at": a.published_at,
            "text": a.body,
        }
        for a in articles
    ]


def article_mark(markdown: str) -> str:
    return markdown.strip().splitlines()[0].lstrip("# ").strip()


class Pipeline:
    def __init__(self, session: Session, provider, clusterer=cluster):
        self.session, self.provider, self.clusterer = session, provider, clusterer

    def start(self, settings: Settings) -> Run:
        record = settings.record()
        record["prompts"] = {
            name: (prompt_dir() / (name + ".txt")).read_text(encoding="utf-8")
            for name in ("generation", "verification")
        }
        run = Run(settings=record)
        self.session.add(run)
        self.session.flush()
        winners = {}
        for article in self.session.scalars(select(Article)):
            key = (
                datetime.fromisoformat(article.published_at),
                article.release_id,
                article.url,
                datetime.fromisoformat(article.fetched_at),
                article.id,
            )
            if article.company_id not in winners or key > winners[article.company_id][0]:
                winners[article.company_id] = (key, article)
        for _, article in winners.values():
            self.session.add(RunArticle(run_id=run.id, article_id=article.id))
        if not winners:
            raise ValueError("NO_ELIGIBLE_ARTICLES")
        run.step = "embed"
        self.session.commit()
        return run

    def members(self, run: Run) -> list[tuple[RunArticle, Article]]:
        return list(
            self.session.execute(
                select(RunArticle, Article)
                .join(
                    Article,
                    RunArticle.article_id == Article.id,
                )
                .where(RunArticle.run_id == run.id)
                .order_by(Article.id)
            ).all()
        )

    def reject_marked(self, draft: Draft) -> Verification | None:
        if draft.markdown is None or article_mark(draft.markdown) != "比較不適（公開不可）":
            return None
        result = self.session.get(Verification, draft.id)
        if result is None:
            result = Verification(
                draft_id=draft.id,
                status="ineligible",
                score=None,
                reason="生成本文が比較不適（公開不可）を明示したため不適で確定。評価モデルは未実行。",
            )
            self.session.add(result)
        return result

    def evaluate(self, draft: Draft, articles: list[Article], settings, prompts) -> Verification:
        result = self.session.get(Verification, draft.id)
        if result is not None:
            return result
        result = self.reject_marked(draft)
        if result is None:
            output = self.provider.complete(
                settings.verification_model,
                prompts["verification"],
                {
                    "article_markdown": draft.markdown,
                    "sources": sources(articles),
                    "generation_instructions": prompts["generation"],
                },
                VERIFICATION_SCHEMA,
            )
            validate_result(output, VERIFICATION_SCHEMA)
            if (
                article_mark(draft.markdown) == "要確認（公開不可）"
                and output["status"] == "eligible"
            ):
                raise ValueError("VERDICT_CONTRADICTS_ARTICLE_MARK")
            result = Verification(draft_id=draft.id, **output)
            self.session.add(result)
        self.session.commit()
        return result

    def verify_comparison(self, comparison: Comparison, settings, prompts) -> None:
        drafts = list(
            self.session.scalars(
                select(Draft).where(Draft.comparison_id == comparison.id).order_by(Draft.revision)
            )
        )
        initial = drafts[0]
        articles = [
            self.session.get(Article, i)
            for i in (comparison.source1, comparison.source2, comparison.source3)
        ]
        verdict = self.evaluate(initial, articles, settings, prompts)
        if verdict.status == "eligible" or article_mark(initial.markdown) == "比較不適（公開不可）":
            return
        if len(drafts) == 1:
            # Persist the only repair slot before sending the request. An uncertain
            # outcome must never cause resume to send a second repair request.
            revised = Draft(comparison_id=comparison.id, revision=1, markdown=None)
            self.session.add(revised)
            self.session.commit()
            output = self.provider.complete(
                settings.generation_model,
                prompts["generation"],
                {
                    "sources": sources(articles),
                    "article_markdown": initial.markdown,
                    "feedback": verdict.reason,
                },
                GENERATION_SCHEMA,
            )
            validate_result(output, GENERATION_SCHEMA)
            if not output["article_markdown"].strip():
                raise ValueError("EMPTY_ARTICLE")
            revised.markdown = output["article_markdown"]
            self.reject_marked(revised)
            self.session.commit()
        else:
            revised = drafts[1]
            if revised.markdown is None:
                raise ValueError("REPAIR_RESULT_UNAVAILABLE")
        # This result is final regardless of status. There is no further repair.
        self.evaluate(revised, articles, settings, prompts)

    def process(self, run_id: str) -> Run:
        run = self.session.get(Run, run_id)
        if run is None:
            raise ValueError("RUN_NOT_FOUND")
        parameters = {k: v for k, v in run.settings.items() if k != "prompts"}
        settings = Settings(**parameters)
        settings.validate()
        prompts = run.settings["prompts"]
        try:
            if run.step == "embed":
                for row, article in self.members(run):
                    if row.embedding is not None:
                        continue
                    values = self.provider.embed(
                        settings.embedding_model, [article.title + "\n\n" + article.body]
                    )
                    if (
                        len(values) != 1
                        or len(values[0]) < 2
                        or not all(math.isfinite(x) for x in values[0])
                        or not any(values[0])
                    ):
                        raise ValueError("EMBEDDING_INVALID")
                    row.embedding = values[0]
                    self.session.commit()
                run.step = "cluster"
                self.session.commit()
            if run.step == "cluster":
                members = self.members(run)
                labels = self.clusterer([r.embedding for r, _ in members], settings)
                if len(labels) != len(members) or any(type(x) is not int or x < -1 for x in labels):
                    raise ValueError("INVALID_CLUSTER_LABELS")
                for (row, _), label in zip(members, labels, strict=True):
                    row.cluster_id = label
                run.step = "select"
                self.session.commit()
            if run.step == "select":
                groups = defaultdict(list)
                for row, article in self.members(run):
                    if row.cluster_id >= 0:
                        groups[row.cluster_id].append((article.id, article.url, row.embedding))
                existing = {
                    c.cluster_id
                    for c in self.session.scalars(
                        select(Comparison).where(
                            Comparison.run_id == run.id,
                        )
                    )
                }
                for label, candidates in sorted(groups.items()):
                    if label in existing:
                        continue
                    ids = select_three(candidates)
                    if not ids:
                        continue
                    self.session.add(
                        Comparison(
                            run_id=run.id,
                            cluster_id=label,
                            source1=ids[0],
                            source2=ids[1],
                            source3=ids[2],
                        )
                    )
                    self.session.commit()
                run.step = "generate"
                self.session.commit()
            comparisons = list(
                self.session.scalars(
                    select(Comparison)
                    .where(
                        Comparison.run_id == run.id,
                    )
                    .order_by(Comparison.cluster_id)
                )
            )
            if run.step == "generate":
                for comparison in comparisons:
                    if self.session.scalar(
                        select(Draft).where(
                            Draft.comparison_id == comparison.id, Draft.revision == 0
                        )
                    ):
                        continue
                    articles = [
                        self.session.get(Article, i)
                        for i in (
                            comparison.source1,
                            comparison.source2,
                            comparison.source3,
                        )
                    ]
                    result = self.provider.complete(
                        settings.generation_model,
                        prompts["generation"],
                        {"sources": sources(articles)},
                        GENERATION_SCHEMA,
                    )
                    validate_result(result, GENERATION_SCHEMA)
                    if not result["article_markdown"].strip():
                        raise ValueError("EMPTY_ARTICLE")
                    draft = Draft(comparison_id=comparison.id, markdown=result["article_markdown"])
                    self.session.add(draft)
                    self.session.flush()
                    self.reject_marked(draft)
                    self.session.commit()
                run.step = "verify"
                self.session.commit()
            if run.step == "verify":
                for comparison in comparisons:
                    self.verify_comparison(comparison, settings, prompts)
                run.step = "complete"
            run.error = None
            self.session.commit()
        except Exception as exc:
            self.session.rollback()
            # Do not persist HTTP response bodies or potentially credential-bearing messages.
            run.error = type(exc).__name__
            self.session.commit()
            raise
        return run

    def export(self, run_id: str, output: Path) -> dict:
        output.mkdir(parents=True, exist_ok=True)
        rows = []
        latest = {}
        for comparison, draft, verification in self.session.execute(
            select(Comparison, Draft, Verification)
            .join(Draft, Draft.comparison_id == Comparison.id)
            .outerjoin(Verification, Verification.draft_id == Draft.id)
            .where(Comparison.run_id == run_id)
            .order_by(Comparison.cluster_id, Draft.revision)
        ):
            latest[comparison.id] = (comparison, draft, verification)
        for comparison, draft, verification in latest.values():
            filename = None
            if draft.markdown is not None:
                filename = f"cluster-{comparison.cluster_id}.md"
                (output / filename).write_text(draft.markdown, encoding="utf-8")
            final = verification is not None and (
                draft.revision == 1
                or verification.status == "eligible"
                or article_mark(draft.markdown) == "比較不適（公開不可）"
            )
            rows.append(
                {
                    "comparison_id": comparison.id,
                    "revision": draft.revision,
                    "article": filename,
                    "sources": [comparison.source1, comparison.source2, comparison.source3],
                    "status": verification.status if final else None,
                    "score": verification.score if final else None,
                    "reason": verification.reason if final else None,
                }
            )
        result = {"run_id": run_id, "articles": rows}
        (output / "results.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return result
