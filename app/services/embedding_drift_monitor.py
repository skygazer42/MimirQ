
import math
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.constants import EmbeddingProviders
from app.models.document import Document as DBDocument
from app.models.document import DocumentChunk
from app.rag.embedding import create_langchain_embeddings_from_config
from app.rag.embedding.utils import current_embedding_space_hash


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _percentile(sorted_values: list[float], p: float) -> float | None:
    if not sorted_values:
        return None
    if p <= 0:
        return float(sorted_values[0])
    if p >= 100:
        return float(sorted_values[-1])

    n = len(sorted_values)
    pos = (p / 100.0) * (n - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return float(sorted_values[lo])
    frac = pos - lo
    return float(sorted_values[lo] * (1.0 - frac) + sorted_values[hi] * frac)


def _cosine_distance(a: list[float], b: list[float]) -> float | None:
    if not a or not b:
        return None
    if len(a) != len(b):
        return None

    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b, strict=False):
        fx = float(x)
        fy = float(y)
        dot += fx * fy
        norm_a += fx * fx
        norm_b += fy * fy

    if norm_a <= 0.0 or norm_b <= 0.0:
        return None

    denom = math.sqrt(norm_a) * math.sqrt(norm_b)
    if denom <= 0.0:
        return None

    cos = dot / denom
    if cos > 1.0:
        cos = 1.0
    elif cos < -1.0:
        cos = -1.0
    return 1.0 - cos


def _summarize_distances(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {
            "count": 0,
            "avg": None,
            "min": None,
            "p50": None,
            "p95": None,
            "p99": None,
            "max": None,
        }

    sorted_values = sorted(float(v) for v in values)
    count = len(sorted_values)
    avg = sum(sorted_values) / float(count)
    return {
        "count": count,
        "avg": float(avg),
        "min": float(sorted_values[0]),
        "p50": _percentile(sorted_values, 50.0),
        "p95": _percentile(sorted_values, 95.0),
        "p99": _percentile(sorted_values, 99.0),
        "max": float(sorted_values[-1]),
    }


def _init_embedding_model_for_drift():
    provider = (settings.EMBEDDING_PROVIDER or "local").lower()
    mapped_provider = EmbeddingProviders.PROVIDER_MAP.get(provider, "openai_compatible")
    api_key = settings.EMBEDDING_API_KEY or settings.LLM_API_KEY
    base_url = settings.EMBEDDING_API_BASE or settings.LLM_API_BASE
    return create_langchain_embeddings_from_config(
        provider=mapped_provider,
        model=str(settings.EMBEDDING_MODEL or "text-embedding-3-small"),
        api_key=api_key or "",
        base_url=base_url or "",
        dimension=None,  # Auto-detect
    )


@dataclass(frozen=True)
class _DriftSampleItem:
    vector_id: str
    content: str
    stored_space: str | None


def run_embedding_drift_monitor(
    *,
    db: Session,
    tenant_id: UUID,
    dataset_id: UUID | None = None,
    document_id: UUID | None = None,
    sample_n: int = 200,
    drift_threshold: float = 0.05,
    max_ids_per_query: int = 128,
    max_content_chars: int = 8000,
) -> dict[str, Any]:
    """
    Best-effort embedding drift monitor (Phase 1, PII-safe).

    Compares stored vectors (Milvus) with re-embedded vectors (current embedding config)
    for a bounded sample of active document chunks, and aggregates drift statistics.

    Output intentionally does NOT include chunk/document identifiers or raw content.
    """
    vector_backend = str(getattr(settings, "VECTOR_BACKEND", "milvus") or "milvus").strip().lower()
    current_space = str(current_embedding_space_hash() or "").strip() or None

    cap = max(0, int(sample_n or 0))
    cap = min(cap, 2000)
    threshold = float(drift_threshold)

    payload: dict[str, Any] = {
        "schema": "mimirq.embedding_drift_snapshot.v1",
        "ts": _utc_now_iso(),
        "ok": True,
        "vector_backend": vector_backend,
        "current_embedding_space_hash": current_space,
        "sample_n_requested": int(sample_n or 0),
        "sample_n_used": int(cap),
        "threshold": float(threshold),
        "scope": {
            "dataset_scoped": bool(dataset_id is not None),
            "document_scoped": bool(document_id is not None),
        },
    }

    if cap <= 0:
        payload["ok"] = False
        payload["error"] = "sample_n_must_be_positive"
        return payload

    if vector_backend != "milvus":
        payload["ok"] = False
        payload["error"] = "unsupported_vector_backend"
        return payload

    # "Active" documents: searchable in RAG (mirrors retrieval readiness checks).
    doc_ready_clause = or_(
        DBDocument.status == "completed",
        (DBDocument.doc_metadata["active_pipeline_ready"].astext == "true"),  # type: ignore[attr-defined]
    )

    # Active pipeline hash: chunks must match this version to be considered "active".
    doc_active_hash = func.coalesce(
        DBDocument.doc_metadata["active_pipeline_hash"].astext,  # type: ignore[attr-defined]
        DBDocument.doc_metadata["pipeline_hash"].astext,  # type: ignore[attr-defined]
        "",
    )
    chunk_hash = func.coalesce(
        DocumentChunk.doc_metadata["pipeline_hash"].astext,  # type: ignore[attr-defined]
        "",
    )

    chunks_q = (
        db.query(
            DocumentChunk.vector_id,
            DocumentChunk.content,
            DocumentChunk.doc_metadata,
        )
        .join(
            DBDocument,
            and_(
                DBDocument.id == DocumentChunk.document_id,
                DBDocument.tenant_id == DocumentChunk.tenant_id,
            ),
        )
        .filter(
            DBDocument.tenant_id == tenant_id,
            DBDocument.archived_at.is_(None),
            DBDocument.disabled_at.is_(None),
        )
        .filter(doc_ready_clause)
        .filter(DocumentChunk.disabled_at.is_(None))
        .filter(chunk_hash == doc_active_hash)
    )

    if dataset_id is not None:
        chunks_q = chunks_q.filter(DBDocument.dataset_id == dataset_id)
    if document_id is not None:
        chunks_q = chunks_q.filter(DBDocument.id == document_id)

    rows = (
        chunks_q.order_by(
            DocumentChunk.updated_at.desc().nullslast(),  # type: ignore[attr-defined]
            DocumentChunk.id.asc(),
        )
        .limit(cap)
        .all()
    )

    items: list[_DriftSampleItem] = []
    stored_space_counts: Counter[str] = Counter()
    for row in rows:
        if not row or len(row) < 3:
            continue
        vector_id_raw, content_raw, meta_raw = row
        vector_id = str(vector_id_raw or "").strip()
        if not vector_id:
            continue
        content = str(content_raw or "")
        if not content.strip():
            continue
        if int(max_content_chars or 0) > 0 and len(content) > int(max_content_chars or 0):
            content = content[: int(max_content_chars or 0)]
        meta = meta_raw if isinstance(meta_raw, dict) else {}
        stored_space = str(meta.get("embedding_space_hash") or "").strip() or None
        if stored_space:
            stored_space_counts[stored_space] += 1
        items.append(_DriftSampleItem(vector_id=vector_id, content=content, stored_space=stored_space))

    payload["sampled_items"] = int(len(items))
    payload["stored_embedding_space_hash_counts"] = dict(stored_space_counts.most_common(10))

    if not items:
        payload["drift"] = _summarize_distances([])
        payload["missing_vectors"] = 0
        payload["dim_mismatch"] = 0
        payload["above_threshold"] = {"count": 0, "ratio": 0.0}
        return payload

    from app.storage.vector.milvus import milvus_store

    vector_ids = [x.vector_id for x in items]
    stored_vectors = milvus_store.fetch_vectors_by_ids(vector_ids, max_ids_per_query=max_ids_per_query)
    payload["stored_vectors_fetched"] = int(len(stored_vectors))

    items_with_vectors: list[_DriftSampleItem] = [x for x in items if x.vector_id in stored_vectors]
    missing_vectors = int(len(items) - len(items_with_vectors))
    payload["missing_vectors"] = int(missing_vectors)

    if not items_with_vectors:
        payload["drift"] = _summarize_distances([])
        payload["dim_mismatch"] = 0
        payload["above_threshold"] = {"count": 0, "ratio": 0.0}
        return payload

    emb = _init_embedding_model_for_drift()
    try:
        reembedded = emb.embed_documents([x.content for x in items_with_vectors])
    except Exception as exc:
        payload["ok"] = False
        payload["error"] = f"embed_failed:{type(exc).__name__}"
        return payload

    distances: list[float] = []
    dim_mismatch = 0
    for item, new_vec in zip(items_with_vectors, reembedded, strict=False):
        stored_vec = stored_vectors.get(item.vector_id)
        if not stored_vec:
            continue
        if not isinstance(new_vec, list) or not new_vec:
            continue
        if len(stored_vec) != len(new_vec):
            dim_mismatch += 1
            continue
        d = _cosine_distance(stored_vec, [float(x) for x in new_vec])
        if d is None:
            continue
        distances.append(float(d))

    payload["dim_mismatch"] = int(dim_mismatch)
    payload["drift"] = _summarize_distances(distances)
    above = [d for d in distances if d >= threshold]
    ratio = (len(above) / len(distances)) if distances else 0.0
    payload["above_threshold"] = {"count": int(len(above)), "ratio": float(ratio)}
    return payload


__all__ = [
    "run_embedding_drift_monitor",
]

