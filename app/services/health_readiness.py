"""Cache readiness probe results and invalidate them after runtime configuration updates."""

import time
from typing import Any, TypedDict

from app.core.config import settings


class ReadyCache(TypedDict):
    ts: float
    payload: dict[str, Any] | None
    status: int
    key: tuple[object, ...] | None


_READY_CACHE_TTL_SEC = max(0.0, settings.READY_CACHE_TTL_SEC)
_ready_cache: ReadyCache = {"ts": 0.0, "payload": None, "status": 200, "key": None}


def invalidate_ready_cache() -> None:
    _ready_cache.update({"ts": 0.0, "payload": None, "status": 200, "key": None})


def get_ready_cache(cache_key: tuple[object, ...]) -> tuple[dict[str, Any], int] | None:
    snapshot = _ready_cache.copy()
    payload = snapshot["payload"]
    if (
        payload is not None
        and snapshot["key"] == cache_key
        and time.monotonic() - snapshot["ts"] < _READY_CACHE_TTL_SEC
    ):
        return payload, snapshot["status"]
    return None


def store_ready_cache(payload: dict[str, Any], status: int, key: tuple[object, ...]) -> None:
    _ready_cache.update({"ts": time.monotonic(), "payload": payload, "status": status, "key": key})
