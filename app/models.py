"""The six persistence tables used by the seven-stage pipeline."""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def identifier() -> str:
    return str(uuid4())


def now() -> str:
    return datetime.now(UTC).isoformat()


class Base(DeclarativeBase):
    pass


class Article(Base):
    __tablename__ = "articles"
    __table_args__ = (
        UniqueConstraint("url", "snapshot_hash"),
        CheckConstraint("release_type = '01'"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    url: Mapped[str]
    company_id: Mapped[str] = mapped_column(index=True)
    company_name: Mapped[str]
    release_id: Mapped[int]
    published_at: Mapped[str]
    title: Mapped[str]
    body: Mapped[str]
    domains: Mapped[list[str]] = mapped_column(JSON)
    release_type: Mapped[str] = mapped_column(default="01")
    raw_html: Mapped[str]
    snapshot_hash: Mapped[str]
    fetched_at: Mapped[str] = mapped_column(default=now)


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    created_at: Mapped[str] = mapped_column(default=now)
    step: Mapped[str] = mapped_column(default="latest")
    error: Mapped[str | None]
    settings: Mapped[dict[str, Any]] = mapped_column(JSON)


class RunArticle(Base):
    __tablename__ = "run_articles"
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), primary_key=True)
    article_id: Mapped[str] = mapped_column(ForeignKey("articles.id"), primary_key=True)
    embedding: Mapped[list[float] | None] = mapped_column(JSON)
    cluster_id: Mapped[int | None]


class Comparison(Base):
    __tablename__ = "comparisons"
    __table_args__ = (
        UniqueConstraint("run_id", "cluster_id"),
        CheckConstraint("cluster_id >= 0"),
        CheckConstraint("source1 <> source2 AND source1 <> source3 AND source2 <> source3"),
        *(
            ForeignKeyConstraint(
                ["run_id", field], ["run_articles.run_id", "run_articles.article_id"]
            )
            for field in ("source1", "source2", "source3")
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"))
    cluster_id: Mapped[int]
    source1: Mapped[str]
    source2: Mapped[str]
    source3: Mapped[str]


class Draft(Base):
    __tablename__ = "drafts"
    __table_args__ = (
        UniqueConstraint("comparison_id", "revision"),
        CheckConstraint("revision IN (0, 1)"),
        CheckConstraint("revision = 1 OR markdown IS NOT NULL"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    comparison_id: Mapped[str] = mapped_column(ForeignKey("comparisons.id"))
    revision: Mapped[int] = mapped_column(default=0)
    # A reserved repair has no text until its one generation request succeeds.
    markdown: Mapped[str | None]
    created_at: Mapped[str] = mapped_column(default=now)


class Verification(Base):
    __tablename__ = "verifications"
    __table_args__ = (
        CheckConstraint("status IN ('eligible', 'ineligible', 'needs_confirmation')"),
        CheckConstraint("score BETWEEN 0 AND 100"),
    )
    draft_id: Mapped[str] = mapped_column(ForeignKey("drafts.id"), primary_key=True)
    status: Mapped[str]
    # No model score is invented when the generation itself rejects the comparison.
    score: Mapped[int | None]
    reason: Mapped[str]
    created_at: Mapped[str] = mapped_column(default=now)
