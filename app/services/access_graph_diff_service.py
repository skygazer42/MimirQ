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


def _parse_record(obj: dict[str, Any]) -> _ParsedRecord | None:
    kind = _norm_str(obj.get("kind")).lower()
    if not kind:
        return None
    if kind not in _SUPPORTED_KINDS:
        return None

    if kind == "group":
        rec_id = _norm_str(obj.get("id"))
        if not rec_id:
            return None
        fp = (
            _hash_or_fallback(obj, raw_key="name", hash_key="name_hash"),
            _hash_or_fallback(obj, raw_key="external_id", hash_key="external_id_hash"),
        )
        return _ParsedRecord(kind=kind, key=(rec_id,), fingerprint=fp)

    if kind == "dataset":
        rec_id = _norm_str(obj.get("id"))
        if not rec_id:
            return None
        fp = (
            _norm_str(obj.get("permission")) or None,
            _hash_or_fallback(obj, raw_key="owner_id", hash_key="owner_id_hash"),
            _hash_or_fallback(obj, raw_key="name", hash_key="name_hash"),
        )
        return _ParsedRecord(kind=kind, key=(rec_id,), fingerprint=fp)

    if kind == "document":
        rec_id = _norm_str(obj.get("id"))
        if not rec_id:
            return None
        fp = (
            _norm_str(obj.get("dataset_id")) or None,
            _norm_access_mode(obj.get("access_mode")),
            _hash_or_fallback(obj, raw_key="owner_id", hash_key="owner_id_hash"),
        )
        return _ParsedRecord(kind=kind, key=(rec_id,), fingerprint=fp)

    if kind == "group_member":
        group_id = _norm_str(obj.get("group_id"))
        user_hash = _hash_or_fallback(obj, raw_key="user_id", hash_key="user_id_hash")
        if not group_id or not user_hash:
            return None
        return _ParsedRecord(kind=kind, key=(group_id, user_hash), fingerprint=None)

    if kind == "dataset_member_permission":
        dataset_id = _norm_str(obj.get("dataset_id"))
        account_hash = _hash_or_fallback(obj, raw_key="account_id", hash_key="account_id_hash")
        if not dataset_id or not account_hash:
            return None
        return _ParsedRecord(kind=kind, key=(dataset_id, account_hash), fingerprint=None)

    if kind == "dataset_group_permission":
        dataset_id = _norm_str(obj.get("dataset_id"))
        group_id = _norm_str(obj.get("group_id"))
        if not dataset_id or not group_id:
            return None
        return _ParsedRecord(kind=kind, key=(dataset_id, group_id), fingerprint=None)

    if kind == "document_member_permission":
        document_id = _norm_str(obj.get("document_id"))
        account_hash = _hash_or_fallback(obj, raw_key="account_id", hash_key="account_id_hash")
        if not document_id or not account_hash:
            return None
        return _ParsedRecord(kind=kind, key=(document_id, account_hash), fingerprint=None)

    if kind == "document_group_permission":
        document_id = _norm_str(obj.get("document_id"))
        group_id = _norm_str(obj.get("group_id"))
        if not document_id or not group_id:
            return None
        return _ParsedRecord(kind=kind, key=(document_id, group_id), fingerprint=None)

    return None


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

    counts_a: Counter[str] = Counter()
    counts_b: Counter[str] = Counter()

    keys_a: dict[str, set[tuple[str, ...]]] = {k: set() for k in _SUPPORTED_KINDS}
    keys_b: dict[str, set[tuple[str, ...]]] = {k: set() for k in _SUPPORTED_KINDS}

    fps_a: dict[str, dict[tuple[str, ...], tuple[str | None, ...]]] = {k: {} for k in _FINGERPRINTED_KINDS}
    fps_b: dict[str, dict[tuple[str, ...], tuple[str | None, ...]]] = {k: {} for k in _FINGERPRINTED_KINDS}

    for obj in records_a:
        if not isinstance(obj, dict):
            continue
        parsed = _parse_record(obj)
        if parsed is None:
            continue
        counts_a[parsed.kind] += 1
        keys_a[parsed.kind].add(parsed.key)
        if parsed.kind in _FINGERPRINTED_KINDS and parsed.fingerprint is not None:
            fps_a[parsed.kind][parsed.key] = parsed.fingerprint

    for obj in records_b:
        if not isinstance(obj, dict):
            continue
        parsed = _parse_record(obj)
        if parsed is None:
            continue
        counts_b[parsed.kind] += 1
        keys_b[parsed.kind].add(parsed.key)
        if parsed.kind in _FINGERPRINTED_KINDS and parsed.fingerprint is not None:
            fps_b[parsed.kind][parsed.key] = parsed.fingerprint

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

        changed = 0
        if kind in _FINGERPRINTED_KINDS:
            inter = a_keys & b_keys
            fp_map_a = fps_a.get(kind) or {}
            fp_map_b = fps_b.get(kind) or {}
            for key in inter:
                fp_a = fp_map_a.get(key)
                fp_b = fp_map_b.get(key)
                if fp_a is None or fp_b is None:
                    continue
                if fp_a == fp_b:
                    continue
                changed += 1
                bucket = f"{kind}_changed"
                if len(examples.get(bucket) or []) < max_examples:
                    rec_id = key[0] if key else ""
                    examples[bucket].append(
                        {
                            "id": str(rec_id),
                            "changed_fields": _changed_fields(kind, fp_a, fp_b),
                        }
                    )

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
        added = b_keys - a_keys
        removed = a_keys - b_keys
        add_cnt: Counter[str] = Counter()
        rm_cnt: Counter[str] = Counter()
        for key in added:
            if len(key) > parent_idx:
                add_cnt[str(key[parent_idx])] += 1
        for key in removed:
            if len(key) > parent_idx:
                rm_cnt[str(key[parent_idx])] += 1

        totals: Counter[str] = Counter()
        for k, v in add_cnt.items():
            totals[k] += int(v)
        for k, v in rm_cnt.items():
            totals[k] += int(v)

        rows: list[dict[str, Any]] = []
        for parent_id, _total in totals.most_common(max_examples):
            rows.append(
                {
                    label: str(parent_id),
                    "added": int(add_cnt.get(parent_id) or 0),
                    "removed": int(rm_cnt.get(parent_id) or 0),
                }
            )
        top_churn[f"{kind}_by_{label}"] = rows

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
