"""
文档解析模块

提供文档解析、质量评估、文本切块等功能。

主要组件：
- quality: PDF 质量评估和 OCR 验证
- parsers: 各类文档解析器（PDF、Word、Markdown等）
- chunking: 文本切块策略
- processors: 解析流程编排
- utils: 工具函数
"""

# 质量评估
from app.parsing.quality.scorer import score_pdf_quality

# 解析工厂
from app.parsing.factory import parser_factory

# 切块工厂
from app.parsing.chunking.factory import chunker_factory
from app.parsing.chunking.hierarchical import hierarchical_chunk_markdown

# 处理器
from app.parsing.processors.document_processor import document_processor
from app.parsing.processors.parser_service import document_parser_service

# ZIP 处理
from app.parsing.utils.zip_processor import zip_image_processor

__all__ = [
    # 质量评估
    'score_pdf_quality',
    # 工厂
    'parser_factory',
    'chunker_factory',
    # 切块
    'hierarchical_chunk_markdown',
    # 处理器
    'document_processor',
    'document_parser_service',
    # 工具
    'zip_image_processor',
]

