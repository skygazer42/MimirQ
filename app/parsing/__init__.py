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
    "document_processor",
    "document_parser_service",
    "zip_image_processor",
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
    if name == "document_processor":
        from app.parsing.processors.processor import document_processor

        return document_processor
    if name == "document_parser_service":
        from app.parsing.processors.parser_service import document_parser_service

        return document_parser_service
    if name == "zip_image_processor":
        from app.parsing.utils.zip_processor import zip_image_processor

        return zip_image_processor
    raise AttributeError(f"module 'app.parsing' has no attribute {name!r}")



