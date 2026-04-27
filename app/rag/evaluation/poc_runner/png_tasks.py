from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

_TASKS: dict[str, dict[str, Any]] = {}
_RESULTS: dict[str, bytes] = {}


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


def create_png_export_task(*, dataset_id: str, filters: dict[str, Any]) -> dict[str, Any]:
    task_id = uuid4().hex
    payload = {
        "task_id": task_id,
        "dataset_id": str(dataset_id or ""),
        "filters": dict(filters or {}),
        "status": "pending",
        "created_at": _iso_now(),
        "updated_at": _iso_now(),
    }
    _TASKS[task_id] = payload
    return dict(payload)


def complete_png_export_task(task_id: str, png_bytes: bytes) -> dict[str, Any]:
    task = _TASKS[str(task_id)]
    _RESULTS[str(task_id)] = bytes(png_bytes or b"")
    task["status"] = "done"
    task["updated_at"] = _iso_now()
    return dict(task)


def fail_png_export_task(task_id: str, error: str) -> dict[str, Any]:
    task = _TASKS[str(task_id)]
    task["status"] = "failed"
    task["error"] = str(error or "")[:500]
    task["updated_at"] = _iso_now()
    return dict(task)


def get_png_export_task(task_id: str) -> dict[str, Any]:
    return dict(_TASKS[str(task_id)])


def get_png_export_task_result(task_id: str) -> bytes:
    return bytes(_RESULTS[str(task_id)])
