"""
Precheck near-duplicate summary helpers.

The scan runner can emit a full near-dup artifact payload (clusters + pairs). For report
bundles and dashboards we also want a compact, stable summary that doesn't require the
full artifact.
"""

from __future__ import annotations

from typing import Any


def _safe_int(v: Any) -> int:
    try:
        return int(v or 0)
    except Exception:
        return 0


def summarize_near_dup_payload(payload: Any | None) -> dict[str, Any]:
    """
    Build a compact summary from a near-duplicate artifact payload.

    Returns a stable dict so it can be embedded in precheck summary JSON and reports.
    """
    empty = {
        "enabled": False,
        "threshold": 0,
        "pairs": 0,
        "clusters": 0,
        "affected_files": 0,
        "largest_cluster_size": 0,
        "keep_candidates_sample": [],
    }

    if not isinstance(payload, dict) or not payload:
        return dict(empty)

    clusters = payload.get("clusters") if isinstance(payload.get("clusters"), list) else []
    threshold = _safe_int(payload.get("threshold"))
    pairs = _safe_int(payload.get("pairs_returned"))
    if pairs <= 0 and isinstance(payload.get("pairs"), list):
        pairs = len(payload.get("pairs") or [])

    affected: set[str] = set()
    largest = 0
    keep_candidates: list[str] = []
    seen_keep: set[str] = set()

    for c in clusters:
        if not isinstance(c, dict):
            continue
        members_raw = c.get("members")
        members: list[str] = []
        if isinstance(members_raw, list):
            for m in members_raw:
                s = str(m or "").strip()
                if s:
                    members.append(s)
        affected.update(members)
        largest = max(largest, len(members))

        kc = str(c.get("keep_candidate") or "").strip()
        if kc and kc not in seen_keep:
            keep_candidates.append(kc)
            seen_keep.add(kc)

    cluster_count = _safe_int(payload.get("clusters_returned"))
    if cluster_count <= 0:
        cluster_count = len(clusters)

    out = dict(empty)
    out.update(
        {
            "enabled": True,
            "threshold": threshold,
            "pairs": int(pairs),
            "clusters": int(cluster_count),
            "affected_files": int(len(affected)),
            "largest_cluster_size": int(largest),
            "keep_candidates_sample": keep_candidates[:20],
        }
    )
    return out


__all__ = ["summarize_near_dup_payload"]
