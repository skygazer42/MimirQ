"""
Parsed-text quality scoring utilities.

This is used after parsing (before chunking) to:
- attach lightweight observability metrics
- optionally trigger parser fallback when output is obviously low-quality

It is intentionally cheap and dependency-free.
"""


import re
from dataclasses import dataclass

_ALNUM_CJK_RE = re.compile(r"[A-Za-z0-9\u4e00-\u9fff]")


@dataclass(frozen=True)
class TextQualityScore:
    content_chars: int
    chars_non_space: int
    density: float
    replacement_chars: int
    replacement_ratio: float
    lines: int
    avg_line_len: float

    def to_dict(self) -> dict[str, float | int]:
        return {
            "content_chars": int(self.content_chars),
            "chars_non_space": int(self.chars_non_space),
            "density": float(self.density),
            "replacement_chars": int(self.replacement_chars),
            "replacement_ratio": float(self.replacement_ratio),
            "lines": int(self.lines),
            "avg_line_len": float(self.avg_line_len),
        }


def score_parsed_text_quality(text: str) -> TextQualityScore:
    raw = text or ""
    lines = raw.splitlines()
    line_count = len(lines) if lines else 0
    chars_non_space = sum(1 for ch in raw if not ch.isspace())
    content_chars = len(_ALNUM_CJK_RE.findall(raw))
    density = (content_chars / max(1, chars_non_space)) if chars_non_space else 0.0
    replacement_chars = raw.count("\ufffd")
    replacement_ratio = (replacement_chars / max(1, len(raw))) if raw else 0.0
    avg_line_len = (chars_non_space / max(1, line_count)) if line_count else 0.0

    return TextQualityScore(
        content_chars=int(content_chars),
        chars_non_space=int(chars_non_space),
        density=float(density),
        replacement_chars=int(replacement_chars),
        replacement_ratio=float(replacement_ratio),
        lines=int(line_count),
        avg_line_len=float(avg_line_len),
    )


__all__ = [
    "TextQualityScore",
    "score_parsed_text_quality",
]

