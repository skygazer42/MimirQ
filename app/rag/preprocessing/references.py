"""
Reference section trimming helpers (opt-in).

Some documents end with long bibliographies / reference lists which can be low-signal
for many enterprise RAG workloads. This module provides a conservative, best-effort
way to trim such sections.
"""


import re
from dataclasses import dataclass

from app.rag.chunking.utils.heading_parsing import parse_markdown_hash_heading


@dataclass(frozen=True)
class ReferencesTrimResult:
    text: str
    removed_lines: int
    changed: bool


_HEADING_TEXTS = frozenset(
    {
        "references",
        "reference",
        "bibliography",
        "works cited",
        "citations",
        "\u53c2\u8003\u6587\u732e",
        "\u5f15\u7528\u6587\u732e",
        "\u5f15\u7528",
    }
)
_CITATION_LINE_RE = re.compile(r"^\s*(?:\[\d{1,4}\]|\d{1,4}[.)]|\u3010\d{1,4}\u3011)\s+")
_CITATION_TOKEN_RE = re.compile(r"(?:^|\s)(?:\[\d{1,4}\]|\d{1,4}[.)]|\u3010\d{1,4}\u3011)\s+")


def _normalized_heading_title(line: str) -> str:
    stripped = (line or "").strip()
    parsed_heading = parse_markdown_hash_heading(stripped)
    if parsed_heading is None:
        return stripped
    _level, heading_title = parsed_heading
    return heading_title


def _has_enough_reference_tail(lines: list[str], start_idx: int, min_lines_eff: int) -> bool:
    remaining = len(lines) - start_idx - 1
    if remaining >= min_lines_eff:
        return True
    tail_text = "\n".join(lines[start_idx + 1 :])
    return sum(1 for _ in _CITATION_TOKEN_RE.finditer(tail_text)) >= min_lines_eff


def _find_reference_heading_index(
    lines: list[str],
    *,
    min_position_ratio: float,
    min_lines_eff: int,
) -> int | None:
    line_count = len(lines)
    for idx, line in enumerate(lines):
        if not (line or "").strip():
            continue
        title = _normalized_heading_title(line).casefold()
        if title not in _HEADING_TEXTS:
            continue
        if (idx / max(1, line_count)) < min_position_ratio:
            continue
        if not _has_enough_reference_tail(lines, idx, min_lines_eff):
            continue
        return idx
    return None


def _citation_ratio_ok(tail: list[str], citation_like_ratio: float) -> bool:
    if not tail:
        return True
    cite_like = sum(1 for line in tail if _CITATION_LINE_RE.match(line or ""))
    ratio = cite_like / max(1, len(tail))
    return ratio >= citation_like_ratio


def _trim_trailing_blank_lines(lines: list[str]) -> list[str]:
    trimmed = list(lines)
    while trimmed and not (trimmed[-1] or "").strip():
        trimmed.pop()
    return trimmed


def trim_references_section(
    text: str,
    *,
    min_position_ratio: float = 0.6,
    min_lines_after: int = 8,
    citation_like_ratio: float = 0.25,
) -> ReferencesTrimResult:
    original = text or ""
    if not original:
        return ReferencesTrimResult(text="", removed_lines=0, changed=False)

    lines = original.splitlines()
    n = len(lines)
    if n <= 0:
        return ReferencesTrimResult(text=original, removed_lines=0, changed=False)

    min_lines_eff = max(0, int(min_lines_after or 0))
    candidate_idx = _find_reference_heading_index(
        lines,
        min_position_ratio=float(min_position_ratio or 0.0),
        min_lines_eff=min_lines_eff,
    )
    if candidate_idx is None:
        return ReferencesTrimResult(text=original, removed_lines=0, changed=False)

    tail = lines[candidate_idx + 1 :]
    if not _citation_ratio_ok(tail, float(citation_like_ratio or 0.0)):
        return ReferencesTrimResult(text=original, removed_lines=0, changed=False)

    kept_lines = _trim_trailing_blank_lines(lines[:candidate_idx])
    out = "\n".join(kept_lines)
    removed = n - len(kept_lines)
    return ReferencesTrimResult(text=out, removed_lines=int(removed), changed=(out != original))


__all__ = [
    "ReferencesTrimResult",
    "trim_references_section",
]
