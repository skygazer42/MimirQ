"""
PII-safe hard negative mining helpers for LTR training.

Wave7(A) goals:
- Mine "near-miss" negatives (ranked above first positive) from regression traces.
- Output must be PII-safe by construction: NO raw query/document text.
- Deterministic and bounded (stable schema, caps).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from app.rag.core.logging import get_logger

HARD_NEGATIVES_SCHEMA_V1 = "mimirq.hard_negatives.v1"


def _coerce_nonneg_int(value: Any) -> int:
    try:
        iv = int(value) if value is not None else 0
    except Exception:
        return 0
    return iv if iv >= 0 else 0


def _safe_str(value: Any, *, max_len: int = 200) -> str | None:
    s = str(value or "").strip()
    if not s:
        return None
    lim = max(0, int(max_len or 0))
    if lim <= 0:
        return s
    return s[:lim]


def _extract_reference_chunk_ids(case: dict[str, Any]) -> set[str]:
    refs = case.get("reference_sources") or []
    if not isinstance(refs, list):
        return set()
    out: set[str] = set()
    for src in refs:
        if not isinstance(src, dict):
            continue
        cid = _safe_str(src.get("chunk_id"), max_len=200)
        if cid:
            out.add(cid)
    return out


def _dedupe_chunk_rows(
    rows: list[dict[str, Any]],
    *,
    max_hard_negatives: int = 10,
) -> tuple[list[dict[str, Any]], int]:
    cap = max(0, int(max_hard_negatives or 0))
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    dropped = 0
    for row in (rows or []):
        if not isinstance(row, dict):
            continue
        cid = _safe_str(row.get("chunk_id"), max_len=200)
        if not cid:
            continue
        if cid in seen:
            dropped += 1
            continue
        seen.add(cid)
        payload = {
            "chunk_id": cid,
            "document_id": _safe_str(row.get("document_id"), max_len=200),
            "rank": _coerce_nonneg_int(row.get("rank")),
        }
        out.append(payload)
        if cap > 0 and len(out) >= cap:
            break
    return out, dropped


def _trace_retrieval_config_hash(trace_record: dict[str, Any]) -> str | None:
    retrieval = trace_record.get("retrieval")
    if isinstance(retrieval, dict):
        cfg = _safe_str(retrieval.get("retrieval_config_hash"), max_len=128)
        if cfg:
            return cfg
    return _safe_str(trace_record.get("retrieval_config_hash"), max_len=128)


def mine_hard_negatives_for_case_from_trace(
    *,
    case: dict[str, Any],
    trace_record: dict[str, Any],
    query_hash: str,
    max_hard_negatives: int = 10,
    max_negatives_per_document: int = 2,
) -> dict[str, Any]:
    """
    Mine hard negatives from a single trace record for one regression case.

    "Hard negatives" are defined as:
    - retrieved citations with chunk_id NOT in reference_sources
    - ranked before the first positive chunk_id (near-miss)

    The output is PII-safe and MUST NOT include raw query text.
    """
    qh = _safe_str(query_hash, max_len=64) or ""
    ref_chunk_ids = _extract_reference_chunk_ids(case)
    max_hard = max(0, int(max_hard_negatives or 0))
    per_doc_cap = max(0, int(max_negatives_per_document or 0))

    citations_raw = trace_record.get("citations") or []
    citations = citations_raw if isinstance(citations_raw, list) else []

    # Normalize and dedupe by chunk_id (first occurrence wins).
    rows: list[dict[str, Any]] = []
    seen_chunks: set[str] = set()
    for idx, c in enumerate(citations, 1):
        if not isinstance(c, dict):
            continue
        cid = _safe_str(c.get("chunk_id"), max_len=200)
        if not cid or cid in seen_chunks:
            continue
        seen_chunks.add(cid)

        did = _safe_str(c.get("document_id"), max_len=200)
        rows.append(
            {
                "rank": int(idx),
                "chunk_id": cid,
                "document_id": did,
                # keep only numeric scores (PII-safe); helpful for inspection/debug.
                "relevance_score": c.get("relevance_score"),
                "vector_score": c.get("vector_score"),
                "bm25_score": c.get("bm25_score"),
            }
        )

    first_pos_rank: int | None = None
    positives: list[dict[str, Any]] = []
    for r in rows:
        cid = r.get("chunk_id")
        if cid and cid in ref_chunk_ids:
            first_pos_rank = int(r.get("rank") or 0) or None
            positives.append({"chunk_id": cid, "rank": int(r.get("rank") or 0)})
            break

    hard_candidates: list[dict[str, Any]] = []
    if first_pos_rank is not None:
        for r in rows:
            rank = int(r.get("rank") or 0)
            cid = r.get("chunk_id")
            if not cid or cid in ref_chunk_ids:
                continue
            if rank >= int(first_pos_rank):
                break
            hard_candidates.append(r)

    # "Clustering" / governance: cap negatives per document_id to avoid overfitting on one doc.
    hard_selected: list[dict[str, Any]] = []
    per_doc_counts: dict[str, int] = {}
    dedup_dropped = 0
    for r in hard_candidates:
        did = r.get("document_id") or ""
        if per_doc_cap > 0 and did:
            used = int(per_doc_counts.get(did, 0) or 0)
            if used >= per_doc_cap:
                dedup_dropped += 1
                continue
            per_doc_counts[did] = used + 1
        hard_selected.append(r)
        if max_hard > 0 and len(hard_selected) >= max_hard:
            break

    hard_out: list[dict[str, Any]] = []
    for r in hard_selected:
        hard_out.append(
            {
                "chunk_id": r.get("chunk_id"),
                "document_id": r.get("document_id"),
                "rank": _coerce_nonneg_int(r.get("rank")),
            }
        )

    out: dict[str, Any] = {
        "schema": HARD_NEGATIVES_SCHEMA_V1,
        "query_hash": qh,
        "retrieval_config_hash": _trace_retrieval_config_hash(trace_record),
        "hard_negatives": hard_out,
    }
    if positives:
        out["positives"] = positives[:5]

    stats = {
        "citations_total": int(len(citations)),
        "candidates_before_first_positive": int(len(hard_candidates)),
        "hard_negatives_selected": int(len(hard_out)),
        "dedup_dropped": int(dedup_dropped),
    }
    out["stats"] = stats
    return out


def merge_hard_negative_records(
    *,
    records: list[dict[str, Any]] | None,
    max_hard_negatives: int = 10,
) -> dict[str, Any]:
    """
    Merge multiple mined hard-negative records for the same query hash.

    Deterministic:
    - preserve source order
    - dedupe by chunk_id
    - bound output by max_hard_negatives
    """
    rows = [r for r in (records or []) if isinstance(r, dict)]
    if not rows:
        return {
            "schema": HARD_NEGATIVES_SCHEMA_V1,
            "query_hash": "",
            "retrieval_config_hash": None,
            "hard_negatives": [],
            "stats": {"sources_merged": 0, "hard_negatives_selected": 0, "dedup_dropped": 0},
        }

    query_hash = ""
    retrieval_config_hash: str | None = None
    positives: list[dict[str, Any]] = []
    hard_rows: list[dict[str, Any]] = []
    stats_sum: dict[str, int] = {
        "citations_total": 0,
        "candidates_before_first_positive": 0,
        "hard_negatives_selected": 0,
        "dedup_dropped": 0,
    }

    for row in rows:
        if not query_hash:
            query_hash = _safe_str(row.get("query_hash"), max_len=64) or ""
        if retrieval_config_hash is None:
            retrieval_config_hash = _safe_str(row.get("retrieval_config_hash"), max_len=128)

        hard = row.get("hard_negatives")
        if isinstance(hard, list):
            hard_rows.extend([x for x in hard if isinstance(x, dict)])

        pos = row.get("positives")
        if isinstance(pos, list):
            for p in pos:
                if not isinstance(p, dict):
                    continue
                cid = _safe_str(p.get("chunk_id"), max_len=200)
                rank = _coerce_nonneg_int(p.get("rank"))
                if cid and rank > 0:
                    positives.append({"chunk_id": cid, "rank": rank})

        rec_stats = row.get("stats")
        if isinstance(rec_stats, dict):
            for key in stats_sum:
                stats_sum[key] += _coerce_nonneg_int(rec_stats.get(key))

    hard_merged, dedup_extra = _dedupe_chunk_rows(hard_rows, max_hard_negatives=max_hard_negatives)
    stats_sum["dedup_dropped"] += int(dedup_extra)
    stats_sum["hard_negatives_selected"] = int(len(hard_merged))
    stats_sum["sources_merged"] = int(len(rows))

    # Keep at most 5 unique positives for debugging parity.
    pos_seen: set[str] = set()
    pos_out: list[dict[str, Any]] = []
    for p in positives:
        cid = str(p.get("chunk_id") or "")
        if not cid or cid in pos_seen:
            continue
        pos_seen.add(cid)
        pos_out.append({"chunk_id": cid, "rank": _coerce_nonneg_int(p.get("rank"))})
        if len(pos_out) >= 5:
            break

    out: dict[str, Any] = {
        "schema": HARD_NEGATIVES_SCHEMA_V1,
        "query_hash": query_hash,
        "retrieval_config_hash": retrieval_config_hash,
        "hard_negatives": hard_merged,
        "stats": stats_sum,
    }
    if pos_out:
        out["positives"] = pos_out
    return out


def load_hard_negatives_jsonl(path: str | Path) -> dict[str, list[str]]:
    """
    Load a hard-negative JSONL file into a lookup:
      { query_hash: [chunk_id, ...] }

    Deterministic:
    - preserves input order
    - dedupes chunk_ids per query_hash
    - bounded (per query)
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(p)

    out: dict[str, list[str]] = {}
    seen_by_query: dict[str, set[str]] = {}

    with p.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = (line or "").strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
                continue
            if not isinstance(obj, dict):
                continue
            if str(obj.get("schema") or "") != HARD_NEGATIVES_SCHEMA_V1:
                continue

            qh = _safe_str(obj.get("query_hash"), max_len=64)
            if not qh:
                continue

            hn_raw = obj.get("hard_negatives") or []
            if not isinstance(hn_raw, list) or not hn_raw:
                continue

            seen = seen_by_query.setdefault(qh, set())
            bucket = out.setdefault(qh, [])
            for item in hn_raw:
                if not isinstance(item, dict):
                    continue
                cid = _safe_str(item.get("chunk_id"), max_len=200)
                if not cid or cid in seen:
                    continue
                seen.add(cid)
                bucket.append(cid)
                if len(bucket) >= 200:
                    break

    return out


__all__ = [
    "HARD_NEGATIVES_SCHEMA_V1",
    "load_hard_negatives_jsonl",
    "merge_hard_negative_records",
    "mine_hard_negatives_for_case_from_trace",
]
