"""
Parsed-text quality scoring utilities.

This is used after parsing (before chunking) to:
- attach lightweight observability metrics
- optionally trigger parser fallback when output is obviously low-quality

It is intentionally cheap and dependency-free.
"""

import re
from dataclasses import asdict, dataclass

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
        return asdict(self)


def score_parsed_text_quality(text: str) -> TextQualityScore:
    line_count = len(text.splitlines())
    chars_non_space = sum(1 for char in text if not char.isspace())
    content_chars = len(_ALNUM_CJK_RE.findall(text))
    density = content_chars / chars_non_space if chars_non_space else 0.0
    replacement_chars = text.count("\ufffd")
    replacement_ratio = replacement_chars / len(text) if text else 0.0
    avg_line_len = chars_non_space / line_count if line_count else 0.0

    return TextQualityScore(
        content_chars=content_chars,
        chars_non_space=chars_non_space,
        density=density,
        replacement_chars=replacement_chars,
        replacement_ratio=replacement_ratio,
        lines=line_count,
        avg_line_len=avg_line_len,
    )


__all__ = [
    "TextQualityScore",
    "score_parsed_text_quality",
]
