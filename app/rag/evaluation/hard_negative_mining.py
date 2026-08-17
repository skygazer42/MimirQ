"""
PII-safe hard negative mining helpers for LTR training.

Wave7(A) goals:
- Mine "near-miss" negatives (ranked above first positive) from regression traces.
- Output must be PII-safe by construction: NO raw query/document text.
- Deterministic and bounded (stable schema, caps).
"""


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


def _normalize_trace_citations(citations: list[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen_chunks: set[str] = set()
    for rank, citation in enumerate(citations, 1):
        if not isinstance(citation, dict):
            continue
        chunk_id = _safe_str(citation.get("chunk_id"), max_len=200)
        if not chunk_id or chunk_id in seen_chunks:
            continue
        seen_chunks.add(chunk_id)
        rows.append(
            {
                "rank": rank,
                "chunk_id": chunk_id,
                "document_id": _safe_str(citation.get("document_id"), max_len=200),
                "relevance_score": citation.get("relevance_score"),
                "vector_score": citation.get("vector_score"),
                "bm25_score": citation.get("bm25_score"),
            }
        )
    return rows


def _first_positive(
    rows: list[dict[str, Any]],
    reference_chunk_ids: set[str],
) -> tuple[int | None, list[dict[str, Any]]]:
    for row in rows:
        chunk_id = row.get("chunk_id")
        if chunk_id and chunk_id in reference_chunk_ids:
            rank = int(row.get("rank") or 0)
            return rank or None, [{"chunk_id": chunk_id, "rank": rank}]
    return None, []


def _hard_candidates_before_positive(
    rows: list[dict[str, Any]],
    reference_chunk_ids: set[str],
    first_positive_rank: int | None,
) -> list[dict[str, Any]]:
    if first_positive_rank is None:
        return []
    candidates: list[dict[str, Any]] = []
    for row in rows:
        rank = int(row.get("rank") or 0)
        chunk_id = row.get("chunk_id")
        if rank >= first_positive_rank:
            break
        if chunk_id and chunk_id not in reference_chunk_ids:
            candidates.append(row)
    return candidates


def _select_hard_candidates(
    candidates: list[dict[str, Any]],
    *,
    max_hard_negatives: int,
    max_negatives_per_document: int,
) -> tuple[list[dict[str, Any]], int]:
    selected: list[dict[str, Any]] = []
    per_document_counts: dict[str, int] = {}
    dropped = 0
    for row in candidates:
        document_id = row.get("document_id") or ""
        used = int(per_document_counts.get(document_id, 0) or 0)
        if max_negatives_per_document > 0 and document_id and used >= max_negatives_per_document:
            dropped += 1
            continue
        if max_negatives_per_document > 0 and document_id:
            per_document_counts[document_id] = used + 1
        selected.append(row)
        if max_hard_negatives > 0 and len(selected) >= max_hard_negatives:
            break
    return selected, dropped


def _compact_hard_negative_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "chunk_id": row.get("chunk_id"),
            "document_id": row.get("document_id"),
            "rank": _coerce_nonneg_int(row.get("rank")),
        }
        for row in rows
    ]


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
    rows = _normalize_trace_citations(citations)
    first_pos_rank, positives = _first_positive(rows, ref_chunk_ids)
    hard_candidates = _hard_candidates_before_positive(rows, ref_chunk_ids, first_pos_rank)
    hard_selected, dedup_dropped = _select_hard_candidates(
        hard_candidates,
        max_hard_negatives=max_hard,
        max_negatives_per_document=per_doc_cap,
    )
    hard_out = _compact_hard_negative_rows(hard_selected)

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


def _empty_merged_hard_negative_record() -> dict[str, Any]:
    return {
        "schema": HARD_NEGATIVES_SCHEMA_V1,
        "query_hash": "",
        "retrieval_config_hash": None,
        "hard_negatives": [],
        "stats": {"sources_merged": 0, "hard_negatives_selected": 0, "dedup_dropped": 0},
    }


def _first_safe_record_value(
    rows: list[dict[str, Any]],
    key: str,
    *,
    max_len: int,
) -> str | None:
    for row in rows:
        value = _safe_str(row.get(key), max_len=max_len)
        if value:
            return value
    return None


def _collect_record_dicts(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    for row in rows:
        values = row.get(key)
        if isinstance(values, list):
            collected.extend(value for value in values if isinstance(value, dict))
    return collected


def _sum_record_stats(rows: list[dict[str, Any]]) -> dict[str, int]:
    totals = {
        "citations_total": 0,
        "candidates_before_first_positive": 0,
        "hard_negatives_selected": 0,
        "dedup_dropped": 0,
    }
    for row in rows:
        stats = row.get("stats")
        if not isinstance(stats, dict):
            continue
        for key in totals:
            totals[key] += _coerce_nonneg_int(stats.get(key))
    return totals


def _dedupe_positive_rows(rows: list[dict[str, Any]], *, max_items: int = 5) -> list[dict[str, Any]]:
    seen: set[str] = set()
    output: list[dict[str, Any]] = []
    for row in rows:
        chunk_id = _safe_str(row.get("chunk_id"), max_len=200)
        rank = _coerce_nonneg_int(row.get("rank"))
        if not chunk_id or rank <= 0 or chunk_id in seen:
            continue
        seen.add(chunk_id)
        output.append({"chunk_id": chunk_id, "rank": rank})
        if len(output) >= max_items:
            break
    return output


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
        return _empty_merged_hard_negative_record()

    query_hash = _first_safe_record_value(rows, "query_hash", max_len=64) or ""
    retrieval_config_hash = _first_safe_record_value(rows, "retrieval_config_hash", max_len=128)
    hard_rows = _collect_record_dicts(rows, "hard_negatives")
    stats_sum = _sum_record_stats(rows)

    hard_merged, dedup_extra = _dedupe_chunk_rows(hard_rows, max_hard_negatives=max_hard_negatives)
    stats_sum["dedup_dropped"] += int(dedup_extra)
    stats_sum["hard_negatives_selected"] = int(len(hard_merged))
    stats_sum["sources_merged"] = int(len(rows))

    pos_out = _dedupe_positive_rows(_collect_record_dicts(rows, "positives"))

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


def _parse_hard_negative_line(line: str) -> tuple[str, list[Any]] | None:
    text = str(line or "").strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except Exception:
        get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
        return None
    if not isinstance(payload, dict) or str(payload.get("schema") or "") != HARD_NEGATIVES_SCHEMA_V1:
        return None
    query_hash = _safe_str(payload.get("query_hash"), max_len=64)
    hard_negatives = payload.get("hard_negatives") or []
    if not query_hash or not isinstance(hard_negatives, list) or not hard_negatives:
        return None
    return query_hash, hard_negatives


def _append_loaded_hard_negatives(
    output: dict[str, list[str]],
    seen_by_query: dict[str, set[str]],
    *,
    query_hash: str,
    rows: list[Any],
) -> None:
    seen = seen_by_query.setdefault(query_hash, set())
    bucket = output.setdefault(query_hash, [])
    for row in rows:
        if not isinstance(row, dict):
            continue
        chunk_id = _safe_str(row.get("chunk_id"), max_len=200)
        if not chunk_id or chunk_id in seen:
            continue
        seen.add(chunk_id)
        bucket.append(chunk_id)
        if len(bucket) >= 200:
            break


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
            parsed = _parse_hard_negative_line(line)
            if parsed is None:
                continue
            query_hash, rows = parsed
            _append_loaded_hard_negatives(
                out,
                seen_by_query,
                query_hash=query_hash,
                rows=rows,
            )

    return out


__all__ = [
    "HARD_NEGATIVES_SCHEMA_V1",
    "load_hard_negatives_jsonl",
    "merge_hard_negative_records",
    "mine_hard_negatives_for_case_from_trace",
]
