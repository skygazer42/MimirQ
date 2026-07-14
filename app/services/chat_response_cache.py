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
import hashlib
import json
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from app.core.config import settings
from app.core.redis_client import LazyRedisClient
from app.rag.core.logging import get_logger
from app.rag.embedding.utils import current_embedding_space_hash
from app.services.corpus_cache_tokens import resolve_corpus_cache_token

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
_inflight_response_lock: asyncio.Lock | None = None


def _get_inflight_response_lock() -> asyncio.Lock:
    global _inflight_response_lock
    if _inflight_response_lock is None:
        _inflight_response_lock = asyncio.Lock()
    return _inflight_response_lock


def _hash_doc_scope(document_ids: list[str]) -> str:
    joined = ",".join(sorted(str(d) for d in document_ids if d))
    return hashlib.sha256(joined.encode("utf-8", "ignore")).hexdigest()


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


def set_cached_chat_response(key: str, payload: dict[str, Any]) -> bool:
    """Store payload; returns True when stored."""
    if not bool(getattr(settings, "CHAT_RESPONSE_CACHE_ENABLED", False)):
        return False

    client = _get_redis_client()
    if client is None:
        return False

    ttl = int(getattr(settings, "CHAT_RESPONSE_CACHE_TTL_SEC", 300) or 0)
    max_bytes = int(getattr(settings, "CHAT_RESPONSE_CACHE_MAX_VALUE_BYTES", 200_000) or 0)

    try:
        raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
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
        logger.warning("Chat cache write failed: %s", str(exc)[:200])
        _invalidate_redis_client()
        return False


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
        _inflight_response_futures[key] = future
        return True, future


def _pop_inflight_chat_response_future(key: str) -> asyncio.Future[dict[str, Any]] | None:
    return _inflight_response_futures.pop(key, None)


def resolve_inflight_chat_response(key: str, payload: dict[str, Any]) -> None:
    future = _pop_inflight_chat_response_future(key)
    if future is None or future.done():
        return
    future.set_result(payload)


def reject_inflight_chat_response(key: str, exc: BaseException) -> None:
    future = _pop_inflight_chat_response_future(key)
    if future is None or future.done():
        return
    future.set_exception(exc)


def clear_inflight_chat_responses() -> None:
    """
    Test helper: drop all in-process singleflight state.
    """
    _inflight_response_futures.clear()
