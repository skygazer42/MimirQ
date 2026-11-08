from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, TypedDict

from app.services.connector_sync_state import normalize_source_manifest

if TYPE_CHECKING:
    from app.models.document import Document

CONNECTOR_RECONCILE_SCHEMA_V1 = "mimirq.connector_reconcile.v1"


class _ConnectorSourceIdentity(TypedDict):
    connector_id: str | None
    config_id: str | None
    source_ref: str | None
    source_id: str | None


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


def extract_connector_source_identity(doc: Document) -> _ConnectorSourceIdentity:
    meta = doc.doc_metadata
    meta_map = meta if isinstance(meta, Mapping) else {}
    connector = meta_map.get("connector") if isinstance(meta_map.get("connector"), Mapping) else {}

    connector_id = connector.get("connector_id")
    config_id = connector.get("config_id")
    source_ref = next(
        (
            connector[key]
            for key in ("source_ref", "source_id", "page_id", "issue_key", "issue_id", "issue_url")
            if key in connector
        ),
        meta_map.get("source_url"),
    )
    source_id = connector.get("source_id", source_ref)
    return {
        "connector_id": connector_id,
        "config_id": config_id,
        "source_ref": source_ref,
        "source_id": source_id,
    }


def _collect_connector_reconcile_documents(
    *,
    documents: Iterable[Document],
    connector_id: str,
    config_id: str | None,
) -> tuple[dict[str, list[Document]], dict[str, list[Document]], int, int, int]:
    active_by_ref: dict[str, list[Document]] = {}
    disabled_by_ref: dict[str, list[Document]] = {}
    documents_scanned = 0
    documents_considered = 0
    documents_without_identity = 0

    for doc in documents:
        documents_scanned += 1
        identity = extract_connector_source_identity(doc)
        if identity["connector_id"] != connector_id:
            continue
        doc_config_id = identity["config_id"]
        if config_id is not None and doc_config_id not in {config_id, None}:
            continue
        documents_considered += 1
        if config_id is not None and doc_config_id is None:
            documents_without_identity += 1
            continue

        source_ref = identity["source_ref"]
        if not source_ref:
            documents_without_identity += 1
            continue
        bucket = disabled_by_ref if doc.disabled_at is not None else active_by_ref
        bucket.setdefault(source_ref, []).append(doc)

    return active_by_ref, disabled_by_ref, documents_scanned, documents_considered, documents_without_identity


def _apply_connector_reconcile_changes(
    *,
    apply: bool,
    now_dt: datetime,
    active_by_ref: dict[str, list[Document]],
    disabled_by_ref: dict[str, list[Document]],
    stale_refs: list[str],
    reenable_refs: list[str],
) -> tuple[int, int]:
    disabled_documents = 0
    reenabled_documents = 0
    if not apply:
        return disabled_documents, reenabled_documents

    for ref in stale_refs:
        for doc in active_by_ref.get(ref, []):
            if doc.disabled_at is None:
                doc.disabled_at = now_dt
                disabled_documents += 1
    for ref in reenable_refs:
        for doc in disabled_by_ref.get(ref, []):
            if doc.disabled_at is not None:
                doc.disabled_at = None
                reenabled_documents += 1
    return disabled_documents, reenabled_documents


def plan_connector_reconcile(
    *,
    connector_id: str,
    config_id: str | None,
    dataset_id: str | None,
    documents: Iterable[Document],
    desired_source_refs: list[str],
    apply: bool,
    now: datetime | None = None,
    sample_limit: int = 20,
) -> dict[str, Any]:
    now_dt = now or _now_utc()
    normalized_connector_id = connector_id.strip()
    normalized_config_id = config_id
    desired_refs = _normalize_refs(desired_source_refs)
    desired_set = set(desired_refs)
    limit = max(1, int(sample_limit or 0))

    active_by_ref, disabled_by_ref, documents_scanned, documents_considered, documents_without_identity = (
        _collect_connector_reconcile_documents(
            documents=documents,
            connector_id=normalized_connector_id,
            config_id=normalized_config_id,
        )
    )

    stale_refs = sorted(ref for ref in active_by_ref if ref not in desired_set)
    reenable_refs = sorted(ref for ref in desired_set if ref in disabled_by_ref and ref not in active_by_ref)
    missing_refs = sorted(ref for ref in desired_set if ref not in active_by_ref and ref not in disabled_by_ref)

    disabled_documents, reenabled_documents = _apply_connector_reconcile_changes(
        apply=apply,
        now_dt=now_dt,
        active_by_ref=active_by_ref,
        disabled_by_ref=disabled_by_ref,
        stale_refs=stale_refs,
        reenable_refs=reenable_refs,
    )

    return {
        "schema": CONNECTOR_RECONCILE_SCHEMA_V1,
        "generated_at": now_dt.isoformat(),
        "connector_id": normalized_connector_id,
        "config_id": normalized_config_id,
        "dataset_id": dataset_id,
        "apply": apply,
        "documents_scanned": documents_scanned,
        "documents_considered": documents_considered,
        "documents_without_identity": documents_without_identity,
        "desired_source_refs": len(desired_set),
        "active_source_refs": len(active_by_ref),
        "disabled_source_refs": len(disabled_by_ref),
        "stale_source_refs": len(stale_refs),
        "stale_source_refs_sample": stale_refs[:limit],
        "reenable_source_refs": len(reenable_refs),
        "reenable_source_refs_sample": reenable_refs[:limit],
        "missing_source_refs": len(missing_refs),
        "missing_source_refs_sample": missing_refs[:limit],
        "disabled_documents": disabled_documents,
        "reenabled_documents": reenabled_documents,
    }


__all__ = [
    "CONNECTOR_RECONCILE_SCHEMA_V1",
    "extract_connector_source_identity",
    "plan_connector_reconcile",
    "resolve_connector_reconcile_source_refs",
]
