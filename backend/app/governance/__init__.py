"""
Data governance / cleaning utilities for Markdown-based document content.

Goal: keep parsing (file -> markdown) separated from governance (markdown -> clean markdown),
and chunking/indexing separated from both.
"""

from app.governance.cleaning import clean_markdown, CleaningResult, RegexRule
from app.governance.processor import GovernanceProcessor, GovernanceStats, governance_processor
from app.governance.rules import DEFAULT_MARKDOWN_RULES

__all__ = [
    "clean_markdown",
    "CleaningResult",
    "RegexRule",
    "DEFAULT_MARKDOWN_RULES",
    "GovernanceProcessor",
    "GovernanceStats",
    "governance_processor",
]
