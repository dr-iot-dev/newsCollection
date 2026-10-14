"""Check original-space core decisions, rejected inputs, and density integration."""

import json
from pathlib import Path

import pytest

from app.infrastructure.extraction_core_report import core_report_html
from app.orchestration.extraction_cores import (
    CoreParameters,
    describe_clusters,
    extract_density_cores,
    normalized_input,
)

np = pytest.importorskip("numpy")


def article(fid: str, value: list[float]) -> dict:
    return {
        "f_id": fid,
        "article_id": fid,
        "title": "記事 " + fid,
        "url": "https://example.com/" + fid,
        "concept_count": 5,
        "model": "fixture",
        "dimensions": len(value),
        "value": value,
    }


def test_original_cosine_and_membership_intersection_excludes_noise() -> None:
    payload = {
        "model": "fixture",
        "articles": [
            article("F001", [2, 0]),
            article("F002", [2, 0.1]),
            article("F003", [2, -0.1]),
            article("F004", [0, 2]),
            article("F005", [-2, 0]),
        ],
    }
    articles, values = normalized_input(payload)
    rows, clusters = describe_clusters(
        articles,
        values,
        np.array([0, 0, 0, 0, -1]),
        np.array([0.95, 1, 0.2, 0.99, 0]),
        np.array([0.6]),
        CoreParameters(core_top_n=2),
    )
    assert clusters[0]["probability_core_ids"] == ["F002", "F004"]
    assert clusters[0]["centroid_core_ids"] == ["F002", "F001"]
    assert clusters[0]["core_ids"] == ["F002"]
    assert rows[-1]["cluster_id"] is None
    assert not rows[-1]["is_core"]
    expected_center = values[:4].mean(axis=0)
    expected_center /= np.linalg.norm(expected_center)
    assert clusters[0]["centroid_value"] == pytest.approx(expected_center)
    assert rows[0]["centroid_cosine"] == pytest.approx(values[0] @ expected_center)
    assert np.linalg.norm(values, axis=1) == pytest.approx(np.ones(5))


def test_no_forced_core_below_probability_threshold() -> None:
    payload = {"model": "fixture", "articles": [article(f"F{i}", [1, i * 0.1]) for i in range(3)]}
    articles, values = normalized_input(payload)
    rows, clusters = describe_clusters(
        articles,
        values,
        np.array([0, 0, 0]),
        np.array([0.1, 0.2, 0.3]),
        np.array([0.4]),
        CoreParameters(),
    )
    assert clusters[0]["core_ids"] == []
    assert not any(row["is_core"] for row in rows)
    assert all(row["centroid_core"] for row in rows)


@pytest.mark.parametrize("bad", [[0, 0], [float("nan"), 1], [float("inf"), 1]])
def test_invalid_vectors_rejected(bad: list[float]) -> None:
    with pytest.raises(ValueError):
        normalized_input({"model": "fixture", "articles": [article("F001", bad)]})


def test_duplicate_ids_and_metadata_rejected() -> None:
    a = article("F001", [1, 2])
    with pytest.raises(ValueError, match="unique"):
        normalized_input({"model": "fixture", "articles": [a, a]})
    with pytest.raises(ValueError, match="models"):
        normalized_input({"model": "different", "articles": [a]})
    with pytest.raises(ValueError, match="dimensions"):
        normalized_input({"model": "fixture", "articles": [{**a, "dimensions": 3}]})


def test_all_noise_is_valid_and_produces_no_cores() -> None:
    articles, values = normalized_input({"model": "fixture", "articles": [article("F001", [1, 0])]})
    rows, clusters = describe_clusters(
        articles, values, np.array([-1]), np.array([0.0]), np.array([]), CoreParameters()
    )
    assert not clusters
    assert rows[0]["centroid_cosine"] is None
    assert not rows[0]["is_core"]


def test_report_escapes_article_strings_and_does_not_embed_centroid_arrays() -> None:
    html = core_report_html(
        {}, [{"centroid_value": [12345678]}], [{"title": "</script><script>alert(1)</script>"}], []
    )
    assert "</script><script>alert(1)" not in html
    assert "12345678" not in html
    assert "\\u003c/script\\u003e" in html


@pytest.mark.parametrize("selection_method", ["leaf", "eom"])
def test_umap_hdbscan_on_known_separated_vectors(tmp_path: Path, selection_method: str) -> None:
    pytest.importorskip("umap")
    pytest.importorskip("hdbscan")
    rng = np.random.default_rng(23)
    originals = np.vstack([np.eye(8)[group] + rng.normal(0, 0.025, (20, 8)) for group in range(3)])
    source = tmp_path / "values.json"
    source.write_text(
        json.dumps(
            {
                "model": "fixture",
                "articles": [article(f"F{i:03d}", row.tolist()) for i, row in enumerate(originals)],
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "result"
    summary = extract_density_cores(
        source,
        output,
        CoreParameters(
            n_components=3,
            n_neighbors=10,
            min_cluster_size=6,
            cluster_selection_method=selection_method,
        ),
        sensitivity=False,
    )
    # Leaf selection may subdivide a planted group; it must never merge groups.
    assert summary["cluster_count"] >= 3
    if selection_method == "eom":
        assert summary["cluster_count"] == 3
        assert summary["noise_count"] == 0
    assert summary["core_count"] > 0
    rows = json.loads((output / "article-clusters.json").read_text(encoding="utf-8"))["articles"]
    assert {row["f_id"] for row in rows} == {f"F{i:03d}" for i in range(60)}
    for cluster in {row["cluster_id"] for row in rows} - {None}:
        groups = {int(row["f_id"][1:]) // 20 for row in rows if row["cluster_id"] == cluster}
        assert len(groups) == 1
    with np.load(output / "normalized-vectors.npz", allow_pickle=False) as saved:
        assert saved["vectors"].shape == (60, 8)
        assert np.linalg.norm(saved["vectors"], axis=1) == pytest.approx(np.ones(60))
    assert (output / "cores.html").is_file()
    assert json.loads((output / "sensitivity.json").read_text(encoding="utf-8")) == []
