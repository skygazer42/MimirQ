from typing import List, Optional, Dict, Any
from uuid import UUID
from pydantic import BaseModel, Field


class ImageInfo(BaseModel):
    id: str
    url: str
    filename: str


class PDFQualityScore(BaseModel):
    """
    PDF 质量评分（前 3 页抽样）。
    
    评分维度：
    - text_quality_score（50%）：文本提取质量
    - format_consistency_score（30%）：格式一致性
    - table_quality_score（20%）：表格完整性
    """
    score: float = Field(..., description="综合得分 0-1，越高越干净")
    text_quality_score: float = Field(..., description="文本提取质量（0-1）")
    format_consistency_score: float = Field(..., description="格式一致性（0-1）")
    table_quality_score: float = Field(..., description="表格完整性（0-1）")
    is_scanned: bool = Field(..., description="是否为扫描件")
    page_count: float = Field(..., description="总页数")


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
