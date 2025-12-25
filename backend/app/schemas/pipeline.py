from __future__ import annotations

from typing import List, Optional, Dict, Any
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
    normalize_line_endings: bool = True
    trim_trailing_spaces: bool = True
    collapse_blank_lines: bool = True
    remove_control_chars: bool = True


class CleanPreviewResponse(BaseModel):
    markdown: str
    applied_rules: int
    changed: bool


class CleanRulesResponse(BaseModel):
    rules: List[RegexRuleModel]
