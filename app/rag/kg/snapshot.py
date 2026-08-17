"""
KG snapshot + diff helpers.

Wave7(C) goals:
- Provide a stable snapshot shape that can be exported/imported.
- Provide a deterministic diff summary between two snapshots (pipeline_hash A vs B).

Note:
- Snapshot building from DB is implemented in the KG API routes (scoped + ACL-aware).
- This module focuses on the pure diff logic so it is easy to unit-test.
"""

import hashlib
import json
from typing import Any

KG_SNAPSHOT_SCHEMA_V1 = "mimirq.kg_snapshot.v1"
KG_SNAPSHOT_SCHEMA_V2 = "mimirq.kg_snapshot.v2"
KG_SNAPSHOT_DIFF_SCHEMA_V1 = "mimirq.kg_snapshot_diff.v1"
KG_SNAPSHOT_DIFF_SCHEMA_V2 = "mimirq.kg_snapshot_diff.v2"
KG_SNAPSHOT_DIFF_SAMPLE_LIMIT = 200


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


def canonical_json_hash(value: Any) -> str:
    """
    Stable sha256 hash for snapshot detail records.

    sha256 is in the stdlib and sufficient for product-level content addressing
    here; avoiding blake3 keeps the KG snapshot path dependency-free.
    """
    try:
        payload = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    except Exception:
        payload = str(value)
    return hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()


def _detail_items(snapshot: dict[str, Any], key: str) -> list[dict[str, Any]]:
    raw = snapshot.get(key) or []
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or "").strip()
        if not item_id:
            continue
        normalized = dict(item)
        normalized["id"] = item_id
        normalized["props_hash"] = str(
            normalized.get("props_hash") or canonical_json_hash({k: v for k, v in normalized.items() if k != "id"})
        )
        out.append(normalized)
    out.sort(key=lambda x: str(x.get("id") or ""))
    return out


def _detail_index(snapshot: dict[str, Any], key: str) -> dict[str, dict[str, Any]]:
    return {str(item.get("id")): item for item in _detail_items(snapshot, key)}


def _sample(items: list[dict[str, Any]], limit: int = KG_SNAPSHOT_DIFF_SAMPLE_LIMIT) -> list[dict[str, Any]]:
    return items[: max(0, int(limit))]


def _changed_items(
    a_items: dict[str, dict[str, Any]],
    b_items: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    changed: list[dict[str, Any]] = []
    for item_id in sorted(set(a_items) & set(b_items)):
        before = a_items[item_id]
        after = b_items[item_id]
        before_hash = str(before.get("props_hash") or "")
        after_hash = str(after.get("props_hash") or "")
        if before_hash == after_hash:
            continue
        changed.append(
            {
                "id": item_id,
                "before_props_hash": before_hash,
                "after_props_hash": after_hash,
                "before": before,
                "after": after,
            }
        )
    return changed


def _append_exact_detail_diff(out: dict[str, Any], a0: dict[str, Any], b0: dict[str, Any]) -> None:
    node_a = _detail_index(a0, "nodes")
    node_b = _detail_index(b0, "nodes")
    edge_a = _detail_index(a0, "edges")
    edge_b = _detail_index(b0, "edges")

    nodes_added = [node_b[k] for k in sorted(set(node_b) - set(node_a))]
    nodes_removed = [node_a[k] for k in sorted(set(node_a) - set(node_b))]
    nodes_changed = _changed_items(node_a, node_b)

    edges_added = [edge_b[k] for k in sorted(set(edge_b) - set(edge_a))]
    edges_removed = [edge_a[k] for k in sorted(set(edge_a) - set(edge_b))]
    edges_changed = _changed_items(edge_a, edge_b)

    out["node_diff"] = {
        "added_count": len(nodes_added),
        "removed_count": len(nodes_removed),
        "changed_count": len(nodes_changed),
        "sample_limit": KG_SNAPSHOT_DIFF_SAMPLE_LIMIT,
    }
    out["edge_diff"] = {
        "added_count": len(edges_added),
        "removed_count": len(edges_removed),
        "changed_count": len(edges_changed),
        "sample_limit": KG_SNAPSHOT_DIFF_SAMPLE_LIMIT,
    }
    out["nodes_added"] = _sample(nodes_added)
    out["nodes_removed"] = _sample(nodes_removed)
    out["nodes_changed"] = _sample(nodes_changed)
    out["edges_added"] = _sample(edges_added)
    out["edges_removed"] = _sample(edges_removed)
    out["edges_changed"] = _sample(edges_changed)


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

    has_detail_diff = bool(a0.get("nodes") or a0.get("edges") or b0.get("nodes") or b0.get("edges"))

    out: dict[str, Any] = {
        "schema": KG_SNAPSHOT_DIFF_SCHEMA_V2 if has_detail_diff else KG_SNAPSHOT_DIFF_SCHEMA_V1,
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
    if has_detail_diff:
        _append_exact_detail_diff(out, a0, b0)

    return out


__all__ = [
    "KG_SNAPSHOT_DIFF_SAMPLE_LIMIT",
    "KG_SNAPSHOT_DIFF_SCHEMA_V1",
    "KG_SNAPSHOT_DIFF_SCHEMA_V2",
    "KG_SNAPSHOT_SCHEMA_V1",
    "KG_SNAPSHOT_SCHEMA_V2",
    "canonical_json_hash",
    "diff_kg_snapshots",
]
