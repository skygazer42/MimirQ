
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

from app.services.connector_sync_state import normalize_source_manifest

CONNECTOR_RECONCILE_SCHEMA_V1 = "mimirq.connector_reconcile.v1"


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _normalize_refs(value: Any, *, max_items: int = 10_000) -> list[str]:
    raw_items = value if isinstance(value, list) else []
    out: list[str] = []
    seen: set[str] = set()
    limit = max(1, int(max_items or 0))
    for raw in raw_items:
        item = str(raw or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
        if len(out) >= limit:
            break
    out.sort()
    return out


def resolve_connector_reconcile_source_refs(
    *,
    connector_id: str,
    config: Mapping[str, Any] | None,
    state: Mapping[str, Any] | None,
) -> list[str]:
    state_map = state if isinstance(state, Mapping) else {}
    manifest = normalize_source_manifest(state_map.get("source_manifest"))
    if not manifest:
        state_sync = state_map.get("state_sync") if isinstance(state_map.get("state_sync"), Mapping) else {}
        manifest_payload = state_sync.get("manifest") if isinstance(state_sync, Mapping) else {}
        entries = manifest_payload.get("entries") if isinstance(manifest_payload, Mapping) else None
        manifest = normalize_source_manifest(entries)
    if manifest:
        return sorted(manifest.keys())

    config_map = config if isinstance(config, Mapping) else {}
    cid = str(connector_id or "").strip()
    if cid in {"url_batch", "drive_files"}:
        return _normalize_refs(config_map.get("urls"))
    return []


def extract_connector_source_identity(doc: Any) -> dict[str, str | None]:
    meta = getattr(doc, "doc_metadata", None)
    meta_map = meta if isinstance(meta, Mapping) else {}
    connector = meta_map.get("connector") if isinstance(meta_map.get("connector"), Mapping) else {}

    connector_id = str(connector.get("connector_id") or "").strip() or None
    config_id = str(connector.get("config_id") or "").strip() or None

    source_ref = (
        str(
            connector.get("source_ref")
            or connector.get("source_id")
            or connector.get("page_id")
            or connector.get("issue_key")
            or connector.get("issue_id")
            or connector.get("issue_url")
            or meta_map.get("source_url")
            or ""
        ).strip()
        or None
    )
    source_id = str(connector.get("source_id") or source_ref or "").strip() or None
    return {
        "connector_id": connector_id,
        "config_id": config_id,
        "source_ref": source_ref,
        "source_id": source_id,
    }


def plan_connector_reconcile(
    *,
    connector_id: str,
    config_id: str | None,
    dataset_id: str | None,
    documents: Iterable[Any],
    desired_source_refs: list[str],
    apply: bool,
    now: datetime | None = None,
    sample_limit: int = 20,
) -> dict[str, Any]:
    now_dt = now or _now_utc()
    normalized_connector_id = str(connector_id or "").strip()
    normalized_config_id = str(config_id or "").strip() or None
    desired_refs = _normalize_refs(desired_source_refs)
    desired_set = set(desired_refs)
    limit = max(1, int(sample_limit or 0))

    active_by_ref: dict[str, list[Any]] = {}
    disabled_by_ref: dict[str, list[Any]] = {}
    documents_scanned = 0
    documents_considered = 0
    documents_without_identity = 0

    for doc in (documents or []):
        documents_scanned += 1
        identity = extract_connector_source_identity(doc)
        if identity.get("connector_id") != normalized_connector_id:
            continue
        doc_config_id = str(identity.get("config_id") or "").strip() or None
        if normalized_config_id and doc_config_id not in {normalized_config_id, None}:
            continue
        documents_considered += 1
        if normalized_config_id and doc_config_id is None:
            documents_without_identity += 1
            continue

        source_ref = str(identity.get("source_ref") or identity.get("source_id") or "").strip()
        if not source_ref:
            documents_without_identity += 1
            continue
        bucket = disabled_by_ref if getattr(doc, "disabled_at", None) is not None else active_by_ref
        bucket.setdefault(source_ref, []).append(doc)

    stale_refs = sorted(ref for ref in active_by_ref if ref not in desired_set)
    reenable_refs = sorted(ref for ref in desired_set if ref in disabled_by_ref and ref not in active_by_ref)
    missing_refs = sorted(ref for ref in desired_set if ref not in active_by_ref and ref not in disabled_by_ref)

    disabled_documents = 0
    reenabled_documents = 0
    if apply:
        for ref in stale_refs:
            for doc in active_by_ref.get(ref, []):
                if getattr(doc, "disabled_at", None) is None:
                    doc.disabled_at = now_dt
                    disabled_documents += 1
        for ref in reenable_refs:
            for doc in disabled_by_ref.get(ref, []):
                if getattr(doc, "disabled_at", None) is not None:
                    doc.disabled_at = None
                    reenabled_documents += 1

    return {
        "schema": CONNECTOR_RECONCILE_SCHEMA_V1,
        "generated_at": now_dt.isoformat(),
        "connector_id": normalized_connector_id,
        "config_id": normalized_config_id,
        "dataset_id": str(dataset_id or "").strip() or None,
        "apply": bool(apply),
        "documents_scanned": int(documents_scanned),
        "documents_considered": int(documents_considered),
        "documents_without_identity": int(documents_without_identity),
        "desired_source_refs": int(len(desired_set)),
        "active_source_refs": int(len(active_by_ref)),
        "disabled_source_refs": int(len(disabled_by_ref)),
        "stale_source_refs": int(len(stale_refs)),
        "stale_source_refs_sample": list(stale_refs[:limit]),
        "reenable_source_refs": int(len(reenable_refs)),
        "reenable_source_refs_sample": list(reenable_refs[:limit]),
        "missing_source_refs": int(len(missing_refs)),
        "missing_source_refs_sample": list(missing_refs[:limit]),
        "disabled_documents": int(disabled_documents),
        "reenabled_documents": int(reenabled_documents),
    }


__all__ = [
    "CONNECTOR_RECONCILE_SCHEMA_V1",
    "extract_connector_source_identity",
    "plan_connector_reconcile",
    "resolve_connector_reconcile_source_refs",
]
