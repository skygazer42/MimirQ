from __future__ import annotations

import re
from typing import Any

_YEAR_RE = re.compile(r"\b(20\d{2})\b")
_TEMPORAL_HINT_RE = re.compile(r"(?i)\b(current|latest|now|today|timeline|history|before|after)\b|当前|现在|最新|历史|之前|之后")


def route_snapshot_for_query(
    *,
    query: str,
    available_snapshots: list[str],
) -> dict[str, Any]:
    q = str(query or "").strip()
    snapshots = [str(item or "").strip() for item in (available_snapshots or []) if str(item or "").strip()]
    snapshots.sort()
    temporal_query = bool(_TEMPORAL_HINT_RE.search(q) or _YEAR_RE.search(q))
    reason_codes: list[str] = []
    selected_snapshot: str | None = None

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

    year_match = _YEAR_RE.search(q)
    if year_match:
        year = str(year_match.group(1) or "")
        for snap in snapshots:
            if snap.startswith(year):
                selected_snapshot = snap
                reason_codes.append("year_match")
                break

    if selected_snapshot is None and _TEMPORAL_HINT_RE.search(q):
        selected_snapshot = snapshots[-1]
        reason_codes.append("latest_keyword")

    if selected_snapshot is None:
        selected_snapshot = snapshots[-1]
        reason_codes.append("fallback_latest")

    return {
        "selected_snapshot": selected_snapshot,
        "temporal_query": True,
        "reason_codes": reason_codes,
    }


__all__ = ["route_snapshot_for_query"]
