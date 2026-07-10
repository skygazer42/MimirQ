"""
PII-safe retrieval replay capture helpers.

Wave7(B) goals:
- Capture enough information to replay retrieval-only requests offline.
- Default capture format MUST be PII-safe: no raw query text, no document snippets.
- Provide deterministic fingerprints for candidate lists (for CI gating / diffs).
"""


import json
from typing import Any

from app.rag.core.hashing import stable_hash

RETRIEVAL_REPLAY_CAPTURE_SCHEMA_V1 = "mimirq.retrieval_replay_capture.v1"


_CAPTURE_CITATION_KEYS = frozenset(
    {
        # Identifiers / provenance (PII-safe identifiers only).
        "chunk_id",
        "document_id",
        "chunk_index",
        "page_number",
        "start_char",
        "end_char",
        "doc_pipeline_key",
        "pipeline_hash",
        "retrieval_role",
        "neighbor_of",
        # Scores / knobs
        "relevance_score",
        "vector_score",
        "bm25_score",
        "lexical_score",
        "sparse_score",
        "keyword_score",
        "rerank_score",
        "retrieval_score",
        "retriever_score",
        "reranker_provider",
        "retrieval_mode",
        "hit_type",
        # KG-derived ranking signals (optional; low-cardinality)
        "kg_pagerank",
        "kg_shared_events",
        "kg_path_length",
        "kg_edge_conf_low",
        "kg_edge_conf_mid",
        "kg_edge_conf_high",
        "kg_evidence_anchored",
        "kg_path",
    }
)


def sanitize_citations_for_capture(citations: Any, *, max_items: int = 80) -> list[dict[str, Any]]:
    """
    Return a PII-safe list of citations for capture.

    This strips all text fields (chunk_content, document_name, matched_terms, etc)
    and keeps only allowlisted identifiers + numeric signals.
    """
    if not isinstance(citations, list) or not citations:
        return []

    lim = max(0, int(max_items or 0))
    if lim <= 0:
        return []

    out: list[dict[str, Any]] = []
    for c in citations:
        if len(out) >= lim:
            break
        if not isinstance(c, dict):
            continue
        safe: dict[str, Any] = {}
        for k in _CAPTURE_CITATION_KEYS:
            if k in c and c.get(k) is not None:
                safe[k] = c.get(k)
        # Ensure we always include chunk_id when possible (for replay diffs).
        if "chunk_id" not in safe:
            cid = c.get("chunk_id")
            if cid is not None:
                safe["chunk_id"] = cid
        if safe:
            out.append(safe)
    return out


def _round_float(value: Any, *, digits: int = 3) -> float | None:
    try:
        if value is None:
            return None
        return round(float(value), int(digits))
    except Exception:
        return None


def fingerprint_citations(citations: Any) -> str:
    """
    Compute a stable fingerprint of a citation list (ordering-sensitive).

    This is used by deterministic replay runners to compare candidate lists across runs.
    """
    safe = sanitize_citations_for_capture(citations, max_items=200)
    cleaned: list[dict[str, Any]] = []
    for idx, c in enumerate(safe, 1):
        cleaned.append(
            {
                "rank": int(idx),
                "chunk_id": str(c.get("chunk_id") or ""),
                "document_id": str(c.get("document_id") or "") or None,
                "relevance_score": _round_float(c.get("relevance_score")),
                "retrieval_score": _round_float(c.get("retrieval_score")),
                "retrieval_role": (str(c.get("retrieval_role") or "") or None),
            }
        )

    payload = json.dumps(cleaned, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return stable_hash(payload, length=32)


def build_retrieval_replay_capture_record(
    *,
    query: str,
    dataset_id: str | None,
    document_ids: list[str] | None,
    rag_config: dict[str, Any],
    evidence_payload: dict[str, Any],
    seed: int | None = None,
    max_citations: int = 80,
) -> dict[str, Any]:
    """
    Build a single replay capture record from an Evidence API response payload.

    PII-safe by default:
    - stores query_hash + query_chars only (no raw query)
    - stores only allowlisted citation keys (no chunk_content)
    """
    q = str(query or "").strip()
    qh = stable_hash(q, length=16) if q else ""

    metrics = evidence_payload.get("metrics") if isinstance(evidence_payload.get("metrics"), dict) else {}
    retrieval_cfg_hash = str(metrics.get("retrieval_config_hash") or "").strip() or None

    citations_safe = sanitize_citations_for_capture(evidence_payload.get("citations"), max_items=int(max_citations or 0))

    rec: dict[str, Any] = {
        "schema": RETRIEVAL_REPLAY_CAPTURE_SCHEMA_V1,
        "query_hash": qh or None,
        "query_chars": int(len(q)) if q else 0,
        "dataset_id_hash": (stable_hash(str(dataset_id), length=16) if dataset_id else None),
        "document_ids_count": int(len(document_ids or [])),
        "rag_config": dict(rag_config or {}),
        "retrieval_config_hash": retrieval_cfg_hash,
        "seed": int(seed) if seed is not None else None,
        "citations": citations_safe,
        "citations_fingerprint": fingerprint_citations(citations_safe),
    }

    # Drop empty/None fields to keep JSONL small.
    return {k: v for k, v in rec.items() if v not in (None, [], {}, "")}


__all__ = [
    "RETRIEVAL_REPLAY_CAPTURE_SCHEMA_V1",
    "build_retrieval_replay_capture_record",
    "fingerprint_citations",
    "sanitize_citations_for_capture",
]

