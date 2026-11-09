from collections.abc import Callable
from typing import Any, Literal, TypedDict

from app.rag.chunking.roles import build_chunk_type_subindex_payload


class BgeM3TripletPayload(TypedDict):
    schema: Literal["mimirq.bge_m3_triplet.v1"]
    dense: list[float]
    sparse: dict[str, float]
    colbert: list[list[float]]


class BgeM3IndexView(TypedDict):
    view: Literal["dense", "sparse", "colbert"]
    view_id: str
    subindex_key: str
    payload: list[float] | dict[str, float] | list[list[float]]
    metadata: dict[str, str]


class BgeM3TriIndexPayload(TypedDict):
    schema: Literal["mimirq.bge_m3_tri_index.v1"]
    chunk_id: str
    chunk_type: str
    subindex_key: str
    views: list[BgeM3IndexView]


def build_bge_m3_triplet_payload(
    *,
    text: str,
    dense_fn: Callable[[str], list[float]],
    sparse_fn: Callable[[str], dict[str, float]] | None = None,
    colbert_fn: Callable[[str], list[list[float]]] | None = None,
) -> BgeM3TripletPayload:
    raw = text
    dense = [float(v) for v in dense_fn(raw) or []]
    sparse_raw = sparse_fn(raw) if sparse_fn is not None else {}
    sparse = {str(k): float(v) for k, v in dict(sparse_raw or {}).items() if k.strip()}
    colbert_raw = colbert_fn(raw) if colbert_fn is not None else []
    colbert = [[float(v) for v in row or []] for row in colbert_raw or []]
    return {
        "schema": "mimirq.bge_m3_triplet.v1",
        "dense": dense,
        "sparse": sparse,
        "colbert": colbert,
    }


def build_bge_m3_tri_index_payload(
    *,
    chunk_id: str,
    text: str,
    metadata: dict[str, Any] | None,
    dense_fn: Callable[[str], list[float]],
    sparse_fn: Callable[[str], dict[str, float]] | None = None,
    colbert_fn: Callable[[str], list[list[float]]] | None = None,
) -> BgeM3TriIndexPayload:
    resolved_chunk_id = chunk_id.strip()
    subindex = build_chunk_type_subindex_payload(
        chunk_id=resolved_chunk_id,
        content=text,
        meta=dict(metadata or {}),
    )
    chunk_type = str(subindex["chunk_type"] or "text")

    payload = build_bge_m3_triplet_payload(
        text=text,
        dense_fn=dense_fn,
        sparse_fn=sparse_fn,
        colbert_fn=colbert_fn,
    )

    views: list[BgeM3IndexView] = []
    dense = payload["dense"]
    if dense:
        views.append(
            {
                "view": "dense",
                "view_id": f"{resolved_chunk_id}:dense",
                "subindex_key": chunk_type,
                "payload": dense,
                "metadata": {"chunk_type": chunk_type},
            }
        )

    sparse = payload["sparse"]
    if sparse:
        views.append(
            {
                "view": "sparse",
                "view_id": f"{resolved_chunk_id}:sparse",
                "subindex_key": chunk_type,
                "payload": sparse,
                "metadata": {"chunk_type": chunk_type},
            }
        )

    colbert = payload["colbert"]
    if colbert:
        views.append(
            {
                "view": "colbert",
                "view_id": f"{resolved_chunk_id}:colbert",
                "subindex_key": chunk_type,
                "payload": colbert,
                "metadata": {"chunk_type": chunk_type},
            }
        )

    return {
        "schema": "mimirq.bge_m3_tri_index.v1",
        "chunk_id": resolved_chunk_id,
        "chunk_type": chunk_type,
        "subindex_key": str(subindex["subindex_key"]),
        "views": views,
    }


__all__ = ["build_bge_m3_tri_index_payload", "build_bge_m3_triplet_payload"]
