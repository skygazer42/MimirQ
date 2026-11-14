"""
Document parsing module.

Provides document parsing and quality evaluation.

Key components:
- quality: PDF quality evaluation and OCR validation
- parsers: document parsers (PDF, Word, Markdown, and more)
- processors: parsing workflow orchestration
- utils: helper utilities
- text cleaning: handled by app.rag.preprocessing (post-parse, pre-chunking)

Note: text chunking has moved to app.rag.chunking.
"""

from typing import Any

__all__ = [
    "score_pdf_quality",
    "parser_factory",
    "process_document",
    "parse_for_preview",
    "process_zip_with_images",
]


def __getattr__(name: str) -> Any:
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
    if name == "process_document":
        from app.parsing.processors.support.process_document_flow import process_document

        return process_document
    if name == "parse_for_preview":
        from app.parsing.processors.parser_service import parse_for_preview

        return parse_for_preview
    if name == "process_zip_with_images":
        from app.parsing.utils.zip_processor import process_zip_with_images

        return process_zip_with_images
    raise AttributeError(f"module 'app.parsing' has no attribute {name!r}")
