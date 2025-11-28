"""
文档管理 API
"""
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, BackgroundTasks
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
    ManualDocumentCreate
)
from app.services.document_processor import document_processor
from app.services.milvus_store import milvus_store
from app.config import settings

router = APIRouter()


@router.post("/upload", response_model=DocumentUploadResponse, status_code=201)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
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
        metadata={}
    )

    db.add(db_document)
    db.commit()
    db.refresh(db_document)

    # 5. 后台处理文档
    background_tasks.add_task(
        document_processor.process_document,
        file_path,
        file_id,
        db
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

        from app.services.parsers import parser_factory

        documents = parser_factory.parse(temp_path)

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
            segments=segments
        )
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
