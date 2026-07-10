"""
Paragraph-level duplicate dropping helpers.

This is useful for PDF/Office exports that repeat the same boilerplate blocks
across pages (headers/footers/legal notices) which line-based filters miss.

Opt-in and conservative: only drops paragraphs repeated >= min_occurrences.
"""


import re
from dataclasses import dataclass

from app.rag.preprocessing.normalization import normalize_text

_CODE_FENCE_RE = re.compile(r"^\s*```", re.MULTILINE)
_HEADING_RE = re.compile(r"^\s*#{1,6}\s+\S", re.MULTILINE)
_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)


@dataclass(frozen=True)
class ParagraphDedupResult:
    text: str
    paragraphs_total: int
    paragraphs_dropped: int
    changed: bool


def _normalize_paragraph_signature(text: str) -> str:
    norm = normalize_text(text or "", normalize_line_endings=True, remove_control_chars=True)
    norm = re.sub(r"\s+", " ", norm.strip())
    return norm.casefold()


def drop_duplicate_paragraphs(
    text: str,
    *,
    min_occurrences: int = 3,
    min_paragraph_chars: int = 40,
    max_paragraph_chars: int = 1200,
) -> ParagraphDedupResult:
    """
    Drop paragraphs repeated many times within a single document.

    Safety rules:
    - skips code fences/headings/tables (structure)
    - only considers paragraphs within [min_paragraph_chars, max_paragraph_chars]
    """
    original = text or ""
    if not original:
        return ParagraphDedupResult(text="", paragraphs_total=0, paragraphs_dropped=0, changed=False)

    min_occ = max(2, int(min_occurrences or 0))
    min_chars = max(0, int(min_paragraph_chars or 0))
    max_chars = max(0, int(max_paragraph_chars or 0))

    # Normalize to consistent line endings for splitting.
    norm = normalize_text(original, normalize_line_endings=True, remove_control_chars=True)
    parts = re.split(r"\n{2,}", norm)
    paragraphs = [p for p in parts if p is not None]
    total = len(paragraphs)
    if total <= 1:
        return ParagraphDedupResult(text=norm, paragraphs_total=total, paragraphs_dropped=0, changed=(norm != original))

    counts: dict[str, int] = {}
    signatures: list[str | None] = []
    for p in paragraphs:
        raw_p = p or ""
        if not raw_p.strip():
            signatures.append(None)
            continue
        if _CODE_FENCE_RE.search(raw_p) or _HEADING_RE.search(raw_p) or _TABLE_ROW_RE.search(raw_p):
            signatures.append(None)
            continue
        sig = _normalize_paragraph_signature(raw_p)
        if not sig:
            signatures.append(None)
            continue
        if len(sig) < min_chars:
            signatures.append(None)
            continue
        if max_chars and len(sig) > max_chars:
            signatures.append(None)
            continue
        signatures.append(sig)
        counts[sig] = counts.get(sig, 0) + 1

    dropped = 0
    kept: list[str] = []
    for p, sig in zip(paragraphs, signatures, strict=False):
        if sig is not None and counts.get(sig, 0) >= min_occ:
            dropped += 1
            continue
        kept.append(p)

    out = "\n\n".join([k for k in kept if k is not None])
    return ParagraphDedupResult(
        text=out,
        paragraphs_total=int(total),
        paragraphs_dropped=int(dropped),
        changed=bool(out != original),
    )


__all__ = [
    "ParagraphDedupResult",
    "drop_duplicate_paragraphs",
]

