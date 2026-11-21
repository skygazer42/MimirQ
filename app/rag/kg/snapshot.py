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
from typing import Any, TypedDict

KG_SNAPSHOT_SCHEMA_V1 = "mimirq.kg_snapshot.v1"
KG_SNAPSHOT_SCHEMA_V2 = "mimirq.kg_snapshot.v2"
KG_SNAPSHOT_DIFF_SCHEMA_V1 = "mimirq.kg_snapshot_diff.v1"
KG_SNAPSHOT_DIFF_SCHEMA_V2 = "mimirq.kg_snapshot_diff.v2"
KG_SNAPSHOT_DIFF_SAMPLE_LIMIT = 200


class _EntityTypeDelta(TypedDict):
    type: str
    delta: int


def _to_int(v: Any) -> int:
    return int(v) if v is not None else 0


def _type_counts(snapshot: dict[str, Any]) -> dict[str, int]:
    raw = snapshot.get("entity_types", [])
    if not isinstance(raw, list):
        raise ValueError("Snapshot entity_types must be an array")
    out: dict[str, int] = {}
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("Snapshot entity_types entries must be objects")
        typ = str(item.get("type") or "").strip() or "unknown"
        out[typ] = _to_int(item.get("count"))
    return out


def canonical_json_hash(value: Any) -> str:
    """
    Stable sha256 hash for snapshot detail records.

    sha256 is in the stdlib and sufficient for product-level content addressing
    here; avoiding blake3 keeps the KG snapshot path dependency-free.
    """
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _detail_index(snapshot: dict[str, Any], key: str) -> dict[str, dict[str, Any]]:
    raw = snapshot.get(key, [])
    if not isinstance(raw, list):
        raise ValueError(f"Snapshot {key} must be an array")
    out: dict[str, dict[str, Any]] = {}
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError(f"Snapshot {key} entries must be objects")
        item_id = str(item.get("id") or "").strip()
        if not item_id:
            raise ValueError(f"Snapshot {key} entries must have an id")
        if item_id in out:
            raise ValueError(f"Snapshot {key} contains duplicate id {item_id}")
        normalized = dict(item)
        normalized["id"] = item_id
        props_hash = normalized.get("props_hash")
        if props_hash is not None and (not isinstance(props_hash, str) or not props_hash):
            raise ValueError(f"Snapshot {key} props_hash must be a nonempty string")
        normalized["props_hash"] = (
            canonical_json_hash({k: v for k, v in normalized.items() if k != "id"})
            if props_hash is None
            else props_hash
        )
        out[item_id] = normalized
    return out


def _changed_items(
    a_items: dict[str, dict[str, Any]],
    b_items: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    changed: list[dict[str, Any]] = []
    for item_id in sorted(a_items.keys() & b_items.keys()):
        before = a_items[item_id]
        after = b_items[item_id]
        before_hash = before["props_hash"]
        after_hash = after["props_hash"]
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
    samples: dict[str, list[dict[str, Any]]] = {}
    limit = KG_SNAPSHOT_DIFF_SAMPLE_LIMIT
    for singular, plural in (("node", "nodes"), ("edge", "edges")):
        before = _detail_index(a0, plural)
        after = _detail_index(b0, plural)
        added = [after[key] for key in sorted(after.keys() - before.keys())]
        removed = [before[key] for key in sorted(before.keys() - after.keys())]
        changed = _changed_items(before, after)
        out[f"{singular}_diff"] = {
            "added_count": len(added),
            "removed_count": len(removed),
            "changed_count": len(changed),
            "sample_limit": limit,
        }
        samples[f"{plural}_added"] = added[:limit]
        samples[f"{plural}_removed"] = removed[:limit]
        samples[f"{plural}_changed"] = changed[:limit]
    out.update(samples)


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
    if not isinstance(a, dict) or not isinstance(b, dict):
        raise ValueError("Snapshots must be objects")
    a0, b0 = a, b

    has_detail_diff = any(key in snapshot for snapshot in (a0, b0) for key in ("nodes", "edges"))

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
    type_deltas: list[_EntityTypeDelta] = []
    for typ in all_types:
        d = b_types.get(typ, 0) - a_types.get(typ, 0)
        if d == 0:
            continue
        type_deltas.append({"type": typ, "delta": d})

    # Deterministic ordering: larger magnitude first, then type.
    type_deltas.sort(key=lambda x: (-abs(x["delta"]), x["type"]))
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
