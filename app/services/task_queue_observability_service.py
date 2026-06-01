"""
Task queue observability (best-effort, ops-facing).

Ops-T032: expose worker liveness + queue depth via:
- Prometheus gauges (scraped from API process)
- Observability admin API (PII-safe)

Design goals:
- Best-effort: never take down core flows if Redis/arq is unavailable (fail open).
- Broker-agnostic at the interface level: use arq/redis only when TASK_QUEUE_ENABLED=true.
- Low cardinality: do not emit per-worker label series in Prometheus.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from prometheus_client import Gauge

from app.core.config import settings
from app.core.optional_deps import optional_import

logger = logging.getLogger(__name__)

TASK_QUEUE_OBSERVABILITY_SCHEMA_V1 = "mimirq.task_queue_observability.v1"

# Prometheus gauges (updated by a background poller in the API process).
TASK_QUEUE_BROKER_UP = Gauge(
    "task_queue_broker_up",
    "Whether the task queue broker connection is healthy (best-effort)",
    ["queue"],
)
TASK_QUEUE_DEPTH = Gauge(
    "task_queue_depth",
    "Task queue depth (queued jobs, best-effort; includes scheduled/deferred)",
    ["queue"],
)
TASK_QUEUE_WORKERS_ACTIVE = Gauge(
    "task_queue_workers_active",
    "Active task workers by heartbeat (best-effort)",
    ["queue"],
)
TASK_QUEUE_OBSERVABILITY_LAST_REFRESH_TIMESTAMP = Gauge(
    "task_queue_observability_last_refresh_timestamp",
    "Unix timestamp of the last queue observability refresh (best-effort)",
    ["queue"],
)
TASK_QUEUE_OBSERVABILITY_LAST_REFRESH_DURATION_SECONDS = Gauge(
    "task_queue_observability_last_refresh_duration_seconds",
    "Duration of the last queue observability refresh in seconds (best-effort)",
    ["queue"],
)


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _queue_enabled() -> bool:
    return bool(getattr(settings, "TASK_QUEUE_ENABLED", False))


def _queue_name() -> str:
    name = str(getattr(settings, "TASK_QUEUE_NAME", "") or "").strip()
    return name or "mimirq"


def _heartbeat_interval_sec() -> float:
    try:
        return max(1.0, float(getattr(settings, "TASK_WORKER_HEARTBEAT_INTERVAL_SEC", 5.0) or 5.0))
    except Exception:
        return 5.0


def _heartbeat_ttl_sec() -> int:
    try:
        return max(5, int(getattr(settings, "TASK_WORKER_HEARTBEAT_TTL_SEC", 30) or 30))
    except Exception:
        return 30


def _poll_interval_sec() -> float:
    try:
        return max(2.0, float(getattr(settings, "TASK_QUEUE_OBSERVABILITY_POLL_INTERVAL_SEC", 10.0) or 10.0))
    except Exception:
        return 10.0


def _recent_job_outcomes_limit() -> int:
    try:
        return max(1, min(200, int(getattr(settings, "TASK_QUEUE_RECENT_JOB_OUTCOMES_LIMIT", 20) or 20)))
    except Exception:
        return 20


def _workers_registry_key(queue_name: str) -> str:
    q = str(queue_name or "").strip() or "mimirq"
    return f"ops:task_queue:workers:{q}"


def _recent_jobs_key(queue_name: str) -> str:
    q = str(queue_name or "").strip() or "mimirq"
    return f"ops:task_queue:recent_jobs:{q}"


def _sanitize_recent_job_outcome(outcome: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(outcome, dict):
        return None

    job_name = str(outcome.get("job_name") or "").strip()
    if not job_name:
        return None

    payload: dict[str, Any] = {
        "schema": str(outcome.get("schema") or "").strip() or "mimirq.task_job_result.v1",
        "job_name": job_name,
        "ok": bool(outcome.get("ok", False)),
        "reason": str(outcome.get("reason")).strip()[:200] if outcome.get("reason") is not None else None,
        "elapsed_sec": float(outcome.get("elapsed_sec") or 0.0),
        "finished_at": str(outcome.get("finished_at") or "").strip() or _now_utc().isoformat(),
    }
    progress = outcome.get("progress")
    if isinstance(progress, dict) and progress:
        payload["progress"] = dict(progress)
    for key in (
        "tenant_id",
        "dataset_id",
        "document_id",
        "run_id",
        "scan_run_id",
        "suite_id",
        "connector_id",
        "skipped",
    ):
        value = outcome.get(key)
        if value is not None:
            payload[key] = value
    return payload


async def observe_task_worker_heartbeat(*, redis: Any, queue_name: str, worker_id: str) -> None:
    """
    Best-effort worker heartbeat update.

    We use a Redis sorted set:
    - key: ops:task_queue:workers:{queue}
    - member: worker_id
    - score: unix timestamp

    The API poller prunes stale entries and exports an aggregate active count.
    """
    if redis is None:
        return

    q = str(queue_name or "").strip() or _queue_name()
    wid = str(worker_id or "").strip()
    if not wid:
        return

    now_ts = time.time()
    key = _workers_registry_key(q)
    ttl = _heartbeat_ttl_sec()
    # Keep the registry alive as long as workers keep heartbeating.
    expire_sec = max(60, int(ttl * 4))

    try:
        await redis.zadd(key, {wid: float(now_ts)})
        await redis.expire(key, int(expire_sec))
    except Exception:
        # Fail open (no logs here; avoid log spam from tight heartbeat loops).
        return


async def observe_task_job_outcome(*, redis: Any, queue_name: str, outcome: dict[str, Any]) -> None:
    """
    Best-effort recent job outcome registry for admin observability snapshots.
    """
    if redis is None:
        return

    payload = _sanitize_recent_job_outcome(outcome)
    if payload is None:
        return

    q = str(queue_name or "").strip() or _queue_name()
    key = _recent_jobs_key(q)
    ttl = max(300, int(_heartbeat_ttl_sec()) * 10)
    limit = _recent_job_outcomes_limit()

    try:
        await redis.lpush(key, json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str))
        await redis.ltrim(key, 0, int(limit) - 1)
        await redis.expire(key, int(ttl))
    except Exception:
        return


async def _get_arq_redis() -> Any | None:
    """
    Return arq Redis pool when task queue is enabled; otherwise None.

    Must be best-effort and tolerate missing optional dependencies.
    """
    if not _queue_enabled():
        return None

    # Ensure arq is importable when the feature is enabled; degrade gracefully for misconfigs.
    if optional_import("arq", feature="task_queue_observability") is None:
        return None

    try:
        from app.tasks.queue import get_queue  # local import: avoid side effects when unused

        return await get_queue()
    except Exception:
        return None


async def _refresh_from_redis(*, redis: Any, queue_name: str) -> tuple[bool, int | None, int | None, str | None]:
    """
    Return (broker_up, depth, workers_active, recent_job_outcomes, error).
    """
    if redis is None:
        return False, None, None, [], "redis_unavailable"

    q = str(queue_name or "").strip() or _queue_name()

    # Broker health check.
    try:
        pong = await redis.ping()
        broker_up = bool(pong)
    except Exception:
        return False, None, None, [], "redis_ping_failed"

    depth: int | None = None
    try:
        depth = int(await redis.zcard(q))
        if depth < 0:
            depth = 0
    except Exception:
        depth = None

    # Worker liveness: prune stale entries then count.
    workers_active: int | None = None
    try:
        ttl = _heartbeat_ttl_sec()
        now_ts = time.time()
        cutoff = now_ts - float(ttl)
        reg = _workers_registry_key(q)
        # Remove workers that have not heartbeated within TTL.
        await redis.zremrangebyscore(reg, "-inf", float(cutoff))
        workers_active = int(await redis.zcard(reg))
        if workers_active < 0:
            workers_active = 0
    except Exception:
        workers_active = None

    recent_job_outcomes: list[dict[str, Any]] = []
    try:
        raw_items = await redis.lrange(_recent_jobs_key(q), 0, int(_recent_job_outcomes_limit()) - 1)
        for raw in raw_items or []:
            text = raw.decode("utf-8", "ignore") if isinstance(raw, (bytes, bytearray)) else str(raw or "")
            text = text.strip()
            if not text:
                continue
            try:
                item = json.loads(text)
            except Exception:
                logging.getLogger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
                continue
            if isinstance(item, dict):
                recent_job_outcomes.append(item)
    except Exception:
        recent_job_outcomes = []

    return broker_up, depth, workers_active, recent_job_outcomes, None


@dataclass(frozen=True)
class TaskQueueObservabilitySnapshot:
    schema: str
    generated_at: datetime
    source: str

    enabled: bool
    queue_name: str

    broker_up: bool
    queue_depth: int | None = None
    workers_active: int | None = None

    heartbeat_interval_sec: float = 0.0
    heartbeat_ttl_sec: int = 0
    poll_interval_sec: float = 0.0
    recent_job_outcomes: list[dict[str, Any]] = field(default_factory=list)

    error: str | None = None


_snapshot_lock = asyncio.Lock()
_latest_snapshot: TaskQueueObservabilitySnapshot | None = None
_latest_snapshot_ts: float = 0.0

_poller_stop: asyncio.Event | None = None
_poller_task: asyncio.Task | None = None


async def refresh_task_queue_observability_snapshot(*, source: str) -> TaskQueueObservabilitySnapshot:
    """
    Refresh queue observability snapshot and update Prometheus gauges.

    This is safe to call frequently (best-effort, bounded work).
    """
    q = _queue_name()
    enabled = _queue_enabled()
    hb_int = _heartbeat_interval_sec()
    hb_ttl = _heartbeat_ttl_sec()
    poll_int = _poll_interval_sec()

    t0 = time.perf_counter()
    broker_up = False
    depth: int | None = None
    workers_active: int | None = None
    recent_job_outcomes: list[dict[str, Any]] = []
    err: str | None = None

    if enabled:
        redis = await _get_arq_redis()
        broker_up, depth, workers_active, recent_job_outcomes, err = await _refresh_from_redis(redis=redis, queue_name=q)
    else:
        broker_up, depth, workers_active, recent_job_outcomes, err = False, 0, 0, [], None

    snap = TaskQueueObservabilitySnapshot(
        schema=TASK_QUEUE_OBSERVABILITY_SCHEMA_V1,
        generated_at=_now_utc(),
        source=str(source or "unknown"),
        enabled=bool(enabled),
        queue_name=q,
        broker_up=bool(broker_up),
        queue_depth=depth,
        workers_active=workers_active,
        heartbeat_interval_sec=float(hb_int),
        heartbeat_ttl_sec=int(hb_ttl),
        poll_interval_sec=float(poll_int),
        recent_job_outcomes=list(recent_job_outcomes or []),
        error=err,
    )

    # Update gauges (only when prometheus is enabled).
    if bool(getattr(settings, "PROMETHEUS_ENABLED", False)):
        try:
            TASK_QUEUE_BROKER_UP.labels(queue=q).set(1.0 if broker_up else 0.0)
            TASK_QUEUE_DEPTH.labels(queue=q).set(float(depth if depth is not None else -1))
            TASK_QUEUE_WORKERS_ACTIVE.labels(queue=q).set(float(workers_active if workers_active is not None else -1))
            TASK_QUEUE_OBSERVABILITY_LAST_REFRESH_TIMESTAMP.labels(queue=q).set(float(time.time()))
            TASK_QUEUE_OBSERVABILITY_LAST_REFRESH_DURATION_SECONDS.labels(queue=q).set(
                max(0.0, float(time.perf_counter() - t0))
            )
        except Exception as exc:
            # Never fail the refresh due to metrics errors.
            logger.debug("Failed to update task queue observability gauges: %s", exc)

    async with _snapshot_lock:
        global _latest_snapshot, _latest_snapshot_ts
        _latest_snapshot = snap
        _latest_snapshot_ts = time.time()
    return snap


async def get_task_queue_observability_snapshot(*, force_refresh: bool = False) -> TaskQueueObservabilitySnapshot:
    """
    Return a recent snapshot; refresh on-demand when missing/stale.

    - When poller is running, this returns the latest cached snapshot.
    - When poller is not running, this refreshes on demand.
    """
    poll_int = _poll_interval_sec()
    max_age = max(5.0, float(poll_int) * 2.5)

    async with _snapshot_lock:
        snap = _latest_snapshot
        age = time.time() - float(_latest_snapshot_ts or 0.0)

    if (not force_refresh) and snap is not None and age <= max_age:
        return snap

    return await refresh_task_queue_observability_snapshot(source="on_demand")


async def _poller_loop(stop_event: asyncio.Event) -> None:
    """
    Background poller that refreshes gauges periodically.
    """
    interval = _poll_interval_sec()
    while not stop_event.is_set():
        try:
            await refresh_task_queue_observability_snapshot(source="poller")
        except Exception as exc:
            # Fail open and keep looping.
            logger.debug("Task queue observability poll iteration failed; continuing: %s", exc)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=float(interval))
        except asyncio.TimeoutError:
            continue


def start_task_queue_observability_poller() -> None:
    """
    Start the background poller (idempotent).

    Intended to be called from FastAPI lifespan when PROMETHEUS_ENABLED=true.
    """
    global _poller_stop, _poller_task
    if _poller_task is not None and not _poller_task.done():
        return

    _poller_stop = asyncio.Event()
    _poller_task = asyncio.create_task(_poller_loop(_poller_stop))


async def stop_task_queue_observability_poller() -> None:
    """Stop the background poller (best-effort)."""
    global _poller_stop, _poller_task
    if _poller_stop is not None:
        _poller_stop.set()
    if _poller_task is not None:
        try:
            await asyncio.wait_for(_poller_task, timeout=2.0)
        except Exception:
            _poller_task.cancel()
            with contextlib.suppress(Exception):
                await _poller_task
    _poller_stop = None
    _poller_task = None


__all__ = [
    "TASK_QUEUE_OBSERVABILITY_SCHEMA_V1",
    "TaskQueueObservabilitySnapshot",
    "observe_task_job_outcome",
    "observe_task_worker_heartbeat",
    "refresh_task_queue_observability_snapshot",
    "get_task_queue_observability_snapshot",
    "start_task_queue_observability_poller",
    "stop_task_queue_observability_poller",
]
