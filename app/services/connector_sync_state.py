from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence, TypeVar
from uuid import UUID

from app.services.connector_registry import CONNECTOR_REGISTRY

T = TypeVar("T")
_STATE_SCHEMA_VERSION = 1
_STATE_AUDIT_HISTORY_LIMIT = 10


@dataclass(frozen=True)
class ConnectorSyncPolicy:
    connector_id: str
    state_keys: tuple[str, ...] = ()


CONNECTOR_SYNC_POLICIES: dict[str, ConnectorSyncPolicy] = {
    connector_id: ConnectorSyncPolicy(connector_id=connector_id, state_keys=definition.state_keys)
    for connector_id, definition in CONNECTOR_REGISTRY.items()
}


def _isoformat_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _normalize_recorded_at(value: datetime | str | None) -> str:
    if isinstance(value, datetime):
        return _isoformat_utc(value)
    text = str(value or "").strip()
    if text:
        return text
    return _isoformat_utc(datetime.now(timezone.utc))


def normalize_source_manifest(value: Mapping[str, Any] | None) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}

    items: list[tuple[str, str]] = []
    for raw_path, raw_sha in value.items():
        path = str(raw_path or "").strip()
        sha = str(raw_sha or "").strip()
        if not path or not sha:
            continue
        items.append((path, sha))

    items.sort(key=lambda item: item[0])
    return {path: sha for path, sha in items}


def get_resume_cursor(state: Mapping[str, Any] | None) -> int:
    if not isinstance(state, Mapping):
        return 0
    raw = state.get("cursor")
    try:
        cursor = int(raw or 0)
    except Exception:
        return 0
    return cursor if cursor >= 0 else 0


def slice_items_from_cursor(items: Sequence[T], *, cursor: int) -> tuple[list[T], int]:
    items_list = list(items or [])
    cursor_in = max(0, min(int(cursor or 0), len(items_list)))
    return items_list[cursor_in:], cursor_in


def build_persisted_state(
    *,
    connector_id: str,
    existing_state: Mapping[str, Any] | None,
    stats: Mapping[str, Any] | None,
    run_id: UUID | str,
) -> dict[str, Any]:
    policy = CONNECTOR_SYNC_POLICIES.get(str(connector_id or "").strip())
    state = dict(existing_state or {})
    if policy is None:
        return state

    stats_map = stats if isinstance(stats, Mapping) else {}
    for key in policy.state_keys:
        if key == "cursor":
            state["cursor"] = get_resume_cursor(stats_map)
            continue
        if key == "source_manifest":
            manifest = normalize_source_manifest(stats_map.get("source_manifest"))
            if manifest:
                state["source_manifest"] = manifest
            continue
        value = stats_map.get(key)
        if value is None:
            continue
        if key == "last_modified":
            value = str(value or "").strip()
            if not value:
                continue
        state[key] = value

    state["last_run_id"] = str(run_id)
    return state


def build_saved_state_snapshot(
    *,
    connector_id: str,
    existing_state: Mapping[str, Any] | None,
    stats: Mapping[str, Any] | None,
    run_id: UUID | str,
    run_status: str | None = None,
    recorded_at: datetime | str | None = None,
    history_limit: int = _STATE_AUDIT_HISTORY_LIMIT,
) -> dict[str, Any]:
    previous_state = dict(existing_state or {})
    state = build_persisted_state(
        connector_id=connector_id,
        existing_state=previous_state,
        stats=stats,
        run_id=run_id,
    )

    updated_keys = sorted(
        key
        for key, value in state.items()
        if not str(key).startswith("state_") and previous_state.get(key) != value
    )

    try:
        revision0 = int(previous_state.get("state_revision") or 0)
    except Exception:
        revision0 = 0
    revision = max(0, revision0) + 1

    recorded_at_norm = _normalize_recorded_at(recorded_at)
    history_entry = {
        "revision": int(revision),
        "run_id": str(run_id),
        "status": str(run_status or "").strip().lower() or None,
        "recorded_at": recorded_at_norm,
        "updated_keys": list(updated_keys),
    }

    prev_audit = previous_state.get("state_audit") if isinstance(previous_state.get("state_audit"), Mapping) else {}
    prev_history = prev_audit.get("history") if isinstance(prev_audit, Mapping) else None
    history = [dict(item) for item in prev_history] if isinstance(prev_history, list) else []
    limit = max(1, int(history_limit or _STATE_AUDIT_HISTORY_LIMIT))
    history = (history + [history_entry])[-limit:]

    state["state_schema_version"] = int(_STATE_SCHEMA_VERSION)
    state["state_revision"] = int(revision)
    state["state_recorded_at"] = recorded_at_norm
    state["state_audit"] = {
        "last_status": str(run_status or "").strip().lower() or None,
        "last_run_id": str(run_id),
        "last_recorded_at": recorded_at_norm,
        "updated_keys": list(updated_keys),
        "history": history,
    }
    return state


__all__ = [
    "CONNECTOR_SYNC_POLICIES",
    "ConnectorSyncPolicy",
    "build_persisted_state",
    "build_saved_state_snapshot",
    "get_resume_cursor",
    "normalize_source_manifest",
    "slice_items_from_cursor",
]
