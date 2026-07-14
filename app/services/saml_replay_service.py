
import threading
import time

from fastapi import HTTPException

from app.core.config import settings
from app.core.redis_client import LazyRedisClient

_redis_client_slot = LazyRedisClient(
    url=lambda: settings.REDIS_URL,
    kwargs={"decode_responses": False},
    enabled=lambda: bool(getattr(settings, "SAML_REPLAY_REDIS_ENABLED", False)),
    skip_empty_url=True,
    strip_url=True,
)
_get_redis_client = _redis_client_slot.get
_invalidate_redis_client = _redis_client_slot.invalidate
_memory_lock = threading.Lock()
_memory_seen_until: dict[str, float] = {}


def _claim_in_memory(key: str, ttl_sec: int) -> None:
    now = time.monotonic()
    cutoff = now
    with _memory_lock:
        expired = [seen_key for seen_key, seen_until in _memory_seen_until.items() if seen_until <= cutoff]
        for seen_key in expired:
            _memory_seen_until.pop(seen_key, None)

        seen_until = _memory_seen_until.get(key)
        if seen_until is not None and seen_until > now:
            raise HTTPException(status_code=409, detail="SAML assertion replayed")

        _memory_seen_until[key] = now + float(ttl_sec)


def ensure_saml_assertion_not_replayed(assertion_id: str) -> None:
    aid = str(assertion_id or "").strip()
    if not aid:
        return

    ttl_sec = max(1, int(getattr(settings, "SAML_REPLAY_TTL_SEC", 300) or 300))
    key = f"saml:assertion:{aid}"

    client = _get_redis_client()
    if client is not None:
        try:
            acquired = client.set(key, b"1", ex=ttl_sec, nx=True)
            if acquired:
                return
            raise HTTPException(status_code=409, detail="SAML assertion replayed")
        except HTTPException:
            raise
        except Exception:  # noqa: BLE001
            _invalidate_redis_client()

    _claim_in_memory(key, ttl_sec)


__all__ = ["ensure_saml_assertion_not_replayed"]
