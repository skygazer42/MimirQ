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

import gzip
import hashlib
import json
import math
import time
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.rag.core.logging import get_logger

DEFAULT_METRICS_LOG_PATH = "./logs/rag_metrics.jsonl"
logger = get_logger(__name__)
_METRICS_DASHBOARD_FALLBACK_LOG_MESSAGE = "Ignoring non-critical metrics dashboard fallback failure: %s"


def _percentile(values: list[float], p: float) -> float | None:
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


def _mean(values: Iterable[float]) -> float | None:
    vals: list[float] = []
    for v in values:
        try:
            fv = float(v)
        except Exception:
            continue
        vals.append(fv)
    if not vals:
        return None
    return sum(vals) / len(vals)


def _stddev(values: Iterable[float]) -> float | None:
    vals: list[float] = []
    for v in values:
        try:
            fv = float(v)
        except Exception:
            continue
        if not math.isfinite(fv):
            continue
        vals.append(fv)
    if not vals:
        return None
    if len(vals) == 1:
        return 0.0
    mu = _mean(vals)
    if mu is None:
        return None
    var = sum((x - mu) ** 2 for x in vals) / len(vals)
    return math.sqrt(max(0.0, var))


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
    retrieval_candidate_cache_hit_count: int
    retrieval_candidate_cache_store_ok_count: int
    retrieval_candidate_cache_backend_counts: dict[str, int]
    retrieval_candidate_cache_skip_reason_counts: dict[str, int]
    retrieval_rerank_skip_reason_counts: dict[str, int]
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
    path_str = str(getattr(settings, "METRICS_LOG_PATH", DEFAULT_METRICS_LOG_PATH) or DEFAULT_METRICS_LOG_PATH)
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
    retrieval_candidate_cache_hit_count = 0
    retrieval_candidate_cache_store_ok_count = 0
    retrieval_candidate_cache_backend_counts: dict[str, int] = defaultdict(int)
    retrieval_candidate_cache_skip_reason_counts: dict[str, int] = defaultdict(int)
    retrieval_rerank_skip_reason_counts: dict[str, int] = defaultdict(int)

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
                    except Exception as exc:
                        logger.debug(_METRICS_DASHBOARD_FALLBACK_LOG_MESSAGE, exc)
                    enrich1 = dbg.get("enrich_pass1")
                    if isinstance(enrich1, dict):
                        try:
                            filtered_acl_total += int(enrich1.get("filtered_acl") or 0)
                        except Exception as exc:
                            logger.debug(_METRICS_DASHBOARD_FALLBACK_LOG_MESSAGE, exc)

                    channels = dbg.get("channels")
                    if isinstance(channels, dict):
                        cache_meta = channels.get("cache")
                        if isinstance(cache_meta, dict):
                            if bool(cache_meta.get("hit")):
                                retrieval_candidate_cache_hit_count += 1
                            if bool(cache_meta.get("store_ok")):
                                retrieval_candidate_cache_store_ok_count += 1
                            backend = str(cache_meta.get("backend") or "").strip().lower()
                            if backend:
                                retrieval_candidate_cache_backend_counts[backend] += 1
                            skip_reason = str(cache_meta.get("skip_reason") or "").strip()
                            if skip_reason:
                                retrieval_candidate_cache_skip_reason_counts[skip_reason[:80]] += 1

                        rerank_meta = channels.get("rerank")
                        if isinstance(rerank_meta, dict):
                            skip_reason = str(rerank_meta.get("skip_reason") or "").strip()
                            if skip_reason:
                                retrieval_rerank_skip_reason_counts[skip_reason[:80]] += 1

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
                        except Exception as exc:
                            logger.debug(_METRICS_DASHBOARD_FALLBACK_LOG_MESSAGE, exc)
                    rr_sec = c.get("rerank_elapsed_sec")
                    if rr_sec is not None:
                        try:
                            fv = float(rr_sec)
                            if fv >= 0:
                                rerank_elapsed.append(fv)
                        except Exception as exc:
                            logger.debug(_METRICS_DASHBOARD_FALLBACK_LOG_MESSAGE, exc)

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
        "ts_ms": list(ts_keys),
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
        retrieval_candidate_cache_hit_count=int(retrieval_candidate_cache_hit_count),
        retrieval_candidate_cache_store_ok_count=int(retrieval_candidate_cache_store_ok_count),
        retrieval_candidate_cache_backend_counts=dict(retrieval_candidate_cache_backend_counts),
        retrieval_candidate_cache_skip_reason_counts=dict(retrieval_candidate_cache_skip_reason_counts),
        retrieval_rerank_skip_reason_counts=dict(retrieval_rerank_skip_reason_counts),
        retrieval_mode_counts=dict(retrieval_mode_counts),
        hit_type_counts=dict(hit_type_counts),
        error_counts=dict(error_counts),
        timeseries=series,
    )


@dataclass(frozen=True)
class RagCostAttributionSummary:
    enabled: bool
    path: str
    window_minutes: int
    truncated: bool
    record_count: int
    rag_trace_count: int

    llm_prompt_tokens: int
    llm_completion_tokens: int
    llm_total_tokens: int
    llm_model_counts: dict[str, int]
    llm_source_counts: dict[str, int]

    embed_query_tokens: int
    embed_query_chars: int
    embed_query_count: int
    embed_provider_counts: dict[str, int]
    embed_model_counts: dict[str, int]

    retrieval_elapsed_avg_sec: float | None
    retrieval_elapsed_p95_sec: float | None
    rerank_elapsed_avg_sec: float | None
    rerank_elapsed_p95_sec: float | None
    retrieval_vector_backend_counts: dict[str, int]
    retrieval_query_count: int


def summarize_rag_cost_attribution(
    *,
    tenant_id: str | None,
    window_minutes: int = 60,
    max_bytes: int = 5_000_000,
) -> RagCostAttributionSummary:
    """
    Cost attribution aggregates derived from `rag_trace.cost_attribution` records.

    Output is PII-safe by construction (numeric/categorical fields only).
    """

    enabled = bool(getattr(settings, "ENABLE_METRICS_LOG", False))
    path_str = str(getattr(settings, "METRICS_LOG_PATH", DEFAULT_METRICS_LOG_PATH) or DEFAULT_METRICS_LOG_PATH)
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

    rag_trace_count = 0

    llm_prompt_tokens = 0
    llm_completion_tokens = 0
    llm_total_tokens = 0
    llm_model_counts: dict[str, int] = defaultdict(int)
    llm_source_counts: dict[str, int] = defaultdict(int)

    embed_query_tokens = 0
    embed_query_chars = 0
    embed_query_count = 0
    embed_provider_counts: dict[str, int] = defaultdict(int)
    embed_model_counts: dict[str, int] = defaultdict(int)

    retrieval_elapsed: list[float] = []
    rerank_elapsed: list[float] = []
    retrieval_vector_backend_counts: dict[str, int] = defaultdict(int)
    retrieval_query_count = 0

    for r in records:
        if str(r.get("event") or "") != "rag_trace":
            continue

        rag_trace_count += 1

        cost = r.get("cost_attribution")
        if not isinstance(cost, dict) or not cost:
            continue

        llm = cost.get("llm") if isinstance(cost.get("llm"), dict) else {}
        if isinstance(llm, dict):
            try:
                llm_prompt_tokens += int(llm.get("prompt_tokens") or 0)
            except Exception as exc:
                logger.debug(_METRICS_DASHBOARD_FALLBACK_LOG_MESSAGE, exc)
            try:
                llm_completion_tokens += int(llm.get("completion_tokens") or 0)
            except Exception as exc:
                logger.debug(_METRICS_DASHBOARD_FALLBACK_LOG_MESSAGE, exc)
            try:
                llm_total_tokens += int(llm.get("total_tokens") or 0)
            except Exception as exc:
                logger.debug(_METRICS_DASHBOARD_FALLBACK_LOG_MESSAGE, exc)
            model_used = str(llm.get("model_used") or "").strip()
            if model_used:
                llm_model_counts[model_used[:120]] += 1
            source = str(llm.get("source") or "").strip()
            if source:
                llm_source_counts[source[:50]] += 1

        emb = cost.get("embeddings") if isinstance(cost.get("embeddings"), dict) else {}
        if isinstance(emb, dict):
            try:
                embed_query_tokens += int(emb.get("query_tokens") or 0)
            except Exception as exc:
                logger.debug(_METRICS_DASHBOARD_FALLBACK_LOG_MESSAGE, exc)
            try:
                embed_query_chars += int(emb.get("query_chars") or 0)
            except Exception as exc:
                logger.debug(_METRICS_DASHBOARD_FALLBACK_LOG_MESSAGE, exc)
            try:
                embed_query_count += int(emb.get("query_count") or 0)
            except Exception as exc:
                logger.debug(_METRICS_DASHBOARD_FALLBACK_LOG_MESSAGE, exc)

            provider = str(emb.get("provider") or "").strip()
            if provider:
                embed_provider_counts[provider[:50]] += 1
            model = str(emb.get("model") or "").strip()
            if model:
                embed_model_counts[model[:80]] += 1

        retrieval = cost.get("retrieval") if isinstance(cost.get("retrieval"), dict) else {}
        if isinstance(retrieval, dict):
            v = retrieval.get("elapsed_sec")
            if v is not None:
                try:
                    fv = float(v)
                    if fv >= 0:
                        retrieval_elapsed.append(fv)
                except Exception as exc:
                    logger.debug(_METRICS_DASHBOARD_FALLBACK_LOG_MESSAGE, exc)

            v = retrieval.get("rerank_elapsed_sec")
            if v is not None:
                try:
                    fv = float(v)
                    if fv >= 0:
                        rerank_elapsed.append(fv)
                except Exception as exc:
                    logger.debug(_METRICS_DASHBOARD_FALLBACK_LOG_MESSAGE, exc)

            vector_backend = str(retrieval.get("vector_backend") or "").strip()
            if vector_backend:
                retrieval_vector_backend_counts[vector_backend[:50]] += 1
            try:
                retrieval_query_count += int(retrieval.get("query_count") or 0)
            except Exception as exc:
                logger.debug(_METRICS_DASHBOARD_FALLBACK_LOG_MESSAGE, exc)

    return RagCostAttributionSummary(
        enabled=enabled,
        path=path_str,
        window_minutes=int(window_minutes),
        truncated=bool(truncated),
        record_count=len(records),
        rag_trace_count=int(rag_trace_count),
        llm_prompt_tokens=int(llm_prompt_tokens),
        llm_completion_tokens=int(llm_completion_tokens),
        llm_total_tokens=int(llm_total_tokens),
        llm_model_counts=dict(llm_model_counts),
        llm_source_counts=dict(llm_source_counts),
        embed_query_tokens=int(embed_query_tokens),
        embed_query_chars=int(embed_query_chars),
        embed_query_count=int(embed_query_count),
        embed_provider_counts=dict(embed_provider_counts),
        embed_model_counts=dict(embed_model_counts),
        retrieval_elapsed_avg_sec=_mean(retrieval_elapsed),
        retrieval_elapsed_p95_sec=_percentile(retrieval_elapsed, 95.0),
        rerank_elapsed_avg_sec=_mean(rerank_elapsed),
        rerank_elapsed_p95_sec=_percentile(rerank_elapsed, 95.0),
        retrieval_vector_backend_counts=dict(retrieval_vector_backend_counts),
        retrieval_query_count=int(retrieval_query_count),
    )


def _hash_for_analytics(text: str) -> str:
    """
    Stable short hash for query analytics.

    Note: metrics JSONL already writes `query_hash`/`question_hash` when
    METRICS_LOG_INCLUDE_TEXT=false. When text is included, we compute the same
    hash at read time so analytics remain PII-safe.
    """

    raw = (text or "").encode("utf-8", "ignore")
    return hashlib.sha256(raw).hexdigest()[:16]


@dataclass(frozen=True)
class RagQueryAnalyticsSummary:
    enabled: bool
    path: str
    window_minutes: int
    truncated: bool
    record_count: int
    rag_trace_count: int
    unique_query_hashes: int
    zero_hit_count: int
    zero_hit_rate: float | None
    slow_threshold_sec: float
    slow_count: int
    slow_rate: float | None
    retrieval_p50_elapsed_sec: float | None
    retrieval_p95_elapsed_sec: float | None
    retrieval_p99_elapsed_sec: float | None
    error_kind_counts: dict[str, int]
    top_zero_hit_queries: list[dict[str, Any]]
    top_slow_queries: list[dict[str, Any]]
    timeseries: dict[str, list[Any]]
    anomalies: list[dict[str, Any]]


def _safe_rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return float(numerator) / float(denominator)


def _detect_rate_spike(
    *,
    metric: str,
    baseline_rates: list[float],
    current_rate: float,
    current_requests: int,
    baseline_requests: int,
    baseline_window_minutes: int,
    current_window_minutes: int,
    abs_threshold: float,
    ratio_threshold: float,
    zscore_threshold: float,
    hints: list[str],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if current_requests <= 0 or baseline_requests <= 0:
        return None

    baseline_rate = _mean(baseline_rates) if baseline_rates else 0.0
    baseline_std = _stddev(baseline_rates) if baseline_rates else 0.0

    # Guard: avoid division explosions when baseline is near zero.
    ratio = None
    if baseline_rate and baseline_rate > 1e-9:
        ratio = current_rate / baseline_rate

    z_score = None
    if baseline_std is not None and baseline_std > 1e-9:
        z_score = (current_rate - baseline_rate) / baseline_std

    meets_abs = current_rate >= float(abs_threshold or 0.0)
    meets_ratio = ratio is not None and ratio >= float(ratio_threshold or 0.0)
    meets_z = z_score is not None and z_score >= float(zscore_threshold or 0.0)
    meets_spike = meets_abs and (meets_ratio or meets_z or (baseline_rate <= 1e-9))
    if not meets_spike:
        return None

    severity = "warning"
    if (ratio is not None and ratio >= (float(ratio_threshold or 0.0) * 2.0)) or (
        z_score is not None and z_score >= (float(zscore_threshold or 0.0) * 2.0)
    ):
        severity = "critical"

    message = f"{metric} spike: current={current_rate:.3f} baseline={baseline_rate:.3f}"
    payload: dict[str, Any] = {
        "key": f"rag.{metric}.spike",
        "metric": metric,
        "severity": severity,
        "message": message,
        "baseline_window_minutes": int(baseline_window_minutes),
        "current_window_minutes": int(current_window_minutes),
        "current_rate": round(float(current_rate), 6),
        "baseline_rate": round(float(baseline_rate), 6),
        "baseline_std": round(float(baseline_std or 0.0), 6) if baseline_std is not None else None,
        "ratio": round(float(ratio), 6) if ratio is not None else None,
        "z_score": round(float(z_score), 6) if z_score is not None else None,
        "current_requests": int(current_requests),
        "baseline_requests": int(baseline_requests),
        "hints": list(hints or []),
    }
    if extra:
        payload["extra"] = dict(extra)
    return payload


def _detect_query_analytics_anomalies(
    *,
    bucket: dict[int, dict[str, Any]],
    records: list[dict[str, Any]],
    ts_keys: list[int],
    window_minutes: int,
) -> list[dict[str, Any]]:
    if not bool(getattr(settings, "OBS_ANOMALY_ENABLED", True)):
        return []

    if not ts_keys:
        return []

    window_minutes = max(1, int(window_minutes or 0))

    baseline_win = max(1, int(getattr(settings, "OBS_ANOMALY_BASELINE_WINDOW_MINUTES", 60) or 60))
    current_win = max(1, int(getattr(settings, "OBS_ANOMALY_CURRENT_WINDOW_MINUTES", 5) or 5))
    min_reqs = max(1, int(getattr(settings, "OBS_ANOMALY_MIN_REQUESTS_PER_BUCKET", 5) or 5))
    min_baseline_buckets = max(1, int(getattr(settings, "OBS_ANOMALY_MIN_BASELINE_BUCKETS", 10) or 10))

    current_win = min(current_win, window_minutes)
    baseline_win = min(baseline_win, max(0, window_minutes - current_win))
    if baseline_win <= 0 or current_win <= 0:
        return []

    last_ts_ms = max(ts_keys)
    current_start_ms = last_ts_ms - ((current_win - 1) * 60_000)
    baseline_start_ms = current_start_ms - (baseline_win * 60_000)

    baseline_keys = [k for k in ts_keys if baseline_start_ms <= k < current_start_ms]
    current_keys = [k for k in ts_keys if k >= current_start_ms]

    baseline_rates_zero: list[float] = []
    baseline_rates_error: list[float] = []
    baseline_req = 0
    current_req = 0
    current_zero = 0
    current_error = 0
    baseline_bucket_count = 0
    current_bucket_count = 0

    for k in baseline_keys:
        req = int((bucket.get(k) or {}).get("requests") or 0)
        if req < min_reqs:
            continue
        zh = int((bucket.get(k) or {}).get("zero_hit") or 0)
        er = int((bucket.get(k) or {}).get("errors") or 0)
        baseline_bucket_count += 1
        baseline_req += req
        baseline_rates_zero.append(_safe_rate(zh, req))
        baseline_rates_error.append(_safe_rate(er, req))

    for k in current_keys:
        req = int((bucket.get(k) or {}).get("requests") or 0)
        if req < min_reqs:
            continue
        zh = int((bucket.get(k) or {}).get("zero_hit") or 0)
        er = int((bucket.get(k) or {}).get("errors") or 0)
        current_bucket_count += 1
        current_req += req
        current_zero += zh
        current_error += er

    # Not enough baseline -> skip to avoid noisy alerts on low traffic.
    if baseline_bucket_count < min_baseline_buckets or current_req <= 0 or baseline_req <= 0:
        return []

    current_zero_rate = _safe_rate(current_zero, current_req)
    current_error_rate = _safe_rate(current_error, current_req)

    # Error kinds for the current window (PII-safe: only kind prefixes).
    current_error_kinds: dict[str, int] = defaultdict(int)
    for r in records:
        if str(r.get("event") or "") != "rag_trace":
            continue
        try:
            ts_ms = int(r.get("ts_ms") or 0)
        except Exception:
            ts_ms = 0
        if ts_ms and ts_ms < current_start_ms:
            continue
        retrieval = r.get("retrieval") if isinstance(r.get("retrieval"), dict) else {}
        errors = retrieval.get("errors") if isinstance(retrieval, dict) else None
        if not isinstance(errors, list) or not errors:
            continue
        for e in errors:
            if not isinstance(e, str):
                continue
            kind = e.split(":", 1)[0].strip().lower()
            if not kind:
                continue
            current_error_kinds[kind[:30]] += 1
    top_error_kind = None
    if current_error_kinds:
        top_error_kind = sorted(current_error_kinds.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]

    anomalies: list[dict[str, Any]] = []

    zero_hit_hints = [
        "Index 可能为空或入库未完成：检查 ingestion/queue 状态与 index-audit。",
        "检索 scope 过窄或 ACL 过滤过严：确认 dataset/document scope 与权限配置。",
        "检索配置变更：对比 retrieval_config_hash 或最近配置变更。",
    ]
    err_hints = [
        "向量/检索后端异常：检查 /health/ready 与依赖延迟（DB/Redis/vector）。",
        "reranker 上游故障或 429：检查 provider 状态与限流/配额。",
        "查看 error_kind_counts 以定位主要失败类型。",
    ]

    zh_abs = float(getattr(settings, "OBS_ANOMALY_ZERO_HIT_RATE_ABS_THRESHOLD", 0.6) or 0.6)
    zh_ratio = float(getattr(settings, "OBS_ANOMALY_ZERO_HIT_RATE_RATIO_THRESHOLD", 2.0) or 2.0)
    zh_z = float(getattr(settings, "OBS_ANOMALY_ZERO_HIT_RATE_ZSCORE_THRESHOLD", 3.0) or 3.0)
    er_abs = float(getattr(settings, "OBS_ANOMALY_ERROR_RATE_ABS_THRESHOLD", 0.05) or 0.05)
    er_ratio = float(getattr(settings, "OBS_ANOMALY_ERROR_RATE_RATIO_THRESHOLD", 3.0) or 3.0)
    er_z = float(getattr(settings, "OBS_ANOMALY_ERROR_RATE_ZSCORE_THRESHOLD", 3.0) or 3.0)

    zh = _detect_rate_spike(
        metric="zero_hit_rate",
        baseline_rates=baseline_rates_zero,
        current_rate=current_zero_rate,
        current_requests=current_req,
        baseline_requests=baseline_req,
        baseline_window_minutes=baseline_win,
        current_window_minutes=current_win,
        abs_threshold=zh_abs,
        ratio_threshold=zh_ratio,
        zscore_threshold=zh_z,
        hints=zero_hit_hints,
        extra={"baseline_buckets": baseline_bucket_count, "current_buckets": current_bucket_count},
    )
    if zh:
        anomalies.append(zh)

    er = _detect_rate_spike(
        metric="error_rate",
        baseline_rates=baseline_rates_error,
        current_rate=current_error_rate,
        current_requests=current_req,
        baseline_requests=baseline_req,
        baseline_window_minutes=baseline_win,
        current_window_minutes=current_win,
        abs_threshold=er_abs,
        ratio_threshold=er_ratio,
        zscore_threshold=er_z,
        hints=err_hints,
        extra={
            "top_error_kind": top_error_kind,
            "baseline_buckets": baseline_bucket_count,
            "current_buckets": current_bucket_count,
        },
    )
    if er:
        anomalies.append(er)

    anomalies.sort(key=lambda x: str(x.get("metric") or ""))
    return anomalies


def summarize_rag_query_analytics(
    *,
    tenant_id: str | None,
    window_minutes: int = 60,
    max_bytes: int = 5_000_000,
    slow_threshold_sec: float = 2.0,
    top_n: int = 20,
) -> RagQueryAnalyticsSummary:
    """
    Query analytics summary derived from `rag_trace` metrics JSONL records.

    Output is PII-safe by construction:
    - Only query hashes are returned (no raw text)
    - Aggregates are numeric/categorical
    """

    enabled = bool(getattr(settings, "ENABLE_METRICS_LOG", False))
    path_str = str(getattr(settings, "METRICS_LOG_PATH", DEFAULT_METRICS_LOG_PATH) or DEFAULT_METRICS_LOG_PATH)
    path = Path(path_str)

    window_minutes = max(1, int(window_minutes or 0))
    cutoff_ms = int(time.time() * 1000) - (window_minutes * 60 * 1000)
    top_n = max(1, min(200, int(top_n or 0)))
    slow_threshold_sec = max(0.0, float(slow_threshold_sec or 0.0))

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

    rag_trace_count = 0
    query_hashes: set[str] = set()
    retrieval_elapsed: list[float] = []

    zero_hit_count = 0
    slow_count = 0

    error_kind_counts: dict[str, int] = defaultdict(int)
    zero_hit_by_hash: dict[str, int] = defaultdict(int)
    slow_by_hash_count: dict[str, int] = defaultdict(int)
    slow_by_hash_max_elapsed: dict[str, float] = defaultdict(float)

    # Simple minute-bucket time series (PII-safe).
    bucket: dict[int, dict[str, Any]] = {}

    for r in records:
        if str(r.get("event") or "") != "rag_trace":
            continue

        rag_trace_count += 1

        ts_ms = int(r.get("ts_ms") or 0) if r.get("ts_ms") is not None else 0
        minute_ms = (ts_ms // 60_000) * 60_000 if ts_ms else 0
        if minute_ms and minute_ms not in bucket:
            bucket[minute_ms] = {"ts_ms": minute_ms, "requests": 0, "zero_hit": 0, "slow": 0, "errors": 0}
        if minute_ms:
            bucket[minute_ms]["requests"] += 1

        qhash = r.get("query_hash") or r.get("question_hash")
        if not qhash:
            raw_query = r.get("query_for_retrieval") or r.get("question")
            if isinstance(raw_query, str) and raw_query.strip():
                qhash = _hash_for_analytics(raw_query.strip())

        if isinstance(qhash, str) and qhash.strip():
            qhash = qhash.strip()
            query_hashes.add(qhash)
        else:
            qhash = None

        citations_count = 0
        try:
            if r.get("citations_count") is not None:
                citations_count = int(r.get("citations_count") or 0)
            else:
                citations = r.get("citations") or []
                citations_count = len(citations) if isinstance(citations, list) else 0
        except Exception:
            citations_count = 0

        retrieval = r.get("retrieval") if isinstance(r.get("retrieval"), dict) else {}
        elapsed_sec: float | None = None
        try:
            v = retrieval.get("elapsed_sec") if isinstance(retrieval, dict) else None
            if v is not None:
                fv = float(v)
                if fv >= 0:
                    elapsed_sec = fv
        except Exception:
            elapsed_sec = None
        if elapsed_sec is not None:
            retrieval_elapsed.append(elapsed_sec)

        errors = retrieval.get("errors") if isinstance(retrieval, dict) else None
        has_error = False
        if isinstance(errors, list) and errors:
            has_error = True
            for e in errors:
                if not isinstance(e, str):
                    continue
                kind = e.split(":", 1)[0].strip().lower()
                if not kind:
                    continue
                error_kind_counts[kind[:30]] += 1
        if has_error and minute_ms:
            bucket[minute_ms]["errors"] += 1

        if citations_count == 0:
            zero_hit_count += 1
            if minute_ms:
                bucket[minute_ms]["zero_hit"] += 1
            if qhash:
                zero_hit_by_hash[qhash] += 1

        if slow_threshold_sec > 0 and elapsed_sec is not None and elapsed_sec >= slow_threshold_sec:
            slow_count += 1
            if minute_ms:
                bucket[minute_ms]["slow"] += 1
            if qhash:
                slow_by_hash_count[qhash] += 1
                slow_by_hash_max_elapsed[qhash] = max(float(slow_by_hash_max_elapsed.get(qhash) or 0.0), elapsed_sec)

    zero_hit_rate = (zero_hit_count / rag_trace_count) if rag_trace_count else None
    slow_rate = (slow_count / rag_trace_count) if rag_trace_count else None

    top_zero = sorted(zero_hit_by_hash.items(), key=lambda kv: (-kv[1], kv[0]))[:top_n]
    top_zero_hit_queries = [{"query_hash": h, "count": int(c)} for h, c in top_zero]

    top_slow_items = sorted(
        slow_by_hash_count.items(),
        key=lambda kv: (-kv[1], -(float(slow_by_hash_max_elapsed.get(kv[0]) or 0.0)), kv[0]),
    )[:top_n]
    top_slow_queries: list[dict[str, Any]] = []
    for h, c in top_slow_items:
        top_slow_queries.append(
            {
                "query_hash": h,
                "count": int(c),
                "max_elapsed_sec": round(float(slow_by_hash_max_elapsed.get(h) or 0.0), 3),
            }
        )

    ts_keys = sorted(k for k in bucket.keys() if k)
    timeseries = {
        "ts_ms": list(ts_keys),
        "requests": [int(bucket[k]["requests"]) for k in ts_keys],
        "zero_hit": [int(bucket[k]["zero_hit"]) for k in ts_keys],
        "slow": [int(bucket[k]["slow"]) for k in ts_keys],
        "errors": [int(bucket[k]["errors"]) for k in ts_keys],
    }

    anomalies = _detect_query_analytics_anomalies(
        bucket=bucket,
        records=records,
        ts_keys=ts_keys,
        window_minutes=window_minutes,
    )

    return RagQueryAnalyticsSummary(
        enabled=enabled,
        path=path_str,
        window_minutes=int(window_minutes),
        truncated=bool(truncated),
        record_count=len(records),
        rag_trace_count=int(rag_trace_count),
        unique_query_hashes=len(query_hashes),
        zero_hit_count=int(zero_hit_count),
        zero_hit_rate=zero_hit_rate,
        slow_threshold_sec=slow_threshold_sec,
        slow_count=int(slow_count),
        slow_rate=slow_rate,
        retrieval_p50_elapsed_sec=_percentile(retrieval_elapsed, 50.0),
        retrieval_p95_elapsed_sec=_percentile(retrieval_elapsed, 95.0),
        retrieval_p99_elapsed_sec=_percentile(retrieval_elapsed, 99.0),
        error_kind_counts=dict(error_kind_counts),
        top_zero_hit_queries=top_zero_hit_queries,
        top_slow_queries=top_slow_queries,
        timeseries=timeseries,
        anomalies=anomalies,
    )


_TRACE_BUNDLE_CITATION_SAFE_KEYS = {
    "chunk_id",
    "document_id",
    "chunk_index",
    "page_number",
    "start_char",
    "end_char",
    "retrieval_role",
    "neighbor_of",
    "doc_pipeline_key",
    "pipeline_hash",
    "relevance_score",
    "vector_score",
    "bm25_score",
    "keyword_score",
    "kg_path",
    "kg_path_provenance",
    "rerank_score",
    "retrieval_score",
    "reranker_provider",
    "rerank_elapsed_sec",
    "rerank_model_used",
    "retrieval_mode",
    "vector_backend",
    "retrieval_elapsed_sec",
    "hit_type",
    "has_image",
}


def _sanitize_rag_trace_for_bundle(record: dict[str, Any]) -> dict[str, Any]:
    """
    Return a PII-safe copy of a rag_trace record (for incident bundles).

    Guarantees:
    - No raw question/query text in output
    - Citations contain only identifiers + numeric fields (no snippets)
    """

    out = dict(record)

    question = out.pop("question", None)
    if isinstance(question, str) and question.strip():
        q = question.strip()
        out.setdefault("question_hash", _hash_for_analytics(q))
        out.setdefault("question_chars", len(q))

    query = out.pop("query_for_retrieval", None)
    if isinstance(query, str) and query.strip():
        q = query.strip()
        out.setdefault("query_hash", _hash_for_analytics(q))
        out.setdefault("query_chars", len(q))

    citations = out.get("citations")
    if isinstance(citations, list):
        safe: list[dict[str, Any]] = []
        for c in citations:
            if not isinstance(c, dict):
                continue
            item: dict[str, Any] = {}
            for k in _TRACE_BUNDLE_CITATION_SAFE_KEYS:
                if k in c and c.get(k) is not None:
                    item[k] = c.get(k)
            if item:
                safe.append(item)
            if len(safe) >= 50:
                break
        out["citations"] = safe

    return out


def _sanitize_rag_done_for_bundle(record: dict[str, Any]) -> dict[str, Any]:
    """
    Return a PII-safe copy of a rag_done record (for incident bundles).

    We defensively drop fields that can contain user/assistant text.
    """

    out = dict(record)
    metrics = out.get("metrics")
    if isinstance(metrics, dict):
        safe = dict(metrics)
        safe.pop("structured_data", None)
        safe.pop("abstain_followup", None)
        out["metrics"] = safe
    return out


def build_redacted_metrics_tail_gzip(
    *,
    tenant_id: str | None,
    window_minutes: int = 60,
    max_bytes: int = 5_000_000,
) -> bytes:
    """
    Export a redacted JSONL tail for incident/support bundles (PII-safe).

    Guarantees:
    - Strips raw question/query text even when the metrics log includes text.
    - Sanitizes citations to identifiers/numerics only (no snippets).
    - Applies lightweight secret/PII masking on remaining strings (best-effort).
    """

    path_str = str(getattr(settings, "METRICS_LOG_PATH", DEFAULT_METRICS_LOG_PATH) or DEFAULT_METRICS_LOG_PATH)
    path = Path(path_str)

    window_minutes = max(1, int(window_minutes or 0))
    cutoff_ms = int(time.time() * 1000) - (window_minutes * 60 * 1000)

    raw_records, _truncated = _read_jsonl_tail(path, max_bytes=int(max_bytes or 0))

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

    # Apply additional masking on remaining strings (independent of global PII_REDACTION_ENABLED).
    try:
        from app.core.pii_redaction import PIIRedactor

        redactor = PIIRedactor(mask="[REDACTED]")
    except Exception:  # noqa: BLE001
        redactor = None

    lines: list[str] = []
    for r in records:
        if not isinstance(r, dict):
            continue
        event = str(r.get("event") or "")
        if event == "rag_trace":
            safe = _sanitize_rag_trace_for_bundle(r)
        elif event == "rag_done":
            safe = _sanitize_rag_done_for_bundle(r)
        else:
            safe = dict(r)
            for k in (
                "question",
                "query_for_retrieval",
                "prompt",
                "response",
                "messages",
                "snippets",
                "structured_data",
                "abstain_followup",
                "text",
                "content",
            ):
                safe.pop(k, None)
            metrics = safe.get("metrics")
            if isinstance(metrics, dict):
                m = dict(metrics)
                m.pop("structured_data", None)
                m.pop("abstain_followup", None)
                safe["metrics"] = m

        if redactor is not None:
            safe = redactor.redact_obj(safe)

        try:
            lines.append(json.dumps(safe, ensure_ascii=False, default=str))
        except Exception:
            continue

    text = "\n".join(lines)
    if text:
        text += "\n"
    return gzip.compress(text.encode("utf-8"))


@dataclass(frozen=True)
class RagTraceBundle:
    enabled: bool
    path: str
    window_minutes: int
    truncated: bool
    record_count: int
    request_id: str
    records: list[dict[str, Any]]


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _first_event(records: list[dict[str, Any]], event: str) -> dict[str, Any] | None:
    for r in records:
        if str(r.get("event") or "") == event:
            return r
    return None


def _extract_error_kind_counts(errors: Any) -> dict[str, int]:
    if not isinstance(errors, list) or not errors:
        return {}
    out: dict[str, int] = defaultdict(int)
    for e in errors:
        if not isinstance(e, str):
            continue
        kind = e.split(":", 1)[0].strip().lower()
        if not kind:
            continue
        out[kind[:30]] += 1
    return dict(out)


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _extract_trace_bundle_summary(bundle: RagTraceBundle) -> dict[str, Any]:
    trace = _first_event(bundle.records, "rag_trace") or {}
    done = _first_event(bundle.records, "rag_done") or {}

    retrieval = trace.get("retrieval") if isinstance(trace.get("retrieval"), dict) else {}
    route_trace = trace.get("route") if isinstance(trace.get("route"), dict) else {}

    citations_count: int | None = None
    try:
        if trace.get("citations_count") is not None:
            citations_count = int(trace.get("citations_count") or 0)
        else:
            citations = trace.get("citations") or []
            citations_count = len(citations) if isinstance(citations, list) else 0
    except Exception:
        citations_count = None

    retrieval_elapsed_sec = _coerce_float(retrieval.get("elapsed_sec"))
    if retrieval_elapsed_sec is not None:
        retrieval_elapsed_sec = round(max(0.0, retrieval_elapsed_sec), 3)

    retrieval_alpha = _coerce_float(retrieval.get("alpha"))
    if retrieval_alpha is not None:
        retrieval_alpha = round(retrieval_alpha, 6)

    out: dict[str, Any] = {
        "request_id": bundle.request_id,
        "window_minutes": int(bundle.window_minutes),
        "truncated": bool(bundle.truncated),
        # Config fingerprint (stable, PII-safe): per-request retrieval config hash.
        "retrieval_config_hash": (str(retrieval.get("retrieval_config_hash") or "").strip() or None),
        "retrieval_mode": (str(retrieval.get("mode") or done.get("retrieval_mode") or "").strip() or None),
        "retrieval_requested_mode": (str(retrieval.get("requested_mode") or "").strip() or None),
        "retrieval_auto_routed": bool(retrieval.get("auto_routed")) if retrieval.get("auto_routed") is not None else None,
        "retrieval_profile": (str(retrieval.get("profile") or "").strip() or None),
        "retrieval_top_k": _coerce_int(retrieval.get("top_k")),
        "retrieval_alpha": retrieval_alpha,
        "retrieval_enable_reranker": bool(retrieval.get("enable_reranker"))
        if retrieval.get("enable_reranker") is not None
        else None,
        "retrieval_reranker_provider": (str(retrieval.get("reranker_provider") or "").strip() or None),
        "retrieval_reranker_top_n": _coerce_int(retrieval.get("reranker_top_n")),
        "retrieval_query_parallelism": _coerce_int(retrieval.get("query_parallelism")),
        "retrieval_query_count": _coerce_int(retrieval.get("query_count")),
        "retrieval_elapsed_sec": retrieval_elapsed_sec,
        "retrieval_error_kinds": _extract_error_kind_counts(retrieval.get("errors")),
        "citations_count": citations_count,
        "model_route": (str(route_trace.get("model_route") or done.get("route") or "").strip() or None),
        "model_used": (str(route_trace.get("model_used") or done.get("model_used") or "").strip() or None),
        "vector_backend": (str(done.get("vector_backend") or "").strip() or None),
    }
    return out


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _diff_trace_summaries(a: dict[str, Any], b: dict[str, Any]) -> list[dict[str, Any]]:
    diff_keys = [
        "retrieval_config_hash",
        "retrieval_mode",
        "retrieval_requested_mode",
        "retrieval_auto_routed",
        "retrieval_profile",
        "retrieval_top_k",
        "retrieval_alpha",
        "retrieval_enable_reranker",
        "retrieval_reranker_provider",
        "retrieval_reranker_top_n",
        "retrieval_query_parallelism",
        "retrieval_query_count",
        "retrieval_elapsed_sec",
        "citations_count",
        "retrieval_error_kinds",
        "model_route",
        "model_used",
        "vector_backend",
    ]

    out: list[dict[str, Any]] = []
    for k in diff_keys:
        av = a.get(k)
        bv = b.get(k)
        if av == bv:
            continue
        delta = None
        if _is_number(av) and _is_number(bv):
            try:
                delta_raw = float(bv) - float(av)
                delta = round(delta_raw, 6)
            except Exception:
                delta = None
        out.append({"key": k, "a": av, "b": bv, "delta": delta})
    return out


@dataclass(frozen=True)
class RagTraceBundleDiff:
    schema: str
    generated_at: datetime
    request_id_a: str
    request_id_b: str
    truncated: bool
    summary_a: dict[str, Any]
    summary_b: dict[str, Any]
    diff: list[dict[str, Any]]


def build_rag_trace_bundle_diff(*, bundle_a: RagTraceBundle, bundle_b: RagTraceBundle) -> RagTraceBundleDiff:
    summary_a = _extract_trace_bundle_summary(bundle_a)
    summary_b = _extract_trace_bundle_summary(bundle_b)
    diff = _diff_trace_summaries(summary_a, summary_b)
    return RagTraceBundleDiff(
        schema="mimirq.rag_trace_bundle_diff.v1",
        generated_at=_now_utc(),
        request_id_a=bundle_a.request_id,
        request_id_b=bundle_b.request_id,
        truncated=bool(bundle_a.truncated or bundle_b.truncated),
        summary_a=summary_a,
        summary_b=summary_b,
        diff=diff,
    )


def build_rag_trace_bundle(
    *,
    tenant_id: str | None,
    request_id: str,
    window_minutes: int = 24 * 60,
    max_bytes: int = 5_000_000,
) -> RagTraceBundle | None:
    """
    Export a PII-safe trace bundle for incident debugging by request_id.

    Intended for admin-only ops workflows. This reads the metrics JSONL tail and
    returns a small, sanitized set of records matching the request_id.
    """

    enabled = bool(getattr(settings, "ENABLE_METRICS_LOG", False))
    path_str = str(getattr(settings, "METRICS_LOG_PATH", DEFAULT_METRICS_LOG_PATH) or DEFAULT_METRICS_LOG_PATH)
    path = Path(path_str)

    request_id = str(request_id or "").strip()
    if not request_id:
        return None

    window_minutes = max(1, int(window_minutes or 0))
    cutoff_ms = int(time.time() * 1000) - (window_minutes * 60 * 1000)

    raw_records, truncated_by_tail = _read_jsonl_tail(path, max_bytes=int(max_bytes or 0))

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

    matched: list[dict[str, Any]] = []
    for r in records:
        if str(r.get("request_id") or "") != request_id:
            continue
        event = str(r.get("event") or "")
        if event == "rag_trace":
            matched.append(_sanitize_rag_trace_for_bundle(r))
        elif event == "rag_done":
            matched.append(_sanitize_rag_done_for_bundle(r))
        else:
            # Best-effort: include other correlated events (already PII-safe by convention).
            matched.append(dict(r))

    if not matched:
        return None

    matched.sort(key=lambda x: int(x.get("ts_ms") or 0))

    return RagTraceBundle(
        enabled=enabled,
        path=path_str,
        window_minutes=window_minutes,
        truncated=truncated,
        record_count=len(records),
        request_id=request_id,
        records=matched,
    )


__all__ = [
    "RagTraceBundle",
    "build_rag_trace_bundle",
    "RagTraceBundleDiff",
    "build_rag_trace_bundle_diff",
]
