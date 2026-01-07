"""
Shared text normalization helpers.

This module provides conservative, semantics-preserving normalization used by:
- Markdown cleaning (data governance)
- Parsing/indexing pipelines (before chunking)
- Retrieval/query handling (optional)
"""

from __future__ import annotations

import re


CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
ZERO_WIDTH_RE = re.compile(
    r"[\u200b\u200c\u200d\u2060\ufeff\u200e\u200f\u202a-\u202e\u2066-\u2069]"
)
SOFT_HYPHEN_RE = re.compile("\u00ad")

PDF_LIGATURES = {
    "\ufb00": "ff",
    "\ufb01": "fi",
    "\ufb02": "fl",
    "\ufb03": "ffi",
    "\ufb04": "ffl",
    "\ufb05": "ft",
    "\ufb06": "st",
}


def normalize_text(
    text: str,
    *,
    normalize_line_endings: bool = True,
    remove_control_chars: bool = True,
) -> str:
    """
    Normalize common artifacts from PDF/Office export and OCR.

    This is intentionally conservative and does not attempt semantic rewriting.
    """
    if not isinstance(text, str) or not text:
        return ""

    out = text

    if normalize_line_endings:
        out = out.replace("\r\n", "\n").replace("\r", "\n")
        # Unicode newlines occasionally appear in scraped HTML / PDF OCR outputs.
        out = out.replace("\u2028", "\n").replace("\u2029", "\n").replace("\u0085", "\n")

    # Normalize common Unicode whitespace artifacts from PDF/Office exporters.
    out = (
        out.replace("\u00a0", " ")
        .replace("\u202f", " ")
        .replace("\u3000", " ")
        .replace("\u2007", " ")
        .replace("\u2009", " ")
        .replace("\u200a", " ")
        .replace("\u205f", " ")
    )
    out = ZERO_WIDTH_RE.sub("", out)
    out = SOFT_HYPHEN_RE.sub("", out)

    # Normalize common PDF ligatures (ﬁ/ﬂ/ﬃ/ﬄ/…); improves tokenization/search.
    for src, dst in PDF_LIGATURES.items():
        if src in out:
            out = out.replace(src, dst)

    if remove_control_chars:
        out = CONTROL_CHARS_RE.sub("", out)

    return out


def normalize_query(text: str) -> str:
    """Normalize query text for retrieval (strip + collapse whitespace)."""
    norm = normalize_text(text, normalize_line_endings=True, remove_control_chars=True)
    return " ".join((norm or "").strip().split())
