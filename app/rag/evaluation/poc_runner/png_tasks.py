
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from app.core.config import settings
from app.core.redis_client import LazyRedisClient
from app.rag.core.logging import get_logger

logger = get_logger(__name__)

_COMPARE_SWAP_LUA = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
  redis.call("SET", KEYS[1], ARGV[2], "EX", ARGV[3])
  return 1
end
return 0
"""

_redis_client_slot = LazyRedisClient(
    url=lambda: settings.REDIS_URL,
    kwargs={
        "socket_timeout": 1,
        "socket_connect_timeout": 1,
        "decode_responses": False,
    },
    on_error=lambda exc: logger.warning(
        "Dataset-analysis PNG shared state unavailable: %s",
        str(exc)[:200],
    ),
)
_get_redis_client = _redis_client_slot.get
_invalidate_redis_client = _redis_client_slot.invalidate


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso_now() -> str:
    return _utc_now().isoformat()


def _get_client() -> Any:
    client = _get_redis_client()
    if client is None:
        raise RuntimeError("Redis client unavailable for dataset-analysis PNG task state")
    return client


def _prefix() -> str:
    return str(getattr(settings, "DATASET_ANALYSIS_PNG_REDIS_PREFIX", "dataset-analysis-png") or "dataset-analysis-png")


def _active_ttl_sec() -> int:
    stale_after = max(1, int(getattr(settings, "DATASET_ANALYSIS_PNG_STALE_AFTER_SEC", 60) or 60))
    return max(300, stale_after * 4)


def _terminal_ttl_sec() -> int:
    return max(1, int(getattr(settings, "DATASET_ANALYSIS_PNG_TERMINAL_TTL_SEC", 600) or 600))


def _stale_after_sec() -> int:
    return max(1, int(getattr(settings, "DATASET_ANALYSIS_PNG_STALE_AFTER_SEC", 60) or 60))


def _result_max_bytes() -> int:
    return max(1, int(getattr(settings, "DATASET_ANALYSIS_PNG_RESULT_MAX_BYTES", 5_000_000) or 5_000_000))


def get_png_export_task_heartbeat_interval_sec() -> float:
    stale_after = float(_stale_after_sec())
    return min(10.0, max(0.25, stale_after / 4.0))


def _task_key(task_id: str) -> str:
    return f"{_prefix()}:task:{str(task_id or '').strip()}"


def _result_key(task_id: str) -> str:
    return f"{_prefix()}:result:{str(task_id or '').strip()}"


def _serialize_task(task: dict[str, Any]) -> bytes:
    return json.dumps(task, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _deserialize_task(raw: bytes | str | None) -> dict[str, Any]:
    if raw is None:
        raise KeyError("PNG export task not found")
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return dict(json.loads(raw))


def _public_task(task: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in task.items()
        if key
        not in {
            "owner_token",
            "lease_expires_at",
        }
    }


def _read_task(client: Any, task_id: str) -> tuple[bytes, dict[str, Any]]:
    try:
        raw = client.get(_task_key(task_id))
    except Exception as exc:  # noqa: BLE001
        _invalidate_redis_client()
        raise RuntimeError("Failed to read dataset-analysis PNG task state") from exc
    if raw is None:
        raise KeyError(task_id)
    current_raw = raw if isinstance(raw, bytes) else str(raw).encode("utf-8")
    return current_raw, _deserialize_task(raw)


def _delete_result_best_effort(client: Any, task_id: str) -> None:
    try:
        client.delete(_result_key(task_id))
    except Exception:  # noqa: BLE001
        _invalidate_redis_client()


def _cas_task(client: Any, task_id: str, current_raw: bytes, next_task: dict[str, Any], *, ttl_sec: int) -> bool:
    try:
        return bool(
            client.eval(
                _COMPARE_SWAP_LUA,
                1,
                _task_key(task_id),
                current_raw,
                _serialize_task(next_task),
                max(1, int(ttl_sec)),
            )
        )
    except Exception as exc:  # noqa: BLE001
        _invalidate_redis_client()
        raise RuntimeError("Failed to update dataset-analysis PNG task state") from exc


def _scope_matches(task: dict[str, Any], *, tenant_id: str, dataset_id: str) -> bool:
    return (
        str(task.get("tenant_id") or "") == str(tenant_id or "")
        and str(task.get("dataset_id") or "") == str(dataset_id or "")
    )


def _parse_iso_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except Exception:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _is_stale(task: dict[str, Any]) -> bool:
    status = str(task.get("status") or "")
    now = _utc_now()
    if status == "pending":
        updated_at = _parse_iso_datetime(task.get("updated_at")) or _parse_iso_datetime(task.get("created_at"))
        return updated_at is not None and updated_at + timedelta(seconds=_stale_after_sec()) <= now
    if status == "running":
        lease_expires_at = _parse_iso_datetime(task.get("lease_expires_at"))
        return lease_expires_at is not None and lease_expires_at <= now
    return False


def _transition_to_worker_lost(client: Any, task_id: str, *, tenant_id: str, dataset_id: str) -> dict[str, Any]:
    for _attempt in range(4):
        current_raw, current = _read_task(client, task_id)
        if not _scope_matches(current, tenant_id=tenant_id, dataset_id=dataset_id):
            raise KeyError(task_id)
        if str(current.get("status") or "") not in {"pending", "running"} or not _is_stale(current):
            return _public_task(current)

        failed = dict(current)
        failed["status"] = "failed"
        failed["error_code"] = "worker_lost"
        failed["error"] = "PNG export worker lost"
        failed["updated_at"] = _iso_now()
        failed["completed_at"] = failed["updated_at"]
        failed.pop("owner_token", None)
        failed.pop("lease_expires_at", None)
        if _cas_task(client, task_id, current_raw, failed, ttl_sec=_terminal_ttl_sec()):
            _delete_result_best_effort(client, task_id)
            return _public_task(failed)
    return _public_task(_read_task(client, task_id)[1])


def create_png_export_task(*, tenant_id: str, dataset_id: str, filters: dict[str, Any]) -> dict[str, Any]:
    client = _get_client()
    task_id = uuid4().hex
    payload = {
        "task_id": task_id,
        "tenant_id": str(tenant_id or ""),
        "dataset_id": str(dataset_id or ""),
        "filters": dict(filters or {}),
        "status": "pending",
        "created_at": _iso_now(),
        "updated_at": _iso_now(),
    }
    try:
        client.set(_task_key(task_id), _serialize_task(payload), ex=_active_ttl_sec(), nx=True)
    except Exception as exc:  # noqa: BLE001
        _invalidate_redis_client()
        raise RuntimeError("Failed to create dataset-analysis PNG task state") from exc
    return _public_task(payload)


def begin_png_export_task(task_id: str, *, tenant_id: str, dataset_id: str) -> dict[str, Any]:
    client = _get_client()
    for _attempt in range(4):
        current_raw, current = _read_task(client, task_id)
        if not _scope_matches(current, tenant_id=tenant_id, dataset_id=dataset_id):
            raise KeyError(task_id)
        if str(current.get("status") or "") != "pending":
            return dict(current)

        started = dict(current)
        started["status"] = "running"
        started["started_at"] = _iso_now()
        started["updated_at"] = started["started_at"]
        started["owner_token"] = uuid4().hex
        started["lease_expires_at"] = (_utc_now() + timedelta(seconds=_stale_after_sec())).isoformat()
        if _cas_task(client, task_id, current_raw, started, ttl_sec=_active_ttl_sec()):
            return dict(started)
    raise RuntimeError("Failed to begin dataset-analysis PNG task")


def heartbeat_png_export_task(
    task_id: str,
    *,
    tenant_id: str,
    dataset_id: str,
    owner_token: str,
) -> bool:
    client = _get_client()
    for _attempt in range(4):
        current_raw, current = _read_task(client, task_id)
        if not _scope_matches(current, tenant_id=tenant_id, dataset_id=dataset_id):
            raise KeyError(task_id)
        if str(current.get("status") or "") != "running":
            return False
        if str(current.get("owner_token") or "") != str(owner_token or ""):
            return False

        renewed = dict(current)
        renewed["updated_at"] = _iso_now()
        renewed["lease_expires_at"] = (_utc_now() + timedelta(seconds=_stale_after_sec())).isoformat()
        if _cas_task(client, task_id, current_raw, renewed, ttl_sec=_active_ttl_sec()):
            return True
    raise RuntimeError("Failed to heartbeat dataset-analysis PNG task")


def complete_png_export_task(
    task_id: str,
    *,
    tenant_id: str,
    dataset_id: str,
    owner_token: str,
    png_bytes: bytes,
) -> dict[str, Any]:
    client = _get_client()
    if len(bytes(png_bytes or b"")) > _result_max_bytes():
        return fail_png_export_task(
            task_id,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            owner_token=owner_token,
            error="Rendered PNG exceeds the configured size limit",
            error_code="result_too_large",
        )

    for _attempt in range(4):
        current_raw, current = _read_task(client, task_id)
        if not _scope_matches(current, tenant_id=tenant_id, dataset_id=dataset_id):
            raise KeyError(task_id)
        if str(current.get("status") or "") != "running" or str(current.get("owner_token") or "") != str(owner_token or ""):
            return _public_task(current)

        try:
            client.set(_result_key(task_id), bytes(png_bytes or b""), ex=_terminal_ttl_sec())
        except Exception as exc:  # noqa: BLE001
            _invalidate_redis_client()
            raise RuntimeError("Failed to store dataset-analysis PNG task result") from exc

        done = dict(current)
        done["status"] = "done"
        done["updated_at"] = _iso_now()
        done["completed_at"] = done["updated_at"]
        done["result_size_bytes"] = len(bytes(png_bytes or b""))
        done.pop("owner_token", None)
        done.pop("lease_expires_at", None)
        if _cas_task(client, task_id, current_raw, done, ttl_sec=_terminal_ttl_sec()):
            return _public_task(done)
        _delete_result_best_effort(client, task_id)
    raise RuntimeError("Failed to complete dataset-analysis PNG task")


def fail_png_export_task(
    task_id: str,
    *,
    tenant_id: str,
    dataset_id: str,
    owner_token: str | None,
    error: str,
    error_code: str = "render_failed",
) -> dict[str, Any]:
    client = _get_client()
    for _attempt in range(4):
        current_raw, current = _read_task(client, task_id)
        if not _scope_matches(current, tenant_id=tenant_id, dataset_id=dataset_id):
            raise KeyError(task_id)

        current_status = str(current.get("status") or "")
        if current_status not in {"pending", "running"}:
            return _public_task(current)
        if owner_token is not None and str(current.get("owner_token") or "") != str(owner_token or ""):
            return _public_task(current)

        failed = dict(current)
        failed["status"] = "failed"
        failed["error_code"] = str(error_code or "render_failed")[:100]
        failed["error"] = str(error or "")[:500]
        failed["updated_at"] = _iso_now()
        failed["completed_at"] = failed["updated_at"]
        failed.pop("owner_token", None)
        failed.pop("lease_expires_at", None)
        if _cas_task(client, task_id, current_raw, failed, ttl_sec=_terminal_ttl_sec()):
            _delete_result_best_effort(client, task_id)
            return _public_task(failed)
    raise RuntimeError("Failed to fail dataset-analysis PNG task")


def get_png_export_task(task_id: str, *, tenant_id: str, dataset_id: str) -> dict[str, Any]:
    client = _get_client()
    current = _read_task(client, task_id)[1]
    if not _scope_matches(current, tenant_id=tenant_id, dataset_id=dataset_id):
        raise KeyError(task_id)
    if str(current.get("status") or "") in {"pending", "running"} and _is_stale(current):
        return _transition_to_worker_lost(client, task_id, tenant_id=tenant_id, dataset_id=dataset_id)
    return _public_task(current)


def get_png_export_task_result(task_id: str, *, tenant_id: str, dataset_id: str) -> bytes:
    task = get_png_export_task(task_id, tenant_id=tenant_id, dataset_id=dataset_id)
    if str(task.get("status") or "") != "done":
        raise KeyError(task_id)
    client = _get_client()
    try:
        raw = client.get(_result_key(task_id))
    except Exception as exc:  # noqa: BLE001
        _invalidate_redis_client()
        raise RuntimeError("Failed to read dataset-analysis PNG task result") from exc
    if raw is None:
        raise KeyError(task_id)
    return bytes(raw)
