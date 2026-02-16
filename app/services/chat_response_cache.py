"""
Chat response cache (Redis, best-effort).

This cache stores full assistant responses for identical (safe) requests to reduce:
- repeated retrieval + rerank costs
- repeated LLM costs

Security posture:
- disabled by default
- key includes tenant + account + doc-scope hash + config hash
- best-effort fail-open (cache errors never break chat)
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

from app.core.config import settings
from app.rag.core.logging import get_logger
from app.rag.embedding.utils import current_embedding_space_hash

logger = get_logger("chat.cache")

_redis_client: Any | None = None


def _get_redis_client():  # noqa: ANN202
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        import redis  # type: ignore

        _redis_client = redis.Redis.from_url(
            settings.REDIS_URL,
            socket_timeout=1,
            socket_connect_timeout=1,
            decode_responses=False,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Chat cache disabled (redis init failed): %s", str(exc)[:200])
        _redis_client = None
    return _redis_client


def _invalidate_redis_client() -> None:
    global _redis_client
    _redis_client = None


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


def get_cached_chat_response(key: str) -> Optional[dict[str, Any]]:
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
