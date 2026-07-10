
import math
from typing import Any

_ALLOWED_DIMS = (128, 256, 512, 1024)


def truncate_embedding_dimension(embedding: list[float], *, target_dim: int) -> list[float]:
    dim = max(1, int(target_dim or 1))
    return [float(v) for v in list(embedding or [])[:dim]]


def apply_matryoshka_to_embeddings(*, embeddings: list[list[float]], target_dim: int) -> list[list[float]]:
    return [truncate_embedding_dimension(embedding, target_dim=target_dim) for embedding in (embeddings or [])]


def resolve_matryoshka_dimension(
    *,
    query_complexity_label: str | None,
    source_dim: int,
    simple_dim: int = 256,
    structured_dim: int = 512,
    complex_dim: int = 1024,
) -> int:
    src = max(1, int(source_dim or 1))
    label = str(query_complexity_label or "").strip().lower() or "simple"
    desired = {
        "simple": int(simple_dim),
        "structured": int(structured_dim),
        "multi_hop": int(complex_dim),
    }.get(label, int(simple_dim))

    allowed = [dim for dim in _ALLOWED_DIMS if dim <= src]
    if not allowed:
        return src
    for dim in sorted(allowed):
        if dim >= desired:
            return dim
    return max(allowed)


def _cosine(left: list[float], right: list[float]) -> float:
    size = min(len(left), len(right))
    if size <= 0:
        return 0.0
    dot = 0.0
    left_sq = 0.0
    right_sq = 0.0
    for index in range(size):
        lval = float(left[index])
        rval = float(right[index])
        dot += lval * rval
        left_sq += lval * lval
        right_sq += rval * rval
    denom = math.sqrt(left_sq) * math.sqrt(right_sq)
    if denom <= 0.0:
        return 0.0
    return round(float(dot / denom), 6)


def _coerce_vector(value: Any) -> list[float]:
    out: list[float] = []
    for item in value or []:
        try:
            out.append(float(item))
        except (TypeError, ValueError):
            continue
    return out


def shortlist_then_rescore(
    *,
    query_short_embedding: list[float],
    query_full_embedding: list[float],
    corpus_short_embeddings: dict[str, list[float]],
    corpus_full_embeddings: dict[str, list[float]],
    shortlist_k: int,
    top_k: int,
) -> list[dict[str, float | int | str]]:
    """
    Experimental Matryoshka flow:
    use low-dimensional vectors for cheap recall, then full-dimensional vectors
    to reorder the shortlist. This is intentionally pure/offline so callers can
    benchmark before wiring it into production retrieval.
    """
    shortlist_size = max(1, int(shortlist_k or 1))
    top_size = max(1, int(top_k or 1))
    query_short = _coerce_vector(query_short_embedding)
    query_full = _coerce_vector(query_full_embedding)

    shortlist: list[dict[str, float | int | str]] = []
    for doc_id, embedding in (corpus_short_embeddings or {}).items():
        did = str(doc_id or "").strip()
        if not did:
            continue
        shortlist.append(
            {
                "document_id": did,
                "shortlist_score": _cosine(query_short, _coerce_vector(embedding)),
            }
        )
    shortlist.sort(key=lambda item: (-float(item["shortlist_score"]), str(item["document_id"])))

    rescored: list[dict[str, float | int | str]] = []
    for rank, row in enumerate(shortlist[:shortlist_size], start=1):
        did = str(row["document_id"])
        full_embedding = _coerce_vector((corpus_full_embeddings or {}).get(did))
        rescored.append(
            {
                "document_id": did,
                "shortlist_rank": int(rank),
                "shortlist_score": float(row["shortlist_score"]),
                "rescore_score": _cosine(query_full, full_embedding),
            }
        )
    rescored.sort(
        key=lambda item: (
            -float(item["rescore_score"]),
            int(item["shortlist_rank"]),
            str(item["document_id"]),
        )
    )
    return rescored[:top_size]


__all__ = [
    "apply_matryoshka_to_embeddings",
    "resolve_matryoshka_dimension",
    "shortlist_then_rescore",
    "truncate_embedding_dimension",
]
