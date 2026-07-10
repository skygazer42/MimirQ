"""
RAG metrics dashboard helpers.

Reads the JSONL metrics log (when ENABLE_METRICS_LOG=true) and aggregates a small,
PII-safe summary for UI dashboards.

Design constraints:
- Best-effort: tolerate missing/partial/invalid JSON lines.
- Bounded: read only the tail of the metrics file (max_bytes) to avoid O(file_size).
- Safe: never return raw question/query/chunk text; only numeric + categorical aggregates.
"""


import gzip
import hashlib
import json
import math
import time
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.constants import NON_CRITICAL_EXCEPTION_LOG_MESSAGE
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
            get_logger(__name__).debug(NON_CRITICAL_EXCEPTION_LOG_MESSAGE, exc_info=True)
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
            get_logger(__name__).debug(NON_CRITICAL_EXCEPTION_LOG_MESSAGE, exc_info=True)
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


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _record_event(record: dict[str, Any]) -> str:
    return str(record.get("event") or "")


def _record_ts_ms(record: dict[str, Any]) -> int:
    try:
        return int(record.get("ts_ms") or 0)
    except Exception:
        return 0


def _safe_int_value(value: Any, *, default: int = 0) -> int:
    try:
        return int(value if value is not None else default)
    except Exception as exc:
        logger.debug(_METRICS_DASHBOARD_FALLBACK_LOG_MESSAGE, exc)
        return default


def _safe_non_negative_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        fv = float(value)
    except Exception as exc:
        logger.debug(_METRICS_DASHBOARD_FALLBACK_LOG_MESSAGE, exc)
        return None
    if fv < 0:
        return None
    return fv


def _increment_limited_count(counter: dict[str, int], value: Any, *, limit: int) -> None:
    key = str(value or "").strip()
    if key:
        counter[key[:limit]] += 1


def _tail_read_plan(path: Path, *, max_bytes: int) -> tuple[int, bool] | None:
    try:
        size = int(path.stat().st_size)
    except Exception:
        return None
    start = max(0, size - max_bytes)
    return start, start > 0


def _read_tail_bytes(path: Path, *, start: int) -> bytes | None:
    try:
        with path.open("rb") as f:
            if start:
                f.seek(start)
            return f.read()
    except Exception:
        return None


def _drop_partial_first_line(raw: bytes, *, start: int) -> bytes:
    if start:
        nl = raw.find(b"\n")
        if nl >= 0:
            return raw[nl + 1 :]
    return raw


def _decode_tail_bytes(raw: bytes) -> str | None:
    try:
        return raw.decode("utf-8", errors="replace")
    except Exception:
        return None


def _parse_jsonl_records(text: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = (line or "").strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            get_logger(__name__).debug(NON_CRITICAL_EXCEPTION_LOG_MESSAGE, exc_info=True)
            continue
        if isinstance(obj, dict):
            records.append(obj)
    return records


def _read_jsonl_tail(path: Path, *, max_bytes: int) -> tuple[list[dict[str, Any]], bool]:
    """
    Return: (records, truncated)
    `truncated=true` means we did not read the entire file, so results might be incomplete.
    """
    max_bytes = max(1, int(max_bytes or 0))
    plan = _tail_read_plan(path, max_bytes=max_bytes)
    if plan is None:
        return [], False

    start, truncated = plan
    raw = _read_tail_bytes(path, start=start)
    if raw is None:
        return [], truncated

    text = _decode_tail_bytes(_drop_partial_first_line(raw, start=start))
    if text is None:
        return [], truncated
    return _parse_jsonl_records(text), truncated


@dataclass(frozen=True)
class _MetricsRecordWindow:
    path: str
    records: list[dict[str, Any]]
    truncated: bool


def _metrics_log_path_str() -> str:
    return str(getattr(settings, "METRICS_LOG_PATH", DEFAULT_METRICS_LOG_PATH) or DEFAULT_METRICS_LOG_PATH)


def _normalize_window_minutes(window_minutes: int) -> int:
    return max(1, int(window_minutes or 0))


def _cutoff_ms_for_window(window_minutes: int) -> int:
    return int(time.time() * 1000) - (_normalize_window_minutes(window_minutes) * 60 * 1000)


def _matches_tenant(record: dict[str, Any], tenant_key: str | None) -> bool:
    if not tenant_key:
        return True
    rid = record.get("tenant_id")
    return not rid or str(rid) == tenant_key


def _filter_records_for_window(
    raw_records: list[dict[str, Any]],
    *,
    tenant_id: str | None,
    cutoff_ms: int,
) -> list[dict[str, Any]]:
    tenant_key = str(tenant_id) if tenant_id else None
    records: list[dict[str, Any]] = []
    for record in raw_records:
        ts_ms = _record_ts_ms(record)
        if ts_ms and ts_ms < cutoff_ms:
            continue
        if _matches_tenant(record, tenant_key):
            records.append(record)
    return records


def _earliest_record_ts_ms(records: list[dict[str, Any]]) -> int | None:
    timestamps = [ts_ms for record in records if (ts_ms := _record_ts_ms(record))]
    return min(timestamps) if timestamps else None


def _is_window_truncated(*, truncated_by_tail: bool, records: list[dict[str, Any]], cutoff_ms: int) -> bool:
    earliest_ts_ms = _earliest_record_ts_ms(records)
    return bool(truncated_by_tail and earliest_ts_ms is not None and earliest_ts_ms > cutoff_ms)


def _load_metrics_record_window(
    *,
    tenant_id: str | None,
    window_minutes: int,
    max_bytes: int,
) -> _MetricsRecordWindow:
    path_str = _metrics_log_path_str()
    raw_records, truncated_by_tail = _read_jsonl_tail(Path(path_str), max_bytes=int(max_bytes or 0))
    cutoff_ms = _cutoff_ms_for_window(window_minutes)
    records = _filter_records_for_window(raw_records, tenant_id=tenant_id, cutoff_ms=cutoff_ms)
    truncated = _is_window_truncated(truncated_by_tail=truncated_by_tail, records=records, cutoff_ms=cutoff_ms)
    return _MetricsRecordWindow(path=path_str, records=records, truncated=truncated)


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


@dataclass
class _RagMetricsAccumulator:
    retrieval_elapsed: list[float] = field(default_factory=list)
    rerank_elapsed: list[float] = field(default_factory=list)
    citations_counts: list[int] = field(default_factory=list)
    retrieval_mode_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    hit_type_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    error_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    overfetch_ratios: list[float] = field(default_factory=list)
    overfetch_count: int = 0
    filtered_acl_total: int = 0
    retrieval_candidate_cache_hit_count: int = 0
    retrieval_candidate_cache_store_ok_count: int = 0
    retrieval_candidate_cache_backend_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    retrieval_candidate_cache_skip_reason_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    retrieval_rerank_skip_reason_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    bucket: dict[int, dict[str, Any]] = field(default_factory=dict)
    rag_trace_count: int = 0
    reranker_api_count: int = 0


def _metric_minute_ms(record: dict[str, Any]) -> int:
    ts_ms = _record_ts_ms(record)
    return (ts_ms // 60_000) * 60_000 if ts_ms else 0


def _rag_metrics_bucket(state: _RagMetricsAccumulator, minute_ms: int) -> dict[str, Any] | None:
    if not minute_ms:
        return None
    return state.bucket.setdefault(
        minute_ms,
        {"ts_ms": minute_ms, "rag_trace": 0, "reranker_api": 0, "retrieval_elapsed_sum": 0.0},
    )


def _collect_overfetch_stats(state: _RagMetricsAccumulator, debug: dict[str, Any]) -> None:
    if not bool(debug.get("overfetch_enabled")):
        return
    state.overfetch_count += 1
    req = _safe_int_value(debug.get("requested_k"))
    search = _safe_int_value(debug.get("search_k"))
    if req > 0 and search > 0:
        state.overfetch_ratios.append(search / req)


def _collect_cache_channel_stats(state: _RagMetricsAccumulator, cache_meta: dict[str, Any]) -> None:
    if bool(cache_meta.get("hit")):
        state.retrieval_candidate_cache_hit_count += 1
    if bool(cache_meta.get("store_ok")):
        state.retrieval_candidate_cache_store_ok_count += 1
    backend = str(cache_meta.get("backend") or "").strip().lower()
    if backend:
        state.retrieval_candidate_cache_backend_counts[backend] += 1
    _increment_limited_count(
        state.retrieval_candidate_cache_skip_reason_counts,
        cache_meta.get("skip_reason"),
        limit=80,
    )


def _collect_retriever_debug_stats(state: _RagMetricsAccumulator, debug: dict[str, Any]) -> None:
    _collect_overfetch_stats(state, debug)
    state.filtered_acl_total += _safe_int_value(_safe_dict(debug.get("enrich_pass1")).get("filtered_acl"))

    channels = _safe_dict(debug.get("channels"))
    cache_meta = _safe_dict(channels.get("cache"))
    if cache_meta:
        _collect_cache_channel_stats(state, cache_meta)

    rerank_meta = _safe_dict(channels.get("rerank"))
    if rerank_meta:
        _increment_limited_count(state.retrieval_rerank_skip_reason_counts, rerank_meta.get("skip_reason"), limit=80)


def _collect_per_query_debug_stats(state: _RagMetricsAccumulator, retrieval: dict[str, Any]) -> None:
    per_query = retrieval.get("per_query")
    if not isinstance(per_query, list):
        return
    for query_record in per_query:
        debug = _safe_dict(query_record).get("retriever_debug")
        if isinstance(debug, dict):
            _collect_retriever_debug_stats(state, debug)


def _collect_citation_metrics(
    state: _RagMetricsAccumulator,
    citations: Any,
    bucket_entry: dict[str, Any] | None,
) -> None:
    if not isinstance(citations, list):
        return
    state.citations_counts.append(len(citations))
    for citation in citations:
        citation_dict = _safe_dict(citation)
        if not citation_dict:
            continue
        _increment_limited_count(state.hit_type_counts, citation_dict.get("hit_type"), limit=120)

        retrieval_elapsed = _safe_non_negative_float(citation_dict.get("retrieval_elapsed_sec"))
        if retrieval_elapsed is not None:
            state.retrieval_elapsed.append(retrieval_elapsed)
            if bucket_entry is not None:
                bucket_entry["retrieval_elapsed_sum"] += retrieval_elapsed

        rerank_elapsed = _safe_non_negative_float(citation_dict.get("rerank_elapsed_sec"))
        if rerank_elapsed is not None:
            state.rerank_elapsed.append(rerank_elapsed)


def _collect_retrieval_error_counts(state: _RagMetricsAccumulator, retrieval: dict[str, Any]) -> None:
    errors = retrieval.get("errors")
    if not isinstance(errors, list):
        return
    for error in errors:
        _increment_limited_count(state.error_counts, error, limit=80)


def _accumulate_rag_trace_metrics(
    state: _RagMetricsAccumulator,
    record: dict[str, Any],
    bucket_entry: dict[str, Any] | None,
) -> None:
    state.rag_trace_count += 1
    if bucket_entry is not None:
        bucket_entry["rag_trace"] += 1

    retrieval = _safe_dict(record.get("retrieval"))
    _increment_limited_count(state.retrieval_mode_counts, retrieval.get("mode"), limit=120)
    _collect_per_query_debug_stats(state, retrieval)
    _collect_citation_metrics(state, record.get("citations"), bucket_entry)
    _collect_retrieval_error_counts(state, retrieval)


def _accumulate_rag_metrics_record(state: _RagMetricsAccumulator, record: dict[str, Any]) -> None:
    event = _record_event(record)
    bucket_entry = _rag_metrics_bucket(state, _metric_minute_ms(record))
    if event == "rag_trace":
        _accumulate_rag_trace_metrics(state, record, bucket_entry)
    elif event == "reranker_api":
        state.reranker_api_count += 1
        if bucket_entry is not None:
            bucket_entry["reranker_api"] += 1
        if record.get("error"):
            state.error_counts["reranker_api_error"] += 1


def _rag_metrics_timeseries(bucket: dict[int, dict[str, Any]]) -> dict[str, list[Any]]:
    ts_keys = sorted(k for k in bucket.keys() if k)
    return {
        "ts_ms": list(ts_keys),
        "rag_trace": [int(bucket[k]["rag_trace"]) for k in ts_keys],
        "reranker_api": [int(bucket[k]["reranker_api"]) for k in ts_keys],
        "retrieval_avg_elapsed_sec": [
            (bucket[k]["retrieval_elapsed_sum"] / bucket[k]["rag_trace"]) if bucket[k]["rag_trace"] else None
            for k in ts_keys
        ],
    }


def _build_rag_metrics_summary(
    *,
    enabled: bool,
    record_window: _MetricsRecordWindow,
    window_minutes: int,
    state: _RagMetricsAccumulator,
) -> RagMetricsSummary:
    return RagMetricsSummary(
        enabled=enabled,
        path=record_window.path,
        window_minutes=int(window_minutes),
        truncated=bool(record_window.truncated),
        record_count=len(record_window.records),
        rag_trace_count=int(state.rag_trace_count),
        reranker_api_count=int(state.reranker_api_count),
        retrieval_avg_elapsed_sec=_mean(state.retrieval_elapsed),
        retrieval_p95_elapsed_sec=_percentile(state.retrieval_elapsed, 95.0),
        rerank_avg_elapsed_sec=_mean(state.rerank_elapsed),
        citations_avg_count=_mean(state.citations_counts),
        retriever_overfetch_count=int(state.overfetch_count),
        retriever_overfetch_avg_ratio=_mean(state.overfetch_ratios),
        retriever_filtered_acl_total=int(state.filtered_acl_total),
        retrieval_candidate_cache_hit_count=int(state.retrieval_candidate_cache_hit_count),
        retrieval_candidate_cache_store_ok_count=int(state.retrieval_candidate_cache_store_ok_count),
        retrieval_candidate_cache_backend_counts=dict(state.retrieval_candidate_cache_backend_counts),
        retrieval_candidate_cache_skip_reason_counts=dict(state.retrieval_candidate_cache_skip_reason_counts),
        retrieval_rerank_skip_reason_counts=dict(state.retrieval_rerank_skip_reason_counts),
        retrieval_mode_counts=dict(state.retrieval_mode_counts),
        hit_type_counts=dict(state.hit_type_counts),
        error_counts=dict(state.error_counts),
        timeseries=_rag_metrics_timeseries(state.bucket),
    )


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
    window_minutes = _normalize_window_minutes(window_minutes)
    record_window = _load_metrics_record_window(
        tenant_id=tenant_id,
        window_minutes=window_minutes,
        max_bytes=max_bytes,
    )
    state = _RagMetricsAccumulator()
    for record in record_window.records:
        _accumulate_rag_metrics_record(state, record)
    return _build_rag_metrics_summary(
        enabled=enabled,
        record_window=record_window,
        window_minutes=window_minutes,
        state=state,
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


@dataclass
class _RagCostAttributionAccumulator:
    rag_trace_count: int = 0
    llm_prompt_tokens: int = 0
    llm_completion_tokens: int = 0
    llm_total_tokens: int = 0
    llm_model_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    llm_source_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    embed_query_tokens: int = 0
    embed_query_chars: int = 0
    embed_query_count: int = 0
    embed_provider_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    embed_model_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    retrieval_elapsed: list[float] = field(default_factory=list)
    rerank_elapsed: list[float] = field(default_factory=list)
    retrieval_vector_backend_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    retrieval_query_count: int = 0


def _collect_cost_llm(state: _RagCostAttributionAccumulator, llm: dict[str, Any]) -> None:
    state.llm_prompt_tokens += _safe_int_value(llm.get("prompt_tokens"))
    state.llm_completion_tokens += _safe_int_value(llm.get("completion_tokens"))
    state.llm_total_tokens += _safe_int_value(llm.get("total_tokens"))
    _increment_limited_count(state.llm_model_counts, llm.get("model_used"), limit=120)
    _increment_limited_count(state.llm_source_counts, llm.get("source"), limit=50)


def _collect_cost_embeddings(state: _RagCostAttributionAccumulator, embeddings: dict[str, Any]) -> None:
    state.embed_query_tokens += _safe_int_value(embeddings.get("query_tokens"))
    state.embed_query_chars += _safe_int_value(embeddings.get("query_chars"))
    state.embed_query_count += _safe_int_value(embeddings.get("query_count"))
    _increment_limited_count(state.embed_provider_counts, embeddings.get("provider"), limit=50)
    _increment_limited_count(state.embed_model_counts, embeddings.get("model"), limit=80)


def _collect_cost_retrieval(state: _RagCostAttributionAccumulator, retrieval: dict[str, Any]) -> None:
    elapsed = _safe_non_negative_float(retrieval.get("elapsed_sec"))
    if elapsed is not None:
        state.retrieval_elapsed.append(elapsed)

    rerank_elapsed = _safe_non_negative_float(retrieval.get("rerank_elapsed_sec"))
    if rerank_elapsed is not None:
        state.rerank_elapsed.append(rerank_elapsed)

    _increment_limited_count(state.retrieval_vector_backend_counts, retrieval.get("vector_backend"), limit=50)
    state.retrieval_query_count += _safe_int_value(retrieval.get("query_count"))


def _accumulate_cost_attribution_record(
    state: _RagCostAttributionAccumulator,
    record: dict[str, Any],
) -> None:
    if _record_event(record) != "rag_trace":
        return

    state.rag_trace_count += 1
    cost = _safe_dict(record.get("cost_attribution"))
    if not cost:
        return

    _collect_cost_llm(state, _safe_dict(cost.get("llm")))
    _collect_cost_embeddings(state, _safe_dict(cost.get("embeddings")))
    _collect_cost_retrieval(state, _safe_dict(cost.get("retrieval")))


def _build_cost_attribution_summary(
    *,
    enabled: bool,
    record_window: _MetricsRecordWindow,
    window_minutes: int,
    state: _RagCostAttributionAccumulator,
) -> RagCostAttributionSummary:
    return RagCostAttributionSummary(
        enabled=enabled,
        path=record_window.path,
        window_minutes=int(window_minutes),
        truncated=bool(record_window.truncated),
        record_count=len(record_window.records),
        rag_trace_count=int(state.rag_trace_count),
        llm_prompt_tokens=int(state.llm_prompt_tokens),
        llm_completion_tokens=int(state.llm_completion_tokens),
        llm_total_tokens=int(state.llm_total_tokens),
        llm_model_counts=dict(state.llm_model_counts),
        llm_source_counts=dict(state.llm_source_counts),
        embed_query_tokens=int(state.embed_query_tokens),
        embed_query_chars=int(state.embed_query_chars),
        embed_query_count=int(state.embed_query_count),
        embed_provider_counts=dict(state.embed_provider_counts),
        embed_model_counts=dict(state.embed_model_counts),
        retrieval_elapsed_avg_sec=_mean(state.retrieval_elapsed),
        retrieval_elapsed_p95_sec=_percentile(state.retrieval_elapsed, 95.0),
        rerank_elapsed_avg_sec=_mean(state.rerank_elapsed),
        rerank_elapsed_p95_sec=_percentile(state.rerank_elapsed, 95.0),
        retrieval_vector_backend_counts=dict(state.retrieval_vector_backend_counts),
        retrieval_query_count=int(state.retrieval_query_count),
    )


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
    window_minutes = _normalize_window_minutes(window_minutes)
    record_window = _load_metrics_record_window(
        tenant_id=tenant_id,
        window_minutes=window_minutes,
        max_bytes=max_bytes,
    )
    state = _RagCostAttributionAccumulator()
    for record in record_window.records:
        _accumulate_cost_attribution_record(state, record)
    return _build_cost_attribution_summary(
        enabled=enabled,
        record_window=record_window,
        window_minutes=window_minutes,
        state=state,
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


@dataclass(frozen=True)
class _RateSpikeStats:
    baseline_rate: float
    baseline_std: float | None
    ratio: float | None
    z_score: float | None


def _rate_spike_stats(*, baseline_rates: list[float], current_rate: float) -> _RateSpikeStats:
    baseline_rate = _mean(baseline_rates) if baseline_rates else 0.0
    baseline_std = _stddev(baseline_rates) if baseline_rates else 0.0
    ratio = current_rate / baseline_rate if baseline_rate and baseline_rate > 1e-9 else None
    z_score = None
    if baseline_std is not None and baseline_std > 1e-9:
        z_score = (current_rate - baseline_rate) / baseline_std
    return _RateSpikeStats(
        baseline_rate=float(baseline_rate or 0.0),
        baseline_std=baseline_std,
        ratio=ratio,
        z_score=z_score,
    )


def _rate_spike_matches(
    *,
    current_rate: float,
    stats: _RateSpikeStats,
    abs_threshold: float,
    ratio_threshold: float,
    zscore_threshold: float,
) -> bool:
    meets_abs = current_rate >= float(abs_threshold or 0.0)
    meets_ratio = stats.ratio is not None and stats.ratio >= float(ratio_threshold or 0.0)
    meets_z = stats.z_score is not None and stats.z_score >= float(zscore_threshold or 0.0)
    return bool(meets_abs and (meets_ratio or meets_z or (stats.baseline_rate <= 1e-9)))


def _rate_spike_severity(
    *,
    stats: _RateSpikeStats,
    ratio_threshold: float,
    zscore_threshold: float,
) -> str:
    ratio_is_critical = stats.ratio is not None and stats.ratio >= (float(ratio_threshold or 0.0) * 2.0)
    zscore_is_critical = stats.z_score is not None and stats.z_score >= (float(zscore_threshold or 0.0) * 2.0)
    return "critical" if ratio_is_critical or zscore_is_critical else "warning"


def _rate_spike_payload(
    *,
    metric: str,
    current_rate: float,
    stats: _RateSpikeStats,
    current_requests: int,
    baseline_requests: int,
    baseline_window_minutes: int,
    current_window_minutes: int,
    severity: str,
    hints: list[str],
    extra: dict[str, Any] | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "key": f"rag.{metric}.spike",
        "metric": metric,
        "severity": severity,
        "message": f"{metric} spike: current={current_rate:.3f} baseline={stats.baseline_rate:.3f}",
        "baseline_window_minutes": int(baseline_window_minutes),
        "current_window_minutes": int(current_window_minutes),
        "current_rate": round(float(current_rate), 6),
        "baseline_rate": round(float(stats.baseline_rate), 6),
        "baseline_std": round(float(stats.baseline_std or 0.0), 6) if stats.baseline_std is not None else None,
        "ratio": round(float(stats.ratio), 6) if stats.ratio is not None else None,
        "z_score": round(float(stats.z_score), 6) if stats.z_score is not None else None,
        "current_requests": int(current_requests),
        "baseline_requests": int(baseline_requests),
        "hints": list(hints or []),
    }
    if extra:
        payload["extra"] = dict(extra)
    return payload


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

    stats = _rate_spike_stats(baseline_rates=baseline_rates, current_rate=current_rate)
    if not _rate_spike_matches(
        current_rate=current_rate,
        stats=stats,
        abs_threshold=abs_threshold,
        ratio_threshold=ratio_threshold,
        zscore_threshold=zscore_threshold,
    ):
        return None

    severity = _rate_spike_severity(
        stats=stats,
        ratio_threshold=ratio_threshold,
        zscore_threshold=zscore_threshold,
    )
    return _rate_spike_payload(
        metric=metric,
        current_rate=current_rate,
        stats=stats,
        current_requests=current_requests,
        baseline_requests=baseline_requests,
        baseline_window_minutes=baseline_window_minutes,
        current_window_minutes=current_window_minutes,
        severity=severity,
        hints=hints,
        extra=extra,
    )


@dataclass(frozen=True)
class _QueryAnomalyConfig:
    baseline_window_minutes: int
    current_window_minutes: int
    min_requests_per_bucket: int
    min_baseline_buckets: int
    zero_hit_abs_threshold: float
    zero_hit_ratio_threshold: float
    zero_hit_zscore_threshold: float
    error_abs_threshold: float
    error_ratio_threshold: float
    error_zscore_threshold: float


@dataclass(frozen=True)
class _QueryAnomalyWindow:
    current_start_ms: int
    baseline_keys: list[int]
    current_keys: list[int]


@dataclass(frozen=True)
class _QueryAnomalyBucketStats:
    baseline_rates_zero: list[float]
    baseline_rates_error: list[float]
    baseline_requests: int
    current_requests: int
    current_zero: int
    current_error: int
    baseline_bucket_count: int
    current_bucket_count: int


def _query_anomaly_config(window_minutes: int) -> _QueryAnomalyConfig | None:
    if not bool(getattr(settings, "OBS_ANOMALY_ENABLED", True)):
        return None
    window_minutes = max(1, int(window_minutes or 0))
    baseline_win = max(1, int(getattr(settings, "OBS_ANOMALY_BASELINE_WINDOW_MINUTES", 60) or 60))
    current_win = max(1, int(getattr(settings, "OBS_ANOMALY_CURRENT_WINDOW_MINUTES", 5) or 5))
    min_reqs = max(1, int(getattr(settings, "OBS_ANOMALY_MIN_REQUESTS_PER_BUCKET", 5) or 5))
    min_baseline_buckets = max(1, int(getattr(settings, "OBS_ANOMALY_MIN_BASELINE_BUCKETS", 10) or 10))

    current_win = min(current_win, window_minutes)
    baseline_win = min(baseline_win, max(0, window_minutes - current_win))
    if baseline_win <= 0 or current_win <= 0:
        return None

    return _QueryAnomalyConfig(
        baseline_window_minutes=baseline_win,
        current_window_minutes=current_win,
        min_requests_per_bucket=min_reqs,
        min_baseline_buckets=min_baseline_buckets,
        zero_hit_abs_threshold=float(getattr(settings, "OBS_ANOMALY_ZERO_HIT_RATE_ABS_THRESHOLD", 0.6) or 0.6),
        zero_hit_ratio_threshold=float(getattr(settings, "OBS_ANOMALY_ZERO_HIT_RATE_RATIO_THRESHOLD", 2.0) or 2.0),
        zero_hit_zscore_threshold=float(getattr(settings, "OBS_ANOMALY_ZERO_HIT_RATE_ZSCORE_THRESHOLD", 3.0) or 3.0),
        error_abs_threshold=float(getattr(settings, "OBS_ANOMALY_ERROR_RATE_ABS_THRESHOLD", 0.05) or 0.05),
        error_ratio_threshold=float(getattr(settings, "OBS_ANOMALY_ERROR_RATE_RATIO_THRESHOLD", 3.0) or 3.0),
        error_zscore_threshold=float(getattr(settings, "OBS_ANOMALY_ERROR_RATE_ZSCORE_THRESHOLD", 3.0) or 3.0),
    )


def _query_anomaly_window(ts_keys: list[int], config: _QueryAnomalyConfig) -> _QueryAnomalyWindow:
    last_ts_ms = max(ts_keys)
    current_start_ms = last_ts_ms - ((config.current_window_minutes - 1) * 60_000)
    baseline_start_ms = current_start_ms - (config.baseline_window_minutes * 60_000)
    return _QueryAnomalyWindow(
        current_start_ms=current_start_ms,
        baseline_keys=[k for k in ts_keys if baseline_start_ms <= k < current_start_ms],
        current_keys=[k for k in ts_keys if k >= current_start_ms],
    )


def _collect_baseline_anomaly_stats(
    bucket: dict[int, dict[str, Any]],
    keys: list[int],
    *,
    min_requests: int,
) -> tuple[list[float], list[float], int, int]:
    baseline_rates_zero: list[float] = []
    baseline_rates_error: list[float] = []
    baseline_req = 0
    baseline_bucket_count = 0

    for k in keys:
        req = int((bucket.get(k) or {}).get("requests") or 0)
        if req < min_requests:
            continue
        zh = int((bucket.get(k) or {}).get("zero_hit") or 0)
        er = int((bucket.get(k) or {}).get("errors") or 0)
        baseline_bucket_count += 1
        baseline_req += req
        baseline_rates_zero.append(_safe_rate(zh, req))
        baseline_rates_error.append(_safe_rate(er, req))

    return baseline_rates_zero, baseline_rates_error, baseline_req, baseline_bucket_count


def _collect_current_anomaly_stats(
    bucket: dict[int, dict[str, Any]],
    keys: list[int],
    *,
    min_requests: int,
) -> tuple[int, int, int, int]:
    current_req = 0
    current_zero = 0
    current_error = 0
    current_bucket_count = 0

    for k in keys:
        req = int((bucket.get(k) or {}).get("requests") or 0)
        if req < min_requests:
            continue
        zh = int((bucket.get(k) or {}).get("zero_hit") or 0)
        er = int((bucket.get(k) or {}).get("errors") or 0)
        current_bucket_count += 1
        current_req += req
        current_zero += zh
        current_error += er

    return current_req, current_zero, current_error, current_bucket_count


def _collect_query_anomaly_bucket_stats(
    bucket: dict[int, dict[str, Any]],
    window: _QueryAnomalyWindow,
    config: _QueryAnomalyConfig,
) -> _QueryAnomalyBucketStats:
    zero_rates, error_rates, baseline_req, baseline_bucket_count = _collect_baseline_anomaly_stats(
        bucket,
        window.baseline_keys,
        min_requests=config.min_requests_per_bucket,
    )
    current_req, current_zero, current_error, current_bucket_count = _collect_current_anomaly_stats(
        bucket,
        window.current_keys,
        min_requests=config.min_requests_per_bucket,
    )
    return _QueryAnomalyBucketStats(
        baseline_rates_zero=zero_rates,
        baseline_rates_error=error_rates,
        baseline_requests=baseline_req,
        current_requests=current_req,
        current_zero=current_zero,
        current_error=current_error,
        baseline_bucket_count=baseline_bucket_count,
        current_bucket_count=current_bucket_count,
    )


def _has_enough_anomaly_data(stats: _QueryAnomalyBucketStats, config: _QueryAnomalyConfig) -> bool:
    return bool(
        stats.baseline_bucket_count >= config.min_baseline_buckets
        and stats.current_requests > 0
        and stats.baseline_requests > 0
    )


def _collect_current_error_kind_counts(
    records: list[dict[str, Any]],
    *,
    current_start_ms: int,
) -> dict[str, int]:
    current_error_kinds: dict[str, int] = defaultdict(int)
    for record in records:
        if _record_event(record) != "rag_trace":
            continue
        ts_ms = _record_ts_ms(record)
        if ts_ms and ts_ms < current_start_ms:
            continue
        errors = _safe_dict(record.get("retrieval")).get("errors")
        if not isinstance(errors, list) or not errors:
            continue
        for error in errors:
            if not isinstance(error, str):
                continue
            kind = error.split(":", 1)[0].strip().lower()
            if not kind:
                continue
            current_error_kinds[kind[:30]] += 1
    return dict(current_error_kinds)


def _top_error_kind(error_kind_counts: dict[str, int]) -> str | None:
    if not error_kind_counts:
        return None
    return min(error_kind_counts.items(), key=lambda kv: (-kv[1], kv[0]))[0]


def _zero_hit_anomaly_hints() -> list[str]:
    return [
        "Index 可能为空或入库未完成：检查 ingestion/queue 状态与 index-audit。",
        "检索 scope 过窄或 ACL 过滤过严：确认 dataset/document scope 与权限配置。",
        "检索配置变更：对比 retrieval_config_hash 或最近配置变更。",
    ]


def _error_anomaly_hints() -> list[str]:
    return [
        "向量/检索后端异常：检查 /health/ready 与依赖延迟（DB/Redis/vector）。",
        "reranker 上游故障或 429：检查 provider 状态与限流/配额。",
        "查看 error_kind_counts 以定位主要失败类型。",
    ]


def _zero_hit_rate_anomaly(
    *,
    stats: _QueryAnomalyBucketStats,
    config: _QueryAnomalyConfig,
) -> dict[str, Any] | None:
    return _detect_rate_spike(
        metric="zero_hit_rate",
        baseline_rates=stats.baseline_rates_zero,
        current_rate=_safe_rate(stats.current_zero, stats.current_requests),
        current_requests=stats.current_requests,
        baseline_requests=stats.baseline_requests,
        baseline_window_minutes=config.baseline_window_minutes,
        current_window_minutes=config.current_window_minutes,
        abs_threshold=config.zero_hit_abs_threshold,
        ratio_threshold=config.zero_hit_ratio_threshold,
        zscore_threshold=config.zero_hit_zscore_threshold,
        hints=_zero_hit_anomaly_hints(),
        extra={"baseline_buckets": stats.baseline_bucket_count, "current_buckets": stats.current_bucket_count},
    )


def _error_rate_anomaly(
    *,
    stats: _QueryAnomalyBucketStats,
    config: _QueryAnomalyConfig,
    top_error_kind: str | None,
) -> dict[str, Any] | None:
    return _detect_rate_spike(
        metric="error_rate",
        baseline_rates=stats.baseline_rates_error,
        current_rate=_safe_rate(stats.current_error, stats.current_requests),
        current_requests=stats.current_requests,
        baseline_requests=stats.baseline_requests,
        baseline_window_minutes=config.baseline_window_minutes,
        current_window_minutes=config.current_window_minutes,
        abs_threshold=config.error_abs_threshold,
        ratio_threshold=config.error_ratio_threshold,
        zscore_threshold=config.error_zscore_threshold,
        hints=_error_anomaly_hints(),
        extra={
            "top_error_kind": top_error_kind,
            "baseline_buckets": stats.baseline_bucket_count,
            "current_buckets": stats.current_bucket_count,
        },
    )


def _detect_query_analytics_anomalies(
    *,
    bucket: dict[int, dict[str, Any]],
    records: list[dict[str, Any]],
    ts_keys: list[int],
    window_minutes: int,
) -> list[dict[str, Any]]:
    if not ts_keys:
        return []

    config = _query_anomaly_config(window_minutes)
    if config is None:
        return []

    window = _query_anomaly_window(ts_keys, config)
    stats = _collect_query_anomaly_bucket_stats(bucket, window, config)
    if not _has_enough_anomaly_data(stats, config):
        return []

    top_error_kind = _top_error_kind(
        _collect_current_error_kind_counts(records, current_start_ms=window.current_start_ms)
    )
    anomalies = [
        anomaly
        for anomaly in (
            _zero_hit_rate_anomaly(stats=stats, config=config),
            _error_rate_anomaly(stats=stats, config=config, top_error_kind=top_error_kind),
        )
        if anomaly
    ]
    return sorted(anomalies, key=lambda x: str(x.get("metric") or ""))


@dataclass
class _RagQueryAnalyticsAccumulator:
    rag_trace_count: int = 0
    query_hashes: set[str] = field(default_factory=set)
    retrieval_elapsed: list[float] = field(default_factory=list)
    zero_hit_count: int = 0
    slow_count: int = 0
    error_kind_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    zero_hit_by_hash: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    slow_by_hash_count: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    slow_by_hash_max_elapsed: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    bucket: dict[int, dict[str, Any]] = field(default_factory=dict)


def _query_analytics_bucket(state: _RagQueryAnalyticsAccumulator, minute_ms: int) -> dict[str, Any] | None:
    if not minute_ms:
        return None
    return state.bucket.setdefault(
        minute_ms,
        {"ts_ms": minute_ms, "requests": 0, "zero_hit": 0, "slow": 0, "errors": 0},
    )


def _query_hash_from_record(record: dict[str, Any]) -> str | None:
    qhash = record.get("query_hash") or record.get("question_hash")
    if not qhash:
        raw_query = record.get("query_for_retrieval") or record.get("question")
        if isinstance(raw_query, str) and raw_query.strip():
            qhash = _hash_for_analytics(raw_query.strip())
    if isinstance(qhash, str) and qhash.strip():
        return qhash.strip()
    return None


def _citation_count_from_record(record: dict[str, Any]) -> int:
    try:
        if record.get("citations_count") is not None:
            return int(record.get("citations_count") or 0)
        citations = record.get("citations") or []
        return len(citations) if isinstance(citations, list) else 0
    except Exception:
        return 0


def _query_error_kinds(retrieval: dict[str, Any]) -> tuple[list[str], bool]:
    errors = retrieval.get("errors")
    if not isinstance(errors, list) or not errors:
        return [], False

    kinds: list[str] = []
    for error in errors:
        if not isinstance(error, str):
            continue
        kind = error.split(":", 1)[0].strip().lower()
        if kind:
            kinds.append(kind[:30])
    return kinds, True


def _collect_query_error_metrics(
    state: _RagQueryAnalyticsAccumulator,
    retrieval: dict[str, Any],
    bucket_entry: dict[str, Any] | None,
) -> None:
    kinds, has_error = _query_error_kinds(retrieval)
    for kind in kinds:
        state.error_kind_counts[kind] += 1
    if has_error and bucket_entry is not None:
        bucket_entry["errors"] += 1


def _collect_zero_hit_query(
    state: _RagQueryAnalyticsAccumulator,
    *,
    qhash: str | None,
    bucket_entry: dict[str, Any] | None,
) -> None:
    state.zero_hit_count += 1
    if bucket_entry is not None:
        bucket_entry["zero_hit"] += 1
    if qhash:
        state.zero_hit_by_hash[qhash] += 1


def _collect_slow_query(
    state: _RagQueryAnalyticsAccumulator,
    *,
    qhash: str | None,
    elapsed_sec: float,
    bucket_entry: dict[str, Any] | None,
) -> None:
    state.slow_count += 1
    if bucket_entry is not None:
        bucket_entry["slow"] += 1
    if qhash:
        state.slow_by_hash_count[qhash] += 1
        state.slow_by_hash_max_elapsed[qhash] = max(
            float(state.slow_by_hash_max_elapsed.get(qhash) or 0.0),
            elapsed_sec,
        )


def _accumulate_query_analytics_record(
    state: _RagQueryAnalyticsAccumulator,
    record: dict[str, Any],
    *,
    slow_threshold_sec: float,
) -> None:
    if _record_event(record) != "rag_trace":
        return

    state.rag_trace_count += 1
    bucket_entry = _query_analytics_bucket(state, _metric_minute_ms(record))
    if bucket_entry is not None:
        bucket_entry["requests"] += 1

    qhash = _query_hash_from_record(record)
    if qhash:
        state.query_hashes.add(qhash)

    retrieval = _safe_dict(record.get("retrieval"))
    elapsed_sec = _safe_non_negative_float(retrieval.get("elapsed_sec"))
    if elapsed_sec is not None:
        state.retrieval_elapsed.append(elapsed_sec)

    _collect_query_error_metrics(state, retrieval, bucket_entry)

    if _citation_count_from_record(record) == 0:
        _collect_zero_hit_query(state, qhash=qhash, bucket_entry=bucket_entry)
    if slow_threshold_sec > 0 and elapsed_sec is not None and elapsed_sec >= slow_threshold_sec:
        _collect_slow_query(state, qhash=qhash, elapsed_sec=elapsed_sec, bucket_entry=bucket_entry)


def _top_zero_hit_queries(state: _RagQueryAnalyticsAccumulator, *, top_n: int) -> list[dict[str, Any]]:
    top_zero = sorted(state.zero_hit_by_hash.items(), key=lambda kv: (-kv[1], kv[0]))[:top_n]
    return [{"query_hash": h, "count": int(c)} for h, c in top_zero]


def _top_slow_queries(state: _RagQueryAnalyticsAccumulator, *, top_n: int) -> list[dict[str, Any]]:
    top_slow_items = sorted(
        state.slow_by_hash_count.items(),
        key=lambda kv: (-kv[1], -(float(state.slow_by_hash_max_elapsed.get(kv[0]) or 0.0)), kv[0]),
    )[:top_n]
    return [
        {
            "query_hash": h,
            "count": int(c),
            "max_elapsed_sec": round(float(state.slow_by_hash_max_elapsed.get(h) or 0.0), 3),
        }
        for h, c in top_slow_items
    ]


def _query_analytics_timeseries(bucket: dict[int, dict[str, Any]]) -> dict[str, list[Any]]:
    ts_keys = sorted(k for k in bucket.keys() if k)
    return {
        "ts_ms": list(ts_keys),
        "requests": [int(bucket[k]["requests"]) for k in ts_keys],
        "zero_hit": [int(bucket[k]["zero_hit"]) for k in ts_keys],
        "slow": [int(bucket[k]["slow"]) for k in ts_keys],
        "errors": [int(bucket[k]["errors"]) for k in ts_keys],
    }


def _build_query_analytics_summary(
    *,
    enabled: bool,
    record_window: _MetricsRecordWindow,
    window_minutes: int,
    slow_threshold_sec: float,
    top_n: int,
    state: _RagQueryAnalyticsAccumulator,
) -> RagQueryAnalyticsSummary:
    ts_keys = sorted(k for k in state.bucket.keys() if k)
    return RagQueryAnalyticsSummary(
        enabled=enabled,
        path=record_window.path,
        window_minutes=int(window_minutes),
        truncated=bool(record_window.truncated),
        record_count=len(record_window.records),
        rag_trace_count=int(state.rag_trace_count),
        unique_query_hashes=len(state.query_hashes),
        zero_hit_count=int(state.zero_hit_count),
        zero_hit_rate=(state.zero_hit_count / state.rag_trace_count) if state.rag_trace_count else None,
        slow_threshold_sec=slow_threshold_sec,
        slow_count=int(state.slow_count),
        slow_rate=(state.slow_count / state.rag_trace_count) if state.rag_trace_count else None,
        retrieval_p50_elapsed_sec=_percentile(state.retrieval_elapsed, 50.0),
        retrieval_p95_elapsed_sec=_percentile(state.retrieval_elapsed, 95.0),
        retrieval_p99_elapsed_sec=_percentile(state.retrieval_elapsed, 99.0),
        error_kind_counts=dict(state.error_kind_counts),
        top_zero_hit_queries=_top_zero_hit_queries(state, top_n=top_n),
        top_slow_queries=_top_slow_queries(state, top_n=top_n),
        timeseries=_query_analytics_timeseries(state.bucket),
        anomalies=_detect_query_analytics_anomalies(
            bucket=state.bucket,
            records=record_window.records,
            ts_keys=ts_keys,
            window_minutes=window_minutes,
        ),
    )


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
    window_minutes = _normalize_window_minutes(window_minutes)
    top_n = max(1, min(200, int(top_n or 0)))
    slow_threshold_sec = max(0.0, float(slow_threshold_sec or 0.0))

    record_window = _load_metrics_record_window(
        tenant_id=tenant_id,
        window_minutes=window_minutes,
        max_bytes=max_bytes,
    )
    state = _RagQueryAnalyticsAccumulator()
    for record in record_window.records:
        _accumulate_query_analytics_record(state, record, slow_threshold_sec=slow_threshold_sec)
    return _build_query_analytics_summary(
        enabled=enabled,
        record_window=record_window,
        window_minutes=window_minutes,
        slow_threshold_sec=slow_threshold_sec,
        top_n=top_n,
        state=state,
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


def _add_hashed_text_metadata(
    out: dict[str, Any],
    *,
    source_field: str,
    hash_field: str,
    chars_field: str,
) -> None:
    text = out.pop(source_field, None)
    if isinstance(text, str) and text.strip():
        normalized = text.strip()
        out.setdefault(hash_field, _hash_for_analytics(normalized))
        out.setdefault(chars_field, len(normalized))


def _sanitize_trace_citations(citations: Any) -> list[dict[str, Any]] | None:
    if not isinstance(citations, list):
        return None

    safe: list[dict[str, Any]] = []
    for citation in citations:
        citation_dict = _safe_dict(citation)
        if not citation_dict:
            continue
        item = {key: citation_dict.get(key) for key in _TRACE_BUNDLE_CITATION_SAFE_KEYS if citation_dict.get(key) is not None}
        if item:
            safe.append(item)
        if len(safe) >= 50:
            break
    return safe


def _sanitize_rag_trace_for_bundle(record: dict[str, Any]) -> dict[str, Any]:
    """
    Return a PII-safe copy of a rag_trace record (for incident bundles).

    Guarantees:
    - No raw question/query text in output
    - Citations contain only identifiers + numeric fields (no snippets)
    """

    out = dict(record)
    _add_hashed_text_metadata(out, source_field="question", hash_field="question_hash", chars_field="question_chars")
    _add_hashed_text_metadata(
        out,
        source_field="query_for_retrieval",
        hash_field="query_hash",
        chars_field="query_chars",
    )

    safe_citations = _sanitize_trace_citations(out.get("citations"))
    if safe_citations is not None:
        out["citations"] = safe_citations

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


def _metrics_tail_redactor() -> Any | None:
    try:
        from app.core.pii_redaction import PIIRedactor

        return PIIRedactor(mask="[REDACTED]")
    except Exception:  # noqa: BLE001
        return None


def _strip_generic_sensitive_fields(record: dict[str, Any]) -> dict[str, Any]:
    safe = dict(record)
    for key in (
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
        safe.pop(key, None)

    metrics = safe.get("metrics")
    if isinstance(metrics, dict):
        metric_payload = dict(metrics)
        metric_payload.pop("structured_data", None)
        metric_payload.pop("abstain_followup", None)
        safe["metrics"] = metric_payload
    return safe


def _redacted_metrics_tail_record(record: dict[str, Any], redactor: Any | None) -> dict[str, Any]:
    event = _record_event(record)
    if event == "rag_trace":
        safe = _sanitize_rag_trace_for_bundle(record)
    elif event == "rag_done":
        safe = _sanitize_rag_done_for_bundle(record)
    else:
        safe = _strip_generic_sensitive_fields(record)
    return redactor.redact_obj(safe) if redactor is not None else safe


def _json_line_or_none(record: dict[str, Any]) -> str | None:
    try:
        return json.dumps(record, ensure_ascii=False, default=str)
    except Exception:
        return None


def _gzip_jsonl_lines(lines: list[str]) -> bytes:
    text = "\n".join(lines)
    if text:
        text += "\n"
    return gzip.compress(text.encode("utf-8"))


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

    record_window = _load_metrics_record_window(
        tenant_id=tenant_id,
        window_minutes=_normalize_window_minutes(window_minutes),
        max_bytes=max_bytes,
    )
    redactor = _metrics_tail_redactor()

    lines: list[str] = []
    for record in record_window.records:
        line = _json_line_or_none(_redacted_metrics_tail_record(record, redactor))
        if line is not None:
            lines.append(line)
    return _gzip_jsonl_lines(lines)


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


def _trace_bundle_citations_count(trace: dict[str, Any]) -> int | None:
    try:
        if trace.get("citations_count") is not None:
            return int(trace.get("citations_count") or 0)
        citations = trace.get("citations") or []
        return len(citations) if isinstance(citations, list) else 0
    except Exception:
        return None


def _rounded_non_negative_float(value: Any, *, digits: int) -> float | None:
    coerced = _coerce_float(value)
    if coerced is None:
        return None
    return round(max(0.0, coerced), digits)


def _rounded_float(value: Any, *, digits: int) -> float | None:
    coerced = _coerce_float(value)
    return round(coerced, digits) if coerced is not None else None


def _str_or_none(value: Any) -> str | None:
    return str(value or "").strip() or None


def _retrieval_bool_or_none(retrieval: dict[str, Any], key: str) -> bool | None:
    value = retrieval.get(key)
    return bool(value) if value is not None else None


def _trace_bundle_retrieval_summary(retrieval: dict[str, Any], done: dict[str, Any]) -> dict[str, Any]:
    return {
        "retrieval_config_hash": _str_or_none(retrieval.get("retrieval_config_hash")),
        "retrieval_mode": _str_or_none(retrieval.get("mode") or done.get("retrieval_mode")),
        "retrieval_requested_mode": _str_or_none(retrieval.get("requested_mode")),
        "retrieval_auto_routed": _retrieval_bool_or_none(retrieval, "auto_routed"),
        "retrieval_profile": _str_or_none(retrieval.get("profile")),
        "retrieval_top_k": _coerce_int(retrieval.get("top_k")),
        "retrieval_alpha": _rounded_float(retrieval.get("alpha"), digits=6),
        "retrieval_enable_reranker": _retrieval_bool_or_none(retrieval, "enable_reranker"),
        "retrieval_reranker_provider": _str_or_none(retrieval.get("reranker_provider")),
        "retrieval_reranker_top_n": _coerce_int(retrieval.get("reranker_top_n")),
        "retrieval_query_parallelism": _coerce_int(retrieval.get("query_parallelism")),
        "retrieval_query_count": _coerce_int(retrieval.get("query_count")),
        "retrieval_elapsed_sec": _rounded_non_negative_float(retrieval.get("elapsed_sec"), digits=3),
        "retrieval_error_kinds": _extract_error_kind_counts(retrieval.get("errors")),
    }


def _trace_bundle_model_summary(route_trace: dict[str, Any], done: dict[str, Any]) -> dict[str, Any]:
    return {
        "model_route": _str_or_none(route_trace.get("model_route") or done.get("route")),
        "model_used": _str_or_none(route_trace.get("model_used") or done.get("model_used")),
        "vector_backend": _str_or_none(done.get("vector_backend")),
    }


def _extract_trace_bundle_summary(bundle: RagTraceBundle) -> dict[str, Any]:
    trace = _first_event(bundle.records, "rag_trace") or {}
    done = _first_event(bundle.records, "rag_done") or {}
    retrieval = _safe_dict(trace.get("retrieval"))
    route_trace = _safe_dict(trace.get("route"))

    out: dict[str, Any] = {
        "request_id": bundle.request_id,
        "window_minutes": int(bundle.window_minutes),
        "truncated": bool(bundle.truncated),
        "citations_count": _trace_bundle_citations_count(trace),
    }
    out.update(_trace_bundle_retrieval_summary(retrieval, done))
    out.update(_trace_bundle_model_summary(route_trace, done))
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


def _sanitize_trace_bundle_record(record: dict[str, Any]) -> dict[str, Any]:
    event = _record_event(record)
    if event == "rag_trace":
        return _sanitize_rag_trace_for_bundle(record)
    if event == "rag_done":
        return _sanitize_rag_done_for_bundle(record)
    return dict(record)


def _matching_trace_bundle_records(records: list[dict[str, Any]], *, request_id: str) -> list[dict[str, Any]]:
    matched = [
        _sanitize_trace_bundle_record(record)
        for record in records
        if str(record.get("request_id") or "") == request_id
    ]
    return sorted(matched, key=lambda x: int(x.get("ts_ms") or 0))


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
    request_id = str(request_id or "").strip()
    if not request_id:
        return None

    window_minutes = _normalize_window_minutes(window_minutes)
    record_window = _load_metrics_record_window(
        tenant_id=tenant_id,
        window_minutes=window_minutes,
        max_bytes=max_bytes,
    )
    matched = _matching_trace_bundle_records(record_window.records, request_id=request_id)

    if not matched:
        return None

    return RagTraceBundle(
        enabled=enabled,
        path=record_window.path,
        window_minutes=window_minutes,
        truncated=record_window.truncated,
        record_count=len(record_window.records),
        request_id=request_id,
        records=matched,
    )


__all__ = [
    "RagTraceBundle",
    "build_rag_trace_bundle",
    "RagTraceBundleDiff",
    "build_rag_trace_bundle_diff",
]
