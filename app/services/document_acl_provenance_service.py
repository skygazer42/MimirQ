"""
Document-level ACL provenance metadata (PII-safe by default).

We persist a small, bounded record under `documents.metadata.acl_provenance` so
operators can understand *why* a document ended up with a particular doc-level
ACL (especially when inheriting permissions from a source system).

Security posture:
- Stored provenance must be safe to expose in normal document detail responses.
  Therefore we do NOT store raw source principal identifiers (which can include
  emails / group names). We store stable SHA-256 hashes instead.
- Payloads are bounded to prevent metadata bloat.
"""


from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from app.rag.core.hashing import stable_hash

ACL_PROVENANCE_SCHEMA = "mimirq.document_acl_provenance.v1"


def _now_utc_iso() -> str:
    s = datetime.now(UTC).isoformat()
    if s.endswith("+00:00"):
        return s[:-6] + "Z"
    return s


def _normalize_mode(v: object, *, default: str = "inherit") -> str:
    mode = str(v or "").strip().lower()
    return mode or default


def _normalize_external_ids(
    external_ids: Iterable[object] | None,
    *,
    max_items: int,
    max_len: int = 255,
) -> list[str]:
    max_items = max(0, int(max_items or 0))
    max_len = max(1, int(max_len or 255))

    out: list[str] = []
    seen: set[str] = set()
    for raw in external_ids or []:
        if not isinstance(raw, (str, int, float)):
            continue
        s = str(raw).strip()
        if not s:
            continue
        if len(s) > max_len:
            s = s[:max_len]
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
        if max_items and len(out) >= max_items:
            break
    return sorted(out)


def _normalize_group_ids(group_ids: Iterable[object] | None, *, max_items: int) -> list[str]:
    max_items = max(0, int(max_items or 0))
    out: list[str] = []
    seen: set[str] = set()
    for raw in group_ids or []:
        s = str(raw or "").strip()
        if not s:
            continue
        if len(s) > 80:
            s = s[:80]
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
        if max_items and len(out) >= max_items:
            break
    return sorted(out)


def build_document_acl_provenance(
    *,
    connector_id: str,
    connector_run_id: str | None,
    effective_access: dict | None,
    source_acl_mode: str | None,
    source_acl_fallback_mode: str | None,
    source_principal_external_ids: Iterable[object] | None,
    mapped_group_ids: Iterable[object] | None,
    fallback_used: bool,
    allow_anyone: bool | None = None,
    anyone_detected: bool | None = None,
    restricted: bool | None = None,
    max_principals: int = 200,
    max_groups: int = 200,
) -> dict[str, Any]:
    """
    Build a JSON-safe provenance record for `documents.metadata.acl_provenance`.

    Notes:
    - `source_principal_external_ids` are hashed (SHA-256) to avoid PII leakage.
    - `mapped_group_ids` are stored as strings (tenant group UUIDs).
    """

    effective_mode = _normalize_mode((effective_access or {}).get("mode"), default="inherit")
    partial_member_list = (effective_access or {}).get("partial_member_list")
    partial_group_list = (effective_access or {}).get("partial_group_list")

    member_count = 0
    if isinstance(partial_member_list, list):
        member_count = len([v for v in partial_member_list if isinstance(v, (str, int, float)) and str(v).strip()])

    # Note: group ids here are already internal UUIDs (non-PII).
    effective_group_ids = []
    if isinstance(partial_group_list, list):
        effective_group_ids = _normalize_group_ids(partial_group_list, max_items=max_groups)

    principals_norm = _normalize_external_ids(source_principal_external_ids, max_items=max_principals)
    principal_hashes = [stable_hash(v, length=32) for v in principals_norm]

    mapped_groups_norm = _normalize_group_ids(mapped_group_ids, max_items=max_groups)

    record: dict[str, Any] = {
        "schema": ACL_PROVENANCE_SCHEMA,
        "applied_at": _now_utc_iso(),
        "applied_by": {
            "kind": "connector",
            "connector_id": str(connector_id or "").strip(),
            "run_id": (str(connector_run_id or "").strip() or None),
        },
        "effective_access": {
            "mode": effective_mode,
            "partial_member_count": int(member_count),
            "partial_group_ids": effective_group_ids,
        },
        "source_acl": {
            "mode": _normalize_mode(source_acl_mode, default="disabled"),
            "fallback_mode": _normalize_mode(source_acl_fallback_mode, default="partial_members"),
            "fallback_used": bool(fallback_used),
            "mapping_strategy": "tenant_groups.external_id",
            "principal_count": int(len(principals_norm)),
            "principal_hash_alg": "sha256",
            "principal_hashes": principal_hashes,
            "mapped_group_count": int(len(mapped_groups_norm)),
            "mapped_group_ids": mapped_groups_norm,
        },
    }

    # Optional hints (still PII-safe).
    if allow_anyone is not None:
        record["source_acl"]["allow_anyone"] = bool(allow_anyone)
    if anyone_detected is not None:
        record["source_acl"]["anyone_detected"] = bool(anyone_detected)
    if restricted is not None:
        record["source_acl"]["restricted"] = bool(restricted)

    return record


def apply_document_acl_provenance(doc, *, provenance: dict[str, Any]) -> None:  # noqa: ANN001
    """
    Best-effort: patch `documents.metadata.acl_provenance` on an ORM document.

    Caller is responsible for committing.
    """
    try:
        meta0 = dict(getattr(doc, "doc_metadata", None) or {})
        meta0["acl_provenance"] = dict(provenance or {})
        doc.doc_metadata = meta0
    except Exception:
        # Never fail ingestion due to metadata patching.
        return None


__all__ = ["ACL_PROVENANCE_SCHEMA", "apply_document_acl_provenance", "build_document_acl_provenance"]

