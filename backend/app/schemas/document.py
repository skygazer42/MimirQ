"""
文档相关 Pydantic Schema
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID


class DocumentUploadResponse(BaseModel):
    """文档上传响应"""
    id: UUID
    filename: str
    file_type: str
    file_size: int
    status: str
    created_at: datetime
    metadata: Dict[str, Any] = {}

    class Config:
        from_attributes = True


class DocumentChunkSchema(BaseModel):
    """文档块"""
    id: UUID
    content: str
    page_number: Optional[int] = None
    chunk_index: int
    metadata: Dict[str, Any] = {}

    class Config:
        from_attributes = True


class DocumentDetail(BaseModel):
    """文档详情"""
    id: UUID
    filename: str
    file_type: str
    file_size: int
    status: str
    processing_progress: int
    chunk_count: int
    total_characters: int
    created_at: datetime
    updated_at: datetime
    processed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = {}
    chunks: Optional[List[DocumentChunkSchema]] = None

    class Config:
        from_attributes = True


class DocumentList(BaseModel):
    """文档列表"""
    total: int
    items: List[DocumentDetail]


class DocumentStatus(BaseModel):
    """文档处理状态"""
    id: UUID
    status: str
    processing_progress: int
    current_stage: Optional[str] = None
    error_message: Optional[str] = None

    class Config:
        from_attributes = True
