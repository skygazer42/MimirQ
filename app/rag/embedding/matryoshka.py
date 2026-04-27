from __future__ import annotations

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


__all__ = [
    "apply_matryoshka_to_embeddings",
    "resolve_matryoshka_dimension",
    "truncate_embedding_dimension",
]
