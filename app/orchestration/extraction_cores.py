"""Local density cores from saved article vectors, with original-space diagnostics."""

import csv
import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CoreParameters:
    n_components: int = 15
    n_neighbors: int = 15
    min_dist: float = 0.0
    random_state: int = 42
    min_cluster_size: int = 5
    min_samples: int = 5
    cluster_selection_method: str = "leaf"
    core_top_n: int = 3
    core_min_probability: float = 0.9

    def validate(self, count: int) -> None:
        if not 2 <= self.n_components < count - 1:
            raise ValueError("UMAP dimensions must be between 2 and article_count - 2")
        if not 2 <= self.n_neighbors < count:
            raise ValueError("UMAP neighbors must be between 2 and article_count - 1")
        if not 0 <= self.min_dist <= 1:
            raise ValueError("UMAP min_dist must be in [0, 1]")
        if not 2 <= self.min_cluster_size <= count or not 1 <= self.min_samples < count:
            raise ValueError("invalid HDBSCAN minimum sizes")
        if self.cluster_selection_method not in {"leaf", "eom"}:
            raise ValueError("invalid HDBSCAN cluster selection method")
        if self.core_top_n < 1 or not 0 <= self.core_min_probability <= 1:
            raise ValueError("invalid core selection parameters")


DEFAULT_CORE_PARAMETERS = CoreParameters()


def normalized_input(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], Any]:
    import numpy as np

    articles = payload["articles"]
    ids = [a["f_id"] for a in articles]
    if len(ids) != len(set(ids)) or not ids or any(not isinstance(i, str) or not i for i in ids):
        raise ValueError("article IDs must be nonempty and unique")
    vectors = np.asarray([a["value"] for a in articles], dtype=np.float64)
    if vectors.ndim != 2 or vectors.shape[1] < 2 or not np.isfinite(vectors).all():
        raise ValueError("vectors must form a finite, nonempty matrix")
    if any(a["dimensions"] != vectors.shape[1] for a in articles):
        raise ValueError("vector dimensions do not match metadata")
    if any(a["model"] != payload["model"] for a in articles):
        raise ValueError("vector models do not match metadata")
    norms = np.linalg.norm(vectors, axis=1)
    if not np.isfinite(norms).all() or (norms <= 0).any():
        raise ValueError("vectors must have nonzero finite norms")
    return articles, vectors / norms[:, None]


def fit_density(vectors: Any, parameters: CoreParameters) -> tuple[Any, Any, Any, Any]:
    import hdbscan
    import numpy as np
    import umap

    reduced = umap.UMAP(
        metric="cosine",
        n_components=parameters.n_components,
        n_neighbors=parameters.n_neighbors,
        min_dist=parameters.min_dist,
        random_state=parameters.random_state,
        n_jobs=1,
    ).fit_transform(vectors)
    if not np.isfinite(reduced).all():
        raise ValueError("UMAP produced nonfinite coordinates")
    model = hdbscan.HDBSCAN(
        metric="euclidean",
        min_cluster_size=parameters.min_cluster_size,
        min_samples=parameters.min_samples,
        cluster_selection_method=parameters.cluster_selection_method,
        core_dist_n_jobs=1,
        approx_min_span_tree=False,
    ).fit(reduced)
    return reduced, model.labels_, model.probabilities_, model.cluster_persistence_


def describe_clusters(
    articles: list[dict[str, Any]],
    vectors: Any,
    labels: Any,
    probabilities: Any,
    persistence: Any,
    parameters: CoreParameters,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    import numpy as np

    if len(labels) != len(articles) or len(probabilities) != len(articles):
        raise ValueError("cluster assignment length mismatch")
    if (
        not np.isfinite(probabilities).all()
        or (probabilities < 0).any()
        or (probabilities > 1).any()
    ):
        raise ValueError("invalid membership strengths")
    rows = [
        {
            **{k: v for k, v in a.items() if k != "value"},
            "hdbscan_label": int(labels[i]),
            "cluster_id": None,
            "probability": float(probabilities[i]),
            "centroid_cosine": None,
            "probability_rank": None,
            "centroid_rank": None,
            "probability_core": False,
            "centroid_core": False,
            "is_core": False,
        }
        for i, a in enumerate(articles)
    ]
    groups = [np.flatnonzero(labels == label).tolist() for label in sorted(set(labels) - {-1})]
    groups.sort(key=lambda members: min(articles[i]["f_id"] for i in members))
    clusters = []
    for serial, members in enumerate(groups, 1):
        cluster_id = f"C{serial:02d}"
        center = vectors[members].mean(axis=0)
        norm = np.linalg.norm(center)
        if norm <= 0 or not np.isfinite(norm):
            raise ValueError("cluster centroid has zero or nonfinite norm")
        center /= norm
        similarities = np.clip(vectors[members] @ center, -1.0, 1.0)
        for i, similarity in zip(members, similarities, strict=True):
            rows[i]["cluster_id"] = cluster_id
            rows[i]["centroid_cosine"] = float(similarity)
        by_center = sorted(members, key=lambda i: (-rows[i]["centroid_cosine"], rows[i]["f_id"]))
        by_probability = sorted(
            members,
            key=lambda i: (-rows[i]["probability"], -rows[i]["centroid_cosine"], rows[i]["f_id"]),
        )
        probability_core = {
            i
            for i in by_probability[: parameters.core_top_n]
            if rows[i]["probability"] >= parameters.core_min_probability
        }
        centroid_core = set(by_center[: parameters.core_top_n])
        core = probability_core & centroid_core
        for rank, i in enumerate(by_probability, 1):
            rows[i]["probability_rank"] = rank
        for rank, i in enumerate(by_center, 1):
            rows[i]["centroid_rank"] = rank
            rows[i]["probability_core"] = i in probability_core
            rows[i]["centroid_core"] = i in centroid_core
            rows[i]["is_core"] = i in core
        matrix = np.clip(vectors[members] @ vectors[members].T, -1.0, 1.0)
        values = matrix[np.triu_indices(len(members), k=1)]
        ordered_core = [i for i in by_center if i in core]
        pairs = [
            {
                "left_id": articles[i]["f_id"],
                "right_id": articles[j]["f_id"],
                "cosine": float(np.clip(vectors[i] @ vectors[j], -1, 1)),
            }
            for position, i in enumerate(ordered_core)
            for j in ordered_core[position + 1 :]
        ]
        clusters.append(
            {
                "cluster_id": cluster_id,
                "hdbscan_label": int(labels[members[0]]),
                "article_count": len(members),
                "persistence": float(persistence[int(labels[members[0]])]),
                "core_count": len(core),
                "core_ids": [articles[i]["f_id"] for i in ordered_core],
                "probability_core_ids": [
                    articles[i]["f_id"] for i in by_probability if i in probability_core
                ],
                "centroid_core_ids": [articles[i]["f_id"] for i in by_center if i in centroid_core],
                "member_ids": [articles[i]["f_id"] for i in by_center],
                "representative_id": articles[by_center[0]]["f_id"],
                "mean_pair_cosine": float(values.mean()) if len(values) else None,
                "min_pair_cosine": float(values.min()) if len(values) else None,
                "core_pairs": pairs,
                "centroid_value": center.tolist(),
            }
        )
    return rows, clusters


def sensitivity_parameters(
    parameters: CoreParameters, count: int
) -> list[tuple[str, CoreParameters]]:
    candidates = [
        ("seed-7", replace(parameters, random_state=7)),
        ("seed-21", replace(parameters, random_state=21)),
        ("dimensions-10", replace(parameters, n_components=10)),
        ("dimensions-20", replace(parameters, n_components=20)),
        ("neighbors-30", replace(parameters, n_neighbors=30)),
        ("minimum-size-8", replace(parameters, min_cluster_size=8)),
    ]
    result = []
    for name, candidate in candidates:
        if candidate == parameters:
            continue
        try:
            candidate.validate(count)
        except ValueError:
            continue
        result.append((name, candidate))
    return result


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


def extract_density_cores(
    source: Path,
    output: Path,
    parameters: CoreParameters = DEFAULT_CORE_PARAMETERS,
    sensitivity: bool = True,
    progress: Callable[[dict[str, Any]], None] = lambda _: None,
) -> dict[str, Any]:
    import numpy as np
    from sklearn.metrics import adjusted_rand_score

    source_bytes = source.read_bytes()
    payload = json.loads(source_bytes.decode("utf-8-sig"))
    articles, vectors = normalized_input(payload)
    if payload.get("cohort", {}).get("organization_filter"):
        organizations = [a["organization_id"] for a in articles]
        if len(organizations) != len(set(organizations)):
            raise ValueError("organization-filtered input contains duplicate organizations")
    parameters.validate(len(articles))
    signature = {
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "parameters": asdict(parameters),
        "sensitivity": sensitivity,
    }
    run_key = hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()
    progress({"stage": "main", "parameters": asdict(parameters)})
    reduced, labels, probabilities, persistence = fit_density(vectors, parameters)
    rows, clusters = describe_clusters(
        articles, vectors, labels, probabilities, persistence, parameters
    )
    variants = []
    assignments = []
    if sensitivity:
        for name, candidate in sensitivity_parameters(parameters, len(articles)):
            progress({"stage": "sensitivity", "name": name})
            _, variant_labels, variant_probabilities, variant_persistence = fit_density(
                vectors, candidate
            )
            variant_rows, variant_clusters = describe_clusters(
                articles,
                vectors,
                variant_labels,
                variant_probabilities,
                variant_persistence,
                candidate,
            )
            variants.append(
                {
                    "name": name,
                    "parameters": asdict(candidate),
                    "cluster_count": len(variant_clusters),
                    "noise_count": int((variant_labels == -1).sum()),
                    "core_count": sum(r["is_core"] for r in variant_rows),
                    "adjusted_rand_index_vs_main": float(
                        adjusted_rand_score(labels, variant_labels)
                    ),
                    "labels": dict(
                        zip([a["f_id"] for a in articles], variant_labels.tolist(), strict=True)
                    ),
                    "core_ids": [r["f_id"] for r in variant_rows if r["is_core"]],
                }
            )
            assignments.append(variant_labels)
    positions = {row["f_id"]: i for i, row in enumerate(rows)}
    for cluster in clusters:
        core_indices = [positions[f_id] for f_id in cluster["core_ids"]]
        for pair in cluster["core_pairs"]:
            i, j = positions[pair["left_id"]], positions[pair["right_id"]]
            pair["sensitivity_coassignment"] = (
                sum(int(v[i] >= 0 and v[i] == v[j]) for v in assignments) / len(assignments)
                if assignments
                else None
            )
        for i in core_indices:
            rows[i]["sensitivity_clustered_fraction"] = (
                sum(int(v[i] >= 0) for v in assignments) / len(assignments) if assignments else None
            )
        cluster["core_mean_cosine"] = (
            sum(p["cosine"] for p in cluster["core_pairs"]) / len(cluster["core_pairs"])
            if cluster["core_pairs"]
            else None
        )
    summary = {
        "run_key": run_key,
        **signature,
        "source_file": str(source),
        "embedding_model": payload["model"],
        "cohort": payload.get("cohort", {}),
        "article_count": len(articles),
        "original_dimensions": vectors.shape[1],
        "reduced_dimensions": reduced.shape[1],
        "cluster_count": len(clusters),
        "clustered_count": int((labels >= 0).sum()),
        "noise_count": int((labels == -1).sum()),
        "core_count": sum(row["is_core"] for row in rows),
        "probability_core_count": sum(row["probability_core"] for row in rows),
        "centroid_core_count": sum(row["centroid_core"] for row in rows),
        "core_policy": "intersection(probability>=threshold and top-N, original-centroid top-N)",
        "versions": {
            name: version(name)
            for name in [
                "numpy",
                "scipy",
                "scikit-learn",
                "umap-learn",
                "hdbscan",
                "numba",
                "pynndescent",
            ]
        },
        "completed_at": datetime.now(UTC).isoformat(),
    }
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "summary.json", summary)
    write_json(output / "clusters.json", {"summary": summary, "clusters": clusters})
    write_json(output / "article-clusters.json", {"summary": summary, "articles": rows})
    write_json(
        output / "cores.json", {"summary": summary, "articles": [r for r in rows if r["is_core"]]}
    )
    write_json(output / "sensitivity.json", variants)
    write_json(
        output / "reduced-vectors.json",
        {
            "run_key": run_key,
            "metric": "cosine",
            "articles": [
                {"f_id": article["f_id"], "value": reduced[i].tolist()}
                for i, article in enumerate(articles)
            ],
        },
    )
    np.savez_compressed(
        output / "normalized-vectors.npz",
        f_ids=np.array([a["f_id"] for a in articles]),
        vectors=vectors,
    )
    for filename, selection in [
        ("article-clusters.csv", rows),
        ("cores.csv", [r for r in rows if r["is_core"]]),
    ]:
        with (output / filename).open("w", encoding="utf-8-sig", newline="") as stream:
            fields = [
                "cluster_id",
                "f_id",
                "title",
                "organization_id",
                "organization_name",
                "published_at",
                "url",
                "probability",
                "centroid_cosine",
                "probability_rank",
                "centroid_rank",
                "is_core",
                "probability_core",
                "centroid_core",
                "concept_count",
            ]
            writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(selection)
    from app.infrastructure.extraction_core_report import core_report_html

    (output / "cores.html").write_text(
        core_report_html(summary, clusters, rows, variants), encoding="utf-8"
    )
    return summary
