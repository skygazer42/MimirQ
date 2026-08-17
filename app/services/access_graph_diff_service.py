"""
PII-safe diff summary for access-graph exports.

Provides a bounded, content-free diff that can be used for access reviews:
- input: two access-graph exports (records as dicts)
- output: counts of added/removed/changed per kind + small samples

Security posture:
- Never emits raw user/account identifiers (uses *_hash when present, or stable_hash fallback).
- Never emits document content/filenames/URLs (not present in the export; we also ignore extra keys).
"""


from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from app.rag.core.hashing import stable_hash
from app.rag.core.logging import get_logger

ACCESS_GRAPH_DIFF_SCHEMA_V1 = "mimirq.access_graph_diff.v1"


_FINGERPRINTED_KINDS = {"group", "dataset", "document"}
_MEMBERSHIP_KINDS = {
    "group_member",
    "dataset_member_permission",
    "dataset_group_permission",
    "document_member_permission",
    "document_group_permission",
}
_SUPPORTED_KINDS = _FINGERPRINTED_KINDS | _MEMBERSHIP_KINDS


def _norm_str(v: Any) -> str:
    return str(v or "").strip()


def _hash_or_fallback(obj: dict[str, Any], *, raw_key: str, hash_key: str) -> str | None:
    hv = _norm_str(obj.get(hash_key))
    if hv:
        return hv
    raw = _norm_str(obj.get(raw_key))
    if not raw:
        return None
    return stable_hash(raw, length=16)


def _norm_access_mode(v: Any) -> str:
    s = _norm_str(v).lower()
    if not s or s == "inherit":
        return "inherit"
    return s


@dataclass(frozen=True)
class _ParsedRecord:
    kind: str
    key: tuple[str, ...]
    fingerprint: tuple[str | None, ...] | None = None


def _parse_group_record(obj: dict[str, Any]) -> _ParsedRecord | None:
    rec_id = _norm_str(obj.get("id"))
    if not rec_id:
        return None
    return _ParsedRecord(
        kind="group",
        key=(rec_id,),
        fingerprint=(
            _hash_or_fallback(obj, raw_key="name", hash_key="name_hash"),
            _hash_or_fallback(obj, raw_key="external_id", hash_key="external_id_hash"),
        ),
    )


def _parse_dataset_record(obj: dict[str, Any]) -> _ParsedRecord | None:
    rec_id = _norm_str(obj.get("id"))
    if not rec_id:
        return None
    return _ParsedRecord(
        kind="dataset",
        key=(rec_id,),
        fingerprint=(
            _norm_str(obj.get("permission")) or None,
            _hash_or_fallback(obj, raw_key="owner_id", hash_key="owner_id_hash"),
            _hash_or_fallback(obj, raw_key="name", hash_key="name_hash"),
        ),
    )


def _parse_document_record(obj: dict[str, Any]) -> _ParsedRecord | None:
    rec_id = _norm_str(obj.get("id"))
    if not rec_id:
        return None
    return _ParsedRecord(
        kind="document",
        key=(rec_id,),
        fingerprint=(
            _norm_str(obj.get("dataset_id")) or None,
            _norm_access_mode(obj.get("access_mode")),
            _hash_or_fallback(obj, raw_key="owner_id", hash_key="owner_id_hash"),
        ),
    )


def _parse_group_member_record(obj: dict[str, Any]) -> _ParsedRecord | None:
    group_id = _norm_str(obj.get("group_id"))
    user_hash = _hash_or_fallback(obj, raw_key="user_id", hash_key="user_id_hash")
    if not group_id or not user_hash:
        return None
    return _ParsedRecord(kind="group_member", key=(group_id, user_hash), fingerprint=None)


def _parse_dataset_member_permission_record(obj: dict[str, Any]) -> _ParsedRecord | None:
    dataset_id = _norm_str(obj.get("dataset_id"))
    account_hash = _hash_or_fallback(obj, raw_key="account_id", hash_key="account_id_hash")
    if not dataset_id or not account_hash:
        return None
    return _ParsedRecord(kind="dataset_member_permission", key=(dataset_id, account_hash), fingerprint=None)


def _parse_dataset_group_permission_record(obj: dict[str, Any]) -> _ParsedRecord | None:
    dataset_id = _norm_str(obj.get("dataset_id"))
    group_id = _norm_str(obj.get("group_id"))
    if not dataset_id or not group_id:
        return None
    return _ParsedRecord(kind="dataset_group_permission", key=(dataset_id, group_id), fingerprint=None)


def _parse_document_member_permission_record(obj: dict[str, Any]) -> _ParsedRecord | None:
    document_id = _norm_str(obj.get("document_id"))
    account_hash = _hash_or_fallback(obj, raw_key="account_id", hash_key="account_id_hash")
    if not document_id or not account_hash:
        return None
    return _ParsedRecord(kind="document_member_permission", key=(document_id, account_hash), fingerprint=None)


def _parse_document_group_permission_record(obj: dict[str, Any]) -> _ParsedRecord | None:
    document_id = _norm_str(obj.get("document_id"))
    group_id = _norm_str(obj.get("group_id"))
    if not document_id or not group_id:
        return None
    return _ParsedRecord(kind="document_group_permission", key=(document_id, group_id), fingerprint=None)


_KIND_PARSERS = {
    "group": _parse_group_record,
    "dataset": _parse_dataset_record,
    "document": _parse_document_record,
    "group_member": _parse_group_member_record,
    "dataset_member_permission": _parse_dataset_member_permission_record,
    "dataset_group_permission": _parse_dataset_group_permission_record,
    "document_member_permission": _parse_document_member_permission_record,
    "document_group_permission": _parse_document_group_permission_record,
}


def _parse_record(obj: dict[str, Any]) -> _ParsedRecord | None:
    kind = _norm_str(obj.get("kind")).lower()
    parser = _KIND_PARSERS.get(kind)
    if parser is None:
        return None
    return parser(obj)


def _changed_fields(kind: str, fp_a: tuple[str | None, ...], fp_b: tuple[str | None, ...]) -> list[str]:
    if kind == "group":
        names = ("name_hash", "external_id_hash")
    elif kind == "dataset":
        names = ("permission", "owner_id_hash", "name_hash")
    elif kind == "document":
        names = ("dataset_id", "access_mode", "owner_id_hash")
    else:
        names = ()

    out: list[str] = []
    for idx, name in enumerate(names):
        try:
            if fp_a[idx] != fp_b[idx]:
                out.append(str(name))
        except Exception:
            get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
            continue
    return out


def _empty_kind_sets() -> dict[str, set[tuple[str, ...]]]:
    return {kind: set() for kind in _SUPPORTED_KINDS}


def _empty_fingerprint_maps() -> dict[str, dict[tuple[str, ...], tuple[str | None, ...]]]:
    return {kind: {} for kind in _FINGERPRINTED_KINDS}


def _collect_graph_records(
    records: Iterable[dict[str, Any]],
) -> tuple[Counter[str], dict[str, set[tuple[str, ...]]], dict[str, dict[tuple[str, ...], tuple[str | None, ...]]]]:
    counts: Counter[str] = Counter()
    keys = _empty_kind_sets()
    fingerprints = _empty_fingerprint_maps()
    for obj in records:
        if not isinstance(obj, dict):
            continue
        parsed = _parse_record(obj)
        if parsed is None:
            continue
        counts[parsed.kind] += 1
        keys[parsed.kind].add(parsed.key)
        if parsed.kind in _FINGERPRINTED_KINDS and parsed.fingerprint is not None:
            fingerprints[parsed.kind][parsed.key] = parsed.fingerprint
    return counts, keys, fingerprints


def _changed_examples_for_kind(
    *,
    kind: str,
    a_keys: set[tuple[str, ...]],
    b_keys: set[tuple[str, ...]],
    fps_a: dict[str, dict[tuple[str, ...], tuple[str | None, ...]]],
    fps_b: dict[str, dict[tuple[str, ...], tuple[str | None, ...]]],
    max_examples: int,
) -> tuple[int, list[dict[str, Any]]]:
    if kind not in _FINGERPRINTED_KINDS:
        return 0, []

    changed = 0
    examples: list[dict[str, Any]] = []
    fp_map_a = fps_a.get(kind) or {}
    fp_map_b = fps_b.get(kind) or {}
    for key in a_keys & b_keys:
        fp_a = fp_map_a.get(key)
        fp_b = fp_map_b.get(key)
        if fp_a is None or fp_b is None or fp_a == fp_b:
            continue
        changed += 1
        if len(examples) < max_examples:
            rec_id = key[0] if key else ""
            examples.append(
                {
                    "id": str(rec_id),
                    "changed_fields": _changed_fields(kind, fp_a, fp_b),
                }
            )
    return changed, examples


def _parent_churn_rows(
    *,
    added: set[tuple[str, ...]],
    removed: set[tuple[str, ...]],
    parent_idx: int,
    label: str,
    max_examples: int,
) -> list[dict[str, Any]]:
    add_cnt: Counter[str] = Counter()
    rm_cnt: Counter[str] = Counter()
    for key in added:
        if len(key) > parent_idx:
            add_cnt[str(key[parent_idx])] += 1
    for key in removed:
        if len(key) > parent_idx:
            rm_cnt[str(key[parent_idx])] += 1

    totals: Counter[str] = Counter()
    for key, value in add_cnt.items():
        totals[key] += int(value)
    for key, value in rm_cnt.items():
        totals[key] += int(value)

    rows: list[dict[str, Any]] = []
    for parent_id, _total in totals.most_common(max_examples):
        rows.append(
            {
                label: str(parent_id),
                "added": int(add_cnt.get(parent_id) or 0),
                "removed": int(rm_cnt.get(parent_id) or 0),
            }
        )
    return rows


def diff_access_graph_records(
    records_a: Iterable[dict[str, Any]],
    records_b: Iterable[dict[str, Any]],
    *,
    max_examples: int = 20,
) -> dict[str, Any]:
    """
    Compute a bounded, PII-safe diff summary from two access-graph record iterables.
    """
    max_examples = max(0, int(max_examples or 0))
    counts_a, keys_a, fps_a = _collect_graph_records(records_a)
    counts_b, keys_b, fps_b = _collect_graph_records(records_b)

    kinds_summary: dict[str, Any] = {}
    examples: dict[str, list[dict[str, Any]]] = {
        "group_changed": [],
        "dataset_changed": [],
        "document_changed": [],
    }

    for kind in sorted(_SUPPORTED_KINDS):
        a_keys = keys_a.get(kind) or set()
        b_keys = keys_b.get(kind) or set()
        added = b_keys - a_keys
        removed = a_keys - b_keys

        changed, changed_examples = _changed_examples_for_kind(
            kind=kind,
            a_keys=a_keys,
            b_keys=b_keys,
            fps_a=fps_a,
            fps_b=fps_b,
            max_examples=max_examples,
        )
        if changed_examples:
            examples[f"{kind}_changed"] = changed_examples

        kinds_summary[kind] = {
            "a": int(counts_a.get(kind) or 0),
            "b": int(counts_b.get(kind) or 0),
            "added": int(len(added)),
            "removed": int(len(removed)),
            "changed": int(changed),
        }

    # Churn summaries (PII-minimal): aggregate changes by parent resource id.
    top_churn: dict[str, list[dict[str, Any]]] = {}

    def _churn_by_parent(kind: str, *, parent_idx: int, label: str) -> None:
        a_keys = keys_a.get(kind) or set()
        b_keys = keys_b.get(kind) or set()
        top_churn[f"{kind}_by_{label}"] = _parent_churn_rows(
            added=b_keys - a_keys,
            removed=a_keys - b_keys,
            parent_idx=parent_idx,
            label=label,
            max_examples=max_examples,
        )

    _churn_by_parent("group_member", parent_idx=0, label="group_id")
    _churn_by_parent("dataset_member_permission", parent_idx=0, label="dataset_id")
    _churn_by_parent("dataset_group_permission", parent_idx=0, label="dataset_id")
    _churn_by_parent("document_member_permission", parent_idx=0, label="document_id")
    _churn_by_parent("document_group_permission", parent_idx=0, label="document_id")

    return {
        "schema": ACCESS_GRAPH_DIFF_SCHEMA_V1,
        "summary": {
            "kinds": kinds_summary,
            "top_churn": top_churn,
        },
        "examples": examples,
    }


__all__ = [
    "ACCESS_GRAPH_DIFF_SCHEMA_V1",
    "diff_access_graph_records",
]
