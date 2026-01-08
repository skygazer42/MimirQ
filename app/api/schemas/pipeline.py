"""
Document processing pipeline schemas.
Defines data models for document parsing, chunking, and other pipeline operations.
"""

from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, Field


class ImageInfo(BaseModel):
    id: str
    url: str
    filename: str


class PDFQualityScore(BaseModel):
    """
    PDF quality score (sampled from first 3 pages).

    Scoring dimensions:
    - text_quality_score (50%): Text extraction quality
    - format_consistency_score (30%): Format consistency
    - table_quality_score (20%): Table completeness
    """
    score: float = Field(..., description="Overall score 0-1, higher is cleaner")
    text_quality_score: float = Field(..., description="Text extraction quality (0-1)")
    format_consistency_score: float = Field(..., description="Format consistency (0-1)")
    table_quality_score: float = Field(..., description="Table completeness (0-1)")
    is_scanned: bool = Field(..., description="Whether it is a scanned document")
    page_count: float = Field(..., description="Total page count")


class ParsePreviewResponse(BaseModel):
    backend: str
    pdf_quality: Optional[PDFQualityScore] = None
    markdown: str
    images: List[ImageInfo] = Field(default_factory=list)


class ChunkItem(BaseModel):
    id: str
    level: str
    index: int
    text: str
    start: int
    end: int
    tokens_est: int
    parent_id: Optional[str] = None


class ChunkPreviewRequest(BaseModel):
    markdown: str


class ChunkPreviewResponse(BaseModel):
    paragraphs: List[ChunkItem]
    sentences: List[ChunkItem]


class RegexRuleModel(BaseModel):
    pattern: str
    repl: str = ""
    flags: int = 0


class CleanPreviewRequest(BaseModel):
    markdown: str
    rules: List[RegexRuleModel] = Field(default_factory=list)
    use_default_rules: bool = True
    normalize_line_endings: bool = True
    trim_trailing_spaces: bool = True
    collapse_blank_lines: bool = True
    remove_control_chars: bool = True
    remove_toc_lines: bool = True
    remove_noise_lines: bool = True
    remove_common_lines: bool = True
    unwrap_lines: bool = True
    unwrap_max_line_length: int = Field(default=120, ge=40, le=400)
    noise_min_chars: int = Field(default=2, ge=1, le=20)
    noise_ratio_threshold: float = Field(default=0.2, ge=0.0, le=1.0)
    common_lines_min_occurrences: int = Field(default=3, ge=2, le=30)


class CleanPreviewResponse(BaseModel):
    markdown: str
    applied_rules: int
    changed: bool


class CleanRulesResponse(BaseModel):
    rules: List[RegexRuleModel]


class KeywordExtractRequest(BaseModel):
    text: str
    provider: str = Field(default="jieba")
    top_k: int = Field(default=10, ge=1, le=50)


class KeywordExtractResponse(BaseModel):
    provider: str
    keywords: List[str] = Field(default_factory=list)


class LLMCleanPreviewRequest(BaseModel):
    markdown: str
    prompt_template_id: Optional[UUID] = None
    template_key: Optional[str] = None
    ab_experiment_key: Optional[str] = None
    ab_user_key: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(default=None, ge=16, le=32768)
    max_chars: int = Field(default=15000, ge=1000, le=200000)


class LLMCleanPreviewResponse(BaseModel):
    markdown: str
    changed: bool
    model_used: Optional[str] = None
    prompt_template_id: Optional[str] = None
    template_key: Optional[str] = None
    ab_experiment_key: Optional[str] = None
    ab_variant: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)


class ParserBackendInfo(BaseModel):
    name: str
    available: bool
    notes: Optional[str] = None


class ChunkStrategyInfo(BaseModel):
    name: str
    available: bool
    notes: Optional[str] = None


class PipelineCapabilitiesResponse(BaseModel):
    default_parser_backend: str
    default_chunk_strategy: str
    pdf_backends: List[ParserBackendInfo] = Field(default_factory=list)
    chunk_strategies: List[ChunkStrategyInfo] = Field(default_factory=list)


class ZipImageInfo(BaseModel):
    img_id: str
    original_path: str
    url: str


class ZipWithImagesResponse(BaseModel):
    markdown: str
    images: List[ZipImageInfo] = Field(default_factory=list)
    image_count: int
    dataset_id: str
    document_id: str
