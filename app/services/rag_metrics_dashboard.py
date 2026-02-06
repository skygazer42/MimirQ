"""
RAG metrics dashboard helpers.

Reads the JSONL metrics log (when ENABLE_METRICS_LOG=true) and aggregates a small,
PII-safe summary for UI dashboards.

Design constraints:
- Best-effort: tolerate missing/partial/invalid JSON lines.
- Bounded: read only the tail of the metrics file (max_bytes) to avoid O(file_size).
- Safe: never return raw question/query/chunk text; only numeric + categorical aggregates.
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, List, Optional

from app.core.config import settings


def _percentile(values: List[float], p: float) -> Optional[float]:
    if not values:
        return None
    vals = sorted(float(v) for v in values if v is not None)
    if not vals:
        return None
    p = max(0.0, min(100.0, float(p)))
    if len(vals) == 1:
        return vals[0]
    k = (len(vals) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(vals) - 1)
    if f == c:
        return vals[f]
    d0 = vals[f] * (c - k)
    d1 = vals[c] * (k - f)
    return d0 + d1


def _mean(values: Iterable[float]) -> Optional[float]:
    vals: List[float] = []
    for v in values:
        try:
            fv = float(v)
        except Exception:
            continue
        vals.append(fv)
    if not vals:
        return None
    return sum(vals) / len(vals)


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
        raw = b""
        with path.open("rb") as f:
            if start:
                f.seek(start)
            raw = f.read()
    except Exception:
        return [], truncated

    if start:
        # Drop partial first line when reading from the middle.
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
            continue
        if isinstance(obj, dict):
            records.append(obj)
    return records, truncated


@dataclass(frozen=True)
class RagMetricsSummary:
    enabled: bool
    path: str
    window_minutes: int
    truncated: bool
    record_count: int
    rag_trace_count: int
    reranker_api_count: int
    retrieval_avg_elapsed_sec: float | None
    retrieval_p95_elapsed_sec: float | None
    rerank_avg_elapsed_sec: float | None
    citations_avg_count: float | None
    retriever_overfetch_count: int
    retriever_overfetch_avg_ratio: float | None
    retriever_filtered_acl_total: int
    retrieval_mode_counts: dict[str, int]
    hit_type_counts: dict[str, int]
    error_counts: dict[str, int]
    timeseries: dict[str, list[Any]]


def summarize_rag_metrics(
    *,
    tenant_id: str | None,
    window_minutes: int = 60,
    max_bytes: int = 5_000_000,
) -> RagMetricsSummary:
    """
    Build a small dashboard summary from the metrics JSONL file.
    """
    enabled = bool(getattr(settings, "ENABLE_METRICS_LOG", False))
    path_str = str(getattr(settings, "METRICS_LOG_PATH", "./logs/rag_metrics.jsonl") or "./logs/rag_metrics.jsonl")
    path = Path(path_str)

    window_minutes = max(1, int(window_minutes or 0))
    cutoff_ms = int(time.time() * 1000) - (window_minutes * 60 * 1000)

    raw_records, truncated_by_tail = _read_jsonl_tail(path, max_bytes=int(max_bytes or 0))

    # Tenant filter (avoid cross-tenant leakage on shared log files).
    tenant_key = str(tenant_id) if tenant_id else None
    records: list[dict[str, Any]] = []
    for r in raw_records:
        try:
            ts_ms = int(r.get("ts_ms") or 0)
        except Exception:
            ts_ms = 0
        if ts_ms and ts_ms < cutoff_ms:
            continue
        if tenant_key:
            rid = r.get("tenant_id")
            if rid and str(rid) != tenant_key:
                continue
        records.append(r)

    earliest_ts_ms: int | None = None
    for r in records:
        try:
            ts_ms = int(r.get("ts_ms") or 0)
        except Exception:
            continue
        if not ts_ms:
            continue
        if earliest_ts_ms is None or ts_ms < earliest_ts_ms:
            earliest_ts_ms = ts_ms
    truncated = bool(truncated_by_tail and earliest_ts_ms is not None and earliest_ts_ms > cutoff_ms)

    retrieval_elapsed: list[float] = []
    rerank_elapsed: list[float] = []
    citations_counts: list[int] = []
    retrieval_mode_counts: dict[str, int] = defaultdict(int)
    hit_type_counts: dict[str, int] = defaultdict(int)
    error_counts: dict[str, int] = defaultdict(int)

    overfetch_ratios: list[float] = []
    overfetch_count = 0
    filtered_acl_total = 0

    # Simple minute-bucket time series.
    bucket: dict[int, dict[str, Any]] = {}

    rag_trace_count = 0
    reranker_api_count = 0

    for r in records:
        event = str(r.get("event") or "")
        ts_ms = int(r.get("ts_ms") or 0) if r.get("ts_ms") is not None else 0
        minute_ms = (ts_ms // 60_000) * 60_000 if ts_ms else 0
        if minute_ms and minute_ms not in bucket:
            bucket[minute_ms] = {"ts_ms": minute_ms, "rag_trace": 0, "reranker_api": 0, "retrieval_elapsed_sum": 0.0}

        if event == "rag_trace":
            rag_trace_count += 1
            if minute_ms:
                bucket[minute_ms]["rag_trace"] += 1

            retrieval = r.get("retrieval") or {}
            mode = retrieval.get("mode")
            if mode:
                retrieval_mode_counts[str(mode)] += 1

            # Best-effort: retriever debug counters (if present).
            per_query = retrieval.get("per_query") if isinstance(retrieval, dict) else None
            if isinstance(per_query, list):
                for q in per_query:
                    if not isinstance(q, dict):
                        continue
                    dbg = q.get("retriever_debug")
                    if not isinstance(dbg, dict):
                        continue
                    try:
                        if bool(dbg.get("overfetch_enabled")):
                            overfetch_count += 1
                            req = int(dbg.get("requested_k") or 0)
                            search = int(dbg.get("search_k") or 0)
                            if req > 0 and search > 0:
                                overfetch_ratios.append(search / req)
                    except Exception:
                        pass
                    enrich1 = dbg.get("enrich_pass1")
                    if isinstance(enrich1, dict):
                        try:
                            filtered_acl_total += int(enrich1.get("filtered_acl") or 0)
                        except Exception:
                            pass

            # Citations are already structured for UI; ignore text, only aggregate numeric fields.
            citations = r.get("citations") or []
            if isinstance(citations, list):
                citations_counts.append(len(citations))
                for c in citations:
                    if not isinstance(c, dict):
                        continue
                    hit_type = c.get("hit_type")
                    if hit_type:
                        hit_type_counts[str(hit_type)] += 1
                    re_sec = c.get("retrieval_elapsed_sec")
                    if re_sec is not None:
                        try:
                            fv = float(re_sec)
                            if fv >= 0:
                                retrieval_elapsed.append(fv)
                                if minute_ms:
                                    bucket[minute_ms]["retrieval_elapsed_sum"] += fv
                        except Exception:
                            pass
                    rr_sec = c.get("rerank_elapsed_sec")
                    if rr_sec is not None:
                        try:
                            fv = float(rr_sec)
                            if fv >= 0:
                                rerank_elapsed.append(fv)
                        except Exception:
                            pass

            # Track errors (PII-safe): only keep short error strings.
            errors = retrieval.get("errors") if isinstance(retrieval, dict) else None
            if isinstance(errors, list):
                for e in errors:
                    s = (str(e) if e is not None else "").strip()
                    if not s:
                        continue
                    error_counts[s[:80]] += 1

        elif event == "reranker_api":
            reranker_api_count += 1
            if minute_ms:
                bucket[minute_ms]["reranker_api"] += 1
            if r.get("error"):
                error_counts["reranker_api_error"] += 1

    # Build timeseries arrays (sorted by time).
    ts_keys = sorted(k for k in bucket.keys() if k)
    series = {
        "ts_ms": [k for k in ts_keys],
        "rag_trace": [int(bucket[k]["rag_trace"]) for k in ts_keys],
        "reranker_api": [int(bucket[k]["reranker_api"]) for k in ts_keys],
        "retrieval_avg_elapsed_sec": [
            (bucket[k]["retrieval_elapsed_sum"] / bucket[k]["rag_trace"]) if bucket[k]["rag_trace"] else None
            for k in ts_keys
        ],
    }

    return RagMetricsSummary(
        enabled=enabled,
        path=path_str,
        window_minutes=int(window_minutes),
        truncated=bool(truncated),
        record_count=len(records),
        rag_trace_count=int(rag_trace_count),
        reranker_api_count=int(reranker_api_count),
        retrieval_avg_elapsed_sec=_mean(retrieval_elapsed),
        retrieval_p95_elapsed_sec=_percentile(retrieval_elapsed, 95.0),
        rerank_avg_elapsed_sec=_mean(rerank_elapsed),
        citations_avg_count=_mean(citations_counts),
        retriever_overfetch_count=int(overfetch_count),
        retriever_overfetch_avg_ratio=_mean(overfetch_ratios),
        retriever_filtered_acl_total=int(filtered_acl_total),
        retrieval_mode_counts=dict(retrieval_mode_counts),
        hit_type_counts=dict(hit_type_counts),
        error_counts=dict(error_counts),
        timeseries=series,
    )
