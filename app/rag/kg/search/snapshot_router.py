from __future__ import annotations

import re
from typing import Any

_YEAR_RE = re.compile(r"\b(20\d{2})\b")
_TEMPORAL_HINT_RE = re.compile(r"(?i)\b(current|latest|now|today|timeline|history|before|after)\b|当前|现在|最新|历史|之前|之后")


def _sorted_snapshots(available_snapshots: list[str]) -> list[str]:
    snapshots = [str(item or "").strip() for item in (available_snapshots or []) if str(item or "").strip()]
    return sorted(snapshots)


def _snapshot_for_year(query: str, snapshots: list[str]) -> str | None:
    year_match = _YEAR_RE.search(query)
    if not year_match:
        return None
    year = str(year_match.group(1) or "")
    return next((snap for snap in snapshots if snap.startswith(year)), None)


def _select_temporal_snapshot(query: str, snapshots: list[str]) -> tuple[str, str]:
    year_snapshot = _snapshot_for_year(query, snapshots)
    if year_snapshot is not None:
        return year_snapshot, "year_match"
    if _TEMPORAL_HINT_RE.search(query):
        return snapshots[-1], "latest_keyword"
    return snapshots[-1], "fallback_latest"


def route_snapshot_for_query(
    *,
    query: str,
    available_snapshots: list[str],
) -> dict[str, Any]:
    q = str(query or "").strip()
    snapshots = _sorted_snapshots(available_snapshots)
    temporal_query = bool(_TEMPORAL_HINT_RE.search(q) or _YEAR_RE.search(q))

    if not snapshots:
        return {
            "selected_snapshot": None,
            "temporal_query": bool(temporal_query),
            "reason_codes": ["no_snapshots"],
        }

    if not temporal_query:
        return {
            "selected_snapshot": None,
            "temporal_query": False,
            "reason_codes": ["non_temporal_query"],
        }

    selected_snapshot, reason_code = _select_temporal_snapshot(q, snapshots)
    return {
        "selected_snapshot": selected_snapshot,
        "temporal_query": True,
        "reason_codes": [reason_code],
    }


__all__ = ["route_snapshot_for_query"]
