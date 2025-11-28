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
    DocumentStatus
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

    # 如果需要包含切片
    if include_chunks:
        # 由于关系已定义，可以直接访问 document.chunks
        pass

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
