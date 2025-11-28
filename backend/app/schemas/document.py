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
    start_char: Optional[int] = None
    end_char: Optional[int] = None
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


class ParsedSegment(BaseModel):
    """文档解析预览片段"""
    index: int
    content: str
    page_number: Optional[int] = None
    metadata: Dict[str, Any] = {}


class DocumentParsePreview(BaseModel):
    """文档解析预览结果"""
    filename: str
    file_type: str
    file_size: int
    segments: List[ParsedSegment]


class ManualChunkCreate(BaseModel):
    """手动切片创建请求中的单个片段"""
    content: str
    page_number: Optional[int] = None
    start_char: Optional[int] = None
    end_char: Optional[int] = None
    metadata: Dict[str, Any] = {}


class ManualDocumentCreate(BaseModel):
    """基于手动切片创建文档的请求"""
    filename: str
    file_type: str
    file_size: int
    chunks: List[ManualChunkCreate]
    metadata: Dict[str, Any] = {}


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
