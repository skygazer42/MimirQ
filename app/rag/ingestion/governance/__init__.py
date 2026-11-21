"""Document governance for RAG ingestion."""

from app.rag.ingestion.governance.cleaning import CleaningResult, RegexRule, clean_markdown
from app.rag.ingestion.governance.contracts import GovernanceStats
from app.rag.ingestion.governance.processor import clean_documents
from app.rag.ingestion.governance.rules import DEFAULT_MARKDOWN_RULES
from app.rag.ingestion.governance.tagging.metadata_enrichment import (
    build_document_metadata_enrichment,
    build_rich_metadata_header,
    enrich_documents_metadata,
)
from app.rag.ingestion.governance.text.normalization import normalize_query_text, normalize_text

__all__ = [
    "clean_markdown",
    "CleaningResult",
    "RegexRule",
    "normalize_text",
    "normalize_query_text",
    "DEFAULT_MARKDOWN_RULES",
    "build_document_metadata_enrichment",
    "build_rich_metadata_header",
    "enrich_documents_metadata",
    "clean_documents",
    "GovernanceStats",
]
