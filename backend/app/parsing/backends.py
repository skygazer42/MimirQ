"""
Parser backend normalization helpers.

We accept a few common aliases from UI / env / user input and map them to the
canonical backend names used internally.
"""

from __future__ import annotations

from typing import Optional


_BACKEND_ALIASES: dict[str, str] = {
    # PyMuPDF basic parser aliases
    "pymupdf": "basic",
    "fitz": "basic",
    # MagicPDF (PyPI: magic-pdf, module: magic_pdf, CLI: magic-pdf)
    "magic-pdf": "magicpdf",
    "magicpdf": "magicpdf",
}


def normalize_parser_backend(value: Optional[str]) -> str:
    """
    Normalize user-facing backend values into our canonical identifiers.

    Examples:
    - "magic-pdf" / "magic_pdf" -> "magicpdf"
    - "pymupdf" -> "basic"
    """
    text = (value or "").strip().lower()
    if not text:
        return ""
    text = text.replace("_", "-")
    return _BACKEND_ALIASES.get(text, text)

