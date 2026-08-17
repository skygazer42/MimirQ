"""
Best-effort document retrieval hit frequency (Gap10).

We approximate "document hit frequency" by scanning the metrics JSONL tail for
recent `rag_trace` events and counting citations that reference a document_id.

Design constraints:
- PII-safe output: counts only (no queries, no chunk text)
- Bounded IO: tail-read of the metrics file (max_bytes)
"""


from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from app.core.config import settings
from app.rag.core.logging import get_logger
from app.services.jsonl_tail import read_jsonl_tail

logger = get_logger("document_retrieval_hit_frequency")


def _to_int(v: Any) -> int | None:
    try:
        if v is None:
            return None
        return int(v)
    except Exception:
        return None


def _read_jsonl_tail(path: Path, *, max_bytes: int) -> tuple[list[dict[str, Any]], bool]:
    """
    Return: (records, truncated)
    `truncated=true` means we did not read the entire file, so results might be incomplete.
    """
    return read_jsonl_tail(path, max_bytes=max_bytes)


def _unavailable_summary(
    *,
    enabled: bool,
    path: str,
    window_minutes: int,
    max_bytes: int,
) -> dict[str, Any]:
    return {
        "enabled": enabled,
        "available": False,
        "path": path,
        "window_minutes": window_minutes,
        "max_bytes": max_bytes,
        "truncated": False,
        "traces_scanned": 0,
        "traces_with_hits": 0,
        "citations_matched": 0,
        "unique_chunks_matched": 0,
        "hit_rate": None,
    }


def _count_matching_citations(
    citations: list[Any],
    *,
    document_id: str,
    unique_chunk_ids: set[str],
) -> int:
    matched = 0
    for citation in citations:
        if not isinstance(citation, dict):
            continue
        if str(citation.get("document_id") or "") != document_id:
            continue
        matched += 1
        chunk_id = str(citation.get("chunk_id") or "").strip()
        if chunk_id:
            unique_chunk_ids.add(chunk_id)
    return matched


def _scan_trace_hits(
    records: list[dict[str, Any]],
    *,
    tenant_id: str,
    document_id: str,
    cutoff_ms: int,
) -> tuple[int, int, int, set[str]]:
    traces_scanned = 0
    traces_with_hits = 0
    citations_matched = 0
    unique_chunk_ids: set[str] = set()
    for record in records:
        try:
            if str(record.get("event") or "") != "rag_trace":
                continue
            if str(record.get("tenant_id") or "") != tenant_id:
                continue
            ts_ms = _to_int(record.get("ts_ms")) or 0
            if ts_ms and ts_ms < cutoff_ms:
                continue
            traces_scanned += 1
            citations = record.get("citations")
            if not isinstance(citations, list) or not citations:
                continue
            matched = _count_matching_citations(
                citations,
                document_id=document_id,
                unique_chunk_ids=unique_chunk_ids,
            )
            citations_matched += matched
            if matched:
                traces_with_hits += 1
        except Exception:
            logger.debug("Skipping item after non-critical exception", exc_info=True)
    return traces_scanned, traces_with_hits, citations_matched, unique_chunk_ids


def compute_document_retrieval_hit_frequency(
    *,
    tenant_id: UUID,
    document_id: UUID,
    window_minutes: int = 60,
    max_bytes: int = 5_000_000,
    now: datetime | None = None,
) -> dict[str, Any]:
    enabled = bool(getattr(settings, "ENABLE_METRICS_LOG", False))
    path_str = str(getattr(settings, "METRICS_LOG_PATH", "./logs/rag_metrics.jsonl") or "./logs/rag_metrics.jsonl")
    path = Path(path_str)

    window_minutes_i = max(1, min(int(window_minutes or 0), 60 * 24 * 30))
    max_bytes_i = max(1, min(int(max_bytes or 0), 50_000_000))
    now0 = now or datetime.now(UTC)
    cutoff_ms = int(now0.timestamp() * 1000) - (window_minutes_i * 60 * 1000)

    if not enabled or not path.exists():
        return _unavailable_summary(
            enabled=enabled,
            path=path_str,
            window_minutes=window_minutes_i,
            max_bytes=max_bytes_i,
        )

    raw_records, truncated = _read_jsonl_tail(path, max_bytes=max_bytes_i)
    traces_scanned, traces_with_hits, citations_matched, unique_chunk_ids = _scan_trace_hits(
        raw_records,
        tenant_id=str(tenant_id),
        document_id=str(document_id),
        cutoff_ms=cutoff_ms,
    )

    hit_rate = (float(traces_with_hits) / float(traces_scanned)) if traces_scanned else None

    return {
        "enabled": True,
        "available": True,
        "path": path_str,
        "window_minutes": window_minutes_i,
        "max_bytes": max_bytes_i,
        "truncated": bool(truncated),
        "traces_scanned": int(traces_scanned),
        "traces_with_hits": int(traces_with_hits),
        "citations_matched": int(citations_matched),
        "unique_chunks_matched": int(len(unique_chunk_ids)),
        "hit_rate": (round(float(hit_rate), 4) if hit_rate is not None else None),
    }


__all__ = ["compute_document_retrieval_hit_frequency"]
