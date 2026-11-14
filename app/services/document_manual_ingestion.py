"""Manual document creation and background indexing operations."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy.orm import Session

from app.api.schemas.documents import ManualChunkCreate, ManualDocumentCreate
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.dataset import Dataset
from app.models.document import Document as DBDocument
from app.models.document import DocumentChunk
from app.rag.core.logging import get_logger
from app.rag.kg.pipeline import extract_events
from app.services import dataset_service
from app.services.chunking_stats_utils import compute_chunking_stats_from_texts
from app.services.document_identity import compute_pipeline_hash
from app.services.document_lifecycle_service import MANUAL_FILE_PATH_PREFIX
from app.services.document_preview_utils import MINIO_IMAGE_REF_RE, _rewrite_preview_images_to_minio
from app.services.indexer import Indexer
from app.services.pipeline_config import build_indexing_options, resolve_pipeline_effective, upsert_pipeline_metadata
from app.types.indexing import IndexingOptions, IndexKind, IndexRecord, PersistChunksResult
from app.types.pipeline import PipelineOptions

logger = get_logger("services.document_manual_ingestion")


def _pipeline_options(request: ManualDocumentCreate) -> PipelineOptions:
    if request.pipeline is None:
        return PipelineOptions()
    return PipelineOptions(**request.pipeline.model_dump(exclude_none=True))


def _build_manual_document_metadata(request: ManualDocumentCreate) -> tuple[dict[str, Any], PipelineOptions]:
    pipeline_options = _pipeline_options(request)
    metadata = dict(request.metadata)
    upsert_pipeline_metadata(metadata, options=pipeline_options)
    metadata.setdefault("parser_backend", "manual")
    metadata.setdefault("chunk_strategy", "manual")
    metadata.setdefault("parser_backend_requested", "manual")
    metadata.setdefault("chunk_strategy_requested", "manual")
    pipeline_hash = compute_pipeline_hash(metadata)
    metadata.setdefault("pipeline_hash", pipeline_hash)
    metadata.setdefault("active_pipeline_hash", metadata.get("pipeline_hash") or pipeline_hash)
    metadata.setdefault("active_pipeline_ready", False)
    return metadata, pipeline_options


def _run_manual_kg_extraction(
    *,
    document_id: UUID,
    tenant_id: UUID,
    account_id: str,
    chunk_ids: list[UUID],
    db_chunks: list[DocumentChunk],
    index_options: IndexingOptions,
) -> None:
    prompt_template_id = None
    raw_template_id = settings.KG_EXTRACT_PROMPT_TEMPLATE_ID.strip()
    if raw_template_id:
        try:
            prompt_template_id = UUID(raw_template_id)
        except ValueError:
            logger.warning("Invalid KG_EXTRACT_PROMPT_TEMPLATE_ID: %s", raw_template_id[:50])

    try:
        asyncio.run(
            extract_events(
                chunk_ids=chunk_ids,
                tenant_id=tenant_id,
                chunks=db_chunks,
                index_options=index_options,
                prompt_template_id=prompt_template_id,
                prompt_template_key=settings.KG_EXTRACT_PROMPT_TEMPLATE_KEY,
                prompt_ab_experiment_key=settings.KG_EXTRACT_PROMPT_AB_EXPERIMENT_KEY,
                ab_user_key=account_id,
            )
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("KG extraction failed for document %s: %s", document_id, str(exc)[:200])


def _manual_chunk_metadata(
    *,
    request: ManualDocumentCreate,
    dataset: Dataset,
    document: DBDocument,
    chunk: ManualChunkCreate,
    chunk_index: int,
) -> dict[str, Any]:
    pipeline_hash = (document.doc_metadata or {}).get("pipeline_hash")
    if pipeline_hash is not None:
        pipeline_hash = pipeline_hash.strip()
    return {
        "source": request.filename,
        "file_type": request.file_type.lower(),
        "dataset_id": str(dataset.id),
        "page": chunk.page_number,
        "document_id": str(document.id),
        "chunk_index": chunk_index,
        "pipeline_hash": pipeline_hash,
        "doc_pipeline_key": f"{document.id}:{pipeline_hash}" if pipeline_hash else str(document.id),
        **chunk.metadata,
    }


def _populate_manual_existing_image_metadata(content: str, metadata: dict[str, Any]) -> None:
    if not settings.MINIO_ENABLED or metadata.get("img_id") or metadata.get("image_id"):
        return
    match = MINIO_IMAGE_REF_RE.search(content)
    if match and match.group(1):
        metadata["img_id"] = match.group(1).strip()


def _merge_manual_document_image_ids(document: DBDocument, image_ids: set[str]) -> None:
    if not settings.MINIO_ENABLED or not image_ids:
        return
    metadata = dict(document.doc_metadata or {})
    existing_ids = metadata.get("img_ids")
    merged_ids = (
        {value for value in existing_ids if isinstance(value, str) and value.strip()}
        if isinstance(existing_ids, list)
        else set()
    )
    merged_ids.update(image_ids)
    metadata["img_ids"] = sorted(merged_ids)
    metadata["image_count"] = len(merged_ids)
    document.doc_metadata = metadata


def _require_manual_chunk_persist_result(result: PersistChunksResult | None) -> PersistChunksResult:
    if result is None:
        raise RuntimeError("Chunk indexing returned no result")
    if not result.chunk_ids:
        raise RuntimeError("No chunks were indexed")
    if not result.db_chunks:
        raise RuntimeError("Database chunks were not persisted")
    return result


def _index_manual_document_chunks(
    *,
    db: Session,
    request: ManualDocumentCreate,
    tenant_id: UUID,
    account_id: str,
    dataset: Dataset,
    document: DBDocument,
) -> None:
    pipeline_options = _pipeline_options(request)
    pipeline_effective = resolve_pipeline_effective(
        dataset_metadata=dataset.dataset_metadata or {},
        document_metadata=document.doc_metadata or {},
        request_overrides=pipeline_options,
    )
    index_options = build_indexing_options(pipeline_effective)

    document.status = "processing"
    document.processing_attempts = (document.processing_attempts or 0) + 1
    document.processing_progress = 10
    document.current_stage = "embedding"
    document.failed_stage = None
    document.error_code = None
    document.error_message = None
    db.commit()
    db.refresh(document)

    images_dir = Path(settings.UPLOAD_DIR) / str(tenant_id) / "images"
    local_id_to_img_id: dict[str, str] = {}
    digest_to_img_id: dict[str, str] = {}
    asset_index = 0
    document_image_ids: set[str] = set()
    records: list[IndexRecord] = []

    for chunk_index, chunk in enumerate(request.chunks):
        content = chunk.content
        metadata = _manual_chunk_metadata(
            request=request,
            dataset=dataset,
            document=document,
            chunk=chunk,
            chunk_index=chunk_index,
        )
        _populate_manual_existing_image_metadata(content, metadata)
        content, image_ids, asset_index = _rewrite_preview_images_to_minio(
            content,
            tenant_id=str(tenant_id),
            dataset_id=str(dataset.id),
            document_id=str(document.id),
            account_id=account_id,
            images_dir=images_dir,
            local_id_to_img_id=local_id_to_img_id,
            digest_to_img_id=digest_to_img_id,
            db=db,
            start_index=asset_index,
        )
        if image_ids:
            document_image_ids.update(image_ids)
            metadata.setdefault("img_id", image_ids[0])
            metadata.setdefault("img_ids", image_ids)
            metadata.setdefault("image_count", len(image_ids))
        records.append(
            IndexRecord(
                kind=IndexKind.CHUNK,
                content=content,
                metadata=metadata,
                document_id=document.id,
                page_number=chunk.page_number,
                start_char=chunk.start_char,
                end_char=chunk.end_char,
            )
        )

    _merge_manual_document_image_ids(document, document_image_ids)
    persist_result = _require_manual_chunk_persist_result(
        Indexer(db)
        .upsert(
            tenant_id=tenant_id,
            records=records,
            default_source=request.filename,
            options=index_options,
            commit=False,
        )
        .chunk_result
    )

    document.chunk_count = len(request.chunks)
    document.total_characters = persist_result.total_characters
    document.status = "completed"
    document.processing_progress = 100
    document.current_stage = "completed"
    document.processed_at = datetime.now(UTC)
    metadata = dict(document.doc_metadata or {})
    if metadata.get("active_pipeline_hash") and metadata.get("pipeline_hash"):
        metadata["active_pipeline_hash"] = metadata["pipeline_hash"]
    metadata["active_pipeline_ready"] = True
    try:
        stats = compute_chunking_stats_from_texts(chunk.content for chunk in request.chunks)
        if stats:
            metadata["chunking_stats"] = stats
    except Exception as exc:  # noqa: BLE001
        logger.debug("Failed computing chunking stats for manual document %s: %s", document.id, str(exc)[:200])
    document.doc_metadata = metadata
    db.commit()
    db.refresh(document)

    if pipeline_effective.kg_enabled:
        _run_manual_kg_extraction(
            document_id=document.id,
            tenant_id=tenant_id,
            account_id=account_id,
            chunk_ids=persist_result.chunk_ids,
            db_chunks=persist_result.db_chunks,
            index_options=index_options,
        )


def _mark_manual_document_failed(*, db: Session, tenant_id: UUID, document_id: UUID, error: Exception) -> None:
    db.rollback()
    try:
        Indexer(db).delete_chunk_indexes(tenant_id=tenant_id, document_id=document_id)
    except Exception:
        logger.warning("Failed removing partial indexes for manual document %s", document_id, exc_info=True)

    document = db.query(DBDocument).filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id).first()
    if document is None or document.status == "cancelled":
        return

    document.status = "failed"
    document.processing_progress = 0
    document.current_stage = "failed"
    document.failed_stage = "embedding"
    document.error_code = "manual_ingest_failed"
    document.error_message = str(error)[:2000]
    db.commit()
    db.refresh(document)


def process_manual_chunks(
    document_id: UUID,
    tenant_id: UUID,
    account_id: str,
    request_payload: dict[str, Any],
) -> None:
    db = SessionLocal()
    try:
        request = ManualDocumentCreate.model_validate(request_payload)
        document = db.query(DBDocument).filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id).first()
        if document is None or document.status == "cancelled":
            return

        dataset = dataset_service.get_dataset(db, tenant_id, document.dataset_id)
        dataset_service.assert_dataset_writable(db, dataset, account_id)
        _index_manual_document_chunks(
            db=db,
            request=request,
            tenant_id=tenant_id,
            account_id=account_id,
            dataset=dataset,
            document=document,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Manual document background indexing failed for document %s", document_id)
        _mark_manual_document_failed(db=db, tenant_id=tenant_id, document_id=document_id, error=exc)
    finally:
        db.close()


def create_manual_document(
    *,
    request: ManualDocumentCreate,
    background_tasks: BackgroundTasks,
    db: Session,
    tenant_id: UUID,
    account_id: str,
) -> DBDocument:
    dataset = dataset_service.resolve_writable_dataset(db, tenant_id, account_id, request.dataset_id)
    if not request.chunks:
        raise HTTPException(status_code=400, detail="Chunks cannot be empty")

    file_type = request.file_type.lower()
    if f".{file_type}" not in settings.allowed_extensions_list:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {request.file_type}")

    document_id = uuid4()
    metadata, pipeline_options = _build_manual_document_metadata(request)
    effective = resolve_pipeline_effective(
        dataset_metadata=dataset.dataset_metadata or {},
        document_metadata={},
        request_overrides=pipeline_options,
    )
    build_indexing_options(effective)

    document = DBDocument(
        id=document_id,
        tenant_id=tenant_id,
        dataset_id=dataset.id,
        filename=request.filename,
        file_type=file_type,
        file_size=request.file_size,
        file_path=f"{MANUAL_FILE_PATH_PREFIX}{document_id}",
        owner_id=account_id,
        access_mode=None,
        status="processing",
        processing_progress=1,
        current_stage="queued",
        chunk_count=0,
        total_characters=0,
        doc_metadata=metadata,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    background_tasks.add_task(
        process_manual_chunks,
        document_id,
        tenant_id,
        account_id,
        request.model_dump(mode="json"),
    )
    return document


__all__ = ["create_manual_document", "process_manual_chunks"]
