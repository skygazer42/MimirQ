"""
Document-related Pydantic schemas.
"""
from pydantic import AliasChoices, BaseModel, Field, model_validator
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


class DocumentChunkSchema(OrmModel):
    """Document chunk."""
    id: UUID
    content: str
    page_number: Optional[int] = None
    start_char: Optional[int] = None
    end_char: Optional[int] = None
    chunk_index: int
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("doc_metadata", "metadata"),
    )


class GovernanceInfo(BaseModel):
    enabled: bool = False
    documents: int = 0
    changed_documents: int = 0
    rules_applied: int = 0


class DocumentDetail(OrmModel):
    """Document detail."""
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
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("doc_metadata", "metadata"),
    )
    governance: GovernanceInfo = Field(default_factory=GovernanceInfo)
    # Avoid accidental lazy-loading on list endpoints: only include chunks when
    # the API handler explicitly sets `chunks_loaded` on the ORM instance.
    chunks: Optional[List[DocumentChunkSchema]] = Field(default=None, validation_alias="chunks_loaded")

    @model_validator(mode="after")
    def _populate_governance(self) -> "DocumentDetail":
        meta = self.metadata or {}
        try:
            self.governance = GovernanceInfo(
                enabled=bool(meta.get("governance_enabled") or False),
                documents=int(meta.get("governance_documents") or 0),
                changed_documents=int(meta.get("governance_changed_documents") or 0),
                rules_applied=int(meta.get("governance_rules_applied") or 0),
            )
        except Exception:
            self.governance = GovernanceInfo()
        return self


class ParsedSegment(BaseModel):
    """Document parse preview segment."""
    index: int
    content: str
    page_number: Optional[int] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DocumentParsePreview(BaseModel):
    """Document parse preview result."""
    filename: str
    file_type: str
    file_size: int
    segments: List[ParsedSegment]
    parser_backend: str


class ManualChunkCreate(BaseModel):
    """Single chunk entry in a manual chunking request."""
    content: str
    page_number: Optional[int] = None
    start_char: Optional[int] = None
    end_char: Optional[int] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ManualDocumentCreate(BaseModel):
    """Request to create a document from manual chunks."""
    dataset_id: Optional[UUID] = None
    filename: str
    file_type: str
    file_size: int
    chunks: List[ManualChunkCreate]
    metadata: Dict[str, Any] = Field(default_factory=dict)
    pipeline: Optional[DocumentPipelineOptions] = None


class DocumentList(BaseModel):
    """Document list."""
    total: int
    items: List[DocumentDetail]


class DocumentStatus(OrmModel):
    """Document processing status."""
    id: UUID
    status: str
    processing_progress: int
    current_stage: Optional[str] = None
    error_message: Optional[str] = None


# ============ Chunk preview schemas ============

class ChunkPreviewParams(BaseModel):
    """Chunk preview parameters."""
    chunk_size: int = Field(default=1000, ge=100, le=4000, description="切块大小")
    chunk_overlap: int = Field(default=200, ge=0, le=1000, description="重叠大小")
    unit: str = Field(default="chars", description="chunk_size/chunk_overlap unit: chars | tokens")


class ChunkPreviewItem(BaseModel):
    """Chunk preview item."""
    index: int
    content: str
    length: int
    start_index: int  # Start position in original text.
    end_index: int    # End position in original text.
    page_number: Optional[int] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ChunkPreviewResponse(BaseModel):
    """Chunk preview response."""
    filename: str
    file_type: str
    file_size: int
    total_chunks: int
    total_characters: int
    params: ChunkPreviewParams
    chunks: List[ChunkPreviewItem]
    # Original text for frontend highlighting.
    original_text: Optional[str] = None
    parser_backend: str
    chunk_strategy: str


# ============ Batch upload schemas ============

class BatchFileInfo(BaseModel):
    """Batch upload file info."""
    name: str = Field(..., description="文件名")
    data_id: str = Field(..., description="自定义数据 ID，用于标识文件")


class BatchUploadRequest(BaseModel):
    """Batch request for upload URLs."""
    files: List[BatchFileInfo] = Field(..., max_length=200, description="文件列表，最多 200 个")


class BatchUploadResponse(BaseModel):
    """Batch response for upload URLs."""
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


# ============ 批量文件上传（单次多文件）相关 Schema ============

class DocumentBatchUploadSuccess(BaseModel):
    """批量上传成功的单个文件结果（轻量返回）。"""
    document_id: UUID
    filename: str
    status: str


class DocumentBatchUploadFailure(BaseModel):
    """批量上传失败的单个文件结果。"""
    filename: str
    error: str


class DocumentBatchUploadResponse(BaseModel):
    """批量上传接口响应。"""
    total: int
    successful_count: int
    failed_count: int
    successful: List[DocumentBatchUploadSuccess] = Field(default_factory=list)
    failed: List[DocumentBatchUploadFailure] = Field(default_factory=list)
