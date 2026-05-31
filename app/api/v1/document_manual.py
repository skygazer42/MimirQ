from __future__ import annotations

import contextlib
import importlib
import uuid
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.document import DocumentDetail, ManualDocumentCreate
from app.core.config import settings
from app.core.database import get_db
from app.models.document import Document as DBDocument
from app.services.document_preview_utils import DATA_IMAGE_PREFIX, MINIO_IMAGE_REF_RE, PREVIEW_IMAGE_REF_RE
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


def _rewrite_preview_images_to_minio(
    content: str,
    *,
    tenant_id: str,
    dataset_id: str,
    document_id: str,
    images_dir: Path,
    local_id_to_img_id: dict[str, str],
    digest_to_img_id: dict[str, str],
    start_index: int,
) -> tuple[str, list[str], int]:
    """
    Preserve existing preview image refs for manual chunks.

    Manual chunk creation consumes content emitted by `/documents/preview`, which
    may already contain preview-time `/api/v1/documents/image/{id}` refs or
    `data:image` content. The legacy helper name is still used by this module,
    but after router splitting the implementation was no longer re-exported.

    For now, keep manual content stable and avoid a hard failure:
    - existing MinIO refs are passed through untouched
    - preview refs / data URIs are also left untouched

    This is sufficient for current manual-upload flows because the API should not
    500 when preview content contains images; MinIO-backed image normalization can
    be added later without changing this call site.
    """
    del tenant_id, dataset_id, document_id, images_dir, local_id_to_img_id, digest_to_img_id

    if not isinstance(content, str) or not content:
        return content, [], start_index
    if MINIO_IMAGE_REF_RE.search(content) or PREVIEW_IMAGE_REF_RE.search(content) or DATA_IMAGE_PREFIX in content.lower():
        return content, [], start_index
    return content, [], start_index


@router.post("/manual", response_model=DocumentDetail, status_code=201, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def create_document_with_manual_chunks(
    request: ManualDocumentCreate,
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
    pipeline_options = docs_mod._to_pipeline_options(pipeline=request.pipeline)
    pipeline_effective = docs_mod.resolve_pipeline_effective(
        dataset_metadata=(getattr(dataset, "dataset_metadata", None) or {}),
        document_metadata={},
        request_overrides=pipeline_options,
    )
    index_options = docs_mod.build_indexing_options(pipeline_effective)

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
        processing_progress=0,
        current_stage="embedding",
        doc_metadata=doc_metadata,
    )

    db.add(db_document)
    db.flush()

    try:
        images_dir = Path(settings.UPLOAD_DIR) / str(tenant_id) / "images"
        local_id_to_img_id: dict[str, str] = {}
        digest_to_img_id: dict[str, str] = {}
        asset_index = 0
        document_img_ids: set[str] = set()

        records: list[IndexRecord] = []
        for idx, chunk in enumerate(request.chunks):
            content = chunk.content or ""
            pipeline_hash = str((db_document.doc_metadata or {}).get("pipeline_hash") or "").strip()
            metadata = {
                "source": request.filename,
                "file_type": request.file_type.lower(),
                "dataset_id": str(dataset.id),
                "page": chunk.page_number,
                "document_id": str(document_id),
                "chunk_index": idx,
                "pipeline_hash": pipeline_hash,
                "doc_pipeline_key": f"{document_id}:{pipeline_hash}" if pipeline_hash else str(document_id),
                **(chunk.metadata or {}),
            }

            if settings.MINIO_ENABLED:
                if not (metadata.get("img_id") or metadata.get("image_id")):
                    match = docs_mod.MINIO_IMAGE_REF_RE.search(content)
                    if match:
                        maybe_id = (match.group(1) or "").strip()
                        if maybe_id:
                            metadata["img_id"] = maybe_id

                content, img_ids, asset_index = _rewrite_preview_images_to_minio(
                    content,
                    tenant_id=str(tenant_id),
                    dataset_id=str(dataset.id),
                    document_id=str(document_id),
                    images_dir=images_dir,
                    local_id_to_img_id=local_id_to_img_id,
                    digest_to_img_id=digest_to_img_id,
                    start_index=asset_index,
                )
                if img_ids:
                    document_img_ids.update(img_ids)
                    metadata.setdefault("img_id", img_ids[0])
                    metadata.setdefault("img_ids", img_ids)
                    metadata.setdefault("image_count", len(img_ids))

            records.append(
                IndexRecord(
                    kind=IndexKind.CHUNK,
                    content=content,
                    metadata=metadata,
                    document_id=document_id,
                    page_number=chunk.page_number,
                    start_char=chunk.start_char,
                    end_char=chunk.end_char,
                )
            )

        if settings.MINIO_ENABLED and document_img_ids:
            meta = dict(db_document.doc_metadata or {})
            existing = meta.get("img_ids")
            merged: set[str] = set()
            if isinstance(existing, list):
                merged |= {value for value in existing if isinstance(value, str) and value.strip()}
            merged |= {value for value in document_img_ids if isinstance(value, str) and value.strip()}
            meta["img_ids"] = sorted(merged)
            meta["image_count"] = len(merged)
            db_document.doc_metadata = meta

        persist_result = Indexer(db).upsert(
            tenant_id=tenant_id,
            records=records,
            default_source=request.filename,
            options=index_options,
            commit=False,
        ).chunk_result
        if persist_result is None:
            raise RuntimeError("Chunk indexing returned no result")
        if not persist_result.chunk_ids:
            raise RuntimeError("No chunks were indexed")
        if not persist_result.db_chunks:
            raise RuntimeError("Database chunks were not persisted")

        db_document.chunk_count = len(request.chunks)
        db_document.total_characters = persist_result.total_characters
        db_document.status = "completed"
        db_document.processing_progress = 100
        db_document.current_stage = "completed"
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
                document_id,
                str(exc)[:200],
            )
        db_document.doc_metadata = meta
        db.commit()
        db.refresh(db_document)

        if pipeline_effective.kg_enabled:
            try:
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
                await docs_mod.extract_events(
                    chunk_ids=persist_result.chunk_ids,
                    tenant_id=tenant_id,
                    chunks=persist_result.db_chunks,
                    index_options=index_options,
                    prompt_template_id=prompt_template_id,
                    prompt_template_key=(getattr(settings, "KG_EXTRACT_PROMPT_TEMPLATE_KEY", "") or "").strip() or None,
                    prompt_ab_experiment_key=(
                        getattr(settings, "KG_EXTRACT_PROMPT_AB_EXPERIMENT_KEY", "") or ""
                    ).strip()
                    or None,
                    ab_user_key=account_id,
                )
            except Exception as exc:  # noqa: BLE001
                docs_mod.logger.warning(
                    "KG extraction failed for document %s: %s",
                    document_id,
                    str(exc)[:200],
                )

        return db_document

    except Exception as exc:  # noqa: BLE001
        db.rollback()
        with contextlib.suppress(Exception):
            Indexer(db).delete_chunk_indexes(tenant_id=tenant_id, document_id=document_id)
        db_document.status = "failed"
        db_document.processing_progress = 0
        db_document.current_stage = "failed"
        db_document.error_message = str(exc)
        db.commit()
        db.refresh(db_document)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create document with manual chunks: {str(exc)}",
        ) from exc
