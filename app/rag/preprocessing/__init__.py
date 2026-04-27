"""
RAG Preprocessing module.

Provides text cleaning and preprocessing utilities for RAG workflows.
Merged from app/governance/.
"""

from app.rag.preprocessing.cleaning import CleaningResult, RegexRule, clean_markdown
from app.rag.preprocessing.metadata_enrichment import (
    build_document_metadata_enrichment,
    build_rich_metadata_header,
    enrich_documents_metadata,
)
from app.rag.preprocessing.normalization import normalize_query, normalize_text
from app.rag.preprocessing.processor import GovernanceProcessor, GovernanceStats, governance_processor
from app.rag.preprocessing.rules import DEFAULT_MARKDOWN_RULES

__all__ = [
    "clean_markdown",
    "CleaningResult",
    "RegexRule",
    "normalize_text",
    "normalize_query",
    "DEFAULT_MARKDOWN_RULES",
    "build_document_metadata_enrichment",
    "build_rich_metadata_header",
    "enrich_documents_metadata",
    "GovernanceProcessor",
    "GovernanceStats",
    "governance_processor",
]
