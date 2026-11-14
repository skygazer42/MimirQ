"""
Stub for integrated file utilities.
These are integrated-internal utilities that are not available in this project.
"""

from typing import Any


def extract_embed_file(binary: bytes | None) -> list[tuple[str, bytes]]:
    """Extract embedded files - stub implementation."""
    _ = binary
    # Return empty list - no embedded file extraction
    return []


def extract_links_from_pdf(binary: bytes | None) -> set[str]:
    """Extract hyperlinks from PDF - stub implementation."""
    _ = binary
    return set()


def extract_links_from_docx(binary: bytes | None) -> set[str]:
    """Extract hyperlinks from DOCX - stub implementation."""
    _ = binary
    return set()


def extract_html(url: str) -> tuple[bytes | None, dict[str, Any]]:
    """Extract HTML content from URL - stub implementation."""
    _ = url
    return None, {}
