from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence, TypeVar
from uuid import UUID

T = TypeVar("T")


@dataclass(frozen=True)
class ConnectorSyncPolicy:
    connector_id: str
    state_keys: tuple[str, ...] = ()


CONNECTOR_SYNC_POLICIES: dict[str, ConnectorSyncPolicy] = {
    "url_batch": ConnectorSyncPolicy(connector_id="url_batch", state_keys=("cursor", "total_urls")),
    "web_crawl": ConnectorSyncPolicy(connector_id="web_crawl", state_keys=("cursor", "total_urls")),
    "github_repo": ConnectorSyncPolicy(connector_id="github_repo", state_keys=("cursor", "total_files")),
    "drive_files": ConnectorSyncPolicy(connector_id="drive_files", state_keys=("cursor", "total_urls")),
    "minio_bucket": ConnectorSyncPolicy(connector_id="minio_bucket", state_keys=("cursor", "total_objects")),
    "confluence_space": ConnectorSyncPolicy(connector_id="confluence_space", state_keys=("last_modified",)),
    "mysql_catalog": ConnectorSyncPolicy(connector_id="mysql_catalog"),
    "sqlserver_catalog": ConnectorSyncPolicy(connector_id="sqlserver_catalog"),
}


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


__all__ = [
    "CONNECTOR_SYNC_POLICIES",
    "ConnectorSyncPolicy",
    "build_persisted_state",
    "get_resume_cursor",
    "slice_items_from_cursor",
]
