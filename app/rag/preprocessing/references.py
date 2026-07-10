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

    candidate_idx: int | None = None
    min_lines_eff = max(0, int(min_lines_after or 0))
    for idx, ln in enumerate(lines):
        stripped = (ln or "").strip()
        if not stripped:
            continue
        title = stripped
        parsed_heading = parse_markdown_hash_heading(stripped)
        if parsed_heading is not None:
            _level, heading_title = parsed_heading
            title = heading_title

        title_cf = title.casefold()
        if title_cf in _HEADING_TEXTS:
            # Must be near the end and have enough content after it to matter.
            if (idx / max(1, n)) < float(min_position_ratio or 0.0):
                continue
            remaining = n - idx - 1
            if remaining < min_lines_eff:
                # unwrap_lines in cleaning can collapse reference lists into a single long line;
                # accept if we still see enough citation markers after the heading.
                tail_text = "\n".join(lines[idx + 1 :])
                if sum(1 for _ in _CITATION_TOKEN_RE.finditer(tail_text)) < min_lines_eff:
                    continue
            candidate_idx = idx
            break

    if candidate_idx is None:
        return ReferencesTrimResult(text=original, removed_lines=0, changed=False)

    tail = lines[candidate_idx + 1 :]
    if tail:
        cite_like = sum(1 for ln in tail if _CITATION_LINE_RE.match(ln or ""))
        ratio = cite_like / max(1, len(tail))
        if ratio < float(citation_like_ratio or 0.0):
            # Not a typical bibliography list; keep content.
            return ReferencesTrimResult(text=original, removed_lines=0, changed=False)

    kept_lines = lines[:candidate_idx]
    # Trim trailing blank lines after removal for cleanliness.
    while kept_lines and not (kept_lines[-1] or "").strip():
        kept_lines.pop()

    out = "\n".join(kept_lines)
    removed = n - len(kept_lines)
    return ReferencesTrimResult(text=out, removed_lines=int(removed), changed=(out != original))


__all__ = [
    "ReferencesTrimResult",
    "trim_references_section",
]
