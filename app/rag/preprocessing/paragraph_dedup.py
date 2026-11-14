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


def _eligible_paragraph_signature(
    paragraph: str,
    *,
    min_chars: int,
    max_chars: int,
) -> str | None:
    if not paragraph.strip():
        return None
    if _CODE_FENCE_RE.search(paragraph) or _HEADING_RE.search(paragraph) or _TABLE_ROW_RE.search(paragraph):
        return None
    # The whole document is normalized before it is split into paragraphs.
    sig = re.sub(r"\s+", " ", paragraph.strip()).casefold()
    if len(sig) < min_chars:
        return None
    if max_chars and len(sig) > max_chars:
        return None
    return sig


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
    original = text
    if not original:
        return ParagraphDedupResult(text="", paragraphs_total=0, paragraphs_dropped=0, changed=False)

    min_occ = max(2, int(min_occurrences or 0))
    min_chars = max(0, int(min_paragraph_chars or 0))
    max_chars = max(0, int(max_paragraph_chars or 0))

    # Normalize to consistent line endings for splitting.
    norm = normalize_text(original, normalize_line_endings=True, remove_control_chars=True)
    paragraphs = re.split(r"\n{2,}", norm)
    total = len(paragraphs)
    if total <= 1:
        return ParagraphDedupResult(text=norm, paragraphs_total=total, paragraphs_dropped=0, changed=(norm != original))

    counts: dict[str, int] = {}
    signatures: list[str | None] = []
    for p in paragraphs:
        sig = _eligible_paragraph_signature(
            p,
            min_chars=min_chars,
            max_chars=max_chars,
        )
        signatures.append(sig)
        if sig is not None:
            counts[sig] = counts.get(sig, 0) + 1

    dropped = 0
    kept: list[str] = []
    for p, sig in zip(paragraphs, signatures, strict=False):
        if sig is not None and counts[sig] >= min_occ:
            dropped += 1
            continue
        kept.append(p)

    out = "\n\n".join(kept)
    return ParagraphDedupResult(
        text=out,
        paragraphs_total=total,
        paragraphs_dropped=dropped,
        changed=out != original,
    )


__all__ = [
    "ParagraphDedupResult",
    "drop_duplicate_paragraphs",
]
