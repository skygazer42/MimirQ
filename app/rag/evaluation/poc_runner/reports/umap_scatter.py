
from collections import Counter
from typing import Any

import numpy as np
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer

_SCHEMA = "mimirq.dataset_analysis.umap_scatter.v1"


def _document_records(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        for filename in row.get("final_context_filenames") or []:
            name = str(filename or "").strip()
            if name:
                counts[name] += 1
    out: list[dict[str, Any]] = []
    for filename, count in counts.most_common(max(1, int(limit or 1))):
        out.append(
            {
                "label": filename,
                "kind": "document",
                "group": "document",
                "weight": int(count),
                "text": filename,
            }
        )
    return out


def _query_records(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in list(rows or [])[: max(1, int(limit or 1))]:
        if not isinstance(row, dict):
            continue
        query = str(row.get("original_query") or "").strip()
        if not query:
            continue
        is_out_of_scope_candidate = (
            str(row.get("feedback_polarity") or "").strip().lower() == "negative"
            and int(row.get("citation_count") or 0) <= 0
        )
        group = "out_of_scope_candidate" if is_out_of_scope_candidate else "query"
        out.append(
            {
                "label": str(row.get("interaction_id") or "") or query[:24],
                "kind": "query",
                "group": group,
                "weight": 1,
                "text": query,
            }
        )
    return out


def _project_points(texts: list[str]) -> np.ndarray:
    if len(texts) <= 1:
        return np.array([[0.0, 0.0]], dtype=float)
    if len(texts) == 2:
        return np.array([[0.0, 0.0], [1.0, 0.0]], dtype=float)
    matrix = TfidfVectorizer(min_df=1).fit_transform(texts)
    try:
        from umap.umap_ import UMAP

        projector = UMAP(
            n_components=2,
            n_neighbors=max(2, min(10, len(texts) - 1)),
            min_dist=0.15,
            metric="cosine",
            random_state=42,
            transform_seed=42,
        )
        return np.asarray(projector.fit_transform(matrix), dtype=float)
    except Exception:
        dense = np.asarray(matrix.toarray(), dtype=float)
        if dense.shape[1] <= 1:
            zeros = np.zeros((dense.shape[0], 2), dtype=float)
            if dense.shape[1] == 1:
                zeros[:, 0] = dense[:, 0]
            return zeros
        projector = TruncatedSVD(n_components=2, random_state=42)
        return np.asarray(projector.fit_transform(matrix), dtype=float)


def build_umap_scatter(
    rows: list[dict[str, Any]],
    *,
    max_document_points: int = 40,
    max_query_points: int = 80,
) -> dict[str, Any]:
    doc_records = _document_records(rows, limit=max_document_points)
    query_records = _query_records(rows, limit=max_query_points)
    records = doc_records + query_records
    if not records:
        return {"schema": _SCHEMA, "point_count": 0, "points": []}

    texts = [str(item.get("text") or item.get("label") or "").strip() for item in records]
    coords = _project_points(texts)
    points: list[dict[str, Any]] = []
    for idx, item in enumerate(records):
        points.append(
            {
                "label": str(item.get("label") or ""),
                "kind": str(item.get("kind") or ""),
                "group": str(item.get("group") or ""),
                "weight": int(item.get("weight") or 1),
                "x": round(float(coords[idx][0]), 6),
                "y": round(float(coords[idx][1]), 6),
            }
        )

    return {
        "schema": _SCHEMA,
        "point_count": int(len(points)),
        "points": points,
    }
