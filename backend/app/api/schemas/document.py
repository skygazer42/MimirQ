"""
文档相关 Pydantic Schema
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID

from .base import OrmModel


class DocumentPipelineOptions(BaseModel):
    """Per-document pipeline options."""
    governance_enabled: Optional[bool] = None
    governance_remove_toc_lines: Optional[bool] = None
    governance_remove_noise_lines: Optional[bool] = None
    governance_unwrap_lines: Optional[bool] = None
    governance_remove_common_lines: Optional[bool] = None
    governance_unwrap_max_line_length: Optional[int] = Field(default=None, ge=40, le=400, description="max line length")
    governance_noise_min_chars: Optional[int] = Field(default=None, ge=1, le=20, description="noise min chars")
    governance_noise_ratio_threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="noise ratio threshold")
    governance_common_lines_min_docs: Optional[int] = Field(default=None, ge=2, le=50, description="common line min docs")
    governance_common_lines_min_ratio: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="common line ratio")
    chunk_size: Optional[int] = Field(default=None, ge=100, le=4000, description="切块大小")
    chunk_overlap: Optional[int] = Field(default=None, ge=0, le=1000, description="重叠大小")
    chunk_vector_enabled: Optional[bool] = None
    bm25_index_enabled: Optional[bool] = None
    kg_enabled: Optional[bool] = None
    event_vector_enabled: Optional[bool] = None
    entity_vector_enabled: Optional[bool] = None


class DocumentUploadResponse(OrmModel):
    """文档上传响应"""
    id: UUID
    dataset_id: Optional[UUID] = None
    filename: str
    file_type: str
    file_size: int
    status: str
    created_at: datetime
    metadata: Dict[str, Any] = {}


class DocumentChunkSchema(OrmModel):
    """文档块"""
    id: UUID
    content: str
    page_number: Optional[int] = None
    start_char: Optional[int] = None
    end_char: Optional[int] = None
    chunk_index: int
    metadata: Dict[str, Any] = {}


class DocumentDetail(OrmModel):
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
    dataset_id: Optional[UUID] = None
    metadata: Dict[str, Any] = {}
    chunks: Optional[List[DocumentChunkSchema]] = None


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
    parser_backend: str


class ManualChunkCreate(BaseModel):
    """手动切片创建请求中的单个片段"""
    content: str
    page_number: Optional[int] = None
    start_char: Optional[int] = None
    end_char: Optional[int] = None
    metadata: Dict[str, Any] = {}


class ManualDocumentCreate(BaseModel):
    """基于手动切片创建文档的请求"""
    dataset_id: Optional[UUID] = None
    filename: str
    file_type: str
    file_size: int
    chunks: List[ManualChunkCreate]
    metadata: Dict[str, Any] = {}
    pipeline: Optional[DocumentPipelineOptions] = None


class DocumentList(BaseModel):
    """文档列表"""
    total: int
    items: List[DocumentDetail]


class DocumentStatus(OrmModel):
    """文档处理状态"""
    id: UUID
    status: str
    processing_progress: int
    current_stage: Optional[str] = None
    error_message: Optional[str] = None


# ============ 切块预览相关 Schema ============

class ChunkPreviewParams(BaseModel):
    """切块预览参数"""
    chunk_size: int = Field(default=1000, ge=100, le=4000, description="切块大小")
    chunk_overlap: int = Field(default=200, ge=0, le=1000, description="重叠大小")


class ChunkPreviewItem(BaseModel):
    """切块预览单项"""
    index: int
    content: str
    length: int
    start_index: int  # 在原文中的起始位置
    end_index: int    # 在原文中的结束位置
    page_number: Optional[int] = None
    metadata: Dict[str, Any] = {}


class ChunkPreviewResponse(BaseModel):
    """切块预览响应"""
    filename: str
    file_type: str
    file_size: int
    total_chunks: int
    total_characters: int
    params: ChunkPreviewParams
    chunks: List[ChunkPreviewItem]
    # 原文内容，用于前端高亮显示
    original_text: Optional[str] = None
    parser_backend: str
    chunk_strategy: str


# ============ 批量上传相关 Schema ============

class BatchFileInfo(BaseModel):
    """批量上传文件信息"""
    name: str = Field(..., description="文件名")
    data_id: str = Field(..., description="自定义数据 ID，用于标识文件")


class BatchUploadRequest(BaseModel):
    """批量申请上传 URL 请求"""
    files: List[BatchFileInfo] = Field(..., max_length=200, description="文件列表，最多 200 个")


class BatchUploadResponse(BaseModel):
    """批量申请上传 URL 响应"""
    batch_id: str = Field(..., description="批次 ID")
    file_urls: List[str] = Field(..., description="上传 URL 列表")
    files: List[BatchFileInfo] = Field(..., description="文件信息列表")
    message: str = Field(default="Upload URLs generated. Please upload files within 24 hours.")


class BatchTaskStatus(BaseModel):
    """批量任务状态"""
    batch_id: str
    status: str = Field(..., description="任务状态: pending, processing, completed, failed")
    total_files: int
    completed_files: int
    failed_files: int
    progress: int = Field(..., ge=0, le=100, description="进度百分比")
    result_url: Optional[str] = None
    error: Optional[str] = None
