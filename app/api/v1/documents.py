"""
Document management API.
"""
import asyncio
import hashlib
import json
import re
import shutil
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, BackgroundTasks, Form
from sqlalchemy.orm import Session, selectinload
from typing import List, Optional
from uuid import UUID
from pathlib import Path
import uuid

from app.core.database import get_db
from app.models.document import Document as DBDocument, DocumentChunk
from app.api.schemas.document import (
    DocumentList,
    DocumentDetail,
    DocumentStatus,
    DocumentParsePreview,
    ParsedSegment,
    ManualDocumentCreate,
    DocumentPipelineOptions,
    ChunkPreviewParams,
    ChunkPreviewItem,
    ChunkPreviewResponse,
    BatchUploadRequest,
    BatchUploadResponse,
    BatchTaskStatus,
    DocumentBatchUploadResponse,
)
from app.parsing.processors.processor import document_processor
from app.parsing.factory import parser_factory
from app.parsing.routing import route_pdf_backend
from app.rag.chunking.factory import chunker_factory
from app.types.indexing import IndexKind, IndexRecord
from app.types.pipeline import PipelineOptions
from app.services.indexer import Indexer
from app.services.pipeline_config import (
    build_indexing_options,
    build_pipeline_metadata,
    resolve_pipeline_options,
)
from app.services.mineru_service import mineru_service
from app.services.dataset_service import DatasetService, EDIT_ROLES
from app.storage.object.minio import minio_service
from app.models.dataset import Dataset, DatasetPermission, DatasetPermissionEnum
from app.core.config import settings
from fastapi.responses import FileResponse, RedirectResponse
from app.api.dependencies.tenant import get_tenant_id
from app.api.dependencies.auth import get_current_account_id
from app.rag.kg.pipeline import extract_events
from sqlalchemy import or_, and_
from app.rag.core.logging import get_logger
from app.rag.preprocessing.processor import governance_processor
from app.api.utils.upload import save_upload_file
from app.tasks.queue import enqueue_document_processing


logger = get_logger("api.documents")

router = APIRouter()

# Safe filename characters: letters, digits, CJK, spaces, dots, underscores, hyphens.
SAFE_FILENAME_PATTERN = re.compile(r'^[a-zA-Z0-9\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af._\-\s]+$')

def _compute_pipeline_hash(doc_metadata: dict) -> str:
    """
    Generate a stable pipeline_hash based on processing-related doc_metadata fields.
    Use cases: task idempotency, lock keys, job_id dedupe (configs do not block each other).
    """
    relevant = {
        # Parser/chunk strategy.
        "parser_backend": doc_metadata.get("parser_backend"),
        "parser_backend_requested": doc_metadata.get("parser_backend_requested"),
        "chunk_strategy": doc_metadata.get("chunk_strategy"),
        "chunk_strategy_requested": doc_metadata.get("chunk_strategy_requested"),
        # Pipeline options (stable structure).
        "pipeline": doc_metadata.get("pipeline") or {},
    }
    raw = json.dumps(relevant, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def _validate_filename(filename: str) -> None:
    """Validate filename safety."""
    if not filename:
        raise HTTPException(status_code=400, detail="Filename is required")
    if len(filename) > 255:
        raise HTTPException(status_code=400, detail="Filename too long (max 255 characters)")
    if not SAFE_FILENAME_PATTERN.match(filename):
        raise HTTPException(status_code=400, detail="Filename contains invalid characters")


def _to_pipeline_options(
    *,
    pipeline: Optional[DocumentPipelineOptions] = None,
    governance_enabled: Optional[bool] = None,
    governance_remove_toc_lines: Optional[bool] = None,
    governance_remove_noise_lines: Optional[bool] = None,
    governance_unwrap_lines: Optional[bool] = None,
    governance_remove_common_lines: Optional[bool] = None,
    governance_unwrap_max_line_length: Optional[int] = None,
    governance_noise_min_chars: Optional[int] = None,
    governance_noise_ratio_threshold: Optional[float] = None,
    governance_common_lines_min_docs: Optional[int] = None,
    governance_common_lines_min_ratio: Optional[float] = None,
    chunk_size: Optional[int] = None,
    chunk_overlap: Optional[int] = None,
    chunk_vector_enabled: Optional[bool] = None,
    bm25_index_enabled: Optional[bool] = None,
    kg_enabled: Optional[bool] = None,
    event_vector_enabled: Optional[bool] = None,
    entity_vector_enabled: Optional[bool] = None,
) -> PipelineOptions:
    if pipeline is None:
        pipeline = DocumentPipelineOptions(
            governance_enabled=governance_enabled,
            governance_remove_toc_lines=governance_remove_toc_lines,
            governance_remove_noise_lines=governance_remove_noise_lines,
            governance_unwrap_lines=governance_unwrap_lines,
            governance_remove_common_lines=governance_remove_common_lines,
            governance_unwrap_max_line_length=governance_unwrap_max_line_length,
            governance_noise_min_chars=governance_noise_min_chars,
            governance_noise_ratio_threshold=governance_noise_ratio_threshold,
            governance_common_lines_min_docs=governance_common_lines_min_docs,
            governance_common_lines_min_ratio=governance_common_lines_min_ratio,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            chunk_vector_enabled=chunk_vector_enabled,
            bm25_index_enabled=bm25_index_enabled,
            kg_enabled=kg_enabled,
            event_vector_enabled=event_vector_enabled,
            entity_vector_enabled=entity_vector_enabled,
        )
    data = pipeline.model_dump(exclude_none=True)
    return PipelineOptions(**data) if data else PipelineOptions()


def _validate_chunk_params(chunk_size: int, chunk_overlap: int) -> None:
    if chunk_overlap >= chunk_size:
        raise HTTPException(
            status_code=400,
            detail="chunk_overlap must be less than chunk_size",
        )


def _resolve_writable_dataset(
    db: Session,
    tenant_id: UUID,
    account_id: str,
    dataset_id: Optional[UUID],
) -> Dataset:
    """
    Resolve a dataset that the current user can write to.

    - If dataset_id is provided: enforce writable permission.
    - Otherwise: pick the earliest writable dataset in tenant, or auto-create a default one.
    """
    if dataset_id:
        dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
        DatasetService.assert_dataset_writable(db, dataset, account_id)
        return dataset

    # Ensure member exists and has edit role (assert_dataset_writable enforces it as well).
    member = DatasetService.ensure_member(db, tenant_id, account_id)

    datasets = db.query(Dataset).filter(Dataset.tenant_id == tenant_id).order_by(Dataset.created_at.asc()).all()
    for ds in datasets:
        try:
            DatasetService.assert_dataset_writable(db, ds, account_id)
            return ds
        except HTTPException:
            continue

    # Validate user permission to create a dataset.
    role = (getattr(member, 'role', None) or "").lower()
    if role not in EDIT_ROLES:
        raise HTTPException(
            status_code=403,
            detail="No permission to create dataset. Please contact an administrator."
        )

    # Auto-create a default dataset with restricted permission (ONLY_ME).
    return DatasetService.create_dataset(
        db=db,
        tenant_id=tenant_id,
        name="Default Dataset",
        description="Auto-created (no dataset_id specified)",
        permission=DatasetPermissionEnum.ONLY_ME,  # Restrict permission to avoid privilege escalation.
        owner_id=account_id,
        partial_members=[],
    )


@router.post("/upload", response_model=DocumentDetail, status_code=201)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    parser_backend: str = Form(default=settings.DEFAULT_PARSER_BACKEND),
    chunk_strategy: str = Form(default=settings.DEFAULT_CHUNK_STRATEGY),
    governance_enabled: Optional[bool] = Form(default=None),
    governance_remove_toc_lines: Optional[bool] = Form(default=None),
    governance_remove_noise_lines: Optional[bool] = Form(default=None),
    governance_unwrap_lines: Optional[bool] = Form(default=None),
    governance_remove_common_lines: Optional[bool] = Form(default=None),
    governance_unwrap_max_line_length: Optional[int] = Form(default=None),
    governance_noise_min_chars: Optional[int] = Form(default=None),
    governance_noise_ratio_threshold: Optional[float] = Form(default=None),
    governance_common_lines_min_docs: Optional[int] = Form(default=None),
    governance_common_lines_min_ratio: Optional[float] = Form(default=None),
    chunk_size: Optional[int] = Form(default=None),
    chunk_overlap: Optional[int] = Form(default=None),
    chunk_vector_enabled: Optional[bool] = Form(default=None),
    bm25_index_enabled: Optional[bool] = Form(default=None),
    kg_enabled: Optional[bool] = Form(default=None),
    event_vector_enabled: Optional[bool] = Form(default=None),
    entity_vector_enabled: Optional[bool] = Form(default=None),
    dataset_id: Optional[UUID] = Form(default=None),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db)
):
    """
    Upload a document.

    Flow:
    1. Validate file type and size
    2. Save file locally
    3. Create database record
    4. Process document asynchronously (parse, chunk, embed)
    """

    # 0. Validate filename safety.
    _validate_filename(file.filename)

    # 1. Validate file type.
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in settings.allowed_extensions_list:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {settings.allowed_extensions_list}"
        )

    try:
        requested_parser_backend = (parser_backend or "").strip().lower()
        if file_ext == ".pdf" and requested_parser_backend in {"", "auto"}:
            # Keep "auto" for background routing (quality scoring happens in DocumentProcessor).
            resolved_parser_backend = "auto"
        else:
            resolved_parser_backend = parser_factory.resolve_backend(file_ext, parser_backend)
        resolved_chunk_strategy = chunker_factory.resolve_strategy(chunk_strategy)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    pipeline_options = _to_pipeline_options(
        governance_enabled=governance_enabled,
        governance_remove_toc_lines=governance_remove_toc_lines,
        governance_remove_noise_lines=governance_remove_noise_lines,
        governance_unwrap_lines=governance_unwrap_lines,
        governance_remove_common_lines=governance_remove_common_lines,
        governance_unwrap_max_line_length=governance_unwrap_max_line_length,
        governance_noise_min_chars=governance_noise_min_chars,
        governance_noise_ratio_threshold=governance_noise_ratio_threshold,
        governance_common_lines_min_docs=governance_common_lines_min_docs,
        governance_common_lines_min_ratio=governance_common_lines_min_ratio,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        chunk_vector_enabled=chunk_vector_enabled,
        bm25_index_enabled=bm25_index_enabled,
        kg_enabled=kg_enabled,
        event_vector_enabled=event_vector_enabled,
        entity_vector_enabled=entity_vector_enabled,
    )
    pipeline_effective = resolve_pipeline_options(pipeline_options)
    if resolved_chunk_strategy not in chunker_factory.RAGFLOW_STRATEGIES:
        _validate_chunk_params(pipeline_effective.chunk_size, pipeline_effective.chunk_overlap)
    pipeline_metadata = build_pipeline_metadata(pipeline_options)

    # Permission check.
    dataset = _resolve_writable_dataset(db, tenant_id, account_id, dataset_id)

    # 3. Save file.
    upload_dir = Path(settings.UPLOAD_DIR) / str(tenant_id)
    upload_dir.mkdir(parents=True, exist_ok=True)

    # Generate unique filename.
    file_id = uuid.uuid4()
    file_path = upload_dir / f"{file_id}{file_ext}"

    try:
        file_size = await save_upload_file(file, file_path, max_bytes=settings.MAX_FILE_SIZE)
    except HTTPException:
        raise

    # 4. Create database record.
    doc_metadata = {
        "parser_backend": resolved_parser_backend,
        "parser_backend_requested": (parser_backend or "").lower(),
        "chunk_strategy": resolved_chunk_strategy,
        "chunk_strategy_requested": (chunk_strategy or "").lower(),
    }
    if pipeline_metadata:
        doc_metadata["pipeline"] = pipeline_metadata
    pipeline_hash = _compute_pipeline_hash(doc_metadata)
    doc_metadata["pipeline_hash"] = pipeline_hash

    db_document = DBDocument(
        id=file_id,
        tenant_id=tenant_id,
        dataset_id=dataset.id,
        filename=file.filename,
        file_type=file_ext.lstrip('.'),
        file_size=file_size,
        file_path=str(file_path),
        status='pending',
        processing_progress=0,
        doc_metadata=doc_metadata,
    )

    db.add(db_document)
    db.commit()
    db.refresh(db_document)

    # 5. Process document in background: enqueue if available (fallback to BackgroundTasks).
    job_id = f"doc:{tenant_id}:{file_id}:{pipeline_hash}"
    task_id = await enqueue_document_processing(
        tenant_id=tenant_id,
        document_id=file_id,
        requested_by=account_id,
        job_id=job_id,
    )
    if task_id:
        meta = dict(db_document.doc_metadata or {})
        meta["task_id"] = task_id
        db_document.doc_metadata = meta
        db.commit()
        db.refresh(db_document)
    else:
        background_tasks.add_task(
            document_processor.process_document,
            file_path,
            file_id,
            tenant_id,
            resolved_parser_backend,
            resolved_chunk_strategy,
        )

    return db_document


@router.post("/upload-batch", response_model=DocumentBatchUploadResponse, status_code=201)
async def upload_documents_batch(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    parser_backend: str = Form(default=settings.DEFAULT_PARSER_BACKEND),
    chunk_strategy: str = Form(default=settings.DEFAULT_CHUNK_STRATEGY),
    governance_enabled: Optional[bool] = Form(default=None),
    governance_remove_toc_lines: Optional[bool] = Form(default=None),
    governance_remove_noise_lines: Optional[bool] = Form(default=None),
    governance_unwrap_lines: Optional[bool] = Form(default=None),
    governance_remove_common_lines: Optional[bool] = Form(default=None),
    governance_unwrap_max_line_length: Optional[int] = Form(default=None),
    governance_noise_min_chars: Optional[int] = Form(default=None),
    governance_noise_ratio_threshold: Optional[float] = Form(default=None),
    governance_common_lines_min_docs: Optional[int] = Form(default=None),
    governance_common_lines_min_ratio: Optional[float] = Form(default=None),
    chunk_size: Optional[int] = Form(default=None),
    chunk_overlap: Optional[int] = Form(default=None),
    chunk_vector_enabled: Optional[bool] = Form(default=None),
    bm25_index_enabled: Optional[bool] = Form(default=None),
    kg_enabled: Optional[bool] = Form(default=None),
    event_vector_enabled: Optional[bool] = Form(default=None),
    entity_vector_enabled: Optional[bool] = Form(default=None),
    dataset_id: Optional[UUID] = Form(default=None),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
    max_concurrent: int = Form(default=5)
):
    """
    Batch upload documents (concurrency-optimized).

    Supports uploading multiple documents concurrently to improve performance.

    Args:
        files: Document file list.
        max_concurrent: Max concurrent processing, default 5.
        Other params match the single-file upload endpoint.

    Returns:
        {
            "total": total files,
            "successful": list of successful documents,
            "failed": list of failed files (with errors)
        }
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")
    
    if len(files) > 50:
        raise HTTPException(status_code=400, detail="Too many files. Maximum 50 files per batch.")
    
    # Cap concurrency.
    max_concurrent = min(max_concurrent, 10)  # Max 10 concurrent.
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def process_single_file(file: UploadFile) -> dict:
        """Handle upload for a single file."""
        async with semaphore:
            try:
                # Validate filename.
                _validate_filename(file.filename)
                
                # Validate file type.
                file_ext = Path(file.filename).suffix.lower()
                if file_ext not in settings.allowed_extensions_list:
                    return {
                        "success": False,
                        "filename": file.filename,
                        "error": f"Unsupported file type: {file_ext}"
                    }
                
                # Parser validation.
                requested_parser_backend = (parser_backend or "").strip().lower()
                if file_ext == ".pdf" and requested_parser_backend in {"", "auto"}:
                    resolved_parser_backend = "auto"
                else:
                    resolved_parser_backend = parser_factory.resolve_backend(file_ext, parser_backend)
                resolved_chunk_strategy = chunker_factory.resolve_strategy(chunk_strategy)
                
                pipeline_options = _to_pipeline_options(
                    governance_enabled=governance_enabled,
                    governance_remove_toc_lines=governance_remove_toc_lines,
                    governance_remove_noise_lines=governance_remove_noise_lines,
                    governance_unwrap_lines=governance_unwrap_lines,
                    governance_remove_common_lines=governance_remove_common_lines,
                    governance_unwrap_max_line_length=governance_unwrap_max_line_length,
                    governance_noise_min_chars=governance_noise_min_chars,
                    governance_noise_ratio_threshold=governance_noise_ratio_threshold,
                    governance_common_lines_min_docs=governance_common_lines_min_docs,
                    governance_common_lines_min_ratio=governance_common_lines_min_ratio,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                    chunk_vector_enabled=chunk_vector_enabled,
                    bm25_index_enabled=bm25_index_enabled,
                    kg_enabled=kg_enabled,
                    event_vector_enabled=event_vector_enabled,
                    entity_vector_enabled=entity_vector_enabled,
                )
                pipeline_effective = resolve_pipeline_options(pipeline_options)
                if resolved_chunk_strategy not in chunker_factory.RAGFLOW_STRATEGIES:
                    _validate_chunk_params(pipeline_effective.chunk_size, pipeline_effective.chunk_overlap)
                pipeline_metadata = build_pipeline_metadata(pipeline_options)
                
                # Permission check (already done outside semaphore).
                # Save file.
                upload_dir = Path(settings.UPLOAD_DIR) / str(tenant_id)
                upload_dir.mkdir(parents=True, exist_ok=True)
                
                file_id = uuid.uuid4()
                file_path = upload_dir / f"{file_id}{file_ext}"
                
                file_size = await save_upload_file(file, file_path, max_bytes=settings.MAX_FILE_SIZE)
                
                # Create database record.
                doc_metadata = {
                    "parser_backend": resolved_parser_backend,
                    "parser_backend_requested": (parser_backend or "").lower(),
                    "chunk_strategy": resolved_chunk_strategy,
                    "chunk_strategy_requested": (chunk_strategy or "").lower(),
                }
                if pipeline_metadata:
                    doc_metadata["pipeline"] = pipeline_metadata
                pipeline_hash = _compute_pipeline_hash(doc_metadata)
                doc_metadata["pipeline_hash"] = pipeline_hash
                
                db_document = DBDocument(
                    id=file_id,
                    tenant_id=tenant_id,
                    dataset_id=dataset.id if dataset else None,
                    filename=file.filename,
                    file_type=file_ext.lstrip('.'),
                    file_size=file_size,
                    file_path=str(file_path),
                    status='pending',
                    processing_progress=0,
                    doc_metadata=doc_metadata,
                )
                
                db.add(db_document)
                db.commit()
                db.refresh(db_document)
                
                # Process document in background: enqueue if available (fallback to BackgroundTasks).
                job_id = f"doc:{tenant_id}:{file_id}:{pipeline_hash}"
                task_id = await enqueue_document_processing(
                    tenant_id=tenant_id,
                    document_id=file_id,
                    requested_by=account_id,
                    job_id=job_id,
                )
                if task_id:
                    meta = dict(db_document.doc_metadata or {})
                    meta["task_id"] = task_id
                    db_document.doc_metadata = meta
                    db.commit()
                    db.refresh(db_document)
                else:
                    background_tasks.add_task(
                        document_processor.process_document,
                        file_path,
                        file_id,
                        tenant_id,
                        resolved_parser_backend,
                        resolved_chunk_strategy,
                    )
                
                return {
                    "success": True,
                    "filename": file.filename,
                    "document_id": str(file_id),
                    "document": db_document
                }
                
            except Exception as e:
                logger.error(f"Error processing file {file.filename}: {str(e)}")
                return {
                    "success": False,
                    "filename": file.filename,
                    "error": str(e)
                }
    
    # Permission check (done once).
    dataset = _resolve_writable_dataset(db, tenant_id, account_id, dataset_id)
    
    # Process all files concurrently.
    tasks = [process_single_file(file) for file in files]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Handle error results.
    processed_results = []
    for result in results:
        if isinstance(result, Exception):
            processed_results.append({
                "success": False,
                "filename": "unknown",
                "error": str(result)
            })
        else:
            processed_results.append(result)
    
    successful = [r for r in processed_results if r.get("success")]
    failed = [r for r in processed_results if not r.get("success")]
    
    return {
        "total": len(files),
        "successful_count": len(successful),
        "failed_count": len(failed),
        "successful": [
            {
                "document_id": r["document_id"],
                "filename": r["filename"],
                "status": r["document"].status
            }
            for r in successful
        ],
        "failed": [
            {
                "filename": r["filename"],
                "error": r.get("error", "Unknown error")
            }
            for r in failed
        ]
    }


@router.get("/", response_model=DocumentList)
async def list_documents(
    skip: int = 0,
    limit: int = 20,
    status: Optional[str] = None,
    dataset_id: Optional[UUID] = None,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db)
):
    """
    List documents.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    query = db.query(DBDocument).filter(DBDocument.tenant_id == tenant_id)

    if dataset_id:
        dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
        DatasetService.assert_dataset_readable(db, dataset, account_id)
        query = query.filter(DBDocument.dataset_id == dataset_id)
    else:
        # No dataset_id: return all documents the user can read within the tenant.
        # Optimization: use database filtering to avoid N+1 queries.

        # Subquery: dataset IDs accessible via PARTIAL_MEMBERS permission.
        partial_member_subq = (
            db.query(DatasetPermission.dataset_id)
            .filter(
                DatasetPermission.tenant_id == tenant_id,
                DatasetPermission.account_id == account_id,
            )
            .subquery()
        )

        # Build allowed dataset filters.
        allowed_dataset_filter = or_(
            # User is owner.
            Dataset.owner_id == account_id,
            # ALL_TEAM_MEMBERS permission.
            Dataset.permission == DatasetPermissionEnum.ALL_TEAM_MEMBERS,
            # PARTIAL_MEMBERS permission and user in list.
            and_(
                Dataset.permission == DatasetPermissionEnum.PARTIAL_MEMBERS,
                Dataset.id.in_(partial_member_subq)
            )
        )

        # Fetch accessible dataset IDs.
        allowed_dataset_ids_subq = (
            db.query(Dataset.id)
            .filter(
                Dataset.tenant_id == tenant_id,
                allowed_dataset_filter
            )
            .subquery()
        )

        query = query.filter(
            or_(
                DBDocument.dataset_id.is_(None),
                DBDocument.dataset_id.in_(allowed_dataset_ids_subq),
            )
        )

    # Status filter.
    if status and status != 'all':
        query = query.filter(DBDocument.status == status)

    # Total count.
    total = query.count()

    # Pagination.
    documents = query.order_by(DBDocument.created_at.desc()).offset(skip).limit(limit).all()

    return {
        "total": total,
        "items": documents
    }


@router.get("/{document_id}", response_model=DocumentDetail)
async def get_document(
    document_id: uuid.UUID,
    include_chunks: bool = False,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db)
):
    """
    Get document detail.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)
    query = db.query(DBDocument).filter(
        DBDocument.id == document_id,
        DBDocument.tenant_id == tenant_id
    )
    if include_chunks:
        query = query.options(selectinload(DBDocument.chunks))
    document = query.first()

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    # Permission check.
    if document.dataset_id:
        ds = DatasetService.get_dataset(db, tenant_id, document.dataset_id)
        DatasetService.assert_dataset_readable(db, ds, account_id)

    # If chunks are needed, touch the relationship to ensure load.
    if include_chunks:
        # Expose a non-relationship attribute for Pydantic to serialize without triggering
        # accidental lazy-loading when include_chunks=false.
        setattr(document, "chunks_loaded", document.chunks)

    return document


@router.get("/{document_id}/status", response_model=DocumentStatus)
async def get_document_status(
    document_id: uuid.UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db)
):
    """
    Get document processing status (for polling).
    """
    DatasetService.ensure_member(db, tenant_id, account_id)
    document = db.query(DBDocument).filter(
        DBDocument.id == document_id,
        DBDocument.tenant_id == tenant_id
    ).first()

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    if document.dataset_id:
        ds = DatasetService.get_dataset(db, tenant_id, document.dataset_id)
        DatasetService.assert_dataset_readable(db, ds, account_id)

    return {
        "id": document.id,
        "status": document.status,
        "processing_progress": document.processing_progress,
        "current_stage": document.current_stage,
        "error_message": document.error_message
    }


@router.delete("/{document_id}", status_code=204)
async def delete_document(
    document_id: uuid.UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db)
):
    """
    Delete document.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)
    document = db.query(DBDocument).filter(
        DBDocument.id == document_id,
        DBDocument.tenant_id == tenant_id
    ).first()

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    if document.dataset_id:
        ds = DatasetService.get_dataset(db, tenant_id, document.dataset_id)
        DatasetService.assert_dataset_writable(db, ds, account_id)

    # 1. Delete images in MinIO (if enabled).
    if settings.MINIO_ENABLED:
        img_ids: set[str] = set()

        # Prefer document-level aggregated list (avoid missing ZIP/embedded images, etc.).
        doc_meta = document.doc_metadata or {}
        doc_img_ids = doc_meta.get("img_ids")
        if isinstance(doc_img_ids, list):
            for v in doc_img_ids:
                if isinstance(v, str) and v.strip():
                    img_ids.add(v)

        # Compatibility: delete per chunk (older data may lack documents.metadata.img_ids).
        chunks = (
            db.query(DocumentChunk)
            .filter(DocumentChunk.document_id == document_id, DocumentChunk.tenant_id == tenant_id)
            .all()
        )
        for chunk in chunks:
            img_id = chunk.doc_metadata.get("img_id") if chunk.doc_metadata else None
            if isinstance(img_id, str) and img_id.strip():
                img_ids.add(img_id)

        for img_id in sorted(img_ids):
            try:
                minio_service.delete_image(img_id, extension="jpg")
            except Exception as e:
                logger.warning("Failed to delete image %s from object storage: %s", img_id, e)

    # 2. Delete vectors from vector store (backend-dependent).
    Indexer(db).delete_all(tenant_id=tenant_id, document_id=document_id, commit=False)

    # 3. Delete local file.
    try:
        file_path = Path(document.file_path)
        if file_path.exists():
            file_path.unlink()
    except Exception as e:
        logger.warning("Failed to delete file: %s", e)

    # 4. Delete DB record (cascade chunks).
    db.delete(document)
    db.commit()

    # 5. Remove chunks from BM25 index (in-memory).
    return None


@router.get("/image/{image_id}")
async def get_image(
    image_id: str,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    Return stored image by image_id.
    Standard path: {UPLOAD_DIR}/images/{image_id}.png
    """
    DatasetService.ensure_member(db, tenant_id, account_id)
    images_dir = Path(settings.UPLOAD_DIR) / str(tenant_id) / "images"
    # Prevent path traversal: only allow UUID / 32-hex (internal image_id).
    try:
        safe_id = uuid.UUID(image_id).hex
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found")

    images_dir_resolved = images_dir.resolve(strict=False)
    file_path = (images_dir / f"{safe_id}.png").resolve(strict=False)

    # Safety check: ensure file_path stays under images_dir (prevent path traversal).
    if not str(file_path).startswith(str(images_dir_resolved) + "/"):
        raise HTTPException(status_code=404, detail="Image not found")

    # Check file exists and is a regular file.
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(file_path, media_type="image/png")


@router.get("/image-url/{img_id}")
async def get_image_url(
    img_id: str,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    Get MinIO presigned URL by img_id ({tenant_id}:{dataset_id}:{document_id}:{chunk_index}).
    Returns a 302 redirect to the image URL.
    """
    if not settings.MINIO_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="MinIO is disabled; cannot retrieve image URL"
        )

    DatasetService.ensure_member(db, tenant_id, account_id)

    # Basic access control: ensure img_id tenant prefix matches request tenant (legacy dataset-chunk exempt).
    def _tenant_from_img_id(val: str) -> Optional[str]:
        if ":" in val:
            parts = val.split(":", 1)
            return parts[0]
        return None

    tenant_in_img = _tenant_from_img_id(img_id)
    if tenant_in_img and tenant_in_img != str(tenant_id):
        raise HTTPException(status_code=403, detail="Image access denied for this tenant")

    # Permission check: parse dataset/document from img_id when possible for dataset-level control.
    if ":" in img_id:
        try:
            _tenant_part, dataset_part, document_part, _chunk_key = img_id.split(":", 3)
            dataset_uuid = UUID(dataset_part)
            document_uuid = UUID(document_part)
        except Exception:
            raise HTTPException(status_code=404, detail="Image not found")

        document = (
            db.query(DBDocument)
            .filter(DBDocument.id == document_uuid, DBDocument.tenant_id == tenant_id)
            .first()
        )
        if not document:
            raise HTTPException(status_code=404, detail="Image not found")
        if document.dataset_id and document.dataset_id != dataset_uuid:
            raise HTTPException(status_code=404, detail="Image not found")
        if document.dataset_id:
            ds = DatasetService.get_dataset(db, tenant_id, document.dataset_id)
            DatasetService.assert_dataset_readable(db, ds, account_id)
    else:
        # Backward compatible: "{dataset_id}-{chunk_id}"
        try:
            dataset_part = img_id.split("-", 1)[0]
            dataset_uuid = UUID(dataset_part)
        except Exception:
            raise HTTPException(status_code=404, detail="Image not found")
        ds = DatasetService.get_dataset(db, tenant_id, dataset_uuid)
        DatasetService.assert_dataset_readable(db, ds, account_id)

    try:
        url = minio_service.get_image_url(img_id, extension="jpg")
        # Redirect to MinIO presigned URL.
        return RedirectResponse(url=url, status_code=302)
    except Exception as e:
        raise HTTPException(
            status_code=404,
            detail=f"Image not found or retrieval failed: {str(e)}"
        )


@router.post("/preview", response_model=DocumentParsePreview)
async def preview_document(
    file: UploadFile = File(...),
    parser_backend: str = Form(default=settings.DEFAULT_PARSER_BACKEND),
    chunk_strategy: str = Form(default=settings.DEFAULT_CHUNK_STRATEGY),
    governance_enabled: Optional[bool] = Form(default=None),
    governance_remove_toc_lines: Optional[bool] = Form(default=None),
    governance_remove_noise_lines: Optional[bool] = Form(default=None),
    governance_unwrap_lines: Optional[bool] = Form(default=None),
    governance_remove_common_lines: Optional[bool] = Form(default=None),
    governance_unwrap_max_line_length: Optional[int] = Form(default=None),
    governance_noise_min_chars: Optional[int] = Form(default=None),
    governance_noise_ratio_threshold: Optional[float] = Form(default=None),
    governance_common_lines_min_docs: Optional[int] = Form(default=None),
    governance_common_lines_min_ratio: Optional[float] = Form(default=None),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    Document parse preview endpoint.

    Only parses the document and returns structured segments; does not create
    a document record or persist data. Useful for frontend custom chunking.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)
    # Validate file type.
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in settings.allowed_extensions_list:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {settings.allowed_extensions_list}"
        )

    # Save file to a temp path for parsing.
    upload_dir = Path(settings.UPLOAD_DIR) / str(tenant_id) / "preview"
    upload_dir.mkdir(parents=True, exist_ok=True)

    temp_path = upload_dir / f"{uuid.uuid4()}{file_ext}"
    artifact_dirs: set[str] = set()

    try:
        file_size = await save_upload_file(file, temp_path, max_bytes=settings.MAX_FILE_SIZE)

        if file_ext == ".pdf":
            requested = (parser_backend or "").strip().lower()
            if not requested or requested == "auto":
                effective_parser_backend, _pdf_quality = route_pdf_backend(
                    temp_path,
                    requested,
                    sample_pages=3,
                    use_ocr_validation=settings.RAPIDOCR_ENABLED,
                )
            else:
                effective_parser_backend = requested
        else:
            effective_parser_backend = parser_backend

        documents, resolved_backend = parser_factory.parse(
            temp_path,
            parser_backend=effective_parser_backend,
        )
        for doc in documents:
            artifact_dir = (doc.metadata or {}).get("artifact_dir")
            if isinstance(artifact_dir, str) and artifact_dir.strip():
                artifact_dirs.add(artifact_dir.strip())

        pipeline_options = _to_pipeline_options(
            governance_enabled=governance_enabled,
            governance_remove_toc_lines=governance_remove_toc_lines,
            governance_remove_noise_lines=governance_remove_noise_lines,
            governance_unwrap_lines=governance_unwrap_lines,
            governance_remove_common_lines=governance_remove_common_lines,
            governance_unwrap_max_line_length=governance_unwrap_max_line_length,
            governance_noise_min_chars=governance_noise_min_chars,
            governance_noise_ratio_threshold=governance_noise_ratio_threshold,
            governance_common_lines_min_docs=governance_common_lines_min_docs,
            governance_common_lines_min_ratio=governance_common_lines_min_ratio,
        )
        pipeline_effective = resolve_pipeline_options(pipeline_options)
        if pipeline_effective.governance_enabled:
            documents, _stats = governance_processor.clean_documents(
                documents,
                remove_toc_lines=pipeline_effective.governance_remove_toc_lines,
                remove_noise_lines=pipeline_effective.governance_remove_noise_lines,
                unwrap_lines=pipeline_effective.governance_unwrap_lines,
                remove_common_lines=pipeline_effective.governance_remove_common_lines,
                unwrap_max_line_length=pipeline_effective.governance_unwrap_max_line_length,
                noise_min_chars=pipeline_effective.governance_noise_min_chars,
                noise_ratio_threshold=pipeline_effective.governance_noise_ratio_threshold,
                common_lines_min_docs=pipeline_effective.governance_common_lines_min_docs,
                common_lines_min_ratio=pipeline_effective.governance_common_lines_min_ratio,
            )

        segments: List[ParsedSegment] = []
        for idx, doc in enumerate(documents):
            segments.append(ParsedSegment(
                index=idx,
                content=doc.page_content,
                page_number=doc.metadata.get('page'),
                metadata=doc.metadata or {}
            ))

        return DocumentParsePreview(
            filename=file.filename,
            file_type=file_ext.lstrip('.'),
            file_size=file_size,
            segments=segments,
            parser_backend=resolved_backend
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid input: {str(e)[:100]}")
    except IOError as e:
        logger.error("File read error during preview: %s", str(e)[:200])
        raise HTTPException(status_code=500, detail="File read error")
    except Exception as e:
        logger.error("Unexpected error during document preview: %s", str(e)[:200])
        raise HTTPException(status_code=500, detail="Failed to parse document")
    finally:
        try:
            if temp_path.exists():
                temp_path.unlink()
        except OSError as e:
            logger.warning("Failed to clean up temporary file %s: %s", temp_path, e)

        # Best-effort cleanup for preview parser artifacts (e.g., MagicPDF output).
        if artifact_dirs and not bool(getattr(settings, "MAGIC_PDF_KEEP_ARTIFACTS", False)):
            upload_root = Path(settings.UPLOAD_DIR).resolve(strict=False)
            tenant_root = (upload_root / str(tenant_id)).resolve(strict=False)
            for raw in sorted(artifact_dirs):
                try:
                    path = Path(raw).resolve(strict=False)
                    if not path.exists():
                        continue
                    if ".magicpdf" not in path.parts:
                        continue
                    path.relative_to(tenant_root)
                except Exception:
                    continue
                try:
                    shutil.rmtree(path, ignore_errors=True)
                except Exception:
                    pass


@router.post("/manual", response_model=DocumentDetail, status_code=201)
async def create_document_with_manual_chunks(
    request: ManualDocumentCreate,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db)
):
    """
    Create a document from frontend custom chunks.

    Flow:
    1. Create document record (status=processing)
    2. Generate embeddings from chunks and store in Milvus
    3. Write chunks to PostgreSQL
    4. Rebuild BM25 index
    5. Update document status to completed
    """
    # Permission check.
    dataset = _resolve_writable_dataset(db, tenant_id, account_id, request.dataset_id)

    # Basic validation.
    if not request.chunks:
        raise HTTPException(status_code=400, detail="Chunks cannot be empty")

    # Validate file type.
    file_type_with_dot = f".{request.file_type.lower()}"
    if file_type_with_dot not in settings.allowed_extensions_list:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {request.file_type}"
        )

    # Create document record.
    document_id = uuid.uuid4()
    pipeline_options = _to_pipeline_options(pipeline=request.pipeline)
    pipeline_effective = resolve_pipeline_options(pipeline_options)
    index_options = build_indexing_options(pipeline_effective)
    pipeline_metadata = build_pipeline_metadata(pipeline_options)

    doc_metadata = dict(request.metadata or {})
    if pipeline_metadata:
        doc_metadata["pipeline"] = pipeline_metadata

    db_document = DBDocument(
        id=document_id,
        tenant_id=tenant_id,
        dataset_id=dataset.id,
        filename=request.filename,
        file_type=request.file_type.lower(),
        file_size=request.file_size,
        # Manual-chunk documents have no real file path; use a placeholder.
        file_path=f"manual://{document_id}",
        status='processing',
        processing_progress=0,
        current_stage='embedding',
        doc_metadata=doc_metadata,
    )

    db.add(db_document)
    db.flush()  # Flush only (no commit) to allow rollback.

    try:
        records: List[IndexRecord] = []
        for idx, chunk in enumerate(request.chunks):
            metadata = {
                "source": request.filename,
                "file_type": request.file_type.lower(),
                "page": chunk.page_number,
                "document_id": str(document_id),
                "chunk_index": idx,
                **(chunk.metadata or {}),
            }
            records.append(
                IndexRecord(
                    kind=IndexKind.CHUNK,
                    content=chunk.content or "",
                    metadata=metadata,
                    document_id=document_id,
                    page_number=chunk.page_number,
                    start_char=chunk.start_char,
                    end_char=chunk.end_char,
                )
            )

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

        # Update document stats and status.
        db_document.chunk_count = len(request.chunks)
        db_document.total_characters = persist_result.total_characters
        db_document.status = 'completed'
        db_document.processing_progress = 100
        db_document.current_stage = 'completed'
        db.commit()
        db.refresh(db_document)

        if pipeline_effective.kg_enabled:
            try:
                prompt_template_id = None
                raw_tid = (getattr(settings, "KG_EXTRACT_PROMPT_TEMPLATE_ID", "") or "").strip()
                if raw_tid:
                    try:
                        prompt_template_id = UUID(raw_tid)
                    except Exception:
                        logger.warning("Invalid KG_EXTRACT_PROMPT_TEMPLATE_ID: %s", raw_tid[:50])
                await extract_events(
                    chunk_ids=persist_result.chunk_ids,
                    tenant_id=tenant_id,
                    chunks=persist_result.db_chunks,
                    index_options=index_options,
                    prompt_template_id=prompt_template_id,
                    prompt_template_key=(getattr(settings, "KG_EXTRACT_PROMPT_TEMPLATE_KEY", "") or "").strip() or None,
                    prompt_ab_experiment_key=(getattr(settings, "KG_EXTRACT_PROMPT_AB_EXPERIMENT_KEY", "") or "").strip() or None,
                    ab_user_key=account_id,
                )
            except Exception as exc:
                # KG extraction is optional; failures do not block the main flow.
                logger.warning("KG extraction failed for document %s: %s", document_id, str(exc)[:200])

        return db_document

    except Exception as e:
        db.rollback()
        # Best-effort cleanup for partially indexed vectors / BM25
        try:
            Indexer(db).delete_chunk_indexes(tenant_id=tenant_id, document_id=document_id)
        except Exception:
            pass
        db_document.status = 'failed'
        db_document.processing_progress = 0
        db_document.current_stage = 'failed'
        db_document.error_message = str(e)
        db.commit()
        db.refresh(db_document)
        raise HTTPException(status_code=500, detail=f"Failed to create document with manual chunks: {str(e)}")


@router.post("/chunk-preview", response_model=ChunkPreviewResponse)
async def preview_chunking(
    file: UploadFile = File(...),
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
    parser_backend: str = Form(default=settings.DEFAULT_PARSER_BACKEND),
    chunk_strategy: str = Form(default=settings.DEFAULT_CHUNK_STRATEGY),
    governance_enabled: Optional[bool] = Form(default=None),
    governance_remove_toc_lines: Optional[bool] = Form(default=None),
    governance_remove_noise_lines: Optional[bool] = Form(default=None),
    governance_unwrap_lines: Optional[bool] = Form(default=None),
    governance_remove_common_lines: Optional[bool] = Form(default=None),
    governance_unwrap_max_line_length: Optional[int] = Form(default=None),
    governance_noise_min_chars: Optional[int] = Form(default=None),
    governance_noise_ratio_threshold: Optional[float] = Form(default=None),
    governance_common_lines_min_docs: Optional[int] = Form(default=None),
    governance_common_lines_min_ratio: Optional[float] = Form(default=None),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    Chunk preview endpoint.

    Upload a file and preview chunking with the given parameters (no DB writes).
    Returns chunk results with positions for frontend highlighting.

    Args:
        file: Uploaded file.
        chunk_size: Chunk size (100-4000).
        chunk_overlap: Overlap size (0-1000).

    Returns:
        Chunk preview result including content and position info.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)
    # Parameter validation.
    if chunk_size < 100 or chunk_size > 4000:
        raise HTTPException(status_code=400, detail="chunk_size must be between 100 and 4000")
    if chunk_overlap < 0 or chunk_overlap > 1000:
        raise HTTPException(status_code=400, detail="chunk_overlap must be between 0 and 1000")
    if chunk_overlap >= chunk_size:
        raise HTTPException(status_code=400, detail="chunk_overlap must be less than chunk_size")

    # Validate file type.
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in settings.allowed_extensions_list:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {settings.allowed_extensions_list}"
        )

    # Save to a temp path.
    upload_dir = Path(settings.UPLOAD_DIR) / str(tenant_id) / "preview"
    upload_dir.mkdir(parents=True, exist_ok=True)
    temp_path = upload_dir / f"{uuid.uuid4()}{file_ext}"

    # Defensive default: avoid NameError if any branch exits early.
    file_size: int = 0

    try:
        file_size = int(await save_upload_file(file, temp_path, max_bytes=settings.MAX_FILE_SIZE) or 0)
        if file_size <= 0:
            try:
                file_size = temp_path.stat().st_size
            except Exception:
                pass

        resolved_chunk_strategy = chunker_factory.resolve_strategy(chunk_strategy)
        pipeline_options = _to_pipeline_options(
            governance_enabled=governance_enabled,
            governance_remove_toc_lines=governance_remove_toc_lines,
            governance_remove_noise_lines=governance_remove_noise_lines,
            governance_unwrap_lines=governance_unwrap_lines,
            governance_remove_common_lines=governance_remove_common_lines,
            governance_unwrap_max_line_length=governance_unwrap_max_line_length,
            governance_noise_min_chars=governance_noise_min_chars,
            governance_noise_ratio_threshold=governance_noise_ratio_threshold,
            governance_common_lines_min_docs=governance_common_lines_min_docs,
            governance_common_lines_min_ratio=governance_common_lines_min_ratio,
        )
        pipeline_effective = resolve_pipeline_options(pipeline_options)
        governance_kwargs = {
            "remove_toc_lines": pipeline_effective.governance_remove_toc_lines,
            "remove_noise_lines": pipeline_effective.governance_remove_noise_lines,
            "unwrap_lines": pipeline_effective.governance_unwrap_lines,
            "remove_common_lines": pipeline_effective.governance_remove_common_lines,
            "unwrap_max_line_length": pipeline_effective.governance_unwrap_max_line_length,
            "noise_min_chars": pipeline_effective.governance_noise_min_chars,
            "noise_ratio_threshold": pipeline_effective.governance_noise_ratio_threshold,
            "common_lines_min_docs": pipeline_effective.governance_common_lines_min_docs,
            "common_lines_min_ratio": pipeline_effective.governance_common_lines_min_ratio,
        }

        # Ragflow preset uses a separate branch (self-parse + chunk).
        if resolved_chunk_strategy in chunker_factory.RAGFLOW_STRATEGIES:
            from app.parsing.processors.processor import document_processor
            chunks = await asyncio.to_thread(
                document_processor._ragflow_chunk_file,
                temp_path,
                resolved_chunk_strategy
            )
            resolved_backend = "ragflow"
            documents = []  # Ragflow already handled.
            if pipeline_effective.governance_enabled:
                chunks, _stats = governance_processor.clean_documents(
                    chunks,
                    **governance_kwargs,
                )
        else:
            # Parse document.
            if file_ext == ".pdf":
                requested = (parser_backend or "").strip().lower()
                if not requested or requested == "auto":
                    effective_parser_backend, _pdf_quality = route_pdf_backend(
                        temp_path,
                        requested,
                        sample_pages=3,
                        use_ocr_validation=settings.RAPIDOCR_ENABLED,
                    )
                else:
                    effective_parser_backend = requested
            else:
                effective_parser_backend = parser_backend
            documents, resolved_backend = parser_factory.parse(
                temp_path,
                parser_backend=effective_parser_backend,
            )
            if pipeline_effective.governance_enabled:
                documents, _stats = governance_processor.clean_documents(
                    documents,
                    **governance_kwargs,
                )

            chunker = chunker_factory.get_chunker(
                resolved_chunk_strategy,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap
            )
            chunks = chunker.split_documents(documents)

        # Align with ingestion: drop extremely short chunks (keep image-bearing chunks).
        min_chars = max(0, int(getattr(settings, "CHUNK_MIN_CHARS", 0) or 0))
        if min_chars > 0 and chunks:
            before = len(chunks)
            original_chunks = chunks
            filtered = []
            for c in original_chunks:
                content = (c.page_content or "").strip()
                if len(content) >= min_chars:
                    filtered.append(c)
                    continue
                meta = c.metadata or {}
                if meta.get("img_id") or meta.get("image_id") or meta.get("image_url"):
                    filtered.append(c)
            kept_short_fallback = False
            if not filtered and original_chunks:
                # Keep the longest chunk so preview stays consistent with ingestion.
                longest = max(original_chunks, key=lambda d: len((d.page_content or "").strip()))
                filtered = [longest]
                kept_short_fallback = True
            chunks = filtered
            dropped = before - len(chunks)
            if kept_short_fallback:
                kept_len = len((chunks[0].page_content or "").strip()) if chunks else 0
                logger.info(
                    "Chunk preview kept 1 short chunk (%s chars) because all chunks were shorter than %s chars",
                    kept_len,
                    min_chars,
                )
            elif dropped:
                logger.info("Chunk preview dropped %s short chunks (<%s chars)", dropped, min_chars)

        # Merge original text: use parsed pages for non-ragflow, chunks for ragflow,
        # to keep original_text aligned with chunks for frontend highlighting.
        page_texts = []
        current_pos = 0
        ragflow_chunk_start_map: dict[int, int] = {}

        if documents:
            for doc in documents:
                text = doc.page_content
                page_num = doc.metadata.get('page')
                page_texts.append({
                    'text': text,
                    'page': page_num,
                    'start': current_pos,
                    'end': current_pos + len(text)
                })
                current_pos += len(text) + 1  # +1 for separator

            full_text = "\n".join([p['text'] for p in page_texts]) if page_texts else ""
            page_start_map = {item['page']: item['start'] for item in page_texts} if page_texts else {}
        else:
            # Ragflow preset: documents is empty; build "locatable" text from chunks.
            # Note: not a strict original full text, but keeps highlighting stable.
            parts: list[str] = []
            for idx, chunk in enumerate(chunks):
                text = chunk.page_content or ""
                parts.append(text)
                ragflow_chunk_start_map[idx] = current_pos
                current_pos += len(text) + 2  # +2 for "\n\n"

            full_text = "\n\n".join(parts) if parts else ""
            page_start_map = {}

        # Build response.
        chunk_items: List[ChunkPreviewItem] = []
        for idx, chunk in enumerate(chunks):
            meta = chunk.metadata or {}
            page_num = meta.get('page') or meta.get('page_number')
            local_start = meta.get('start_char')

            if idx in ragflow_chunk_start_map:
                start_idx = ragflow_chunk_start_map[idx]
            elif local_start is not None and page_num in page_start_map:
                start_idx = page_start_map[page_num] + int(local_start)
            elif page_num in page_start_map:
                start_idx = page_start_map[page_num]
            elif meta.get("start_char") is not None:
                start_idx = int(meta.get("start_char"))
            else:
                start_idx = 0

            end_idx = start_idx + len(chunk.page_content)

            chunk_items.append(ChunkPreviewItem(
                index=idx,
                content=chunk.page_content,
                length=len(chunk.page_content),
                start_index=start_idx,
                end_index=end_idx,
                page_number=page_num,
                metadata=chunk.metadata
            ))

        return ChunkPreviewResponse(
            filename=file.filename,
            file_type=file_ext.lstrip('.'),
            file_size=file_size,
            total_chunks=len(chunks),
            total_characters=len(full_text),
            params=ChunkPreviewParams(
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                unit="tokens" if resolved_chunk_strategy == "langchain_token" else "chars",
            ),
            chunks=chunk_items,
            original_text=full_text if len(full_text) <= 100000 else None,  # Skip original text > 100 KB.
            parser_backend=resolved_backend,
            chunk_strategy=resolved_chunk_strategy
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to preview chunking: {str(e)}")
    finally:
        try:
            if temp_path.exists():
                temp_path.unlink()
        except Exception:
            pass


# ==================== MinerU batch upload API ====================

@router.post("/batch-upload/apply-urls", response_model=BatchUploadResponse)
async def apply_batch_upload_urls(
    request: BatchUploadRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    Batch request file upload URLs (MinerU online parsing).

    Use case: batch upload local files for parsing.

    Flow:
    1. Call this endpoint to request upload URLs (up to 200 files)
    2. Upload files to returned URLs (PUT; no Content-Type needed)
    3. After upload, the system submits parsing tasks automatically
    4. Query status using batch_id

    Notes:
    - Upload links are valid for 24 hours
    - No Content-Type header required for uploads
    - No manual submit needed; the system scans and processes automatically

    Example:
        # Step 1: request upload URLs
        response = requests.post("http://localhost:8000/api/v1/documents/batch-upload/apply-urls", headers={
            "X-User-ID": "demo",
        }, json={
            "files": [
                {"name": "file1.pdf", "data_id": "doc1"},
                {"name": "file2.pdf", "data_id": "doc2"}
            ]
        })

        # Step 2: upload files
        batch_id = response.json()["batch_id"]
        urls = response.json()["file_urls"]

        for i, url in enumerate(urls):
            with open(f"file{i+1}.pdf", "rb") as f:
                requests.put(url, data=f)

        # Step 3: query status
        requests.get(f"http://localhost:8000/api/v1/documents/batch-upload/status/{batch_id}", headers={
            "X-User-ID": "demo",
        })
    """
    member = DatasetService.ensure_member(db, tenant_id, account_id)
    role = (member.role or "").lower()
    if role not in EDIT_ROLES:
        raise HTTPException(status_code=403, detail="No permission to apply upload URLs")

    try:
        result = await mineru_service.aapply_batch_upload_urls(
            files=[f.model_dump() for f in request.files]
        )

        return BatchUploadResponse(
            batch_id=result["batch_id"],
            file_urls=result["file_urls"],
            files=request.files
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to apply upload URLs: {str(e)}")


@router.get("/batch-upload/status/{batch_id}", response_model=BatchTaskStatus)
async def get_batch_task_status(
    batch_id: str,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    Query batch parsing task status.

    Args:
        batch_id: Batch ID (from apply upload URLs).

    Returns:
        Task status info, including progress and completion counts.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)
    try:
        status = await mineru_service.aget_task_status(batch_id)

        # Normalize to a standard format.
        return BatchTaskStatus(
            batch_id=batch_id,
            status=status.get("status", "pending"),
            total_files=status.get("total_files", 0),
            completed_files=status.get("completed_files", 0),
            failed_files=status.get("failed_files", 0),
            progress=status.get("progress", 0),
            result_url=status.get("result_url"),
            error=status.get("error")
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get task status: {str(e)}")
