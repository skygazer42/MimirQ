"""Shared Dify warmup status for readiness probes and warmup execution."""

import threading
from datetime import UTC, datetime
from typing import Any

from app.core.config import settings

_lock = threading.Lock()
_state: dict[str, Any] = {
    "enabled": False,
    "status": "idle",
    "attempted": 0,
    "completed": 0,
    "failed": 0,
    "elapsed_ms": None,
    "updated_at": None,
}


def set_dify_external_warmup_status(**updates: Any) -> None:
    with _lock:
        _state.update(updates)
        _state["updated_at"] = datetime.now(UTC).isoformat()


def get_dify_external_knowledge_warmup_status() -> dict[str, Any]:
    with _lock:
        return dict(_state)


def dify_external_knowledge_warmup_ready() -> bool:
    if not settings.DIFY_EXTERNAL_KNOWLEDGE_ENABLED or not settings.DIFY_EXTERNAL_KNOWLEDGE_WARMUP_ENABLED:
        return True
    return get_dify_external_knowledge_warmup_status()["status"] == "completed"
