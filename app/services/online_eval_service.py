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

from __future__ import annotations

import atexit
import hashlib
import json
import logging
import math
import queue
import threading
import time
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.rag.core.logging import get_logger
from app.rag.core.text import is_claim_supported, split_into_claims
from app.rag.evaluation.chunk_diagnostics import compute_chunk_diagnostics
from app.services.metrics_logger import log_metrics

logger = get_logger(__name__)


def _mean(values: Iterable[float]) -> float | None:
    vals: list[float] = []
    for v in values:
        try:
            fv = float(v)
        except Exception:
            logging.getLogger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
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
            logging.getLogger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
            continue
        if isinstance(obj, dict):
            records.append(obj)
    return records, truncated


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
    return bool(val < r)


def compute_faithfulness_det(answer: str, contexts: list[str], *, max_evidence_chars: int = 24_000) -> float | None:
    """
    Deterministic, bounded faithfulness proxy.

    Same shape as regression `faithfulness_det`:
    - split answer into atomic claims
    - score = supported_claims / total_claims (support checked against joined evidence)
    """
    raw_answer = str(answer or "").strip()
    if not raw_answer:
        return None

    claims = split_into_claims(raw_answer, max_claims=24)
    if not claims:
        return None

    joined = "\n".join([str(c or "") for c in (contexts or []) if str(c or "").strip()])
    evidence = joined
    if max_evidence_chars and max_evidence_chars > 0 and len(evidence) > int(max_evidence_chars):
        evidence = evidence[: int(max_evidence_chars)]

    supported = 0
    total = 0
    for claim in claims:
        c = str(claim or "").strip()
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


def summarize_online_quality(
    *,
    tenant_id: str | None,
    window_minutes: int = 60,
    bucket_minutes: int = 5,
    max_bytes: int = 5_000_000,
) -> OnlineQualitySummary:
    enabled = bool(getattr(settings, "ENABLE_METRICS_LOG", False)) and bool(getattr(settings, "ONLINE_EVAL_ENABLED", False))
    path_str = str(getattr(settings, "METRICS_LOG_PATH", "./logs/rag_metrics.jsonl") or "./logs/rag_metrics.jsonl")
    path = Path(path_str)

    window_minutes = max(1, int(window_minutes or 0))
    bucket_minutes = max(1, min(int(bucket_minutes or 0), 60))
    bucket_ms = bucket_minutes * 60 * 1000
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
        if str(r.get("event") or "") != "online_eval":
            continue
        records.append(r)

    earliest_ts_ms: int | None = None
    for r in records:
        try:
            ts_ms = int(r.get("ts_ms") or 0)
        except Exception:
            logging.getLogger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
            continue
        if not ts_ms:
            continue
        if earliest_ts_ms is None or ts_ms < earliest_ts_ms:
            earliest_ts_ms = ts_ms
    truncated = bool(truncated_by_tail and earliest_ts_ms is not None and earliest_ts_ms > cutoff_ms)

    faith_vals: list[float] = []
    util_vals: list[float] = []

    # Bucket -> accumulators
    buckets: dict[int, dict[str, Any]] = defaultdict(lambda: {"ts_ms": 0, "samples": 0, "faith_sum": 0.0, "faith_n": 0, "util_sum": 0.0, "util_n": 0})
    for r in records:
        try:
            ts_ms = int(r.get("ts_ms") or 0)
        except Exception:
            ts_ms = 0
        if not ts_ms:
            continue
        b = (ts_ms // bucket_ms) * bucket_ms
        bucket = buckets[int(b)]
        bucket["ts_ms"] = int(b)
        bucket["samples"] = int(bucket.get("samples") or 0) + 1

        fd = r.get("faithfulness_det")
        try:
            fd_f = float(fd) if fd is not None else None
        except Exception:
            fd_f = None
        if fd_f is not None and math.isfinite(fd_f):
            faith_vals.append(fd_f)
            bucket["faith_sum"] = float(bucket.get("faith_sum") or 0.0) + float(fd_f)
            bucket["faith_n"] = int(bucket.get("faith_n") or 0) + 1

        cu = r.get("chunk_utilization")
        try:
            cu_f = float(cu) if cu is not None else None
        except Exception:
            cu_f = None
        if cu_f is not None and math.isfinite(cu_f):
            util_vals.append(cu_f)
            bucket["util_sum"] = float(bucket.get("util_sum") or 0.0) + float(cu_f)
            bucket["util_n"] = int(bucket.get("util_n") or 0) + 1

    ts_keys = sorted(buckets.keys())
    ts_ms_series = [int(k) for k in ts_keys]
    samples_series = [int(buckets[k].get("samples") or 0) for k in ts_keys]
    faith_series: list[float | None] = []
    util_series: list[float | None] = []
    for k in ts_keys:
        b = buckets[k]
        fn = int(b.get("faith_n") or 0)
        un = int(b.get("util_n") or 0)
        faith_series.append((float(b.get("faith_sum") or 0.0) / fn) if fn else None)
        util_series.append((float(b.get("util_sum") or 0.0) / un) if un else None)

    # Alerts: simple threshold checks on the latest bucket with enough samples.
    alerts: list[dict[str, Any]] = []
    min_samples = int(getattr(settings, "ONLINE_EVAL_ALERT_MIN_SAMPLES_PER_BUCKET", 10) or 10)
    faith_min = float(getattr(settings, "ONLINE_EVAL_ALERT_FAITHFULNESS_DET_MIN", 0.6) or 0.6)
    util_min = float(getattr(settings, "ONLINE_EVAL_ALERT_CHUNK_UTILIZATION_MIN", 0.12) or 0.12)
    if ts_keys:
        last_k = ts_keys[-1]
        last = buckets[last_k]
        last_samples = int(last.get("samples") or 0)
        last_f = faith_series[-1] if faith_series else None
        last_u = util_series[-1] if util_series else None
        if last_samples >= min_samples:
            if last_f is not None and last_f < faith_min:
                alerts.append(
                    {
                        "kind": "quality_drop",
                        "metric": "faithfulness_det",
                        "value": round(float(last_f), 4),
                        "threshold": round(float(faith_min), 4),
                        "bucket_ts_ms": int(last_k),
                        "samples": int(last_samples),
                    }
                )
            if last_u is not None and last_u < util_min:
                alerts.append(
                    {
                        "kind": "quality_drop",
                        "metric": "chunk_utilization",
                        "value": round(float(last_u), 4),
                        "threshold": round(float(util_min), 4),
                        "bucket_ts_ms": int(last_k),
                        "samples": int(last_samples),
                    }
                )

    return OnlineQualitySummary(
        enabled=bool(enabled),
        path=str(path),
        window_minutes=int(window_minutes),
        bucket_minutes=int(bucket_minutes),
        truncated=bool(truncated),
        record_count=int(len(raw_records)),
        sample_count=int(len(records)),
        faithfulness_det_avg=_mean(faith_vals),
        chunk_utilization_avg=_mean(util_vals),
        timeseries={
            "ts_ms": ts_ms_series,
            "samples": samples_series,
            "faithfulness_det_avg": [None if v is None else round(float(v), 4) for v in faith_series],
            "chunk_utilization_avg": [None if v is None else round(float(v), 4) for v in util_series],
        },
        alerts=alerts,
    )


# ========================== Async sampling worker ==========================


_queue_max = max(10, int(getattr(settings, "ONLINE_EVAL_QUEUE_MAX", 500) or 500))
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
    answer = str(item.get("answer") or "")
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
    enabled = bool(getattr(settings, "ONLINE_EVAL_ENABLED", False)) and bool(getattr(settings, "ENABLE_METRICS_LOG", False))
    if not enabled:
        return {"enabled": False, "enqueued": False, "reason": "disabled"}

    rate = float(getattr(settings, "ONLINE_EVAL_SAMPLE_RATE", 0.05) or 0.05)
    if not _stable_sample(tenant_id=str(tenant_id) if tenant_id else None, request_id=str(request_id or ""), rate=rate):
        return {"enabled": True, "enqueued": False, "reason": "not_sampled", "sample_rate": rate}

    # Keep item small and PII-minimal (no questions). Context text is used only in-memory for evaluation.
    item = {
        "tenant_id": str(tenant_id) if tenant_id else None,
        "dataset_id": str(dataset_id) if dataset_id else None,
        "request_id": str(request_id or "")[:200] if request_id else None,
        "retrieval_mode": str(retrieval_mode or "").strip().lower() or None,
        "citations_count": int(citations_count) if citations_count is not None else None,
        "sample_rate": round(float(rate), 6),
        "answer": str(answer or ""),
        "contexts": [str(c or "") for c in (contexts or []) if str(c or "").strip()],
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
                "sample_rate": round(float(rate), 6),
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
