import json
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.connector import ConnectorRun, ConnectorRunDocument
from app.models.document import Document as DBDocument
from app.services.connector_execution.shared.common import _connector_config_id_from_run
from app.services.connector_execution.shared.runtime import _now


def _apply_connector_identity_metadata(
    *,
    doc: DBDocument,
    run: ConnectorRun,
    connector_id: str,
    source_ref: str | None,
    source_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    meta0 = dict(doc.doc_metadata or {})
    connector_meta = dict(meta0.get("connector") or {})
    if isinstance(extra, dict):
        connector_meta.update({key: value for key, value in extra.items() if value is not None})

    connector_meta["connector_id"] = connector_id.strip()
    connector_meta["run_id"] = str(run.id)
    if run.dataset_id is not None:
        connector_meta["dataset_id"] = str(run.dataset_id)

    config_id = _connector_config_id_from_run(run)
    if config_id:
        connector_meta["config_id"] = config_id

    source_ref_norm = source_ref.strip()[:1000] if source_ref is not None else None
    source_id_norm = source_id.strip()[:1000] if source_id is not None else source_ref_norm
    if source_ref_norm is not None:
        connector_meta["source_ref"] = source_ref_norm
    if source_id_norm is not None:
        connector_meta["source_id"] = source_id_norm

    meta0["connector"] = connector_meta
    doc.doc_metadata = meta0


def _normalize_connector_string_list(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(value or "").strip() for value in values if str(value or "").strip()]


def _normalize_connector_principal_list(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(value).strip() for value in values if isinstance(value, (str, int, float)) and str(value).strip()]


def _db_row_sidecar_file_path(
    *,
    dataset_id: UUID,
    connector_id: str,
    connector_config_id: UUID | str | None = None,
) -> str:
    config_suffix = str(connector_config_id or "").strip()
    if config_suffix:
        return f"virtual://db_catalog/rows/{str(dataset_id)}/{str(connector_id or '').strip()}/{config_suffix}"
    return f"virtual://db_catalog/rows/{str(dataset_id)}/{str(connector_id or '').strip()}"


def _db_row_sidecar_filename(
    *,
    dataset_id: UUID,
    connector_id: str,
    connector_config_id: UUID | str | None = None,
) -> str:
    ds = str(dataset_id)
    cid = str(connector_id or "").strip() or "db_catalog"
    config_suffix = str(connector_config_id or "").strip()
    if config_suffix:
        return f"db_rows_{cid}_{config_suffix}_{ds}.sqlite"
    return f"db_rows_{cid}_{ds}.sqlite"


def _build_db_row_source_manifest(snapshots: list[dict[str, Any]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for snap in snapshots or []:
        if not isinstance(snap, dict):
            continue
        source_table = str(snap.get("source_table") or "").strip()
        sync_token = str(snap.get("source_sync_token") or "").strip()
        if not source_table or not sync_token:
            continue
        out[source_table] = sync_token
    return dict(sorted(out.items(), key=lambda kv: kv[0]))


def _upsert_db_row_sidecar_document(
    *,
    db: Session,
    run: ConnectorRun,
    connector_id: str,
    requested_by: str,
    snapshots: list[dict[str, Any]],
    max_tables: int,
    max_rows_per_table: int,
    max_cols: int,
) -> dict[str, Any] | None:
    if run.dataset_id is None:
        return None
    if not snapshots:
        return None

    from app.services.table_store_service import import_db_row_snapshots

    now = _now()
    connector_config_id = _connector_config_id_from_run(run)
    file_path = _db_row_sidecar_file_path(
        dataset_id=run.dataset_id,
        connector_id=connector_id,
        connector_config_id=connector_config_id,
    )
    filename = _db_row_sidecar_filename(
        dataset_id=run.dataset_id,
        connector_id=connector_id,
        connector_config_id=connector_config_id,
    )
    source_ref = f"db_catalog_rows:{connector_id}"
    source_id = f"{connector_id}:{run.dataset_id}"
    if str(connector_config_id or "").strip():
        source_ref = f"{source_ref}:{connector_config_id}"
        source_id = f"{source_id}:{connector_config_id}"

    doc = (
        db.query(DBDocument)
        .filter(
            DBDocument.tenant_id == run.tenant_id,
            DBDocument.dataset_id == run.dataset_id,
            DBDocument.file_path == file_path,
        )
        .first()
    )
    if doc is None and connector_config_id:
        legacy_path = _db_row_sidecar_file_path(
            dataset_id=run.dataset_id,
            connector_id=connector_id,
        )
        legacy_doc = (
            db.query(DBDocument)
            .filter(
                DBDocument.tenant_id == run.tenant_id,
                DBDocument.dataset_id == run.dataset_id,
                DBDocument.file_path == legacy_path,
            )
            .first()
        )
        legacy_connector_meta = (
            dict((getattr(legacy_doc, "doc_metadata", None) or {}).get("connector") or {})
            if legacy_doc is not None
            else {}
        )
        if str(legacy_connector_meta.get("config_id") or "").strip() == str(connector_config_id):
            doc = legacy_doc
    if doc is None:
        doc = DBDocument(
            tenant_id=run.tenant_id,
            dataset_id=run.dataset_id,
            filename=filename,
            file_type="dbrows",
            file_size=0,
            file_path=file_path,
            owner_id=(requested_by),
            access_mode="inherit",
            status="completed",
            processing_progress=100,
            current_stage="completed",
            error_message=None,
            chunk_count=0,
            total_characters=0,
            doc_metadata={},
            processed_at=now,
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)

    assets = import_db_row_snapshots(
        tenant_id=run.tenant_id,
        dataset_id=run.dataset_id,
        document_id=doc.id,
        snapshots=snapshots,
        max_tables=max_tables,
        max_rows_per_table=max_rows_per_table,
        max_cols=max_cols,
        sample_rows=settings.TABLE_STORE_SAMPLE_ROWS,
    )

    tables_payload: list[dict[str, Any]] = []
    for asset in assets:
        tables_payload.append(
            {
                "table_id": asset.table_id,
                "sheet_index": asset.sheet_index,
                "sheet_name": asset.sheet_name,
                "row_count": asset.row_count,
                "col_count": asset.col_count,
                "truncated": asset.truncated,
                "columns": list(asset.columns),
                "sample_rows": list(asset.sample_rows),
                "row_source_table": asset.row_source_table,
                "row_source_sync_token": asset.row_source_sync_token,
                "row_source_pk_hash_col": asset.row_source_pk_hash_col,
            }
        )

    meta = dict(doc.doc_metadata or {})
    meta["table_store"] = {
        "version": "1",
        "source_ext": ".dbrows",
        "imported_at": now.isoformat(),
        "tables": tables_payload,
    }
    doc.filename = filename
    doc.file_type = "dbrows"
    doc.file_path = file_path
    doc.status = "completed"
    doc.processing_progress = 100
    doc.current_stage = "completed"
    doc.error_message = None
    doc.chunk_count = 0
    doc.total_characters = 0
    doc.processed_at = now
    doc.doc_metadata = meta
    _apply_connector_identity_metadata(
        doc=doc,
        run=run,
        connector_id=connector_id,
        source_ref=source_ref,
        source_id=source_id,
        extra={"doc_kind": "db_row_sidecar"},
    )
    try:
        doc.file_size = int(len(json.dumps(meta, ensure_ascii=False)))
    except Exception:
        doc.file_size = 0
    db.commit()
    db.refresh(doc)

    linked = (
        db.query(ConnectorRunDocument)
        .filter(
            ConnectorRunDocument.tenant_id == run.tenant_id,
            ConnectorRunDocument.run_id == run.id,
            ConnectorRunDocument.document_id == doc.id,
        )
        .first()
    )
    if linked is None:
        db.add(
            ConnectorRunDocument(
                tenant_id=run.tenant_id,
                run_id=run.id,
                document_id=doc.id,
                source_ref=source_ref,
                status="created",
            )
        )
        db.commit()

    return {
        "document_id": str(doc.id),
        "tables": int(len(assets)),
        "source_manifest_count": int(len(_build_db_row_source_manifest(snapshots))),
    }
