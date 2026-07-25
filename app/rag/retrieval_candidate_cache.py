"""
Retrieval candidate cache (Redis, short TTL, best-effort).

Goal:
- Reduce repeated vector/BM25/lexical work for identical retrieval requests
  over a short time window (e.g., chat retries, UI refreshes).

Security posture:
- Disabled by default
- Cache key binds to (tenant, account, scope, pipeline) and request signature
- Best-effort fail-open: cache errors never break retrieval
"""


import concurrent.futures
import copy
import hashlib
import json
import threading
import time
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from app.core.config import settings
from app.core.redis_client import LazyRedisClient
from app.core.redis_lease import release_redis_lease, try_acquire_redis_lease
from app.rag.core.hashing import stable_hash
from app.rag.core.logging import get_logger

logger = get_logger("rag.candidate_cache")

_redis_client_slot = LazyRedisClient(
    url=lambda: settings.REDIS_URL,
    kwargs={
        "socket_timeout": 1,
        "socket_connect_timeout": 1,
        "decode_responses": False,
    },
    on_error=lambda exc: logger.warning(
        "Retrieval candidate cache disabled (redis init failed): %s",
        str(exc)[:200],
    ),
)
_get_redis_client = _redis_client_slot.get
_invalidate_redis_client = _redis_client_slot.invalidate
_inflight_candidate_futures: dict[str, concurrent.futures.Future[list[dict[str, Any]]]] = {}
_inflight_candidate_lock = threading.Lock()
_inflight_candidate_leader_key: ContextVar[str | None] = ContextVar(
    "retrieval_candidate_leader_key",
    default=None,
)
_RETRIEVAL_CANDIDATE_SINGLEFLIGHT_LEASE_SUFFIX = ":lease"
_RETRIEVAL_CANDIDATE_SINGLEFLIGHT_LEASE_POLL_INITIAL_SEC = 0.05
_RETRIEVAL_CANDIDATE_SINGLEFLIGHT_LEASE_POLL_MAX_SEC = 0.25


@dataclass(frozen=True)
class _DistributedRetrievalLease:
    lease_key: str
    owner: str


_current_distributed_candidate_lease: ContextVar[_DistributedRetrievalLease | None] = ContextVar(
    "retrieval_candidate_distributed_lease",
    default=None,
)


def _hash_doc_scope(document_ids: list[str]) -> str:
    joined = ",".join(sorted(str(d) for d in document_ids if d))
    return hashlib.sha256(joined.encode("utf-8", "ignore")).hexdigest()


def build_retrieval_candidate_cache_key(
    *,
    tenant_id: str,
    account_id: str,
    dataset_id: str | None,
    pipeline_key: str | None,
    corpus_cache_token: str | None = None,
    behavior_hash: str | None = None,
    query: str,
    top_k: int,
    score_threshold: float,
    retrieval_mode: str,
    metadata_filter: dict[str, Any] | None,
    document_ids: list[str],
) -> str:
    """
    Build a short, stable Redis key for a retrieval request.

    Note: We hash the full signature to avoid leaking query text or other potentially
    sensitive information in Redis key names.
    """
    prefix = str(getattr(settings, "RETRIEVAL_CANDIDATE_CACHE_PREFIX", "rcand") or "rcand").strip() or "rcand"

    signature: dict[str, Any] = {
        "v": 1,
        "tenant_id": str(tenant_id),
        "account_id": str(account_id or ""),
        "dataset_id": str(dataset_id or "") or None,
        "pipeline_key": str(pipeline_key or "") or None,
        "corpus_cache_token": str(corpus_cache_token or "") or None,
        "behavior_hash": str(behavior_hash or "") or None,
        "doc_scope": _hash_doc_scope(document_ids),
        "doc_count": int(len([d for d in document_ids if d])),
        "query": (query or "").strip(),
        "top_k": int(top_k or 0),
        "score_threshold": float(score_threshold or 0.0),
        "retrieval_mode": str(retrieval_mode or "hybrid").strip().lower() or "hybrid",
        "metadata_filter": metadata_filter if isinstance(metadata_filter, dict) else None,
    }

    raw = json.dumps(signature, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    digest = stable_hash(raw, length=32)
    return f"{prefix}:{tenant_id}:{digest}"


def _current_inflight_retrieval_candidates_key() -> str | None:
    key = _inflight_candidate_leader_key.get()
    return str(key) if key else None


def _clear_current_inflight_retrieval_candidates_key(key: str | None = None) -> None:
    current = _current_inflight_retrieval_candidates_key()
    if current is None:
        return
    if key is not None and current != key:
        return
    _inflight_candidate_leader_key.set(None)


def _set_current_distributed_retrieval_lease(lease: _DistributedRetrievalLease | None) -> None:
    _current_distributed_candidate_lease.set(lease)


def _clear_current_distributed_retrieval_lease(lease: _DistributedRetrievalLease | None = None) -> None:
    current = _current_distributed_candidate_lease.get()
    if current is None:
        return
    if lease is not None and current != lease:
        return
    _current_distributed_candidate_lease.set(None)


def _pop_inflight_retrieval_candidates(key: str) -> concurrent.futures.Future[list[dict[str, Any]]] | None:
    with _inflight_candidate_lock:
        return _inflight_candidate_futures.pop(key, None)


def acquire_inflight_retrieval_candidates(key: str) -> tuple[bool, concurrent.futures.Future[list[dict[str, Any]]]]:
    with _inflight_candidate_lock:
        current = _inflight_candidate_futures.get(key)
        if current is not None:
            return False, current
        future: concurrent.futures.Future[list[dict[str, Any]]] = concurrent.futures.Future()
        _inflight_candidate_futures[key] = future
        _inflight_candidate_leader_key.set(key)
        return True, future


def resolve_inflight_retrieval_candidates(key: str, payload: list[dict[str, Any]]) -> None:
    future = _pop_inflight_retrieval_candidates(key)
    _clear_current_inflight_retrieval_candidates_key(key)
    if future is None or future.done():
        return
    future.set_result(payload)


def reject_inflight_retrieval_candidates(key: str, exc: BaseException) -> None:
    future = _pop_inflight_retrieval_candidates(key)
    _clear_current_inflight_retrieval_candidates_key(key)
    if future is None or future.done():
        return
    future.set_exception(exc)


def reject_current_inflight_retrieval_candidates(exc: BaseException) -> None:
    key = _current_inflight_retrieval_candidates_key()
    if not key:
        return
    reject_inflight_retrieval_candidates(key, exc)


def wait_for_inflight_retrieval_candidates(
    key: str,
    future: concurrent.futures.Future[list[dict[str, Any]]],
    *,
    timeout_sec: float,
) -> list[dict[str, Any]]:
    try:
        return copy.deepcopy(future.result(timeout=max(1.0, float(timeout_sec or 0.0))))
    except concurrent.futures.TimeoutError as exc:
        with _inflight_candidate_lock:
            if _inflight_candidate_futures.get(key) is future:
                _inflight_candidate_futures.pop(key, None)
        raise TimeoutError(f"retrieval candidate singleflight timed out for key={key}") from exc


def _retrieval_candidate_singleflight_lease_ttl_sec(cache_ttl_sec: int) -> int:
    admission_timeout_sec = max(
        15,
        int(getattr(settings, "RAG_RETRIEVAL_ADMISSION_TIMEOUT_SEC", 15.0) or 15.0),
    )
    response_ttl_sec = max(60, int(cache_ttl_sec or 0))
    return max(60, min(300, max(response_ttl_sec, admission_timeout_sec)))


def acquire_or_wait_for_distributed_inflight_retrieval_candidates(
    key: str,
) -> tuple[bool, list[dict[str, Any]] | None, _DistributedRetrievalLease | None]:
    if not key or not bool(getattr(settings, "RETRIEVAL_CANDIDATE_CACHE_ENABLED", False)):
        return True, None, None

    cache_ttl_sec = int(getattr(settings, "RETRIEVAL_CANDIDATE_CACHE_TTL_SEC", 0) or 0)
    if cache_ttl_sec <= 0:
        return True, None, None

    client = _get_redis_client()
    if client is None:
        return True, None, None

    lease_key = f"{key}{_RETRIEVAL_CANDIDATE_SINGLEFLIGHT_LEASE_SUFFIX}"
    owner = uuid4().hex
    lease_ttl_sec = _retrieval_candidate_singleflight_lease_ttl_sec(cache_ttl_sec)
    poll_delay = _RETRIEVAL_CANDIDATE_SINGLEFLIGHT_LEASE_POLL_INITIAL_SEC
    wait_timeout_sec = max(
        1.0,
        min(15.0, float(getattr(settings, "RAG_RETRIEVAL_ADMISSION_TIMEOUT_SEC", 15.0) or 15.0)),
    )
    deadline = time.monotonic() + wait_timeout_sec

    while True:
        cached = get_cached_retrieval_candidates(key)
        if isinstance(cached, list):
            return False, cached, None

        try:
            acquired = try_acquire_redis_lease(
                client,
                lease_key,
                value=owner,
                ttl_sec=lease_ttl_sec,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Retrieval candidate lease acquire failed: %s", str(exc)[:200])
            _invalidate_redis_client()
            return True, None, None

        if acquired:
            lease = _DistributedRetrievalLease(lease_key=lease_key, owner=owner)
            _set_current_distributed_retrieval_lease(lease)
            cached = get_cached_retrieval_candidates(key)
            if isinstance(cached, list):
                release_distributed_inflight_retrieval_candidates(lease)
                return False, cached, None
            return True, None, lease

        if time.monotonic() >= deadline:
            logger.warning(
                "Retrieval candidate distributed singleflight timed out waiting for lease payload: %s (timeout=%.2fs)",
                key,
                wait_timeout_sec,
            )
            return True, None, None

        time.sleep(poll_delay)
        poll_delay = min(
            _RETRIEVAL_CANDIDATE_SINGLEFLIGHT_LEASE_POLL_MAX_SEC,
            poll_delay * 1.5,
        )


def release_distributed_inflight_retrieval_candidates(lease: _DistributedRetrievalLease | None) -> None:
    if lease is None:
        return
    _clear_current_distributed_retrieval_lease(lease)
    client = _get_redis_client()
    if client is None:
        return
    try:
        release_redis_lease(
            client,
            lease.lease_key,
            value=lease.owner,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Retrieval candidate lease release failed: %s", str(exc)[:200])
        _invalidate_redis_client()


def release_current_distributed_inflight_retrieval_candidates() -> None:
    release_distributed_inflight_retrieval_candidates(_current_distributed_candidate_lease.get())


def get_cached_retrieval_candidates(key: str) -> list[dict[str, Any]] | None:
    if not bool(getattr(settings, "RETRIEVAL_CANDIDATE_CACHE_ENABLED", False)):
        return None

    client = _get_redis_client()
    if client is None:
        return None

    try:
        raw = client.get(key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Retrieval candidate cache read failed: %s", str(exc)[:200])
        _invalidate_redis_client()
        return None

    if not raw:
        return None

    try:
        payload = json.loads(raw)
    except Exception:  # noqa: BLE001
        return None

    if not isinstance(payload, list):
        return None
    out: list[dict[str, Any]] = []
    for item in payload:
        if isinstance(item, dict):
            out.append(item)
    return out


def set_cached_retrieval_candidates(key: str, payload: list[dict[str, Any]]) -> bool:
    if not bool(getattr(settings, "RETRIEVAL_CANDIDATE_CACHE_ENABLED", False)):
        return False

    client = _get_redis_client()
    if client is None:
        return False

    ttl = int(getattr(settings, "RETRIEVAL_CANDIDATE_CACHE_TTL_SEC", 30) or 0)
    max_bytes = int(getattr(settings, "RETRIEVAL_CANDIDATE_CACHE_MAX_VALUE_BYTES", 400_000) or 0)

    try:
        raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")
    except Exception:  # noqa: BLE001
        return False

    if max_bytes > 0 and len(raw) > max_bytes:
        return False

    try:
        if ttl > 0:
            client.set(key, raw, ex=ttl)
        else:
            client.set(key, raw)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Retrieval candidate cache write failed: %s", str(exc)[:200])
        _invalidate_redis_client()
        return False


def clear_inflight_retrieval_candidates() -> None:
    with _inflight_candidate_lock:
        futures = list(_inflight_candidate_futures.values())
        _inflight_candidate_futures.clear()

    for future in futures:
        if not future.done():
            future.cancel()
    _clear_current_inflight_retrieval_candidates_key()
    _clear_current_distributed_retrieval_lease()


__all__ = [
    "acquire_or_wait_for_distributed_inflight_retrieval_candidates",
    "acquire_inflight_retrieval_candidates",
    "build_retrieval_candidate_cache_key",
    "clear_inflight_retrieval_candidates",
    "get_cached_retrieval_candidates",
    "reject_current_inflight_retrieval_candidates",
    "reject_inflight_retrieval_candidates",
    "release_current_distributed_inflight_retrieval_candidates",
    "release_distributed_inflight_retrieval_candidates",
    "resolve_inflight_retrieval_candidates",
    "set_cached_retrieval_candidates",
    "wait_for_inflight_retrieval_candidates",
]
