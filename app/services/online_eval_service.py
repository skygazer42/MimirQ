"""
Online (production) evaluation helpers.

Goal (P0):
- Sample a small fraction of production RAG requests (default: 5%)
- Compute lightweight, deterministic quality signals:
  - faithfulness_det (claim-support ratio proxy)
  - chunk_utilization (used_chunks / retrieved_chunks)
- Emit PII-minimal metrics records into the existing JSONL metrics log
- Provide a small dashboard summary (window + timeseries + alerts)
"""

import atexit
import hashlib
import math
import queue
import threading
import time
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict

from app.core.config import settings
from app.core.constants import NON_CRITICAL_EXCEPTION_LOG_MESSAGE
from app.rag.core.logging import get_logger
from app.rag.core.text import is_claim_supported, split_into_claims
from app.rag.evaluation.chunk_diagnostics import compute_chunk_diagnostics
from app.services.jsonl_tail import read_jsonl_tail
from app.services.metrics_logger import log_metrics

logger = get_logger(__name__)


def _mean(values: Iterable[float]) -> float | None:
    vals: list[float] = []
    for v in values:
        try:
            fv = float(v)
        except Exception:
            get_logger(__name__).debug(NON_CRITICAL_EXCEPTION_LOG_MESSAGE, exc_info=True)
            continue
        if math.isnan(fv):
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
    return read_jsonl_tail(
        path,
        max_bytes=max_bytes,
        log_message=NON_CRITICAL_EXCEPTION_LOG_MESSAGE,
    )


def _stable_sample(*, tenant_id: str | None, request_id: str | None, rate: float) -> bool:
    """
    Stable sampling decision for a given (tenant_id, request_id).

    This avoids per-process RNG drift and keeps sampling predictable when multiple workers
    handle requests.
    """
    try:
        r = float(rate)
    except Exception:
        r = 0.0
    r = min(1.0, max(0.0, r))
    if r <= 0.0:
        return False
    if r >= 1.0:
        return True

    key = f"{tenant_id or ''}:{request_id or ''}".encode("utf-8", errors="ignore")
    digest = hashlib.sha256(key).digest()
    # 0..1 float from first 4 bytes.
    val = int.from_bytes(digest[:4], "big") / float(2**32)
    return val < r


def compute_faithfulness_det(answer: str, contexts: list[str], *, max_evidence_chars: int = 24_000) -> float | None:
    """
    Deterministic, bounded faithfulness proxy.

    Same shape as regression `faithfulness_det`:
    - split answer into atomic claims
    - score = supported_claims / total_claims (support checked against joined evidence)
    """
    raw_answer = answer.strip()
    if not raw_answer:
        return None

    claims = split_into_claims(raw_answer, max_claims=24)
    if not claims:
        return None

    joined = "\n".join([c for c in (contexts or []) if c.strip()])
    evidence = joined
    if max_evidence_chars and max_evidence_chars > 0 and len(evidence) > int(max_evidence_chars):
        evidence = evidence[: int(max_evidence_chars)]

    supported = 0
    total = 0
    for claim in claims:
        c = claim.strip()
        if not c:
            continue
        total += 1
        if is_claim_supported(c, evidence):
            supported += 1

    if total <= 0:
        return None
    return round(float(supported) / float(total), 4)


@dataclass(frozen=True)
class OnlineQualitySummary:
    enabled: bool
    path: str
    window_minutes: int
    bucket_minutes: int
    truncated: bool
    record_count: int
    sample_count: int
    faithfulness_det_avg: float | None
    chunk_utilization_avg: float | None
    timeseries: dict[str, list[Any]]
    alerts: list[dict[str, Any]]


def _record_timestamp(record: dict[str, Any]) -> int:
    try:
        return int(record.get("ts_ms") or 0)
    except Exception:
        return 0


def _online_eval_records(
    records: list[dict[str, Any]],
    *,
    tenant_id: str | None,
    cutoff_ms: int,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for record in records:
        ts_ms = _record_timestamp(record)
        if ts_ms and ts_ms < cutoff_ms:
            continue
        if tenant_id:
            record_tenant_id = record.get("tenant_id")
            if record_tenant_id and str(record_tenant_id) != tenant_id:
                continue
        if record.get("event") == "online_eval":
            selected.append(record)
    return selected


def _earliest_record_timestamp(records: list[dict[str, Any]]) -> int | None:
    timestamps = [timestamp for record in records if (timestamp := _record_timestamp(record))]
    return min(timestamps) if timestamps else None


def _finite_metric(value: Any) -> float | None:
    try:
        number = float(value) if value is not None else None
    except Exception:
        return None
    return number if number is not None and math.isfinite(number) else None


class _QualityBucket(TypedDict):
    ts_ms: int
    samples: int
    faith_sum: float
    faith_n: int
    util_sum: float
    util_n: int


def _quality_buckets(
    records: list[dict[str, Any]],
    *,
    bucket_ms: int,
) -> tuple[dict[int, _QualityBucket], list[float], list[float]]:
    faith_values: list[float] = []
    utilization_values: list[float] = []
    buckets: dict[int, _QualityBucket] = defaultdict(
        lambda: {
            "ts_ms": 0,
            "samples": 0,
            "faith_sum": 0.0,
            "faith_n": 0,
            "util_sum": 0.0,
            "util_n": 0,
        }
    )
    for record in records:
        ts_ms = _record_timestamp(record)
        if not ts_ms:
            continue
        bucket_timestamp = (ts_ms // bucket_ms) * bucket_ms
        bucket = buckets[bucket_timestamp]
        bucket["ts_ms"] = bucket_timestamp
        bucket["samples"] += 1
        faithfulness = _finite_metric(record.get("faithfulness_det"))
        if faithfulness is not None:
            faith_values.append(faithfulness)
            bucket["faith_sum"] += faithfulness
            bucket["faith_n"] += 1
        utilization = _finite_metric(record.get("chunk_utilization"))
        if utilization is not None:
            utilization_values.append(utilization)
            bucket["util_sum"] += utilization
            bucket["util_n"] += 1
    return buckets, faith_values, utilization_values


def _quality_timeseries(
    buckets: dict[int, _QualityBucket],
) -> tuple[list[int], list[int], list[float | None], list[float | None]]:
    timestamps = sorted(buckets)
    samples = [buckets[key]["samples"] for key in timestamps]
    faithfulness: list[float | None] = []
    utilization: list[float | None] = []
    for key in timestamps:
        bucket = buckets[key]
        faith_count = bucket["faith_n"]
        utilization_count = bucket["util_n"]
        faithfulness.append((bucket["faith_sum"] / faith_count) if faith_count else None)
        utilization.append((bucket["util_sum"] / utilization_count) if utilization_count else None)
    return timestamps, samples, faithfulness, utilization


def _quality_alert(
    *,
    metric: str,
    value: float | None,
    threshold: float,
    bucket_ts_ms: int,
    samples: int,
) -> dict[str, Any] | None:
    if value is None or value >= threshold:
        return None
    return {
        "kind": "quality_drop",
        "metric": metric,
        "value": round(value, 4),
        "threshold": round(threshold, 4),
        "bucket_ts_ms": bucket_ts_ms,
        "samples": samples,
    }


def _quality_alerts(
    *,
    timestamps: list[int],
    samples: list[int],
    faithfulness: list[float | None],
    utilization: list[float | None],
) -> list[dict[str, Any]]:
    if not timestamps:
        return []
    minimum_samples = int(settings.ONLINE_EVAL_ALERT_MIN_SAMPLES_PER_BUCKET or 10)
    if samples[-1] < minimum_samples:
        return []
    candidates = [
        _quality_alert(
            metric="faithfulness_det",
            value=faithfulness[-1] if faithfulness else None,
            threshold=float(settings.ONLINE_EVAL_ALERT_FAITHFULNESS_DET_MIN or 0.6),
            bucket_ts_ms=timestamps[-1],
            samples=samples[-1],
        ),
        _quality_alert(
            metric="chunk_utilization",
            value=utilization[-1] if utilization else None,
            threshold=float(settings.ONLINE_EVAL_ALERT_CHUNK_UTILIZATION_MIN or 0.12),
            bucket_ts_ms=timestamps[-1],
            samples=samples[-1],
        ),
    ]
    return [alert for alert in candidates if alert is not None]


def summarize_online_quality(
    *,
    tenant_id: str | None,
    window_minutes: int = 60,
    bucket_minutes: int = 5,
    max_bytes: int = 5_000_000,
) -> OnlineQualitySummary:
    enabled = bool(settings.ENABLE_METRICS_LOG) and bool(settings.ONLINE_EVAL_ENABLED)
    path_str = str(settings.METRICS_LOG_PATH or "./logs/rag_metrics.jsonl")
    path = Path(path_str)

    window_minutes = max(1, int(window_minutes or 0))
    bucket_minutes = max(1, min(int(bucket_minutes or 0), 60))
    bucket_ms = bucket_minutes * 60 * 1000
    cutoff_ms = int(time.time() * 1000) - (window_minutes * 60 * 1000)

    raw_records, truncated_by_tail = _read_jsonl_tail(path, max_bytes=int(max_bytes or 0))

    tenant_key = str(tenant_id) if tenant_id else None
    records = _online_eval_records(raw_records, tenant_id=tenant_key, cutoff_ms=cutoff_ms)
    earliest_ts_ms = _earliest_record_timestamp(records)
    truncated = bool(truncated_by_tail and earliest_ts_ms is not None and earliest_ts_ms > cutoff_ms)
    buckets, faith_vals, util_vals = _quality_buckets(records, bucket_ms=bucket_ms)
    ts_ms_series, samples_series, faith_series, util_series = _quality_timeseries(buckets)
    alerts = _quality_alerts(
        timestamps=ts_ms_series,
        samples=samples_series,
        faithfulness=faith_series,
        utilization=util_series,
    )

    return OnlineQualitySummary(
        enabled=enabled,
        path=str(path),
        window_minutes=window_minutes,
        bucket_minutes=bucket_minutes,
        truncated=truncated,
        record_count=len(raw_records),
        sample_count=len(records),
        faithfulness_det_avg=_mean(faith_vals),
        chunk_utilization_avg=_mean(util_vals),
        timeseries={
            "ts_ms": ts_ms_series,
            "samples": samples_series,
            "faithfulness_det_avg": [None if v is None else round(v, 4) for v in faith_series],
            "chunk_utilization_avg": [None if v is None else round(v, 4) for v in util_series],
        },
        alerts=alerts,
    )


# ========================== Async sampling worker ==========================


_queue_max = max(10, int(settings.ONLINE_EVAL_QUEUE_MAX or 500))
_eval_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=_queue_max)
_worker_started = False
_worker_lock = threading.Lock()
_worker_thread: threading.Thread | None = None
_stop_event = threading.Event()


def _ensure_worker_started() -> None:
    global _worker_started, _worker_thread
    if _worker_started:
        return
    with _worker_lock:
        if _worker_started:
            return

        def _run() -> None:
            while not _stop_event.is_set():
                try:
                    item = _eval_queue.get(timeout=0.25)
                except queue.Empty:
                    continue
                try:
                    _process_eval_item(item)
                except Exception as exc:
                    logger.debug("Ignoring online evaluation worker item failure: %s", exc)
                finally:
                    with contextlib.suppress(Exception):
                        _eval_queue.task_done()

        import contextlib

        _worker_thread = threading.Thread(target=_run, name="online-eval-worker", daemon=True)
        _worker_thread.start()
        _worker_started = True


def _process_eval_item(item: dict[str, Any]) -> None:
    answer = item["answer"]
    contexts_raw = item.get("contexts")
    contexts = [str(c or "") for c in (contexts_raw or []) if str(c or "").strip()]
    # Bound context sizes (best-effort).
    contexts = [c[:4000] for c in contexts][:24]

    fd = compute_faithfulness_det(answer, contexts)
    diag = compute_chunk_diagnostics(answer=answer, retrieved_contexts=contexts)
    cu = diag.get("chunk_utilization")
    counts = diag.get("counts") if isinstance(diag.get("counts"), dict) else {}

    payload: dict[str, Any] = {
        "event": "online_eval",
        "tenant_id": item.get("tenant_id"),
        "dataset_id": item.get("dataset_id"),
        "request_id": item.get("request_id"),
        "retrieval_mode": item.get("retrieval_mode"),
        "citations_count": item.get("citations_count"),
        "sample_rate": item.get("sample_rate"),
        "faithfulness_det": fd,
        "chunk_utilization": cu,
        "chunk_attribution": diag.get("chunk_attribution"),
        "claims_total": counts.get("claims_total"),
        "claims_supported": counts.get("claims_supported"),
        "chunks_total": counts.get("chunks_total"),
        "chunks_used": counts.get("chunks_used"),
    }
    log_metrics(payload)


def maybe_enqueue_online_eval(
    *,
    tenant_id: Any | None,
    dataset_id: Any | None,
    request_id: str | None,
    answer: str,
    contexts: list[str],
    retrieval_mode: str | None = None,
    citations_count: int | None = None,
) -> dict[str, Any]:
    """
    Best-effort: enqueue a sampled online evaluation item.

    Returns a small debug dict (PII-minimal) intended for in-memory metrics/debugging only.
    """
    enabled = bool(settings.ONLINE_EVAL_ENABLED) and bool(settings.ENABLE_METRICS_LOG)
    if not enabled:
        return {"enabled": False, "enqueued": False, "reason": "disabled"}

    rate = float(settings.ONLINE_EVAL_SAMPLE_RATE)
    if not _stable_sample(tenant_id=str(tenant_id) if tenant_id else None, request_id=str(request_id or ""), rate=rate):
        return {"enabled": True, "enqueued": False, "reason": "not_sampled", "sample_rate": rate}

    # Keep item small and PII-minimal (no questions). Context text is used only in-memory for evaluation.
    item = {
        "tenant_id": str(tenant_id) if tenant_id else None,
        "dataset_id": str(dataset_id) if dataset_id else None,
        "request_id": str(request_id or "")[:200] if request_id else None,
        "retrieval_mode": retrieval_mode,
        "citations_count": int(citations_count) if citations_count is not None else None,
        "sample_rate": round(rate, 6),
        "answer": answer,
        "contexts": [c for c in (contexts or []) if c.strip()],
    }

    _ensure_worker_started()
    try:
        _eval_queue.put_nowait(item)
        return {"enabled": True, "enqueued": True, "sample_rate": rate}
    except queue.Full:
        # Drop on overload: do not block request path.
        log_metrics(
            {
                "event": "online_eval_drop",
                "tenant_id": str(tenant_id) if tenant_id else None,
                "dataset_id": str(dataset_id) if dataset_id else None,
                "request_id": str(request_id or "")[:200] if request_id else None,
                "reason": "queue_full",
                "sample_rate": round(rate, 6),
            }
        )
        return {"enabled": True, "enqueued": False, "reason": "queue_full", "sample_rate": rate}


def _shutdown_worker() -> None:
    _stop_event.set()


atexit.register(_shutdown_worker)


__all__ = [
    "OnlineQualitySummary",
    "compute_faithfulness_det",
    "maybe_enqueue_online_eval",
    "summarize_online_quality",
]
