"""
文档管理 API
"""
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, BackgroundTasks, Form, Body
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID
from pathlib import Path
import shutil
import uuid
from datetime import datetime

from langchain_core.documents import Document as LCDocument

from app.core.database import get_db
from app.models.document import Document as DBDocument
from app.schemas.document import (
    DocumentUploadResponse,
    DocumentList,
    DocumentDetail,
    DocumentStatus,
    DocumentParsePreview,
    ParsedSegment,
    ManualDocumentCreate,
    ChunkPreviewParams,
    ChunkPreviewItem,
    ChunkPreviewResponse,
    BatchUploadRequest,
    BatchUploadResponse,
    BatchTaskStatus
)
from app.parsing.processors.document_processor import document_processor
from app.parsing.factory import parser_factory
from app.parsing.chunking.factory import chunker_factory
from app.storage.vector.milvus import milvus_store
from app.storage.vector.router import get_vector_store
from app.storage.search.hybrid_retriever import hybrid_retriever
from app.services.mineru_service import mineru_service
from app.services.dataset_service import DatasetService
from app.storage.object.minio import minio_service
from app.models.dataset import Dataset, DatasetPermission, DatasetPermissionEnum
from app.core.config import settings
from fastapi.responses import FileResponse, RedirectResponse
from app.dependencies.tenant import get_tenant_id
from app.dependencies.auth import get_current_account_id
from sqlalchemy import or_, false

router = APIRouter()


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
    DatasetService.ensure_member(db, tenant_id, account_id)

    datasets = db.query(Dataset).filter(Dataset.tenant_id == tenant_id).order_by(Dataset.created_at.asc()).all()
    for ds in datasets:
        try:
            DatasetService.assert_dataset_writable(db, ds, account_id)
            return ds
        except HTTPException:
            continue

    # Auto-create a default dataset (best-effort, dev-friendly).
    return DatasetService.create_dataset(
        db=db,
        tenant_id=tenant_id,
        name="默认知识库",
        description="自动创建（未指定 dataset_id）",
        permission=DatasetPermissionEnum.ALL_TEAM_MEMBERS,
        owner_id=account_id,
        partial_members=[],
    )


@router.post("/upload", response_model=DocumentUploadResponse, status_code=201)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    parser_backend: str = Form(default=settings.DEFAULT_PARSER_BACKEND),
    chunk_strategy: str = Form(default=settings.DEFAULT_CHUNK_STRATEGY),
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

    # 1. 验证文件类型
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in settings.allowed_extensions_list:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {settings.allowed_extensions_list}"
        )

    # 2. 验证文件大小
    file.file.seek(0, 2)  # 移动到文件末尾
    file_size = file.file.tell()
    file.file.seek(0)  # 重置到开头

    if file_size > settings.MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Max size: {settings.MAX_FILE_SIZE / 1024 / 1024}MB"
        )

    try:
        resolved_parser_backend = parser_factory.resolve_backend(file_ext, parser_backend)
        resolved_chunk_strategy = chunker_factory.resolve_strategy(chunk_strategy)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # 权限检查
    dataset = _resolve_writable_dataset(db, tenant_id, account_id, dataset_id)

    # 3. 保存文件
    upload_dir = Path(settings.UPLOAD_DIR) / str(tenant_id)
    upload_dir.mkdir(parents=True, exist_ok=True)

    # 生成唯一文件名
    file_id = uuid.uuid4()
    file_path = upload_dir / f"{file_id}{file_ext}"

    try:
        with file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")

    # 4. 创建数据库记录
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
        doc_metadata={
            "parser_backend": resolved_parser_backend,
            "parser_backend_requested": (parser_backend or "").lower(),
            "chunk_strategy": resolved_chunk_strategy,
            "chunk_strategy_requested": (chunk_strategy or "").lower(),
        }
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
        datasets = db.query(Dataset).filter(Dataset.tenant_id == tenant_id).all()
        allowed_dataset_ids: set[UUID] = set()
        partial_dataset_ids: set[UUID] = set()
        for ds in datasets:
            if ds.owner_id == account_id:
                allowed_dataset_ids.add(ds.id)
                continue
            if ds.permission == DatasetPermissionEnum.ALL_TEAM_MEMBERS:
                allowed_dataset_ids.add(ds.id)
                continue
            if ds.permission == DatasetPermissionEnum.PARTIAL_MEMBERS:
                partial_dataset_ids.add(ds.id)

        if partial_dataset_ids:
            rows = (
                db.query(DatasetPermission.dataset_id)
                .filter(
                    DatasetPermission.tenant_id == tenant_id,
                    DatasetPermission.account_id == account_id,
                    DatasetPermission.dataset_id.in_(list(partial_dataset_ids)),
                )
                .all()
            )
            allowed_dataset_ids.update(row[0] for row in rows)

        query = query.filter(
            or_(
                DBDocument.dataset_id.is_(None),
                DBDocument.dataset_id.in_(list(allowed_dataset_ids)) if allowed_dataset_ids else false(),
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
        try:
            from app.models.document import DocumentChunk
            chunks = db.query(DocumentChunk).filter(
                DocumentChunk.document_id == document_id
            ).all()
            
            for chunk in chunks:
                img_id = chunk.doc_metadata.get("img_id") if chunk.doc_metadata else None
                if img_id:
                    try:
                        minio_service.delete_image(img_id, extension="jpg")
                    except Exception as e:
                        print(f"[WARN] 删除 MinIO 图片失败 {img_id}: {e}")
        except Exception as exc:
            print(f"[WARN] MinIO 图片删除过程失败: {exc}")

    # 2. 删除向量库中的向量（按后端切换）
    try:
        get_vector_store().delete_by_document_id(document_id, tenant_id=tenant_id)
    except Exception as exc:
        print(f"[WARN]  Failed to delete vectors: {exc}")

    # 3. 删除本地文件
    try:
        file_path = Path(document.file_path)
        if file_path.exists():
            file_path.unlink()
    except Exception as e:
        print(f"Warning: Failed to delete file: {str(e)}")

    # 4. 删除数据库记录（级联删除 chunks）
    db.delete(document)
    db.commit()

    # 5. 移除 BM25 索引中的切片（内存索引）
    try:
        hybrid_retriever.remove_document_from_bm25_index(document_id, tenant_id=tenant_id)
    except Exception as exc:
        print(f"[WARN]  Failed to update BM25 index after deletion: {exc}")

    return None


@router.get("/image/{image_id}")
async def get_image(image_id: str, tenant_id: UUID = Depends(get_tenant_id)):
    """
    æ ¹æ“š image_id è¿”å›žä¿å­˜çš„å›¾ç‰‡ã€‚
    æ ‡å‡†ä½ç½®ï¼š{UPLOAD_DIR}/images/{image_id}.png
    """
    images_dir = Path(settings.UPLOAD_DIR) / str(tenant_id) / "images"
    file_path = images_dir / f"{image_id}.png"
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(file_path, media_type="image/png")


@router.get("/image-url/{img_id}")
async def get_image_url(img_id: str):
    """
    根据 img_id（格式：{tenant_id}:{dataset_id}:{document_id}:{chunk_index}）获取 MinIO 预签名 URL。
    返回 302 重定向到图片 URL。
    """
    if not settings.MINIO_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="MinIO 未启用，无法获取图片 URL"
        )

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
    tenant_id: UUID = Depends(get_tenant_id),
):
    """
    文档解析预览接口

    仅解析文档并返回结构化片段，不创建文档记录或入库。
    适用于前端根据解析结果自定义切片。
    """
    # 验证文件类型
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in settings.allowed_extensions_list:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {settings.allowed_extensions_list}"
        )

    # 验证文件大小
    file.file.seek(0, 2)
    file_size = file.file.tell()
    file.file.seek(0)

    if file_size > settings.MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Max size: {settings.MAX_FILE_SIZE / 1024 / 1024}MB"
        )

    # 将文件保存到临时路径进行解析
    upload_dir = Path(settings.UPLOAD_DIR) / str(tenant_id) / "preview"
    upload_dir.mkdir(parents=True, exist_ok=True)

    temp_path = upload_dir / f"{uuid.uuid4()}{file_ext}"

    try:
        with temp_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        documents, resolved_backend = parser_factory.parse(temp_path, parser_backend=parser_backend)

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
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse document: {str(e)}")
    finally:
        try:
            if temp_path.exists():
                temp_path.unlink()
        except Exception:
            # 临时文件删除失败不影响主流程
            pass


@router.post("/manual", response_model=DocumentUploadResponse, status_code=201)
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
        doc_metadata=request.metadata or {}
    )

    db.add(db_document)
    db.commit()
    db.refresh(db_document)

    try:
        # 构建用于向量化的文档列表
        milvus_docs: List[dict] = []
        total_characters = 0

        for idx, chunk in enumerate(request.chunks):
            metadata = {
                "source": request.filename,
                "file_type": request.file_type.lower(),
                "page": chunk.page_number,
                "document_id": str(document_id),
                "chunk_index": idx,
                **(chunk.metadata or {})
            }

            content = chunk.content or ""
            total_characters += len(content)

            milvus_docs.append({
                "content": content,
                "metadata": metadata
            })

        # 生成 Embeddings 并写入向量库（支持后端切换）
        vector_ids = get_vector_store().add_documents(milvus_docs, document_id, tenant_id)

        # 写入 PostgreSQL 的 DocumentChunk
        from app.models.document import DocumentChunk as DBDocumentChunk

        db_chunks = []
        for idx, (chunk, vector_id) in enumerate(zip(request.chunks, vector_ids)):
            db_chunk = DBDocumentChunk(
                tenant_id=tenant_id,
                document_id=document_id,
                chunk_index=idx,
                content=chunk.content,
                page_number=chunk.page_number,
                start_char=chunk.start_char,
                end_char=chunk.end_char,
                doc_metadata=milvus_docs[idx]["metadata"],
                vector_id=vector_id
            )
            db.add(db_chunk)
            db_chunks.append(db_chunk)

        db.commit()

        # 更新文档统计信息和状态
        db_document.chunk_count = len(request.chunks)
        db_document.total_characters = total_characters
        db_document.status = 'completed'
        db_document.processing_progress = 100
        db_document.current_stage = 'completed'
        db.commit()
        db.refresh(db_document)

        # 增量更新 BM25 索引（避免全量扫描）
        try:
            bm25_docs = []
            for db_chunk in db_chunks:
                meta = dict(db_chunk.doc_metadata or {})
                meta.setdefault("tenant_id", str(tenant_id))
                meta.setdefault("document_id", str(document_id))
                meta.setdefault("chunk_index", db_chunk.chunk_index)
                meta.setdefault("source", meta.get("source", request.filename))
                meta.setdefault("page", db_chunk.page_number)
                bm25_docs.append(LCDocument(page_content=db_chunk.content, id=str(db_chunk.id), metadata=meta))
            hybrid_retriever.upsert_bm25_documents(bm25_docs, tenant_id=tenant_id)
        except Exception as exc:
            print(f"[WARN]  Failed to update BM25 index incrementally: {exc}")

        return db_document

    except Exception as e:
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
    tenant_id: UUID = Depends(get_tenant_id),
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

    # 验证文件大小
    file.file.seek(0, 2)
    file_size = file.file.tell()
    file.file.seek(0)

    if file_size > settings.MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Max size: {settings.MAX_FILE_SIZE / 1024 / 1024}MB"
        )

    # 保存到临时路径
    upload_dir = Path(settings.UPLOAD_DIR) / str(tenant_id) / "preview"
    upload_dir.mkdir(parents=True, exist_ok=True)
    temp_path = upload_dir / f"{uuid.uuid4()}{file_ext}"

    try:
        with temp_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        resolved_chunk_strategy = chunker_factory.resolve_strategy(chunk_strategy)

        # ragflow 预设走独立分支（自解析 + 切块）
        if resolved_chunk_strategy in chunker_factory.RAGFLOW_STRATEGIES:
            from app.parsing.processors.document_processor import document_processor
            chunks = await asyncio.to_thread(
                document_processor._ragflow_chunk_file,
                temp_path,
                resolved_chunk_strategy
            )
            resolved_backend = "ragflow"
            documents = []  # ragflow 已自处理
        else:
            # 解析文档
            documents, resolved_backend = parser_factory.parse(temp_path, parser_backend=parser_backend)

            chunker = chunker_factory.get_chunker(
                resolved_chunk_strategy,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap
            )
            chunks = chunker.split_documents(documents)

        # 合并所有页面的文本（保留页码信息）
        page_texts = []
        current_pos = 0

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

        # 构建响应
        chunk_items: List[ChunkPreviewItem] = []
        for idx, chunk in enumerate(chunks):
            meta = chunk.metadata or {}
            page_num = meta.get('page') or meta.get('page_number')
            local_start = meta.get('start_char')

            if local_start is not None and page_num in page_start_map:
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
async def apply_batch_upload_urls(request: BatchUploadRequest):
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
async def get_batch_task_status(batch_id: str):
    """
    查询批量解析任务状态

    Args:
        batch_id: 批次 ID（从申请上传 URL 接口获得）

    Returns:
        任务状态信息，包括进度、完成数量等
    """
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
