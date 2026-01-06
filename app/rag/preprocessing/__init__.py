"""
RAG Preprocessing module.

Provides text cleaning and preprocessing utilities for RAG workflows.
Merged from app/governance/.
"""

from app.rag.preprocessing.cleaning import clean_markdown, CleaningResult, RegexRule
from app.rag.preprocessing.normalization import normalize_text, normalize_query
from app.rag.preprocessing.processor import GovernanceProcessor, GovernanceStats, governance_processor
from app.rag.preprocessing.rules import DEFAULT_MARKDOWN_RULES

__all__ = [
    "clean_markdown",
    "CleaningResult",
    "RegexRule",
    "normalize_text",
    "normalize_query",
    "DEFAULT_MARKDOWN_RULES",
    "GovernanceProcessor",
    "GovernanceStats",
    "governance_processor",
]
