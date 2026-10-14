"""Persistent corpus and SQL candidate counts, separate from content/claim extraction."""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self

from app.contracts.discovery_search_vocabulary_v2 import (
    DiscoveryArticle,
    DiscoverySearchVocabularyV2,
    normalized_text,
)
from app.contracts.envelope import canonical_payload_hash
from app.core.discovery_search_vocabulary import term_matches
from app.core.term_extraction import (
    DOMAIN_FILTER_POLICY,
    DOMAIN_LEAD_CHARS,
    TITLE_FILTER_POLICY,
    article_domain_terms,
    title_exclusion_terms,
    title_is_excluded,
)


class TermCorpusStore:
    def __init__(self, database: Path) -> None:
        database.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(database, timeout=30)
        self.connection.row_factory = sqlite3.Row
        self.connection.create_function("phrase_match", 2, term_matches, deterministic=True)
        self.connection.create_function(
            "title_is_excluded", 1, title_is_excluded, deterministic=True
        )
        self.connection.create_function(
            "title_exclusion_json",
            1,
            lambda title: json.dumps(title_exclusion_terms(title), ensure_ascii=False),
            deterministic=True,
        )
        self.connection.create_function(
            "current_domain_policy", 0, lambda: DOMAIN_FILTER_POLICY, deterministic=True
        )
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS term_corpora (
                corpus_id TEXT PRIMARY KEY, domain_label TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS term_articles (
                corpus_id TEXT NOT NULL, article_id TEXT NOT NULL, url TEXT NOT NULL,
                title TEXT NOT NULL, body TEXT NOT NULL,
                normalized_title TEXT NOT NULL, normalized_body TEXT NOT NULL,
                content_hash TEXT NOT NULL, imported_at TEXT NOT NULL,
                PRIMARY KEY (corpus_id, article_id)
            );
            CREATE TABLE IF NOT EXISTS term_title_exclusions (
                corpus_id TEXT NOT NULL, article_id TEXT NOT NULL, url TEXT NOT NULL,
                title TEXT NOT NULL, matched_terms_json TEXT NOT NULL,
                policy TEXT NOT NULL, screened_at TEXT NOT NULL,
                PRIMARY KEY (corpus_id, article_id)
            );
            CREATE TABLE IF NOT EXISTS term_domain_screenings (
                corpus_id TEXT NOT NULL, article_id TEXT NOT NULL, url TEXT NOT NULL,
                title TEXT NOT NULL, domains_json TEXT NOT NULL, matched_terms_json TEXT NOT NULL,
                policy TEXT NOT NULL, screened_at TEXT NOT NULL,
                PRIMARY KEY (corpus_id, article_id)
            );
            CREATE TABLE IF NOT EXISTS term_vocabularies (
                vocabulary_hash TEXT PRIMARY KEY, payload_json TEXT NOT NULL,
                imported_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS term_candidates (
                vocabulary_hash TEXT NOT NULL, concept_id TEXT NOT NULL,
                label TEXT NOT NULL, layer TEXT NOT NULL, priority TEXT NOT NULL,
                term TEXT NOT NULL, normalized_term TEXT NOT NULL,
                PRIMARY KEY (vocabulary_hash, concept_id, term)
            );
        """)
        columns = {row[1] for row in self.connection.execute("PRAGMA table_info(term_articles)")}
        if "title_excluded" not in columns:
            self.connection.execute(
                "ALTER TABLE term_articles ADD COLUMN title_excluded INTEGER NOT NULL DEFAULT 0"
            )
        if "title_exclusion_terms" not in columns:
            self.connection.execute(
                "ALTER TABLE term_articles ADD COLUMN title_exclusion_terms "
                "TEXT NOT NULL DEFAULT '[]'"
            )
        if "title_filter_policy" not in columns:
            self.connection.execute(
                "ALTER TABLE term_articles ADD COLUMN title_filter_policy TEXT NOT NULL DEFAULT ''"
            )
        for name, declaration in (
            ("domain_eligible", "INTEGER NOT NULL DEFAULT 0"),
            ("matched_domains", "TEXT NOT NULL DEFAULT '[]'"),
            ("domain_filter_policy", "TEXT NOT NULL DEFAULT ''"),
            ("release_type_excluded", "INTEGER NOT NULL DEFAULT 0"),
        ):
            if name not in columns:
                self.connection.execute(
                    f"ALTER TABLE term_articles ADD COLUMN {name} {declaration}"
                )
        corpus_columns = {
            row[1] for row in self.connection.execute("PRAGMA table_info(term_corpora)")
        }
        if "require_product_service" not in corpus_columns:
            self.connection.execute(
                "ALTER TABLE term_corpora ADD COLUMN "
                "require_product_service INTEGER NOT NULL DEFAULT 0"
            )
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS term_release_type_screenings (
                corpus_id TEXT NOT NULL,article_id TEXT NOT NULL,url TEXT NOT NULL,
                title TEXT NOT NULL,release_type_id TEXT NOT NULL,release_type_name TEXT NOT NULL,
                source_hash TEXT NOT NULL,screened_at TEXT NOT NULL,
                PRIMARY KEY(corpus_id,article_id)
            );
        """)
        self.refresh_release_type_filter()
        self.refresh_title_filter()
        self.refresh_domain_filter()

    def refresh_release_type_filter(self) -> None:
        self.connection.execute("""
            UPDATE term_articles AS a SET release_type_excluded=CASE
                WHEN (SELECT require_product_service FROM term_corpora c
                      WHERE c.corpus_id=a.corpus_id)=1 THEN NOT EXISTS (
                    SELECT 1 FROM term_release_type_screenings s
                    WHERE s.corpus_id=a.corpus_id AND s.article_id=a.article_id
                    AND s.release_type_id='01' AND s.release_type_name='商品サービス'
                ) ELSE 0 END
        """)
        self.connection.commit()

    def require_product_service(self, corpus_id: str) -> None:
        self.connection.execute(
            "UPDATE term_corpora SET require_product_service=1 WHERE corpus_id=?", (corpus_id,)
        )
        self.refresh_release_type_filter()

    def record_release_type(
        self,
        corpus_id: str,
        article_id: str,
        title: str,
        url: str,
        release_type: tuple[str, str] | None,
        source_hash: str,
    ) -> None:
        type_id, type_name = release_type or ("", "")
        self.connection.execute(
            "INSERT INTO term_release_type_screenings VALUES (?,?,?,?,?,?,?,?) "
            "ON CONFLICT(corpus_id,article_id) DO UPDATE SET "
            "url=excluded.url,title=excluded.title,release_type_id=excluded.release_type_id,"
            "release_type_name=excluded.release_type_name,source_hash=excluded.source_hash,"
            "screened_at=excluded.screened_at",
            (
                corpus_id,
                article_id,
                url,
                title,
                type_id,
                type_name,
                source_hash,
                datetime.now(UTC).isoformat(),
            ),
        )
        required = self.connection.execute(
            "SELECT require_product_service FROM term_corpora WHERE corpus_id=?", (corpus_id,)
        ).fetchone()
        self.connection.execute(
            "UPDATE term_articles SET release_type_excluded=? WHERE corpus_id=? AND article_id=?",
            (
                int(bool(required and required[0]) and release_type != ("01", "商品サービス")),
                corpus_id,
                article_id,
            ),
        )
        self.connection.commit()

    def refresh_title_filter(self) -> None:
        """Classify legacy stored titles without reading or deleting article bodies."""
        self.connection.execute(
            "UPDATE term_articles SET title_excluded=title_is_excluded(title), "
            "title_exclusion_terms=title_exclusion_json(title), title_filter_policy=? "
            "WHERE title_filter_policy<>?",
            (TITLE_FILTER_POLICY, TITLE_FILTER_POLICY),
        )
        self.connection.execute(
            "UPDATE term_title_exclusions SET matched_terms_json=title_exclusion_json(title), "
            "policy=?,screened_at=? WHERE policy<>?",
            (TITLE_FILTER_POLICY, datetime.now(UTC).isoformat(), TITLE_FILTER_POLICY),
        )
        self.connection.execute(
            "INSERT INTO term_title_exclusions "
            "SELECT corpus_id,article_id,url,title,title_exclusion_terms,title_filter_policy,? "
            "FROM term_articles WHERE title_excluded=1 "
            "ON CONFLICT(corpus_id,article_id) DO NOTHING",
            (datetime.now(UTC).isoformat(),),
        )
        self.connection.execute(
            "UPDATE term_articles AS a SET title_excluded=1,title_exclusion_terms="
            "(SELECT x.matched_terms_json FROM term_title_exclusions x "
            "WHERE x.corpus_id=a.corpus_id AND x.article_id=a.article_id),title_filter_policy=? "
            "WHERE EXISTS (SELECT 1 FROM term_title_exclusions x "
            "WHERE x.corpus_id=a.corpus_id AND x.article_id=a.article_id)",
            (TITLE_FILTER_POLICY,),
        )
        self.connection.commit()

    def refresh_domain_filter(self) -> None:
        rows = self.connection.execute(
            "SELECT corpus_id,article_id,title,substr(body,1,?),url FROM term_articles a "
            "WHERE title_excluded=0 AND release_type_excluded=0 AND domain_filter_policy<>? "
            "AND NOT EXISTS (SELECT 1 FROM term_title_exclusions x "
            "WHERE x.corpus_id=a.corpus_id AND x.article_id=a.article_id)",
            (DOMAIN_LEAD_CHARS, DOMAIN_FILTER_POLICY),
        ).fetchall()
        for row in rows:
            self.record_domain_screening(row[0], row[1], row[2], row[3], row[4])

    def record_domain_screening(
        self, corpus_id: str, article_id: str, title: str, body: str = "", url: str = ""
    ) -> tuple[str, ...]:
        terms = article_domain_terms(title, body)
        domains = tuple(terms)
        domains_json = json.dumps(domains, ensure_ascii=False)
        self.connection.execute(
            "INSERT INTO term_domain_screenings VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(corpus_id,article_id) DO UPDATE SET "
            "url=excluded.url,title=excluded.title,domains_json=excluded.domains_json,"
            "matched_terms_json=excluded.matched_terms_json,policy=excluded.policy,"
            "screened_at=excluded.screened_at",
            (
                corpus_id,
                article_id,
                url,
                title,
                domains_json,
                json.dumps(terms, ensure_ascii=False),
                DOMAIN_FILTER_POLICY,
                datetime.now(UTC).isoformat(),
            ),
        )
        self.connection.execute(
            "UPDATE term_articles SET domain_eligible=?,matched_domains=?,domain_filter_policy=? "
            "WHERE corpus_id=? AND article_id=?",
            (int(bool(domains)), domains_json, DOMAIN_FILTER_POLICY, corpus_id, article_id),
        )
        self.connection.commit()
        return domains

    def domain_screenings(self, corpus_id: str) -> list[dict[str, Any]]:
        rows = [
            dict(row)
            for row in self.connection.execute(
                "SELECT article_id,url,title,domains_json,matched_terms_json,policy "
                "FROM term_domain_screenings WHERE corpus_id=? ORDER BY article_id",
                (corpus_id,),
            )
        ]
        for row in rows:
            row["domains"] = json.loads(row.pop("domains_json"))
            row["matched_domain_terms"] = json.loads(row.pop("matched_terms_json"))
        return rows

    def record_title_exclusion(
        self, corpus_id: str, article_id: str, title: str, url: str = ""
    ) -> None:
        terms = title_exclusion_terms(title)
        if not terms:
            raise ValueError("title does not match the exclusion policy")
        terms_json = json.dumps(terms, ensure_ascii=False)
        self.connection.execute(
            "INSERT INTO term_title_exclusions VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(corpus_id,article_id) DO UPDATE SET "
            "url=excluded.url,title=excluded.title,matched_terms_json=excluded.matched_terms_json,"
            "policy=excluded.policy,screened_at=excluded.screened_at",
            (
                corpus_id,
                article_id,
                url,
                title,
                terms_json,
                TITLE_FILTER_POLICY,
                datetime.now(UTC).isoformat(),
            ),
        )
        self.connection.execute(
            "UPDATE term_articles SET title_excluded=1,title_exclusion_terms=?,"
            "title_filter_policy=? "
            "WHERE corpus_id=? AND article_id=?",
            (terms_json, TITLE_FILTER_POLICY, corpus_id, article_id),
        )
        self.connection.commit()

    def excluded_articles(self, corpus_id: str) -> list[dict[str, Any]]:
        rows = [
            dict(row)
            for row in self.connection.execute(
                "SELECT article_id,url,title,matched_terms_json,policy FROM term_title_exclusions "
                "WHERE corpus_id=? ORDER BY article_id",
                (corpus_id,),
            )
        ]
        for row in rows:
            row["matched_exclusion_terms"] = json.loads(row.pop("matched_terms_json"))
            row["exclusion_reason"] = "title_keyword"
        title_ids = {row["article_id"] for row in rows}
        rows.extend(
            {**row, "matched_exclusion_terms": [], "exclusion_reason": "outside_ai_iot"}
            for row in self.domain_screenings(corpus_id)
            if not row["domains"] and row["article_id"] not in title_ids
        )
        excluded_ids = {row["article_id"] for row in rows}
        required = self.connection.execute(
            "SELECT require_product_service FROM term_corpora WHERE corpus_id=?", (corpus_id,)
        ).fetchone()
        if required and required[0]:
            for record in self.connection.execute(
                "SELECT article_id,url,title,release_type_id,release_type_name "
                "FROM term_release_type_screenings WHERE corpus_id=? "
                "AND NOT (release_type_id='01' AND release_type_name='商品サービス')",
                (corpus_id,),
            ):
                if record["article_id"] not in excluded_ids:
                    rows.append(
                        {
                            **dict(record),
                            "matched_exclusion_terms": [],
                            "exclusion_reason": "outside_product_service"
                            if record["release_type_id"]
                            else "release_type_unconfirmed",
                            "policy": "extraction-prtimes-product-service-v1-20261013",
                        }
                    )
        return sorted(rows, key=lambda row: row["article_id"])

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: Any) -> None:
        self.connection.close()

    def create_corpus(self, corpus_id: str, domain_label: str) -> None:
        self.connection.execute(
            "INSERT INTO term_corpora (corpus_id,domain_label,created_at) VALUES (?, ?, ?) "
            "ON CONFLICT(corpus_id) "
            "DO UPDATE SET domain_label=excluded.domain_label",
            (corpus_id, domain_label, datetime.now(UTC).isoformat()),
        )
        self.connection.commit()

    def import_article(self, corpus_id: str, article: DiscoveryArticle, url: str = "") -> bool:
        if title_is_excluded(article.title):
            self.record_title_exclusion(corpus_id, article.article_id, article.title, url)
            return False
        required = self.connection.execute(
            "SELECT require_product_service FROM term_corpora WHERE corpus_id=?", (corpus_id,)
        ).fetchone()
        if (
            required
            and required[0]
            and self.connection.execute(
                "SELECT 1 FROM term_release_type_screenings WHERE corpus_id=? AND article_id=? "
                "AND release_type_id='01' AND release_type_name='商品サービス'",
                (corpus_id, article.article_id),
            ).fetchone()
            is None
        ):
            return False
        self.connection.execute(
            "DELETE FROM term_title_exclusions WHERE corpus_id=? AND article_id=?",
            (corpus_id, article.article_id),
        )
        domains = self.record_domain_screening(
            corpus_id, article.article_id, article.title, article.body, url
        )
        if not domains:
            return False
        self.connection.execute(
            "INSERT INTO term_articles "
            "(corpus_id,article_id,url,title,body,normalized_title,normalized_body,"
            "content_hash,imported_at,title_excluded,title_exclusion_terms,title_filter_policy,"
            "domain_eligible,matched_domains,domain_filter_policy) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, '[]', ?, 1, ?, ?) "
            "ON CONFLICT(corpus_id,article_id) DO UPDATE SET "
            "url=excluded.url,title=excluded.title,body=excluded.body,"
            "normalized_title=excluded.normalized_title,normalized_body=excluded.normalized_body,"
            "content_hash=excluded.content_hash,imported_at=excluded.imported_at,"
            "title_excluded=0,title_exclusion_terms='[]',title_filter_policy=excluded.title_filter_policy,"
            "domain_eligible=1,matched_domains=excluded.matched_domains,"
            "domain_filter_policy=excluded.domain_filter_policy,release_type_excluded=0",
            (
                corpus_id,
                article.article_id,
                url,
                article.title,
                article.body,
                normalized_text(article.title),
                normalized_text(article.body),
                canonical_payload_hash(article.model_dump(mode="json")),
                datetime.now(UTC).isoformat(),
                TITLE_FILTER_POLICY,
                json.dumps(domains, ensure_ascii=False),
                DOMAIN_FILTER_POLICY,
            ),
        )
        self.connection.commit()
        return True

    def stored_article_count(self, corpus_id: str) -> int:
        return int(
            self.connection.execute(
                "SELECT COUNT(*) FROM term_articles WHERE corpus_id=?", (corpus_id,)
            ).fetchone()[0]
        )

    def article_count(self, corpus_id: str) -> int:
        return int(
            self.connection.execute(
                "SELECT COUNT(*) FROM term_articles a WHERE corpus_id=? "
                "AND title_excluded=0 AND title_is_excluded(title)=0 "
                "AND release_type_excluded=0 AND domain_eligible=1 "
                "AND domain_filter_policy=current_domain_policy() "
                "AND NOT EXISTS (SELECT 1 FROM term_title_exclusions x "
                "WHERE x.corpus_id=a.corpus_id AND x.article_id=a.article_id)",
                (corpus_id,),
            ).fetchone()[0]
        )

    def articles(self, corpus_id: str) -> tuple[DiscoveryArticle, ...]:
        return tuple(
            DiscoveryArticle(article_id=row["article_id"], title=row["title"], body=row["body"])
            for row in self.connection.execute(
                "SELECT article_id,title,body FROM term_articles a "
                "WHERE corpus_id=? AND title_excluded=0 AND title_is_excluded(title)=0 "
                "AND release_type_excluded=0 AND domain_eligible=1 "
                "AND domain_filter_policy=current_domain_policy() "
                "AND NOT EXISTS (SELECT 1 FROM term_title_exclusions x "
                "WHERE x.corpus_id=a.corpus_id AND x.article_id=a.article_id) ORDER BY article_id",
                (corpus_id,),
            )
        )

    def has_article(self, corpus_id: str, article_id: str) -> bool:
        return (
            self.connection.execute(
                "SELECT 1 FROM term_articles WHERE corpus_id=? AND article_id=?",
                (corpus_id, article_id),
            ).fetchone()
            is not None
        )

    def save_vocabulary(self, vocabulary: DiscoverySearchVocabularyV2) -> str:
        key = canonical_payload_hash(vocabulary.model_dump(mode="json"))
        self.connection.execute(
            "INSERT OR IGNORE INTO term_vocabularies VALUES (?, ?, ?)",
            (key, vocabulary.model_dump_json(), datetime.now(UTC).isoformat()),
        )
        self.connection.executemany(
            "INSERT OR IGNORE INTO term_candidates VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (key, c.id, c.label, c.layer, c.priority, term, normalized_text(term))
                for c in vocabulary.concepts
                for term in (c.label, *c.aliases)
            ],
        )
        self.connection.commit()
        return key

    def count_candidates(self, corpus_id: str, vocabulary_hash: str) -> list[dict[str, Any]]:
        if (
            self.connection.execute(
                "SELECT 1 FROM term_vocabularies WHERE vocabulary_hash=?", (vocabulary_hash,)
            ).fetchone()
            is None
        ):
            raise ValueError("vocabulary not registered in database")
        matches_sql = """
            WITH eligible_articles AS MATERIALIZED (
                SELECT article_id,normalized_title,normalized_body
                FROM term_articles a
                WHERE corpus_id=? AND title_excluded=0 AND title_is_excluded(title)=0
                AND release_type_excluded=0 AND domain_eligible=1
                AND domain_filter_policy=current_domain_policy()
                AND NOT EXISTS (SELECT 1 FROM term_title_exclusions x
                    WHERE x.corpus_id=a.corpus_id AND x.article_id=a.article_id)
            )
            SELECT a.article_id, t.concept_id, t.label, t.layer, t.priority, t.term
            FROM eligible_articles a JOIN term_candidates t
                ON t.vocabulary_hash=? AND (
                    phrase_match(t.normalized_term, a.normalized_title)
                    OR phrase_match(t.normalized_term, a.normalized_body))
        """
        counts_sql = """
            WITH eligible_articles AS MATERIALIZED (
                SELECT article_id,title,url,matched_domains,normalized_title,normalized_body
                FROM term_articles a
                WHERE corpus_id=? AND title_excluded=0 AND title_is_excluded(title)=0
                AND release_type_excluded=0 AND domain_eligible=1
                AND domain_filter_policy=current_domain_policy()
                AND NOT EXISTS (SELECT 1 FROM term_title_exclusions x
                    WHERE x.corpus_id=a.corpus_id AND x.article_id=a.article_id)
            ), matches AS (
                SELECT a.article_id, t.concept_id, t.term
                FROM eligible_articles a JOIN term_candidates t
                    ON t.vocabulary_hash=? AND (
                        phrase_match(t.normalized_term, a.normalized_title)
                        OR phrase_match(t.normalized_term, a.normalized_body))
            )
            SELECT a.article_id, a.title, a.url, a.matched_domains,
                COUNT(DISTINCT m.concept_id) AS concept_count,
                COUNT(DISTINCT m.term) AS matched_term_count
            FROM eligible_articles a LEFT JOIN matches m ON m.article_id=a.article_id
            GROUP BY a.article_id, a.title, a.url
            ORDER BY concept_count DESC, a.article_id
        """
        with self.connection:
            self.connection.execute("BEGIN")
            # SQLite performs matching and DISTINCT counts over the persisted corpus and vocabulary.
            rows = [
                dict(row)
                for row in self.connection.execute(counts_sql, (corpus_id, vocabulary_hash))
            ]
            details: dict[str, dict[str, dict[str, Any]]] = {}
            for match in self.connection.execute(matches_sql, (corpus_id, vocabulary_hash)):
                concepts = details.setdefault(match["article_id"], {})
                concept = concepts.setdefault(
                    match["concept_id"],
                    {
                        "concept_id": match["concept_id"],
                        "label": match["label"],
                        "layer": match["layer"],
                        "priority": match["priority"],
                        "matched_terms": [],
                    },
                )
                concept["matched_terms"].append(match["term"])
            domain_details = {
                row["article_id"]: row["matched_domain_terms"]
                for row in self.domain_screenings(corpus_id)
            }
            for row in rows:
                row["domains"] = json.loads(row.pop("matched_domains"))
                row["matched_domain_terms"] = domain_details.get(row["article_id"], {})
                row["matches"] = list(details.get(row["article_id"], {}).values())
                row["matched_terms"] = list(
                    dict.fromkeys(
                        term for match in row["matches"] for term in match["matched_terms"]
                    )
                )
        return rows
