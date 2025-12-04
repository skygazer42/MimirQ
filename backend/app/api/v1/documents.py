"""
文档管理 API
"""
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, BackgroundTasks, Form
from sqlalchemy.orm import Session
from typing import List, Optional
from pathlib import Path
import shutil
import uuid
from datetime import datetime

from app.database import get_db
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
from app.services.document_processor import document_processor
from app.services.parsers import parser_factory
from app.services.chunkers import chunker_factory
from app.services.milvus_store import milvus_store
from app.services.mineru_service import mineru_service
from app.config import settings

router = APIRouter()


@router.post("/upload", response_model=DocumentUploadResponse, status_code=201)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    parser_backend: str = Form(default=settings.DEFAULT_PARSER_BACKEND),
    chunk_strategy: str = Form(default=settings.DEFAULT_CHUNK_STRATEGY),
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
    if file_ext not in settings.ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {settings.ALLOWED_EXTENSIONS}"
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

    # 3. 保存文件
    upload_dir = Path(settings.UPLOAD_DIR)
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
        filename=file.filename,
        file_type=file_ext.lstrip('.'),
        file_size=file_size,
        file_path=str(file_path),
        status='pending',
        processing_progress=0,
        metadata={
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
        db,
        resolved_parser_backend,
        resolved_chunk_strategy
    )

    return db_document


@router.get("/", response_model=DocumentList)
async def list_documents(
    skip: int = 0,
    limit: int = 20,
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    获取文档列表
    """
    query = db.query(DBDocument)

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
    db: Session = Depends(get_db)
):
    """
    获取文档详情
    """
    document = db.query(DBDocument).filter(DBDocument.id == document_id).first()

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    # 如果需要包含切片，访问一次关系以确保加载
    if include_chunks:
        _ = document.chunks

    return document


@router.get("/{document_id}/status", response_model=DocumentStatus)
async def get_document_status(
    document_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    """
    获取文档处理状态（用于轮询）
    """
    document = db.query(DBDocument).filter(DBDocument.id == document_id).first()

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

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
    db: Session = Depends(get_db)
):
    """
    删除文档
    """
    document = db.query(DBDocument).filter(DBDocument.id == document_id).first()

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    # 1. 删除 Milvus 中的向量
    milvus_store.delete_by_document_id(document_id)

    # 2. 删除本地文件
    try:
        file_path = Path(document.file_path)
        if file_path.exists():
            file_path.unlink()
    except Exception as e:
        print(f"Warning: Failed to delete file: {str(e)}")

    # 3. 删除数据库记录（级联删除 chunks）
    db.delete(document)
    db.commit()

    return None


@router.post("/preview", response_model=DocumentParsePreview)
async def preview_document(
    file: UploadFile = File(...),
    parser_backend: str = Form(default=settings.DEFAULT_PARSER_BACKEND),
    chunk_strategy: str = Form(default=settings.DEFAULT_CHUNK_STRATEGY),
):
    """
    文档解析预览接口

    仅解析文档并返回结构化片段，不创建文档记录或入库。
    适用于前端根据解析结果自定义切片。
    """
    # 验证文件类型
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in settings.ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {settings.ALLOWED_EXTENSIONS}"
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
    upload_dir = Path(settings.UPLOAD_DIR) / "preview"
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
    # 基本校验
    if not request.chunks:
        raise HTTPException(status_code=400, detail="Chunks cannot be empty")

    # 校验文件类型
    file_type_with_dot = f".{request.file_type.lower()}"
    if file_type_with_dot not in settings.ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {request.file_type}"
        )

    # 创建文档记录
    document_id = uuid.uuid4()
    db_document = DBDocument(
        id=document_id,
        filename=request.filename,
        file_type=request.file_type.lower(),
        file_size=request.file_size,
        # 手动切片的文档没有真实文件路径，使用占位符
        file_path=f"manual://{document_id}",
        status='processing',
        processing_progress=0,
        current_stage='embedding',
        metadata=request.metadata or {}
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

        # 生成 Embeddings 并写入 Milvus
        from app.services.milvus_store import milvus_store as _milvus_store

        vector_ids = _milvus_store.add_documents(milvus_docs, document_id)

        # 写入 PostgreSQL 的 DocumentChunk
        from app.models.document import DocumentChunk as DBDocumentChunk

        for idx, (chunk, vector_id) in enumerate(zip(request.chunks, vector_ids)):
            db_chunk = DBDocumentChunk(
                document_id=document_id,
                chunk_index=idx,
                content=chunk.content,
                page_number=chunk.page_number,
                start_char=chunk.start_char,
                end_char=chunk.end_char,
                metadata=milvus_docs[idx]["metadata"],
                vector_id=vector_id
            )
            db.add(db_chunk)

        db.commit()

        # 更新文档统计信息和状态
        db_document.chunk_count = len(request.chunks)
        db_document.total_characters = total_characters
        db_document.status = 'completed'
        db_document.processing_progress = 100
        db_document.current_stage = 'completed'
        db.commit()
        db.refresh(db_document)

        # 重建 BM25 索引
        await document_processor._rebuild_bm25_index(db)

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
    if file_ext not in settings.ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {settings.ALLOWED_EXTENSIONS}"
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
    upload_dir = Path(settings.UPLOAD_DIR) / "preview"
    upload_dir.mkdir(parents=True, exist_ok=True)
    temp_path = upload_dir / f"{uuid.uuid4()}{file_ext}"

    try:
        with temp_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # 解析文档
        documents, resolved_backend = parser_factory.parse(temp_path, parser_backend=parser_backend)

        resolved_chunk_strategy = chunker_factory.resolve_strategy(chunk_strategy)
        chunker = chunker_factory.get_chunker(
            resolved_chunk_strategy,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap
        )
        chunks = chunker.split_documents(documents)

        # 合并所有页面的文本（保留页码信息）
        page_texts = []
        current_pos = 0

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

        full_text = "\n".join([p['text'] for p in page_texts])
        page_start_map = {item['page']: item['start'] for item in page_texts}

        # 构建响应
        chunk_items: List[ChunkPreviewItem] = []
        for idx, chunk in enumerate(chunks):
            page_num = chunk.metadata.get('page') or chunk.metadata.get('page_number')
            local_start = chunk.metadata.get('start_char')
            start_idx = None

            if local_start is not None and page_num in page_start_map:
                start_idx = page_start_map[page_num] + int(local_start)
            elif page_num in page_start_map:
                start_idx = page_start_map[page_num]
            else:
                # Fallback：无法定位页码时使用前一段末尾
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
