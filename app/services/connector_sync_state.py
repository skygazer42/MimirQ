from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, TypeVar
from uuid import UUID

from app.services.connector_registry import CONNECTOR_REGISTRY, ConnectorDefinition
from app.rag.core.logging import get_logger

T = TypeVar("T")
_STATE_SCHEMA_VERSION = 2
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
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _normalize_recorded_at(value: datetime | str | None) -> str:
    if isinstance(value, datetime):
        return _isoformat_utc(value)
    text = str(value or "").strip()
    if text:
        return text
    return _isoformat_utc(datetime.now(UTC))


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
    return dict(items)


def normalize_boundary_ids(value: Any, *, max_items: int = 200) -> list[str]:
    raw_items = value if isinstance(value, list) else []
    out: list[str] = []
    seen: set[str] = set()
    limit = max(1, int(max_items or 0))
    for raw in raw_items:
        item = str(raw or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
        if len(out) >= limit:
            break
    out.sort()
    return out


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


def _normalize_cursor_value(*, definition: ConnectorDefinition, state: Mapping[str, Any]) -> dict[str, Any] | None:
    kind = str(getattr(definition, "sync_cursor_kind", "none") or "none").strip().lower() or "none"
    if kind == "offset":
        return {"kind": "offset", "field": "cursor", "value": get_resume_cursor(state)}

    return None


def _normalize_watermark_value(*, definition: ConnectorDefinition, state: Mapping[str, Any]) -> dict[str, Any] | None:
    kind = str(getattr(definition, "sync_cursor_kind", "none") or "none").strip().lower() or "none"
    if kind != "timestamp":
        return None

    value = str(state.get("last_modified") or "").strip()
    if not value:
        return None
    out = {"kind": "timestamp", "field": "last_modified", "value": value}
    seen_ids = normalize_boundary_ids(state.get("last_modified_ids"))
    if seen_ids:
        out["seen_ids"] = seen_ids
    return out


def _normalize_manifest_value(state: Mapping[str, Any]) -> dict[str, Any] | None:
    manifest = normalize_source_manifest(state.get("source_manifest"))
    if not manifest:
        return None
    return {
        "kind": "source_manifest",
        "field": "source_manifest",
        "count": int(len(manifest)),
        "entries": manifest,
    }


def _normalize_totals(*, definition: ConnectorDefinition, state: Mapping[str, Any]) -> dict[str, int] | None:
    totals: dict[str, int] = {}
    for key in getattr(definition, "state_keys", ()) or ():
        if not str(key).startswith("total_"):
            continue
        raw = state.get(key)
        if raw is None:
            continue
        try:
            totals[str(key)] = int(raw)
        except Exception:
            get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
            continue
    return totals or None


def _resolve_last_successful_markers(
    *,
    previous_state: Mapping[str, Any] | None,
    run_id: UUID | str | None,
    run_status: str | None,
    recorded_at_norm: str | None,
) -> tuple[str | None, str | None]:
    prev = previous_state if isinstance(previous_state, Mapping) else {}
    last_successful_run_id = str(prev.get("state_last_successful_run_id") or "").strip() or None
    last_successful_recorded_at = str(prev.get("state_last_successful_recorded_at") or "").strip() or None

    status = str(run_status or "").strip().lower()
    if status == "completed" and run_id is not None:
        last_successful_run_id = str(run_id)
        last_successful_recorded_at = str(recorded_at_norm or "").strip() or last_successful_recorded_at

    return last_successful_run_id, last_successful_recorded_at


def _build_state_sync_payload(
    *,
    connector_id: str,
    state: Mapping[str, Any],
    previous_state: Mapping[str, Any] | None,
    run_id: UUID | str | None = None,
    run_status: str | None = None,
    recorded_at_norm: str | None = None,
) -> dict[str, Any] | None:
    definition = CONNECTOR_REGISTRY.get(str(connector_id or "").strip())
    if definition is None:
        return None

    last_successful_run_id, last_successful_recorded_at = _resolve_last_successful_markers(
        previous_state=previous_state,
        run_id=run_id,
        run_status=run_status,
        recorded_at_norm=recorded_at_norm,
    )

    return {
        "schema": "mimirq.connector_sync_state.v2",
        "connector_id": str(definition.connector_id),
        "supports_incremental": bool(definition.supports_incremental),
        "supports_resume": bool(definition.supports_resume),
        "supports_full_reconcile": bool(getattr(definition, "supports_full_reconcile", False)),
        "cursor": _normalize_cursor_value(definition=definition, state=state),
        "watermark": _normalize_watermark_value(definition=definition, state=state),
        "manifest": _normalize_manifest_value(state),
        "totals": _normalize_totals(definition=definition, state=state),
        "reconcile": {
            "last_successful_run_id": last_successful_run_id,
            "last_successful_recorded_at": last_successful_recorded_at,
        },
    }


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
            if "source_manifest" in stats_map:
                state["source_manifest"] = normalize_source_manifest(stats_map.get("source_manifest"))
            continue
        if key == "last_modified_ids":
            if "last_modified_ids" in stats_map:
                state["last_modified_ids"] = normalize_boundary_ids(stats_map.get("last_modified_ids"))
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
    state["state_schema_version"] = int(_STATE_SCHEMA_VERSION)
    state_sync = _build_state_sync_payload(
        connector_id=connector_id,
        state=state,
        previous_state=existing_state,
        run_id=run_id,
    )
    if state_sync is not None:
        state["state_sync"] = state_sync
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
    last_successful_run_id, last_successful_recorded_at = _resolve_last_successful_markers(
        previous_state=previous_state,
        run_id=run_id,
        run_status=run_status,
        recorded_at_norm=recorded_at_norm,
    )
    state["state_last_successful_run_id"] = last_successful_run_id
    state["state_last_successful_recorded_at"] = last_successful_recorded_at
    state_sync = _build_state_sync_payload(
        connector_id=connector_id,
        state=state,
        previous_state=previous_state,
        run_id=run_id,
        run_status=run_status,
        recorded_at_norm=recorded_at_norm,
    )
    if state_sync is not None:
        state["state_sync"] = state_sync
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
    "normalize_boundary_ids",
    "normalize_source_manifest",
    "slice_items_from_cursor",
]
