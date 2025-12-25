from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Callable, Iterable, Optional


@dataclass(frozen=True)
class RegexRule:
    pattern: str
    repl: str | Callable[[re.Match[str]], str] = ""
    flags: int = 0


@dataclass(frozen=True)
class CleaningResult:
    markdown: str
    applied_rules: int
    changed: bool


_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_TRAILING_SPACES_RE = re.compile(r"[ \t]+\n")
_MANY_BLANK_LINES_RE = re.compile(r"\n{3,}")


def clean_markdown(
    markdown: str,
    *,
    rules: Optional[Iterable[RegexRule]] = None,
    normalize_line_endings: bool = True,
    trim_trailing_spaces: bool = True,
    collapse_blank_lines: bool = True,
    remove_control_chars: bool = True,
) -> CleaningResult:
    """
    Lightweight Markdown cleaning used for "data governance" before chunking.

    Notes:
    - This is intentionally conservative (no semantic rewriting of Markdown).
    - More domain-specific transforms should be added as explicit RegexRule entries.
    """
    original = markdown
    text = markdown

    if normalize_line_endings:
        text = text.replace("\r\n", "\n").replace("\r", "\n")

    if remove_control_chars:
        text = _CONTROL_CHARS_RE.sub("", text)

    if trim_trailing_spaces:
        text = _TRAILING_SPACES_RE.sub("\n", text)

    if collapse_blank_lines:
        text = _MANY_BLANK_LINES_RE.sub("\n\n", text)

    applied = 0
    if rules:
        for rule in rules:
            text2 = re.sub(rule.pattern, rule.repl, text, flags=rule.flags)
            if text2 != text:
                applied += 1
                text = text2

    return CleaningResult(markdown=text, applied_rules=applied, changed=(text != original))
