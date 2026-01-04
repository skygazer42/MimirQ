"""
文档管理 API
"""
import asyncio
import re
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, BackgroundTasks, Form, Body
from sqlalchemy.orm import Session
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
    BatchTaskStatus
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
from sqlalchemy import or_, false, and_
from app.rag.core.logging import get_logger
from app.rag.preprocessing.processor import governance_processor
from app.api.utils.upload import save_upload_file


logger = get_logger("api.documents")

router = APIRouter()

# 文件名安全字符：字母、数字、中文、日文、韩文、空格、点、下划线、连字符
SAFE_FILENAME_PATTERN = re.compile(r'^[a-zA-Z0-9\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af._\-\s]+$')


def _validate_filename(filename: str) -> None:
    """验证文件名安全性"""
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

    # 验证用户是否有权限创建数据集
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
        name="默认知识库",
        description="自动创建（未指定 dataset_id）",
        permission=DatasetPermissionEnum.ONLY_ME,  # 限制权限，避免权限提升
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
    上传文档

    流程：
    1. 验证文件类型和大小
    2. 保存文件到本地
    3. 创建数据库记录
    4. 后台异步处理文档（解析、切片、向量化）
    """

    # 0. 验证文件名安全性
    _validate_filename(file.filename)

    # 1. 验证文件类型
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in settings.allowed_extensions_list:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {settings.allowed_extensions_list}"
        )

    try:
        requested_parser_backend = (parser_backend or "").strip().lower()
        effective_parser_backend = parser_backend
        if file_ext == ".pdf" and requested_parser_backend == "mineru":
            mineru_available = bool(
                settings.MINERU_ENABLED
                and (settings.MINERU_API_TOKEN or settings.MINERU_LOCAL_SERVER_URL)
            )
            if not mineru_available:
                effective_parser_backend = "auto"
                requested_parser_backend = "auto"

        if file_ext == ".pdf" and requested_parser_backend in {"", "auto"}:
            # Keep "auto" for background routing (quality scoring happens in DocumentProcessor).
            resolved_parser_backend = "auto"
        else:
            resolved_parser_backend = parser_factory.resolve_backend(file_ext, effective_parser_backend)
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

    # 权限检查
    dataset = _resolve_writable_dataset(db, tenant_id, account_id, dataset_id)

    # 3. 保存文件
    upload_dir = Path(settings.UPLOAD_DIR) / str(tenant_id)
    upload_dir.mkdir(parents=True, exist_ok=True)

    # 生成唯一文件名
    file_id = uuid.uuid4()
    file_path = upload_dir / f"{file_id}{file_ext}"

    try:
        file_size = await save_upload_file(file, file_path, max_bytes=settings.MAX_FILE_SIZE)
    except HTTPException:
        raise

    # 4. 创建数据库记录
    doc_metadata = {
        "parser_backend": resolved_parser_backend,
        "parser_backend_requested": (parser_backend or "").lower(),
        "chunk_strategy": resolved_chunk_strategy,
        "chunk_strategy_requested": (chunk_strategy or "").lower(),
    }
    if pipeline_metadata:
        doc_metadata["pipeline"] = pipeline_metadata

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

    # 5. 后台处理文档
    background_tasks.add_task(
        document_processor.process_document,
        file_path,
        file_id,
        tenant_id,
        resolved_parser_backend,
        resolved_chunk_strategy
    )

    return db_document


@router.post("/upload-batch", status_code=201)
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
    批量上传文档（并发优化版）
    
    支持同时上传多个文档，使用并发处理以提升性能。
    
    Args:
        files: 文档文件列表
        max_concurrent: 最大并发处理数，默认5
        其他参数同单文件上传接口
    
    Returns:
        {
            "total": 总文件数,
            "successful": 成功上传的文档列表,
            "failed": 失败的文件列表（包含错误信息）
        }
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")
    
    if len(files) > 50:
        raise HTTPException(status_code=400, detail="Too many files. Maximum 50 files per batch.")
    
    # 控制并发数
    max_concurrent = min(max_concurrent, 10)  # 最多10个并发
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def process_single_file(file: UploadFile) -> dict:
        """处理单个文件的上传"""
        async with semaphore:
            try:
                # 验证文件名
                _validate_filename(file.filename)
                
                # 验证文件类型
                file_ext = Path(file.filename).suffix.lower()
                if file_ext not in settings.allowed_extensions_list:
                    return {
                        "success": False,
                        "filename": file.filename,
                        "error": f"Unsupported file type: {file_ext}"
                    }
                
                # 解析器验证
                requested_parser_backend = (parser_backend or "").strip().lower()
                effective_parser_backend = parser_backend
                if file_ext == ".pdf" and requested_parser_backend == "mineru":
                    mineru_available = bool(
                        settings.MINERU_ENABLED
                        and (settings.MINERU_API_TOKEN or settings.MINERU_LOCAL_SERVER_URL)
                    )
                    if not mineru_available:
                        effective_parser_backend = "auto"
                        requested_parser_backend = "auto"
                
                if file_ext == ".pdf" and requested_parser_backend in {"", "auto"}:
                    resolved_parser_backend = "auto"
                else:
                    resolved_parser_backend = parser_factory.resolve_backend(file_ext, effective_parser_backend)
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
                
                # 权限检查（在 semaphore 外部已完成）
                # 保存文件
                upload_dir = Path(settings.UPLOAD_DIR) / str(tenant_id)
                upload_dir.mkdir(parents=True, exist_ok=True)
                
                file_id = uuid.uuid4()
                file_path = upload_dir / f"{file_id}{file_ext}"
                
                file_size = await save_upload_file(file, file_path, max_bytes=settings.MAX_FILE_SIZE)
                
                # 创建数据库记录
                doc_metadata = {
                    "parser_backend": resolved_parser_backend,
                    "parser_backend_requested": (parser_backend or "").lower(),
                    "chunk_strategy": resolved_chunk_strategy,
                    "chunk_strategy_requested": (chunk_strategy or "").lower(),
                }
                if pipeline_metadata:
                    doc_metadata["pipeline"] = pipeline_metadata
                
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
                
                # 后台处理文档
                background_tasks.add_task(
                    document_processor.process_document,
                    file_path,
                    file_id,
                    tenant_id,
                    resolved_parser_backend,
                    resolved_chunk_strategy
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
    
    # 权限检查（一次性完成）
    dataset = _resolve_writable_dataset(db, tenant_id, account_id, dataset_id)
    
    # 并发处理所有文件
    tasks = [process_single_file(file) for file in files]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # 处理异常结果
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
    获取文档列表
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    query = db.query(DBDocument).filter(DBDocument.tenant_id == tenant_id)

    if dataset_id:
        dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
        DatasetService.assert_dataset_readable(db, dataset, account_id)
        query = query.filter(DBDocument.dataset_id == dataset_id)
    else:
        # No dataset_id: return all documents the user can read within the tenant.
        # 优化：使用数据库级别的过滤，避免 N+1 查询

        # 子查询：获取 PARTIAL_MEMBERS 权限中用户有权访问的数据集 ID
        partial_member_subq = (
            db.query(DatasetPermission.dataset_id)
            .filter(
                DatasetPermission.tenant_id == tenant_id,
                DatasetPermission.account_id == account_id,
            )
            .subquery()
        )

        # 构建允许访问的数据集过滤条件
        allowed_dataset_filter = or_(
            # 用户是所有者
            Dataset.owner_id == account_id,
            # ALL_TEAM_MEMBERS 权限
            Dataset.permission == DatasetPermissionEnum.ALL_TEAM_MEMBERS,
            # PARTIAL_MEMBERS 权限且用户在列表中
            and_(
                Dataset.permission == DatasetPermissionEnum.PARTIAL_MEMBERS,
                Dataset.id.in_(partial_member_subq)
            )
        )

        # 获取允许访问的数据集 ID
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

    # 状态过滤
    if status and status != 'all':
        query = query.filter(DBDocument.status == status)

    # 总数
    total = query.count()

    # 分页
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
    获取文档详情
    """
    DatasetService.ensure_member(db, tenant_id, account_id)
    document = db.query(DBDocument).filter(
        DBDocument.id == document_id,
        DBDocument.tenant_id == tenant_id
    ).first()

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    # 权限检查
    if document.dataset_id:
        ds = DatasetService.get_dataset(db, tenant_id, document.dataset_id)
        DatasetService.assert_dataset_readable(db, ds, account_id)

    # 如果需要包含切片，访问一次关系以确保加载
    if include_chunks:
        _ = document.chunks
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
    获取文档处理状态（用于轮询）
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
    删除文档
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

    # 1. 删除 MinIO 中的图片（如果启用）
    if settings.MINIO_ENABLED:
        img_ids: set[str] = set()

        # 优先使用文档级聚合列表（避免遗漏 ZIP/内嵌图片等"非 chunk_index"资源）
        doc_meta = document.doc_metadata or {}
        doc_img_ids = doc_meta.get("img_ids")
        if isinstance(doc_img_ids, list):
            for v in doc_img_ids:
                if isinstance(v, str) and v.strip():
                    img_ids.add(v)

        # 兼容：逐 chunk 删除（老数据可能没有 documents.metadata.img_ids）
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

    # 2. 删除向量库中的向量（按后端切换）
    Indexer(db).delete_all(tenant_id=tenant_id, document_id=document_id, commit=False)

    # 3. 删除本地文件
    try:
        file_path = Path(document.file_path)
        if file_path.exists():
            file_path.unlink()
    except Exception as e:
        logger.warning("Failed to delete file: %s", e)

    # 4. 删除数据库记录（级联删除 chunks）
    db.delete(document)
    db.commit()

    # 5. 移除 BM25 索引中的切片（内存索引）
    return None


@router.get("/image/{image_id}")
async def get_image(
    image_id: str,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    根据 image_id 返回保存的图片。
    标准位置：{UPLOAD_DIR}/images/{image_id}.png
    """
    DatasetService.ensure_member(db, tenant_id, account_id)
    images_dir = Path(settings.UPLOAD_DIR) / str(tenant_id) / "images"
    # 防止路径穿越：仅允许 UUID / 32位十六进制（内部生成的 image_id）
    try:
        safe_id = uuid.UUID(image_id).hex
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found")

    images_dir_resolved = images_dir.resolve(strict=False)
    file_path = (images_dir / f"{safe_id}.png").resolve(strict=False)

    # 安全检查：确保 file_path 在 images_dir 目录下（防止路径穿越）
    if not str(file_path).startswith(str(images_dir_resolved) + "/"):
        raise HTTPException(status_code=404, detail="Image not found")

    # 检查文件是否存在且为普通文件
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
    根据 img_id（格式：{tenant_id}:{dataset_id}:{document_id}:{chunk_index}）获取 MinIO 预签名 URL。
    返回 302 重定向到图片 URL。
    """
    if not settings.MINIO_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="MinIO 未启用，无法获取图片 URL"
        )

    DatasetService.ensure_member(db, tenant_id, account_id)

    # 基础访问控制：确保 img_id 前缀租户与请求租户一致（兼容老格式 dataset-chunk 不做限制）
    def _tenant_from_img_id(val: str) -> Optional[str]:
        if ":" in val:
            parts = val.split(":", 1)
            return parts[0]
        return None

    tenant_in_img = _tenant_from_img_id(img_id)
    if tenant_in_img and tenant_in_img != str(tenant_id):
        raise HTTPException(status_code=403, detail="Image access denied for this tenant")

    # 权限校验：尽可能根据 img_id 解析出 dataset/document，做 dataset 级权限控制
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
        # 直接重定向到 MinIO 预签名 URL
        return RedirectResponse(url=url, status_code=302)
    except Exception as e:
        raise HTTPException(
            status_code=404,
            detail=f"图片不存在或获取失败: {str(e)}"
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
    文档解析预览接口

    仅解析文档并返回结构化片段，不创建文档记录或入库。
    适用于前端根据解析结果自定义切片。
    """
    DatasetService.ensure_member(db, tenant_id, account_id)
    # 验证文件类型
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in settings.allowed_extensions_list:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {settings.allowed_extensions_list}"
        )

    # 将文件保存到临时路径进行解析
    upload_dir = Path(settings.UPLOAD_DIR) / str(tenant_id) / "preview"
    upload_dir.mkdir(parents=True, exist_ok=True)

    temp_path = upload_dir / f"{uuid.uuid4()}{file_ext}"

    try:
        file_size = await save_upload_file(file, temp_path, max_bytes=settings.MAX_FILE_SIZE)

        if file_ext == ".pdf":
            requested = (parser_backend or "").strip().lower()
            if requested == "mineru":
                mineru_available = bool(
                    settings.MINERU_ENABLED
                    and (settings.MINERU_API_TOKEN or settings.MINERU_LOCAL_SERVER_URL)
                )
                if not mineru_available:
                    requested = "auto"

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


@router.post("/manual", response_model=DocumentDetail, status_code=201)
async def create_document_with_manual_chunks(
    request: ManualDocumentCreate,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db)
):
    """
    基于前端自定义切片创建文档

    流程：
    1. 创建文档记录（状态为 processing）
    2. 使用传入的 chunks 生成 Embeddings 并存入 Milvus
    3. 将 chunks 写入 PostgreSQL
    4. 重建 BM25 索引
    5. 更新文档状态为 completed
    """
    # 权限检查
    dataset = _resolve_writable_dataset(db, tenant_id, account_id, request.dataset_id)

    # 基本校验
    if not request.chunks:
        raise HTTPException(status_code=400, detail="Chunks cannot be empty")

    # 校验文件类型
    file_type_with_dot = f".{request.file_type.lower()}"
    if file_type_with_dot not in settings.allowed_extensions_list:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {request.file_type}"
        )

    # 创建文档记录
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
        # 手动切片的文档没有真实文件路径，使用占位符
        file_path=f"manual://{document_id}",
        status='processing',
        processing_progress=0,
        current_stage='embedding',
        doc_metadata=doc_metadata,
    )

    db.add(db_document)
    db.flush()  # 仅 flush，不 commit，便于后续回滚

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

        # 更新文档统计信息和状态
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
                # KG 抽取是可选增强，失败不影响主流程（避免“已入库但标记 failed”）。
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
    切块预览接口

    上传文件并使用指定参数进行切块预览，不存入数据库。
    返回切块结果及每个块在原文中的位置，用于前端高亮展示。

    Args:
        file: 上传的文件
        chunk_size: 切块大小 (100-4000)
        chunk_overlap: 重叠大小 (0-1000)

    Returns:
        切块预览结果，包含每个块的内容和位置信息
    """
    DatasetService.ensure_member(db, tenant_id, account_id)
    # 参数校验
    if chunk_size < 100 or chunk_size > 4000:
        raise HTTPException(status_code=400, detail="chunk_size must be between 100 and 4000")
    if chunk_overlap < 0 or chunk_overlap > 1000:
        raise HTTPException(status_code=400, detail="chunk_overlap must be between 0 and 1000")
    if chunk_overlap >= chunk_size:
        raise HTTPException(status_code=400, detail="chunk_overlap must be less than chunk_size")

    # 验证文件类型
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in settings.allowed_extensions_list:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {settings.allowed_extensions_list}"
        )

    # 保存到临时路径
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

        # ragflow 预设走独立分支（自解析 + 切块）
        if resolved_chunk_strategy in chunker_factory.RAGFLOW_STRATEGIES:
            from app.parsing.processors.processor import document_processor
            chunks = await asyncio.to_thread(
                document_processor._ragflow_chunk_file,
                temp_path,
                resolved_chunk_strategy
            )
            resolved_backend = "ragflow"
            documents = []  # ragflow 已自处理
            if pipeline_effective.governance_enabled:
                chunks, _stats = governance_processor.clean_documents(
                    chunks,
                    **governance_kwargs,
                )
        else:
            # 解析文档
            if file_ext == ".pdf":
                requested = (parser_backend or "").strip().lower()
                if requested == "mineru":
                    mineru_available = bool(
                        settings.MINERU_ENABLED
                        and (settings.MINERU_API_TOKEN or settings.MINERU_LOCAL_SERVER_URL)
                    )
                    if not mineru_available:
                        requested = "auto"

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
            filtered = []
            for c in chunks:
                content = (c.page_content or "").strip()
                if len(content) >= min_chars:
                    filtered.append(c)
                    continue
                meta = c.metadata or {}
                if meta.get("img_id") or meta.get("image_id") or meta.get("image_url"):
                    filtered.append(c)
            chunks = filtered
            dropped = before - len(chunks)
            if dropped:
                logger.info("Chunk preview dropped %s short chunks (<%s chars)", dropped, min_chars)

        # 合并原文：非 ragflow 分支用解析后的 pages；ragflow 预设分支用 chunks 拼接，
        # 以保证 original_text 与 chunks 一致，便于前端高亮定位。
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
            # ragflow 预设：documents 为空，只能从 chunks 构造“可定位”的原文。
            # 注意：这不是严格意义上的原始文档全文，但能确保前端定位稳定。
            parts: list[str] = []
            for idx, chunk in enumerate(chunks):
                text = chunk.page_content or ""
                parts.append(text)
                ragflow_chunk_start_map[idx] = current_pos
                current_pos += len(text) + 2  # +2 for "\n\n"

            full_text = "\n\n".join(parts) if parts else ""
            page_start_map = {}

        # 构建响应
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
            params=ChunkPreviewParams(chunk_size=chunk_size, chunk_overlap=chunk_overlap),
            chunks=chunk_items,
            original_text=full_text if len(full_text) <= 100000 else None,  # 超过 100KB 不返回原文
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


# ==================== MinerU 批量上传 API ====================

@router.post("/batch-upload/apply-urls", response_model=BatchUploadResponse)
async def apply_batch_upload_urls(
    request: BatchUploadRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    批量申请文件上传 URL（MinerU 在线解析）

    适用于本地文件批量上传解析的场景。

    使用流程：
    1. 调用此接口申请上传 URL（最多 200 个文件）
    2. 使用返回的 URL 上传文件（PUT 请求，无需设置 Content-Type）
    3. 上传完成后，系统自动提交解析任务
    4. 使用 batch_id 查询解析状态

    注意事项：
    - 上传链接有效期为 24 小时
    - 上传文件时无需设置 Content-Type 请求头
    - 文件上传完成后无需手动提交任务，系统会自动扫描并处理

    Example:
        # Step 1: 申请上传 URL
        response = requests.post("/api/v1/documents/batch-upload/apply-urls", json={
            "files": [
                {"name": "file1.pdf", "data_id": "doc1"},
                {"name": "file2.pdf", "data_id": "doc2"}
            ]
        })

        # Step 2: 上传文件
        batch_id = response.json()["batch_id"]
        urls = response.json()["file_urls"]

        for i, url in enumerate(urls):
            with open(f"file{i+1}.pdf", "rb") as f:
                requests.put(url, data=f)

        # Step 3: 查询状态
        requests.get(f"/api/v1/documents/batch-upload/status/{batch_id}")
    """
    member = DatasetService.ensure_member(db, tenant_id, account_id)
    role = (member.role or "").lower()
    if role not in EDIT_ROLES:
        raise HTTPException(status_code=403, detail="No permission to apply upload URLs")

    try:
        result = mineru_service.apply_batch_upload_urls(
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
    查询批量解析任务状态

    Args:
        batch_id: 批次 ID（从申请上传 URL 接口获得）

    Returns:
        任务状态信息，包括进度、完成数量等
    """
    DatasetService.ensure_member(db, tenant_id, account_id)
    try:
        status = mineru_service.get_task_status(batch_id)

        # 转换为标准化格式
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
