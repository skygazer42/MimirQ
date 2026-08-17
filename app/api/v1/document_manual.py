
import asyncio
import contextlib
import importlib
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.document import DocumentDetail, ManualDocumentCreate
from app.core.config import settings
from app.core.database import SessionLocal, get_db
from app.models.dataset import Dataset
from app.models.document import Document as DBDocument
from app.services.indexer import Indexer
from app.types.indexing import IndexKind, IndexRecord

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)


def _documents_module() -> Any:
    return importlib.import_module("app.api.v1.documents")


def _build_manual_document_metadata(
    *,
    docs_mod: Any,
    request: ManualDocumentCreate,
) -> tuple[dict[str, Any], Any]:
    pipeline_options = docs_mod._to_pipeline_options(pipeline=request.pipeline)
    doc_metadata = dict(request.metadata or {})
    docs_mod.upsert_pipeline_metadata(doc_metadata, options=pipeline_options)
    doc_metadata.setdefault("parser_backend", "manual")
    doc_metadata.setdefault("chunk_strategy", "manual")
    doc_metadata.setdefault("parser_backend_requested", "manual")
    doc_metadata.setdefault("chunk_strategy_requested", "manual")
    pipeline_hash = docs_mod._compute_pipeline_hash(doc_metadata)
    doc_metadata.setdefault("pipeline_hash", pipeline_hash)
    doc_metadata.setdefault("active_pipeline_hash", doc_metadata.get("pipeline_hash") or pipeline_hash)
    doc_metadata.setdefault("active_pipeline_ready", False)
    return doc_metadata, pipeline_options


def _run_manual_kg_extraction(
    *,
    docs_mod: Any,
    document_id: UUID,
    tenant_id: UUID,
    account_id: str,
    chunk_ids: list[UUID],
    db_chunks: list[Any],
    index_options: Any,
) -> None:
    prompt_template_id = None
    raw_template_id = (getattr(settings, "KG_EXTRACT_PROMPT_TEMPLATE_ID", "") or "").strip()
    if raw_template_id:
        try:
            prompt_template_id = UUID(raw_template_id)
        except ValueError:
            docs_mod.logger.warning(
                "Invalid KG_EXTRACT_PROMPT_TEMPLATE_ID: %s",
                raw_template_id[:50],
            )

    try:
        asyncio.run(
            docs_mod.extract_events(
                chunk_ids=chunk_ids,
                tenant_id=tenant_id,
                chunks=db_chunks,
                index_options=index_options,
                prompt_template_id=prompt_template_id,
                prompt_template_key=(getattr(settings, "KG_EXTRACT_PROMPT_TEMPLATE_KEY", "") or "").strip() or None,
                prompt_ab_experiment_key=(
                    getattr(settings, "KG_EXTRACT_PROMPT_AB_EXPERIMENT_KEY", "") or ""
                ).strip()
                or None,
                ab_user_key=account_id,
            )
        )
    except Exception as exc:  # noqa: BLE001
        docs_mod.logger.warning(
            "KG extraction failed for document %s: %s",
            document_id,
            str(exc)[:200],
        )


def _manual_chunk_metadata(
    *,
    request: ManualDocumentCreate,
    dataset: Dataset,
    db_document: DBDocument,
    chunk: Any,
    chunk_index: int,
) -> dict[str, Any]:
    pipeline_hash = str((db_document.doc_metadata or {}).get("pipeline_hash") or "").strip()
    return {
        "source": request.filename,
        "file_type": request.file_type.lower(),
        "dataset_id": str(dataset.id),
        "page": chunk.page_number,
        "document_id": str(db_document.id),
        "chunk_index": chunk_index,
        "pipeline_hash": pipeline_hash,
        "doc_pipeline_key": f"{db_document.id}:{pipeline_hash}" if pipeline_hash else str(db_document.id),
        **(chunk.metadata or {}),
    }


def _populate_manual_existing_image_metadata(*, docs_mod: Any, content: str, metadata: dict[str, Any]) -> None:
    if not settings.MINIO_ENABLED or metadata.get("img_id") or metadata.get("image_id"):
        return
    match = docs_mod.MINIO_IMAGE_REF_RE.search(content)
    if not match:
        return
    maybe_id = (match.group(1) or "").strip()
    if maybe_id:
        metadata["img_id"] = maybe_id


def _append_manual_chunk_record(
    *,
    records: list[IndexRecord],
    db_document: DBDocument,
    chunk: Any,
    content: str,
    metadata: dict[str, Any],
) -> None:
    records.append(
        IndexRecord(
            kind=IndexKind.CHUNK,
            content=content,
            metadata=metadata,
            document_id=db_document.id,
            page_number=chunk.page_number,
            start_char=chunk.start_char,
            end_char=chunk.end_char,
        )
    )


def _merge_manual_document_image_ids(*, db_document: DBDocument, document_img_ids: set[str]) -> None:
    if not settings.MINIO_ENABLED or not document_img_ids:
        return
    meta = dict(db_document.doc_metadata or {})
    existing = meta.get("img_ids")
    merged: set[str] = set()
    if isinstance(existing, list):
        merged |= {value for value in existing if isinstance(value, str) and value.strip()}
    merged |= {value for value in document_img_ids if isinstance(value, str) and value.strip()}
    meta["img_ids"] = sorted(merged)
    meta["image_count"] = len(merged)
    db_document.doc_metadata = meta


def _require_manual_chunk_persist_result(persist_result: Any) -> Any:
    if persist_result is None:
        raise RuntimeError("Chunk indexing returned no result")
    if not persist_result.chunk_ids:
        raise RuntimeError("No chunks were indexed")
    if not persist_result.db_chunks:
        raise RuntimeError("Database chunks were not persisted")
    return persist_result


def _index_manual_document_chunks(
    *,
    db: Session,
    docs_mod: Any,
    request: ManualDocumentCreate,
    tenant_id: UUID,
    account_id: str,
    dataset: Dataset,
    db_document: DBDocument,
) -> None:
    pipeline_options = docs_mod._to_pipeline_options(pipeline=request.pipeline)
    pipeline_effective = docs_mod.resolve_pipeline_effective(
        dataset_metadata=(getattr(dataset, "dataset_metadata", None) or {}),
        document_metadata=dict(db_document.doc_metadata or {}),
        request_overrides=pipeline_options,
    )
    index_options = docs_mod.build_indexing_options(pipeline_effective)

    db_document.status = "processing"
    db_document.processing_attempts = int(getattr(db_document, "processing_attempts", 0) or 0) + 1
    db_document.processing_progress = 10
    db_document.current_stage = "embedding"
    db_document.failed_stage = None
    db_document.error_code = None
    db_document.error_message = None
    db.commit()
    db.refresh(db_document)

    images_dir = Path(settings.UPLOAD_DIR) / str(tenant_id) / "images"
    local_id_to_img_id: dict[str, str] = {}
    digest_to_img_id: dict[str, str] = {}
    asset_index = 0
    document_img_ids: set[str] = set()

    records: list[IndexRecord] = []
    for idx, chunk in enumerate(request.chunks):
        content = chunk.content or ""
        metadata = _manual_chunk_metadata(
            request=request,
            dataset=dataset,
            db_document=db_document,
            chunk=chunk,
            chunk_index=idx,
        )
        _populate_manual_existing_image_metadata(docs_mod=docs_mod, content=content, metadata=metadata)

        content, img_ids, asset_index = docs_mod._rewrite_preview_images_to_minio(
            content,
            tenant_id=str(tenant_id),
            dataset_id=str(dataset.id),
            document_id=str(db_document.id),
            account_id=str(account_id),
            images_dir=images_dir,
            local_id_to_img_id=local_id_to_img_id,
            digest_to_img_id=digest_to_img_id,
            db=db,
            start_index=asset_index,
        )
        if img_ids:
            document_img_ids.update(img_ids)
            metadata.setdefault("img_id", img_ids[0])
            metadata.setdefault("img_ids", img_ids)
            metadata.setdefault("image_count", len(img_ids))

        _append_manual_chunk_record(
            records=records,
            db_document=db_document,
            chunk=chunk,
            content=content,
            metadata=metadata,
        )

    _merge_manual_document_image_ids(db_document=db_document, document_img_ids=document_img_ids)

    persist_result = _require_manual_chunk_persist_result(
        Indexer(db).upsert(
            tenant_id=tenant_id,
            records=records,
            default_source=request.filename,
            options=index_options,
            commit=False,
        ).chunk_result
    )

    db_document.chunk_count = len(request.chunks)
    db_document.total_characters = persist_result.total_characters
    db_document.status = "completed"
    db_document.processing_progress = 100
    db_document.current_stage = "completed"
    db_document.processed_at = datetime.now(UTC)
    meta = dict(db_document.doc_metadata or {})
    if meta.get("active_pipeline_hash") and meta.get("pipeline_hash"):
        meta["active_pipeline_hash"] = meta.get("pipeline_hash")
    meta["active_pipeline_ready"] = True
    try:
        from app.services.chunking_stats_utils import compute_chunking_stats_from_texts

        stats = compute_chunking_stats_from_texts((chunk.content or "") for chunk in (request.chunks or []))
        if stats:
            meta["chunking_stats"] = stats
    except Exception as exc:  # noqa: BLE001
        docs_mod.logger.debug(
            "Failed computing chunking stats for manual document %s: %s",
            db_document.id,
            str(exc)[:200],
        )
    db_document.doc_metadata = meta
    db.commit()
    db.refresh(db_document)

    if pipeline_effective.kg_enabled:
        _run_manual_kg_extraction(
            docs_mod=docs_mod,
            document_id=db_document.id,
            tenant_id=tenant_id,
            account_id=account_id,
            chunk_ids=persist_result.chunk_ids,
            db_chunks=persist_result.db_chunks,
            index_options=index_options,
        )


def _mark_manual_document_failed(
    *,
    db: Session,
    tenant_id: UUID,
    document_id: UUID,
    error: Exception,
) -> None:
    db.rollback()
    with contextlib.suppress(Exception):
        Indexer(db).delete_chunk_indexes(tenant_id=tenant_id, document_id=document_id)

    db_document = (
        db.query(DBDocument)
        .filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id)
        .first()
    )
    if not db_document:
        return
    if str(db_document.status or "").lower() == "cancelled":
        return

    db_document.status = "failed"
    db_document.processing_progress = 0
    db_document.current_stage = "failed"
    db_document.failed_stage = "embedding"
    db_document.error_code = "manual_ingest_failed"
    db_document.error_message = str(error)[:2000]
    db.commit()
    db.refresh(db_document)


def _process_manual_document_chunks_background(
    document_id: UUID,
    tenant_id: UUID,
    account_id: str,
    request_payload: dict[str, Any],
) -> None:
    docs_mod = _documents_module()
    db = SessionLocal()
    try:
        request = ManualDocumentCreate.model_validate(request_payload)
        db_document = (
            db.query(DBDocument)
            .filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id)
            .first()
        )
        if not db_document:
            return
        if str(db_document.status or "").lower() == "cancelled":
            return

        dataset = docs_mod.DatasetService.get_dataset(db, tenant_id, db_document.dataset_id)
        docs_mod.DatasetService.assert_dataset_writable(db, dataset, account_id)
        _index_manual_document_chunks(
            db=db,
            docs_mod=docs_mod,
            request=request,
            tenant_id=tenant_id,
            account_id=account_id,
            dataset=dataset,
            db_document=db_document,
        )
    except Exception as exc:  # noqa: BLE001
        docs_mod.logger.exception(
            "Manual document background indexing failed for document %s: %s",
            document_id,
            str(exc)[:200],
        )
        _mark_manual_document_failed(
            db=db,
            tenant_id=tenant_id,
            document_id=document_id,
            error=exc,
        )
    finally:
        db.close()


@router.post("/manual", response_model=DocumentDetail, status_code=201, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def create_document_with_manual_chunks(
    request: ManualDocumentCreate,
    background_tasks: BackgroundTasks,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Create a document from frontend custom chunks.
    """
    docs_mod = _documents_module()
    dataset = docs_mod._resolve_writable_dataset(db, tenant_id, account_id, request.dataset_id)

    if not request.chunks:
        raise HTTPException(status_code=400, detail="Chunks cannot be empty")

    file_type_with_dot = f".{request.file_type.lower()}"
    if file_type_with_dot not in settings.allowed_extensions_list:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {request.file_type}")

    document_id = uuid.uuid4()
    doc_metadata, pipeline_options = _build_manual_document_metadata(docs_mod=docs_mod, request=request)
    pipeline_effective = docs_mod.resolve_pipeline_effective(
        dataset_metadata=(getattr(dataset, "dataset_metadata", None) or {}),
        document_metadata={},
        request_overrides=pipeline_options,
    )
    docs_mod.build_indexing_options(pipeline_effective)

    db_document = DBDocument(
        id=document_id,
        tenant_id=tenant_id,
        dataset_id=dataset.id,
        filename=request.filename,
        file_type=request.file_type.lower(),
        file_size=request.file_size,
        file_path=f"{docs_mod.MANUAL_FILE_PATH_PREFIX}{document_id}",
        owner_id=account_id,
        access_mode=None,
        status="processing",
        processing_progress=1,
        current_stage="queued",
        chunk_count=0,
        total_characters=0,
        doc_metadata=doc_metadata,
    )

    db.add(db_document)
    db.commit()
    db.refresh(db_document)

    background_tasks.add_task(
        _process_manual_document_chunks_background,
        document_id,
        tenant_id,
        account_id,
        request.model_dump(mode="json"),
    )
    return db_document
