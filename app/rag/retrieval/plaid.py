from __future__ import annotations

from typing import Any

PLAID_COMPRESSION_SCHEMA = "mimirq.plaid_compression.v1"


def _coerce_vector(raw: Any) -> list[float]:
    return [float(v) for v in raw or []]


def _sq_l2(a: list[float], b: list[float]) -> float:
    n = min(len(a), len(b))
    total = 0.0
    for idx in range(n):
        diff = float(a[idx]) - float(b[idx])
        total += diff * diff
    return total


def _unique_vectors(vectors: list[list[float]]) -> list[list[float]]:
    seen: set[tuple[float, ...]] = set()
    out: list[list[float]] = []
    for vector in vectors:
        key = tuple(float(v) for v in vector)
        if key in seen:
            continue
        seen.add(key)
        out.append(list(vector))
    return out


def _choose_centroids(vectors: list[list[float]], num_centroids: int) -> list[list[float]]:
    if not vectors:
        return []
    unique = _unique_vectors(vectors)
    limit = max(1, min(int(num_centroids or 1), len(unique)))
    if limit >= len(unique):
        return unique

    centroids = [unique[0]]
    while len(centroids) < limit:
        best_idx = 0
        best_score = -1.0
        for idx, candidate in enumerate(unique):
            score = min(_sq_l2(candidate, centroid) for centroid in centroids)
            if score > best_score:
                best_idx = idx
                best_score = score
        centroids.append(unique[best_idx])
        unique.pop(best_idx)
    return centroids


def compress_plaid_vectors(
    *,
    token_vectors: list[list[float]],
    num_centroids: int = 8,
) -> dict[str, Any]:
    vectors = [_coerce_vector(row) for row in token_vectors or []]
    if not vectors:
        return {
            "schema": PLAID_COMPRESSION_SCHEMA,
            "dim": 0,
            "original_tokens": 0,
            "centroids": [],
            "assignments": [],
            "cluster_sizes": [],
        }

    centroids = _choose_centroids(vectors, max(1, int(num_centroids or 1)))
    assignments: list[int] = []
    cluster_sizes = [0 for _ in centroids]
    for vector in vectors:
        best_idx = min(range(len(centroids)), key=lambda idx: (_sq_l2(vector, centroids[idx]), idx))
        assignments.append(int(best_idx))
        cluster_sizes[best_idx] += 1

    return {
        "schema": PLAID_COMPRESSION_SCHEMA,
        "dim": len(vectors[0]),
        "original_tokens": len(vectors),
        "centroids": [[float(v) for v in row] for row in centroids],
        "assignments": assignments,
        "cluster_sizes": [int(v) for v in cluster_sizes],
    }


def decompress_plaid_vectors(payload: dict[str, Any]) -> list[list[float]]:
    centroids = [_coerce_vector(row) for row in (payload or {}).get("centroids") or []]
    assignments = [int(v) for v in (payload or {}).get("assignments") or []]
    if not centroids or not assignments:
        return []
    out: list[list[float]] = []
    for idx in assignments:
        if 0 <= idx < len(centroids):
            out.append(list(centroids[idx]))
    return out


__all__ = [
    "PLAID_COMPRESSION_SCHEMA",
    "compress_plaid_vectors",
    "decompress_plaid_vectors",
]
