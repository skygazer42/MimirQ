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

from __future__ import annotations

from typing import Any

__all__ = [
    "score_pdf_quality",
    "parser_factory",
    "chunker_factory",
    "hierarchical_chunk_markdown",
    "document_processor",
    "document_parser_service",
    "zip_image_processor",
]


def __getattr__(name: str) -> Any:  # pragma: no cover
    """
    Lazy exports to keep package import lightweight and avoid circular imports.

    Prefer importing submodules directly when possible.
    """
    if name == "score_pdf_quality":
        from app.parsing.quality.scorer import score_pdf_quality

        return score_pdf_quality
    if name == "parser_factory":
        from app.parsing.factory import parser_factory

        return parser_factory
    if name == "chunker_factory":
        from app.parsing.chunking.factory import chunker_factory

        return chunker_factory
    if name == "hierarchical_chunk_markdown":
        from app.parsing.chunking.hierarchical import hierarchical_chunk_markdown

        return hierarchical_chunk_markdown
    if name == "document_processor":
        from app.parsing.processors.document_processor import document_processor

        return document_processor
    if name == "document_parser_service":
        from app.parsing.processors.parser_service import document_parser_service

        return document_parser_service
    if name == "zip_image_processor":
        from app.parsing.utils.zip_processor import zip_image_processor

        return zip_image_processor
    raise AttributeError(f"module 'app.parsing' has no attribute {name!r}")

