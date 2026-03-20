"""
Quality filters for governance.

These heuristics are optional and meant to guard against indexing low-value
documents (e.g., outline-only exports, garbled/noisy OCR output).
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class QualityDecision:
    dropped: bool
    reason: str | None = None
    metrics: dict[str, float | int] | None = None


_CODE_FENCE_RE = re.compile(r"^\s*```")
_MD_HEADING_RE = re.compile(r"^\s*#{1,6}\s+\S")
_LIST_RE = re.compile(r"^\s*(?:[-*+]|\d{1,3}[.)])\s+\S")
_SENT_PUNCT_RE = re.compile(r"[.!?\u3002\uff01\uff1f\uff1b;:\uff1a]")
_ALNUM_CJK_RE = re.compile(r"[A-Za-z0-9\u4e00-\u9fff]")
_ALLCAPS_RE = re.compile(r"^[A-Z0-9][A-Z0-9 \-_/]{6,}$")


def _is_outline_line(line: str) -> bool:
    stripped = (line or "").strip()
    if not stripped:
        return False
    if _MD_HEADING_RE.match(stripped):
        return True
    if _LIST_RE.match(stripped):
        body = _LIST_RE.sub("", stripped, count=1).strip()
        if not body:
            return True
        if len(body) <= 60 and not _SENT_PUNCT_RE.search(body):
            return True
    if len(stripped) <= 60 and _ALLCAPS_RE.match(stripped):
        return True
    # Short title-like lines ending with ":" often indicate outline headings.
    if len(stripped) <= 50 and stripped.endswith((":","\uff1a")) and not _SENT_PUNCT_RE.search(stripped[:-1]):
        return True
    return False


def _outline_only_metrics(raw: str) -> tuple[int, int, int]:
    total = 0
    outline = 0
    content_chars = 0
    in_code = False

    for line in raw.splitlines():
        if _CODE_FENCE_RE.match(line):
            in_code = not in_code
            continue
        if in_code:
            continue
        stripped = (line or "").strip()
        if not stripped:
            continue
        total += 1
        content_chars += len(_ALNUM_CJK_RE.findall(stripped))
        if _is_outline_line(stripped):
            outline += 1

    return total, outline, content_chars


def drop_if_outline_only(
    text: str,
    *,
    min_content_chars: int = 200,
    max_heading_ratio: float = 0.85,
) -> QualityDecision:
    raw = text or ""
    if not raw.strip():
        return QualityDecision(dropped=True, reason="empty_document", metrics={"content_chars": 0})

    total, outline, content_chars = _outline_only_metrics(raw)

    if total <= 0:
        return QualityDecision(dropped=True, reason="empty_document", metrics={"content_chars": content_chars})

    heading_ratio = outline / total
    metrics: dict[str, float | int] = {
        "lines_total": total,
        "lines_outline": outline,
        "heading_ratio": float(heading_ratio),
        "content_chars": int(content_chars),
    }

    if content_chars < max(0, int(min_content_chars)) and heading_ratio >= float(max_heading_ratio or 0.0):
        return QualityDecision(dropped=True, reason="outline_only", metrics=metrics)

    return QualityDecision(dropped=False, reason=None, metrics=metrics)


def drop_if_low_density(text: str, *, threshold: float = 0.12) -> QualityDecision:
    """
    Drop documents where the ratio of [A-Za-z0-9/CJK] characters is too low.

    This is useful for garbled OCR or corrupted encodings that produce mostly
    symbols. It is intentionally simple and should be opt-in.
    """
    raw = text or ""
    if not raw.strip():
        return QualityDecision(dropped=True, reason="empty_document", metrics={"density": 0.0})

    non_space = sum(1 for ch in raw if not ch.isspace())
    alnum = len(_ALNUM_CJK_RE.findall(raw))
    density = (alnum / max(1, non_space)) if non_space else 0.0

    metrics: dict[str, float | int] = {
        "chars_non_space": int(non_space),
        "chars_alnum_cjk": int(alnum),
        "density": float(density),
    }

    if density < float(threshold or 0.0):
        return QualityDecision(dropped=True, reason="low_density", metrics=metrics)
    return QualityDecision(dropped=False, reason=None, metrics=metrics)
