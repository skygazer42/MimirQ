"""PDF parser adapters used by the raw-file ingestion flow."""

from .general import PARSERS, by_deepdoc, by_docling, by_mineru, by_plaintext

PDF_SECTION_PARSERS = PARSERS
parse_deepdoc_sections = by_deepdoc
parse_docling_sections = by_docling
parse_mineru_sections = by_mineru
parse_plaintext_sections = by_plaintext

__all__ = [
    "PDF_SECTION_PARSERS",
    "parse_deepdoc_sections",
    "parse_docling_sections",
    "parse_mineru_sections",
    "parse_plaintext_sections",
]
