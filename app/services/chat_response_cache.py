"""
Chat response cache (Redis, best-effort).

This cache stores full assistant responses for identical (safe) requests to reduce:
- repeated retrieval + rerank costs
- repeated LLM costs

Security posture:
- enabled by default for stateless scoped requests
- key includes tenant + account + doc-scope hash + config hash
- best-effort fail-open (cache errors never break chat)
"""


import asyncio
import contextlib
import hashlib
import json
from collections.abc import Sequence
from typing import Any
from uuid import UUID, uuid4

from app.core.config import settings
from app.core.redis_client import LazyRedisClient
from app.core.redis_lease import extend_redis_lease, release_redis_lease, try_acquire_redis_lease
from app.rag.core.logging import get_logger
from app.rag.embedding.utils import current_embedding_space_hash
from app.services.corpus_cache_tokens import resolve_corpus_cache_token
from app.services.rag_runtime_limiter import RetrievalAdmissionTimeoutError

logger = get_logger("chat.cache")

_redis_client_slot = LazyRedisClient(
    url=lambda: settings.REDIS_URL,
    kwargs={
        "socket_timeout": 1,
        "socket_connect_timeout": 1,
        "decode_responses": False,
    },
    on_error=lambda exc: logger.warning(
        "Chat cache disabled (redis init failed): %s",
        str(exc)[:200],
    ),
)
_get_redis_client = _redis_client_slot.get
_invalidate_redis_client = _redis_client_slot.invalidate
_inflight_response_futures: dict[str, asyncio.Future[dict[str, Any]]] = {}
_inflight_response_leases: dict[str, tuple[str, str, asyncio.Task[None], bool]] = {}
_inflight_response_cache_write_tasks: dict[str, asyncio.Task[bool]] = {}
_inflight_response_result_write_tasks: dict[str, asyncio.Task[bool]] = {}
_inflight_response_lock: asyncio.Lock | None = None
_CHAT_RESPONSE_SINGLEFLIGHT_LEASE_SUFFIX = ":lease"
_CHAT_RESPONSE_SINGLEFLIGHT_RESULT_SUFFIX = ":result"
_CHAT_RESPONSE_SINGLEFLIGHT_LEASE_POLL_INITIAL_SEC = 0.05
_CHAT_RESPONSE_SINGLEFLIGHT_LEASE_POLL_MAX_SEC = 0.25
_CHAT_RESPONSE_SINGLEFLIGHT_TRANSIENT_RESULT_TTL_SEC = 10


def _forget_completed_cache_write(key: str, task: asyncio.Task[bool]) -> None:
    if _inflight_response_cache_write_tasks.get(key) is task:
        _inflight_response_cache_write_tasks.pop(key, None)


def _forget_completed_result_write(key: str, task: asyncio.Task[bool]) -> None:
    if _inflight_response_result_write_tasks.get(key) is task:
        _inflight_response_result_write_tasks.pop(key, None)


class InflightResponseLeaderCancelledError(RuntimeError):
    """Signal followers to retry after the request leading their singleflight was cancelled."""


def _consume_unobserved_future_exception(future: asyncio.Future[dict[str, Any]]) -> None:
    if not future.cancelled():
        future.exception()


def _get_inflight_response_lock() -> asyncio.Lock:
    global _inflight_response_lock
    if _inflight_response_lock is None:
        _inflight_response_lock = asyncio.Lock()
    return _inflight_response_lock


def _chat_response_singleflight_wait_timeout_sec() -> float:
    return max(
        1e-3,
        float(getattr(settings, "CHAT_RESPONSE_SINGLEFLIGHT_WAIT_TIMEOUT_SEC", 60.0) or 0.0),
    )


def _chat_response_singleflight_result_key(key: str) -> str:
    return f"{key}{_CHAT_RESPONSE_SINGLEFLIGHT_RESULT_SUFFIX}"


def _chat_response_singleflight_should_publish_transient_result(
    *, cache_enabled: bool, response_cache_ttl_sec: int
) -> bool:
    return (not cache_enabled) or response_cache_ttl_sec <= 0


def _hash_doc_scope(document_ids: list[str]) -> str:
    joined = ",".join(sorted(str(d) for d in document_ids if d))
    return hashlib.sha256(joined.encode("utf-8", "ignore")).hexdigest()


async def get_best_effort_json_cache_value(key: str) -> Any | None:
    if not key:
        return None
    client = _get_redis_client()
    if client is None:
        return None
    try:
        raw = await asyncio.to_thread(client.get, key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis cache read failed: %s", str(exc)[:200])
        _invalidate_redis_client()
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:  # noqa: BLE001
        return None


async def set_best_effort_json_cache_value(
    key: str,
    payload: Any,
    *,
    ttl_sec: int,
    max_value_bytes: int = 0,
) -> bool:
    if not key:
        return False
    client = _get_redis_client()
    if client is None:
        return False
    try:
        raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    except Exception:  # noqa: BLE001
        return False
    if max_value_bytes > 0 and len(raw) > max_value_bytes:
        return False
    try:
        if ttl_sec > 0:
            await asyncio.to_thread(client.set, key, raw, ex=int(ttl_sec))
        else:
            await asyncio.to_thread(client.set, key, raw)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis cache write failed: %s", str(exc)[:200])
        _invalidate_redis_client()
        return False


async def try_acquire_best_effort_redis_lease(
    key: str,
    *,
    value: str,
    ttl_sec: int,
) -> bool | None:
    if not key or not value or ttl_sec <= 0:
        return False
    client = _get_redis_client()
    if client is None:
        return None
    try:
        return bool(await asyncio.to_thread(try_acquire_redis_lease, client, key, value=value, ttl_sec=ttl_sec))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis lease acquire failed: %s", str(exc)[:200])
        _invalidate_redis_client()
        return None


async def release_best_effort_redis_lease(key: str, *, value: str) -> None:
    if not key or not value:
        return
    client = _get_redis_client()
    if client is None:
        return
    try:
        await asyncio.to_thread(release_redis_lease, client, key, value=value)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis lease release failed: %s", str(exc)[:200])
        _invalidate_redis_client()


async def extend_best_effort_redis_lease(
    key: str,
    *,
    value: str,
    ttl_sec: int,
) -> bool | None:
    if not key or not value or ttl_sec <= 0:
        return False
    client = _get_redis_client()
    if client is None:
        return None
    try:
        return bool(
            await asyncio.to_thread(
                extend_redis_lease,
                client,
                key,
                value=value,
                ttl_sec=ttl_sec,
            )
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis lease extend failed: %s", str(exc)[:200])
        _invalidate_redis_client()
        return None


def build_chat_cache_key(
    *,
    tenant_id: str,
    account_id: str,
    dataset_id: str | None,
    document_ids: list[str],
    question: str,
    rag_config: dict[str, Any],
    prompt_config: dict[str, Any],
    structured_output: bool,
    structured_preset: str | None,
    use_graph: bool,
    corpus_cache_token: str | None = None,
) -> str:
    """
    Build a stable Redis key for a chat request.

    We hash the full request signature to keep keys short and to avoid leaking sensitive content
    in Redis key names.
    """
    prefix = str(getattr(settings, "CHAT_RESPONSE_CACHE_PREFIX", "chat") or "chat").strip() or "chat"

    signature = {
        "v": 1,
        "tenant_id": str(tenant_id),
        "account_id": str(account_id or ""),
        "dataset_id": str(dataset_id or "") or None,
        # Bind to the current embedding "space" (provider/model/base_url) so a model
        # change can't serve stale cached responses.
        "embedding_space_hash": str(current_embedding_space_hash() or "") or None,
        "corpus_cache_token": str(corpus_cache_token or "") or None,
        "doc_scope": _hash_doc_scope(document_ids),
        "doc_count": len([d for d in document_ids if d]),
        "question": (question or "").strip(),
        "rag": rag_config,
        "prompt": prompt_config,
        "structured_output": bool(structured_output),
        "structured_preset": str(structured_preset or "") or None,
        "use_graph": bool(use_graph),
    }

    raw = json.dumps(signature, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(raw.encode("utf-8", "ignore")).hexdigest()
    return f"{prefix}:{tenant_id}:{digest}"


def resolve_chat_response_cache_key(
    *,
    db: Any,
    tenant_id: UUID,
    account_id: str,
    dataset_id: UUID | None,
    document_ids: Sequence[UUID] | None,
    question: str,
    rag_config: dict[str, Any],
    prompt_config: dict[str, Any],
    structured_output: bool,
    structured_preset: str | None,
    use_graph: bool,
) -> tuple[str | None, str | None]:
    doc_ids = [doc_id for doc_id in (document_ids or []) if doc_id is not None]
    scope_dataset_id = dataset_id if dataset_id is not None else None
    if not doc_ids and scope_dataset_id is None:
        return None, "missing_scope"

    corpus_cache_token = resolve_corpus_cache_token(
        db,
        tenant_id=tenant_id,
        dataset_id=scope_dataset_id,
        document_ids=doc_ids,
    )
    if not corpus_cache_token:
        return None, "missing_corpus_cache_token"

    try:
        key = build_chat_cache_key(
            tenant_id=str(tenant_id),
            account_id=str(account_id or ""),
            dataset_id=str(scope_dataset_id) if scope_dataset_id is not None else None,
            document_ids=[str(doc_id) for doc_id in doc_ids],
            question=question,
            rag_config=rag_config,
            prompt_config=prompt_config,
            structured_output=bool(structured_output),
            structured_preset=structured_preset,
            use_graph=bool(use_graph),
            corpus_cache_token=corpus_cache_token,
        )
    except Exception:
        return None, "build_error"

    return key, None


def get_cached_chat_response(key: str) -> dict[str, Any] | None:
    """Return cached payload dict or None."""
    if not bool(getattr(settings, "CHAT_RESPONSE_CACHE_ENABLED", False)):
        return None

    client = _get_redis_client()
    if client is None:
        return None

    try:
        raw = client.get(key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Chat cache read failed: %s", str(exc)[:200])
        _invalidate_redis_client()
        return None

    if not raw:
        return None

    try:
        payload = json.loads(raw)
    except Exception:  # noqa: BLE001
        return None

    return payload if isinstance(payload, dict) else None


async def get_cached_chat_response_async(key: str) -> dict[str, Any] | None:
    if not bool(getattr(settings, "CHAT_RESPONSE_CACHE_ENABLED", False)):
        return None
    payload = await get_best_effort_json_cache_value(key)
    return payload if isinstance(payload, dict) else None


def set_cached_chat_response(key: str, payload: dict[str, Any]) -> bool:
    """Store payload; returns True when stored."""
    if not bool(getattr(settings, "CHAT_RESPONSE_CACHE_ENABLED", False)):
        return False

    ttl = int(getattr(settings, "CHAT_RESPONSE_CACHE_TTL_SEC", 300) or 0)
    max_bytes = int(getattr(settings, "CHAT_RESPONSE_CACHE_MAX_VALUE_BYTES", 200_000) or 0)
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return _set_cached_chat_response_sync(
            key,
            payload,
            ttl_sec=ttl,
            max_value_bytes=max_bytes,
        )
    task = asyncio.create_task(
        set_cached_chat_response_async(
            key,
            payload,
            ttl_sec=ttl,
            max_value_bytes=max_bytes,
        )
    )
    _inflight_response_cache_write_tasks[key] = task
    task.add_done_callback(lambda done, cache_key=key: _forget_completed_cache_write(cache_key, done))
    return True


def _set_cached_chat_response_sync(
    key: str,
    payload: dict[str, Any],
    *,
    ttl_sec: int,
    max_value_bytes: int,
) -> bool:
    if not key:
        return False
    client = _get_redis_client()
    if client is None:
        return False
    try:
        raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    except Exception:  # noqa: BLE001
        return False
    if max_value_bytes > 0 and len(raw) > max_value_bytes:
        return False
    try:
        if ttl_sec > 0:
            client.set(key, raw, ex=ttl_sec)
        else:
            client.set(key, raw)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Chat cache write failed: %s", str(exc)[:200])
        _invalidate_redis_client()
        return False


async def set_cached_chat_response_async(
    key: str,
    payload: dict[str, Any],
    *,
    ttl_sec: int | None = None,
    max_value_bytes: int | None = None,
) -> bool:
    if not bool(getattr(settings, "CHAT_RESPONSE_CACHE_ENABLED", False)):
        return False
    ttl = int(
        ttl_sec
        if ttl_sec is not None
        else (getattr(settings, "CHAT_RESPONSE_CACHE_TTL_SEC", 300) or 0)
    )
    max_bytes = int(
        max_value_bytes
        if max_value_bytes is not None
        else (getattr(settings, "CHAT_RESPONSE_CACHE_MAX_VALUE_BYTES", 200_000) or 0)
    )
    return await set_best_effort_json_cache_value(
        key,
        payload,
        ttl_sec=ttl,
        max_value_bytes=max_bytes,
    )


async def acquire_inflight_chat_response(key: str) -> tuple[bool, asyncio.Future[dict[str, Any]]]:
    """
    Claim a best-effort singleflight slot for a cacheable chat request.

    Returns:
    - (True, future) for the leader request, which must later resolve/reject the future.
    - (False, future) for follower requests, which should await the future and reuse the
      leader payload instead of starting another identical LLM call.
    """
    loop = asyncio.get_running_loop()
    async with _get_inflight_response_lock():
        current = _inflight_response_futures.get(key)
        if current is not None:
            return False, current
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        future.add_done_callback(_consume_unobserved_future_exception)
        _inflight_response_futures[key] = future
        return True, future


async def wait_for_inflight_chat_response(
    future: asyncio.Future[dict[str, Any]],
    *,
    timeout_sec: float,
) -> dict[str, Any]:
    done, _pending = await asyncio.wait(
        {future},
        timeout=max(1e-3, float(timeout_sec or 0.0)),
        return_when=asyncio.FIRST_COMPLETED,
    )
    if not done:
        raise RetrievalAdmissionTimeoutError(timeout_sec)
    return future.result()


def _chat_response_singleflight_lease_ttl_sec(response_cache_ttl_sec: int) -> int:
    admission_timeout_sec = max(
        15,
        int(getattr(settings, "RAG_RETRIEVAL_ADMISSION_TIMEOUT_SEC", 15.0) or 15.0),
    )
    response_ttl_sec = max(60, int(response_cache_ttl_sec or 0))
    return max(60, min(300, max(response_ttl_sec, admission_timeout_sec)))


async def _maintain_inflight_chat_response_lease(
    lease_key: str,
    *,
    owner: str,
    ttl_sec: int,
) -> None:
    renew_interval_sec = max(5.0, min(float(ttl_sec) / 3.0, 30.0))
    while True:
        await asyncio.sleep(renew_interval_sec)
        renewed = await extend_best_effort_redis_lease(
            lease_key,
            value=owner,
            ttl_sec=ttl_sec,
        )
        if renewed is False:
            return


async def acquire_or_wait_for_distributed_inflight_chat_response(
    key: str,
    *,
    cache_enabled: bool,
    response_cache_ttl_sec: int,
) -> tuple[bool, dict[str, Any] | None]:
    if not key:
        return True, None

    lease_key = f"{key}{_CHAT_RESPONSE_SINGLEFLIGHT_LEASE_SUFFIX}"
    result_key = _chat_response_singleflight_result_key(key)
    should_read_transient_result = _chat_response_singleflight_should_publish_transient_result(
        cache_enabled=cache_enabled,
        response_cache_ttl_sec=response_cache_ttl_sec,
    )
    owner = uuid4().hex
    lease_ttl_sec = _chat_response_singleflight_lease_ttl_sec(response_cache_ttl_sec)
    poll_delay = _CHAT_RESPONSE_SINGLEFLIGHT_LEASE_POLL_INITIAL_SEC
    loop = asyncio.get_running_loop()
    wait_timeout_sec = _chat_response_singleflight_wait_timeout_sec()
    deadline = loop.time() + wait_timeout_sec

    while True:
        cached = await get_cached_chat_response_async(key) if cache_enabled else None
        if isinstance(cached, dict):
            return False, cached
        if should_read_transient_result:
            transient = await get_best_effort_json_cache_value(result_key)
            if isinstance(transient, dict):
                return False, transient

        acquired = await try_acquire_best_effort_redis_lease(
            lease_key,
            value=owner,
            ttl_sec=lease_ttl_sec,
        )
        if acquired is None:
            return True, None
        if acquired:
            heartbeat = asyncio.create_task(
                _maintain_inflight_chat_response_lease(
                    lease_key,
                    owner=owner,
                    ttl_sec=lease_ttl_sec,
                )
            )
            _inflight_response_leases[key] = (
                lease_key,
                owner,
                heartbeat,
                should_read_transient_result,
            )
            return True, None

        if loop.time() >= deadline:
            logger.warning(
                "Chat distributed singleflight timed out waiting for lease payload: %s (timeout=%.2fs)",
                key,
                wait_timeout_sec,
            )
            raise RetrievalAdmissionTimeoutError(wait_timeout_sec)

        await asyncio.sleep(poll_delay)
        poll_delay = min(
            _CHAT_RESPONSE_SINGLEFLIGHT_LEASE_POLL_MAX_SEC,
            poll_delay * 1.5,
        )


def _pop_inflight_chat_response_future(key: str) -> asyncio.Future[dict[str, Any]] | None:
    return _inflight_response_futures.pop(key, None)


def _pop_inflight_chat_response_lease(
    key: str,
) -> tuple[str, str, asyncio.Task[None], bool] | None:
    return _inflight_response_leases.pop(key, None)


def _schedule_inflight_chat_response_lease_release(key: str) -> None:
    lease = _pop_inflight_chat_response_lease(key)
    if lease is None:
        return
    lease_key, owner, heartbeat, _publish_transient_result = lease
    cache_write = _inflight_response_cache_write_tasks.get(key)
    result_write = _inflight_response_result_write_tasks.get(key)

    async def _release_after_cache_write() -> None:
        if cache_write is not None:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await asyncio.shield(cache_write)
        if result_write is not None:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await asyncio.shield(result_write)
        heartbeat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat
        await release_best_effort_redis_lease(lease_key, value=owner)

    with contextlib.suppress(RuntimeError):
        asyncio.create_task(_release_after_cache_write())


def resolve_inflight_chat_response(key: str, payload: dict[str, Any]) -> None:
    lease = _inflight_response_leases.get(key)
    if lease is not None and lease[3]:
        task = asyncio.create_task(
            set_best_effort_json_cache_value(
                _chat_response_singleflight_result_key(key),
                payload,
                ttl_sec=_CHAT_RESPONSE_SINGLEFLIGHT_TRANSIENT_RESULT_TTL_SEC,
                max_value_bytes=int(
                    getattr(settings, "CHAT_RESPONSE_CACHE_MAX_VALUE_BYTES", 200_000) or 0
                ),
            )
        )
        _inflight_response_result_write_tasks[key] = task
        task.add_done_callback(lambda done, cache_key=key: _forget_completed_result_write(cache_key, done))
    _schedule_inflight_chat_response_lease_release(key)
    future = _pop_inflight_chat_response_future(key)
    if future is None or future.done():
        return
    future.set_result(payload)


def reject_inflight_chat_response(key: str, exc: BaseException) -> None:
    _schedule_inflight_chat_response_lease_release(key)
    future = _pop_inflight_chat_response_future(key)
    if future is None or future.done():
        return
    future.set_exception(exc)


def clear_inflight_chat_responses() -> None:
    """
    Test helper: drop all in-process singleflight state.
    """
    _inflight_response_futures.clear()
    for _lease_key, _owner, heartbeat, _publish_transient_result in _inflight_response_leases.values():
        heartbeat.cancel()
    _inflight_response_leases.clear()
    for task in _inflight_response_result_write_tasks.values():
        task.cancel()
    _inflight_response_result_write_tasks.clear()
    _inflight_response_cache_write_tasks.clear()
