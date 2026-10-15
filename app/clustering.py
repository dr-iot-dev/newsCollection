"""Cluster embeddings and select representative source articles."""

import numpy as np

from app.settings import Settings


def cluster(values: list[list[float]], settings: Settings) -> list[int]:
    import hdbscan
    import umap

    matrix = np.asarray(values, dtype=float)
    if matrix.ndim != 2 or matrix.shape[1] < 2 or not np.isfinite(matrix).all():
        raise ValueError("INVALID_EMBEDDINGS")
    norms = np.linalg.norm(matrix, axis=1)
    if np.any(norms == 0):
        raise ValueError("ZERO_EMBEDDING")
    matrix = matrix / norms[:, None]
    if len(values) <= max(settings.n_components + 1, settings.n_neighbors, settings.min_samples):
        raise ValueError("INSUFFICIENT_ARTICLES_FOR_CLUSTER_PARAMETERS")
    if settings.min_cluster_size > len(values):
        raise ValueError("INSUFFICIENT_ARTICLES_FOR_CLUSTER_PARAMETERS")
    reduced = umap.UMAP(
        metric="cosine",
        n_components=settings.n_components,
        n_neighbors=settings.n_neighbors,
        min_dist=0,
        random_state=42,
        n_jobs=1,
    ).fit_transform(matrix)
    labels = hdbscan.HDBSCAN(
        metric="euclidean",
        min_cluster_size=settings.min_cluster_size,
        min_samples=settings.min_samples,
        cluster_selection_method="leaf",
        core_dist_n_jobs=1,
        approx_min_span_tree=False,
    ).fit_predict(reduced)
    return [int(label) for label in labels]


def selection_candidates(
    candidates: list[tuple[str, str, list[float]]], limit: int = 30
) -> list[str]:
    """Rank against the full cluster centroid, then bound the AI input size."""
    if type(limit) is not int or not 3 <= limit <= 30:
        raise ValueError("INVALID_SELECTION_LIMIT")
    if len(candidates) < 3:
        return []
    if len({item[0] for item in candidates}) != len(candidates):
        raise ValueError("DUPLICATE_ARTICLE_ID")
    vectors = np.asarray([item[2] for item in candidates], dtype=float)
    if vectors.ndim != 2 or vectors.shape[1] < 2 or not np.isfinite(vectors).all():
        raise ValueError("INVALID_EMBEDDINGS")
    norms = np.linalg.norm(vectors, axis=1)
    if np.any(norms == 0):
        raise ValueError("ZERO_EMBEDDING")
    vectors = vectors / norms[:, None]
    center = vectors.mean(axis=0)
    # Scaling the centroid does not change the nearest-member order.
    scores = vectors @ center
    order = sorted(range(len(candidates)), key=lambda i: (-scores[i], candidates[i][0]))
    return [candidates[i][0] for i in order[:limit]]


def select_three(candidates: list[tuple[str, str, list[float]]]) -> list[str]:
    """Original ranking helper; production selection now uses the AI candidate pool."""
    return selection_candidates(candidates, 3)
