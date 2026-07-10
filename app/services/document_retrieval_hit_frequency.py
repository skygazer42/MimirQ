"""
Best-effort document retrieval hit frequency (Gap10).

We approximate "document hit frequency" by scanning the metrics JSONL tail for
recent `rag_trace` events and counting citations that reference a document_id.

Design constraints:
- PII-safe output: counts only (no queries, no chunk text)
- Bounded IO: tail-read of the metrics file (max_bytes)
"""


import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from app.core.config import settings
from app.rag.core.logging import get_logger

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
    max_bytes = max(1, int(max_bytes or 0))
    try:
        st = path.stat()
        size = int(st.st_size)
    except Exception:
        return [], False

    start = max(0, size - max_bytes)
    truncated = start > 0

    try:
        with path.open("rb") as f:
            if start:
                f.seek(start)
            raw = f.read()
    except Exception:
        return [], truncated

    if start:
        nl = raw.find(b"\n")
        if nl >= 0:
            raw = raw[nl + 1 :]

    try:
        text = raw.decode("utf-8", errors="replace")
    except Exception:
        return [], truncated

    records: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = (line or "").strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
            continue
        if isinstance(obj, dict):
            records.append(obj)
    return records, truncated


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

    if not enabled:
        return {
            "enabled": False,
            "available": False,
            "path": path_str,
            "window_minutes": window_minutes_i,
            "max_bytes": max_bytes_i,
            "truncated": False,
            "traces_scanned": 0,
            "traces_with_hits": 0,
            "citations_matched": 0,
            "unique_chunks_matched": 0,
            "hit_rate": None,
        }

    if not path.exists():
        return {
            "enabled": True,
            "available": False,
            "path": path_str,
            "window_minutes": window_minutes_i,
            "max_bytes": max_bytes_i,
            "truncated": False,
            "traces_scanned": 0,
            "traces_with_hits": 0,
            "citations_matched": 0,
            "unique_chunks_matched": 0,
            "hit_rate": None,
        }

    raw_records, truncated = _read_jsonl_tail(path, max_bytes=max_bytes_i)

    tenant_key = str(tenant_id)
    doc_key = str(document_id)

    traces_scanned = 0
    traces_with_hits = 0
    citations_matched = 0
    unique_chunk_ids: set[str] = set()

    for r in raw_records:
        try:
            if str(r.get("event") or "") != "rag_trace":
                continue
            if str(r.get("tenant_id") or "") != tenant_key:
                continue
            ts_ms = _to_int(r.get("ts_ms")) or 0
            if ts_ms and ts_ms < cutoff_ms:
                continue
            traces_scanned += 1

            citations = r.get("citations")
            if not isinstance(citations, list) or not citations:
                continue

            hit_this_trace = False
            for c in citations:
                if not isinstance(c, dict):
                    continue
                if str(c.get("document_id") or "") != doc_key:
                    continue
                citations_matched += 1
                hit_this_trace = True
                cid = str(c.get("chunk_id") or "").strip()
                if cid:
                    unique_chunk_ids.add(cid)

            if hit_this_trace:
                traces_with_hits += 1
        except Exception:
            # Best-effort: never break health card due to one bad line.
            get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
            continue

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
