# ruff: noqa: RUF001
"""One orchestration path for latest → embed → cluster → select → generate → verify."""

import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clustering import cluster, selection_candidates
from app.model_client import (
    GENERATION_SCHEMA,
    SELECTION_SCHEMA,
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
    lines = markdown.strip().splitlines()
    return lines[0].lstrip("# ").strip() if lines else ""


def validate_selection(result: dict, candidates: list[str]) -> None:
    validate_result(result, SELECTION_SCHEMA)
    primary, reserve = result["primary_article_ids"], result["reserve_article_ids"]
    expected = {"TWO_SETS": (3, 3), "ONE_SET": (3, 0), "NO_SET": (0, 0)}
    if (len(primary), len(reserve)) != expected[result["selection_status"]]:
        raise ValueError("SELECTION_STATUS_MISMATCH")
    if not result["reason"].strip():
        raise ValueError("EMPTY_SELECTION_REASON")
    for ids in (primary, reserve):
        if len(set(ids)) != len(ids) or not set(ids) <= set(candidates):
            raise ValueError("INVALID_SELECTION_ARTICLES")
    if reserve and set(primary) == set(reserve):
        raise ValueError("DUPLICATE_SELECTION_SETS")


def apply_generation(draft: Draft, result: dict) -> None:
    validate_result(result, GENERATION_SCHEMA)
    status, text = result["status"], result["article_markdown"]
    if not result["reason"].strip():
        raise ValueError("EMPTY_GENERATION_REASON")
    if status == "APPROPRIATE":
        if not text.strip():
            raise ValueError("EMPTY_ARTICLE")
        if article_mark(text) == "比較不適（公開不可）":
            raise ValueError("GENERATION_STATUS_MISMATCH")
    elif text.strip():
        raise ValueError("INAPPROPRIATE_HAS_ARTICLE")
    draft.generation_status = status
    draft.generation_reason = result["reason"]
    draft.markdown = text


class Pipeline:
    def __init__(self, session: Session, provider, clusterer=cluster):
        self.session, self.provider, self.clusterer = session, provider, clusterer

    def start(self, settings: Settings) -> Run:
        record = settings.record()
        record["prompts"] = {
            name: (prompt_dir() / (name + ".txt")).read_text(encoding="utf-8")
            for name in ("selection", "generation", "verification")
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
        if draft.generation_status != "INAPPROPRIATE":
            return None
        result = self.session.get(Verification, draft.id)
        if result is None:
            result = Verification(
                draft_id=draft.id,
                status="ineligible",
                score=None,
                reason="生成時にINAPPROPRIATEと判定。評価モデルは未実行。"
                + (draft.generation_reason or ""),
            )
            self.session.add(result)
        return result

    def evaluate(self, draft: Draft, articles: list[Article], settings, prompts) -> Verification:
        result = self.session.get(Verification, draft.id)
        if result is not None:
            return result
        result = self.reject_marked(draft)
        if result is None:
            if draft.generation_status != "APPROPRIATE":
                raise ValueError("GENERATION_STATUS_REQUIRED_FOR_VERIFICATION")
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
        if not comparison.source_ids():
            return
        role = self.active_role(comparison)
        drafts = list(
            self.session.scalars(
                select(Draft)
                .where(Draft.comparison_id == comparison.id, Draft.set_role == role)
                .order_by(Draft.revision)
            )
        )
        initial = drafts[0]
        articles = [self.session.get(Article, i) for i in comparison.source_ids(role)]
        verdict = self.evaluate(initial, articles, settings, prompts)
        if verdict.status == "eligible" or initial.generation_status == "INAPPROPRIATE":
            return
        if len(drafts) == 1:
            # Persist the only repair slot before sending the request. An uncertain
            # outcome must never cause resume to send a second repair request.
            revised = Draft(comparison_id=comparison.id, set_role=role, revision=1, markdown=None)
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
            apply_generation(revised, output)
            self.reject_marked(revised)
            self.session.commit()
        else:
            revised = drafts[1]
            if revised.markdown is None:
                raise ValueError("REPAIR_RESULT_UNAVAILABLE")
        # This result is final regardless of status. There is no further repair.
        self.evaluate(revised, articles, settings, prompts)

    def initial(self, comparison: Comparison, role: str) -> Draft | None:
        return self.session.scalar(
            select(Draft).where(
                Draft.comparison_id == comparison.id, Draft.set_role == role, Draft.revision == 0
            )
        )

    def active_role(self, comparison: Comparison) -> str:
        primary = self.initial(comparison, "PRIMARY")
        if (
            primary is not None
            and primary.generation_status == "INAPPROPRIATE"
            and comparison.source_ids("RESERVE")
        ):
            return "RESERVE"
        return "PRIMARY"

    def generate_comparison(self, comparison: Comparison, settings, prompts) -> None:
        for role in ("PRIMARY", "RESERVE"):
            ids = comparison.source_ids(role)
            if not ids:
                break
            draft = self.initial(comparison, role)
            if draft is None:
                articles = [self.session.get(Article, i) for i in ids]
                result = self.provider.complete(
                    settings.generation_model,
                    prompts["generation"],
                    {"sources": sources(articles)},
                    GENERATION_SCHEMA,
                )
                draft = Draft(comparison_id=comparison.id, set_role=role)
                apply_generation(draft, result)
                self.session.add(draft)
                self.session.flush()
                self.reject_marked(draft)
                self.session.commit()
            if draft.generation_status == "APPROPRIATE":
                break

    def process(self, run_id: str, *, stop_after: str | None = None) -> Run:
        if stop_after not in (None, "select"):
            raise ValueError("INVALID_STOP_STAGE")
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
                    ids = selection_candidates(candidates, settings.selection_candidate_limit)
                    if not ids:
                        continue
                    articles = [self.session.get(Article, i) for i in ids]
                    selection = self.provider.complete(
                        settings.selection_model,
                        prompts["selection"],
                        {
                            "cluster_id": label,
                            "candidates": [
                                {"article_id": a.id, "centroid_rank": rank, **sources([a])[0]}
                                for rank, a in enumerate(articles, 1)
                            ],
                        },
                        SELECTION_SCHEMA,
                    )
                    validate_selection(selection, ids)
                    primary = selection["primary_article_ids"] or [None] * 3
                    reserve = selection["reserve_article_ids"] or [None] * 3
                    self.session.add(
                        Comparison(
                            run_id=run.id,
                            cluster_id=label,
                            source1=primary[0],
                            source2=primary[1],
                            source3=primary[2],
                            reserve1=reserve[0],
                            reserve2=reserve[1],
                            reserve3=reserve[2],
                            candidate_article_ids=ids,
                            selection_result=selection,
                        )
                    )
                    self.session.commit()
                run.step = "generate"
                self.session.commit()
            if stop_after == "select" and run.step == "generate":
                run.error = None
                self.session.commit()
                return run
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
                    self.generate_comparison(comparison, settings, prompts)
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
        for comparison in self.session.scalars(
            select(Comparison).where(Comparison.run_id == run_id).order_by(Comparison.cluster_id)
        ):
            role = self.active_role(comparison)
            attempts = list(
                self.session.scalars(
                    select(Draft)
                    .where(Draft.comparison_id == comparison.id)
                    .order_by(Draft.set_role, Draft.revision)
                )
            )
            active = [d for d in attempts if d.set_role == role]
            draft = active[-1] if active else None
            verification = self.session.get(Verification, draft.id) if draft else None
            filename = None
            report = None
            if draft and draft.markdown and draft.generation_status == "APPROPRIATE":
                filename = f"cluster-{comparison.cluster_id}.md"
                (output / filename).write_text(draft.markdown, encoding="utf-8")
            elif draft and draft.generation_status == "INAPPROPRIATE":
                report = f"cluster-{comparison.cluster_id}-inappropriate.md"
                (output / report).write_text(
                    "# 比較不適（公開不可）\n\n" + draft.generation_reason, encoding="utf-8"
                )
            final = (
                draft is not None
                and verification is not None
                and (
                    draft.revision == 1
                    or verification.status == "eligible"
                    or draft.generation_status == "INAPPROPRIATE"
                )
            )
            no_set = comparison.selection_result["selection_status"] == "NO_SET"
            rows.append(
                {
                    "comparison_id": comparison.id,
                    "cluster_id": comparison.cluster_id,
                    "selection": comparison.selection_result,
                    "candidate_article_ids": comparison.candidate_article_ids,
                    "set_role": role,
                    "revision": draft.revision if draft else None,
                    "article": filename,
                    "inappropriate_report": report,
                    "sources": comparison.source_ids(role),
                    "generation_status": draft.generation_status if draft else None,
                    "status": "not_selected" if no_set else verification.status if final else None,
                    "score": verification.score if final else None,
                    "reason": comparison.selection_result["reason"]
                    if no_set
                    else verification.reason
                    if final
                    else None,
                    "attempts": [
                        {
                            "set_role": d.set_role,
                            "revision": d.revision,
                            "generation_status": d.generation_status,
                            "generation_reason": d.generation_reason,
                            "sources": comparison.source_ids(d.set_role),
                        }
                        for d in attempts
                    ],
                }
            )
        result = {"run_id": run_id, "articles": rows}
        (output / "results.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return result
