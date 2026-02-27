"""
KG snapshot + diff helpers.

Wave7(C) goals:
- Provide a stable snapshot shape that can be exported/imported.
- Provide a deterministic diff summary between two snapshots (pipeline_hash A vs B).

Note:
- Snapshot building from DB is implemented in the KG API routes (scoped + ACL-aware).
- This module focuses on the pure diff logic so it is easy to unit-test.
"""

from __future__ import annotations

from typing import Any

KG_SNAPSHOT_SCHEMA_V1 = "mimirq.kg_snapshot.v1"
KG_SNAPSHOT_DIFF_SCHEMA_V1 = "mimirq.kg_snapshot_diff.v1"


def _to_int(v: Any) -> int:
    try:
        return int(v) if v is not None else 0
    except Exception:
        return 0


def _type_counts(snapshot: dict[str, Any]) -> dict[str, int]:
    raw = snapshot.get("entity_types") or []
    if not isinstance(raw, list):
        return {}
    out: dict[str, int] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        typ = str(item.get("type") or "").strip() or "unknown"
        out[typ] = _to_int(item.get("count"))
    return out


def diff_kg_snapshots(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """
    Compute a deterministic diff summary between two KG snapshots.

    Returns:
      {
        "schema": "mimirq.kg_snapshot_diff.v1",
        "pipeline_hash_a": "...",
        "pipeline_hash_b": "...",
        "delta": {"events":..., "entities":..., "links":..., "relations":..., "docs":...},
        "entity_types_delta": [{"type":"Skill","delta":+3}, ...]
      }
    """
    a0 = a if isinstance(a, dict) else {}
    b0 = b if isinstance(b, dict) else {}

    out: dict[str, Any] = {
        "schema": KG_SNAPSHOT_DIFF_SCHEMA_V1,
        "pipeline_hash_a": str(a0.get("pipeline_hash") or ""),
        "pipeline_hash_b": str(b0.get("pipeline_hash") or ""),
    }

    delta: dict[str, int] = {}
    for k in ("docs", "events", "entities", "links", "relations"):
        delta[k] = _to_int(b0.get(k)) - _to_int(a0.get(k))
    out["delta"] = delta

    a_types = _type_counts(a0)
    b_types = _type_counts(b0)

    all_types = sorted(set(a_types.keys()) | set(b_types.keys()))
    type_deltas: list[dict[str, Any]] = []
    for typ in all_types:
        d = int(b_types.get(typ, 0) or 0) - int(a_types.get(typ, 0) or 0)
        if d == 0:
            continue
        type_deltas.append({"type": typ, "delta": int(d)})

    # Deterministic ordering: larger magnitude first, then type.
    type_deltas.sort(key=lambda x: (-abs(int(x.get("delta") or 0)), str(x.get("type") or "")))
    out["entity_types_delta"] = type_deltas

    return out


__all__ = [
    "KG_SNAPSHOT_DIFF_SCHEMA_V1",
    "KG_SNAPSHOT_SCHEMA_V1",
    "diff_kg_snapshots",
]

