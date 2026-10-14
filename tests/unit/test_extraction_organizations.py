import json
import sqlite3
from pathlib import Path

import pytest

from app.orchestration.extraction_organizations import (
    canonical_organizations,
    latest_articles,
    release_metadata,
    select_latest_organizations,
)


def document(company: int, name: str, published: str, modified: str = "2099-01-01") -> str:
    data = {
        "@type": "NewsArticle",
        "datePublished": published,
        "dateModified": modified,
        "author": {"@type": "Organization", "name": name},
    }
    return (
        '<script type="application/ld+json">' + json.dumps(data) + "</script>"
        f'<a href="/main/html/searchrlp/company_id/{company}">Official company</a>'
    )


def row(number: int, company: int, published: str, name: str = "Organization") -> dict:
    url = f"https://prtimes.jp/main/html/rd/p/{number:09d}.{company:09d}.html"
    return {
        "f_id": f"F{number:03d}",
        "article_id": url,
        "url": url,
        "title": f"Product {number}",
        "value": [0.8, 0.6],
        **release_metadata(url, document(company, name, published)),
    }


def test_publication_not_update_and_timezone_equivalence() -> None:
    records = [
        row(3, 7, "2026-01-01 12:00:00"),
        row(1, 7, "2026-01-02T03:00:00Z"),
        row(2, 9, "2026-01-01T03:00:00Z", "Other"),
    ]
    kept, removed = latest_articles(records)
    assert {a["f_id"] for a in kept} == {"F001", "F002"}
    assert removed[0]["selected_f_id"] == "F001"
    assert kept[0]["published_at"] == "2026-01-02T12:00:00+09:00"


def test_same_timestamp_uses_release_number_regardless_of_input_order() -> None:
    records = [row(8, 7, "2026-01-01 12:00:00"), row(9, 7, "2026-01-01 12:00:00")]
    assert latest_articles(records)[0][0]["f_id"] == "F009"
    assert latest_articles(list(reversed(records)))[0][0]["f_id"] == "F009"


def test_same_official_name_keeps_company_ids_separate() -> None:
    records = [
        row(1, 7, "2026-01-01", "株式会社 日立製作所"),
        row(2, 9, "2026-01-02", "株式会社 日立製作所"),
        row(3, 11, "2026-01-03", "Different organization"),
    ]
    annotated, merged = canonical_organizations(records)
    kept, _ = latest_articles(annotated)
    assert {a["f_id"] for a in kept} == {"F001", "F002", "F003"}
    assert [a["organization_id"] for a in kept] == [
        "prtimes:000000007", "prtimes:000000009", "prtimes:000000011"
    ]
    assert merged == []


def test_unverified_company_or_missing_publication_refused() -> None:
    url = "https://prtimes.jp/main/html/rd/p/000000001.000000007.html"
    with pytest.raises(ValueError, match="company link"):
        release_metadata(url, document(9, "Organization", "2026-01-01"))
    with pytest.raises(ValueError):
        release_metadata(url, document(7, "Organization", "invalid date"))
    with pytest.raises(ValueError, match="missing or conflicting"):
        release_metadata(url, '<a href="/main/html/searchrlp/company_id/7">Official</a>')


def test_saved_snapshot_selection_preserves_vectors_and_source(tmp_path: Path) -> None:
    records = [row(1, 7, "2026-01-01"), row(2, 7, "2026-01-02")]
    source = tmp_path / "vectors.json"
    source.write_text(json.dumps({"articles": records, "model": "fixture"}), encoding="utf-8")
    original = source.read_bytes()
    audit = tmp_path / "audit.sqlite"
    with sqlite3.connect(audit) as db:
        db.execute("CREATE TABLE raw_snapshots (final_url,body_text,body_sha256,fetched_at)")
        db.executemany(
            "INSERT INTO raw_snapshots VALUES (?,?,?,?)",
            [
                (
                    a["url"],
                    document(7, "Organization", a["published_at"]),
                    "official-hash",
                    "2026-02-01",
                )
                for a in records
            ],
        )
    target = select_latest_organizations(source, audit, tmp_path / "selection")
    output = json.loads(target.read_text())
    assert len(output["articles"]) == 1
    assert output["articles"][0]["value"] == records[1]["value"]
    assert output["cohort"]["organization_filter"]["embedding_API_requests"] == 0
    assert source.read_bytes() == original
    assert (
        json.loads((target.parent / "organization-excluded.json").read_text())[0]["selected_f_id"]
        == "F002"
    )


def test_missing_snapshot_cannot_silently_keep_an_unknown_date(tmp_path: Path) -> None:
    source = tmp_path / "vectors.json"
    source.write_text(json.dumps({"articles": [row(1, 7, "2026-01-01")]}), encoding="utf-8")
    audit = tmp_path / "audit.sqlite"
    with sqlite3.connect(audit) as db:
        db.execute("CREATE TABLE raw_snapshots (final_url,body_text,body_sha256,fetched_at)")
    with pytest.raises(ValueError, match="metadata missing"):
        select_latest_organizations(source, audit, tmp_path / "selection")
    assert not (tmp_path / "selection/article-values.json").exists()


def test_name_changes_do_not_split_one_company_id() -> None:
    records = [
        row(1, 7, "2026-01-01", "Previous name"),
        row(2, 7, "2026-01-02", "New name"),
        row(3, 9, "2026-01-03", "New name"),
    ]
    annotated, merged = canonical_organizations(records)
    kept, _ = latest_articles(annotated)
    assert {a["f_id"] for a in kept} == {"F002", "F003"}
    assert merged == []


def test_legacy_merged_annotations_restore_publishing_ids() -> None:
    records = [
        row(1, 7, "2026-01-01", "Shared name"),
        row(2, 9, "2026-01-02", "Shared name"),
    ]
    records[1]["publishing_organization_id"] = records[1]["organization_id"]
    records[1]["organization_id"] = records[0]["organization_id"]
    annotated, merged = canonical_organizations(records)
    assert {a["organization_id"] for a in annotated} == {
        "prtimes:000000007", "prtimes:000000009"
    }
    assert len(latest_articles(annotated)[0]) == 2
    assert merged == []
    assert records[1]["organization_id"] == "prtimes:000000007"


def test_snapshot_selection_keeps_latest_per_id_despite_shared_name(tmp_path: Path) -> None:
    records = [
        row(1, 7, "2026-01-01", "Shared company"),
        row(2, 7, "2026-01-02", "Shared company"),
        row(3, 9, "2026-01-01", "Shared company"),
    ]
    source = tmp_path / "vectors.json"
    source.write_text(json.dumps({"articles": records}), encoding="utf-8")
    original = source.read_bytes()
    audit = tmp_path / "audit.sqlite"
    with sqlite3.connect(audit) as db:
        db.execute("CREATE TABLE raw_snapshots (final_url,body_text,body_sha256,fetched_at)")
        db.executemany(
            "INSERT INTO raw_snapshots VALUES (?,?,?,?)",
            [
                (
                    a["url"],
                    document(int(a["organization_id"].split(":")[1]),
                             a["organization_name"], a["published_at"]),
                    "official-hash",
                    "2026-02-01",
                )
                for a in records
            ],
        )
    target = select_latest_organizations(source, audit, tmp_path / "selection")
    output = json.loads(target.read_text(encoding="utf-8"))
    assert {a["f_id"] for a in output["articles"]} == {"F002", "F003"}
    summary = output["cohort"]["organization_filter"]
    assert summary["policy"] == "prtimes-company-id-latest-publication-v2"
    assert summary["same_official_name_company_id_merges"] == []
    assert summary["organization_count"] == summary["official_company_id_count"] == 2
    assert summary["removed_article_count"] == 1
    assert source.read_bytes() == original
