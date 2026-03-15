"""
Stub for integrated file utilities.
These are integrated-internal utilities that are not available in this project.
"""


def extract_embed_file(binary):
    """Extract embedded files - stub implementation."""
    _ = binary
    # Return empty list - no embedded file extraction
    return []


def extract_links_from_pdf(binary):
    """Extract hyperlinks from PDF - stub implementation."""
    _ = binary
    return set()


def extract_links_from_docx(binary):
    """Extract hyperlinks from DOCX - stub implementation."""
    _ = binary
    return set()


def extract_html(url):
    """Extract HTML content from URL - stub implementation."""
    _ = url
    return None, {}
