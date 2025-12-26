from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Callable, Iterable, Optional, Sequence


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
_ZERO_WIDTH_RE = re.compile(r"[\u200b\u200c\u200d\u2060\ufeff]")
_TRAILING_SPACES_RE = re.compile(r"[ \t]+\n")
_MANY_BLANK_LINES_RE = re.compile(r"\n{3,}")
_ALNUM_CJK_RE = re.compile(r"[A-Za-z0-9\u4e00-\u9fff]")
_TOC_HEADER_RE = re.compile(r"^\s*(?:table of contents|contents|\u76ee\u5f55)\s*$", re.IGNORECASE)
_TOC_LINE_RE = re.compile(
    r"^\s*(?:\d+|[IVXLC]+|[\u4e00-\u9fff]+)[\.\-\u3001)]?\s+.+"
    r"(?:\.{2,}|\u00b7{2,}|\u2026{2,}|-{4,})\s*\d+\s*$"
)
_CODE_FENCE_RE = re.compile(r"^\s*```")
_HEADING_RE = re.compile(r"^\s*#{1,6}\s+")
_LIST_RE = re.compile(r"^\s*(?:[-*+]|(?:\d{1,3}[.)]))\s+")
_BLOCKQUOTE_RE = re.compile(r"^\s*>")
_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
_SENT_END_RE = re.compile(r"[.!?\u3002\uff01\uff1f\uff1b;:\uff1a]\s*$")
_TRAILING_PAGE_NUM_RE = re.compile(r"\s+\d{1,4}\s*$")
_TRAILING_PAGE_OF_RE = re.compile(r"\s+\d{1,4}\s*/\s*\d{1,4}\s*$")
_TRAILING_PAGE_WORD_RE = re.compile(r"\s+(?:page|p\.?)\s*\d{1,4}\s*$", re.IGNORECASE)
_LEADING_LINE_NUMBER_RE = re.compile(r"^(\s*)\d{1,4}\s+(?=\S)")


def clean_markdown(
    markdown: str,
    *,
    rules: Optional[Iterable[RegexRule]] = None,
    normalize_line_endings: bool = True,
    trim_trailing_spaces: bool = True,
    collapse_blank_lines: bool = True,
    remove_control_chars: bool = True,
    remove_toc_lines: bool = True,
    remove_noise_lines: bool = True,
    unwrap_lines: bool = True,
    remove_common_lines: bool = True,
    common_lines: Optional[set[str]] = None,
    unwrap_max_line_length: int = 120,
    noise_min_chars: int = 2,
    noise_ratio_threshold: float = 0.2,
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

    # Normalize some common Unicode whitespace artifacts from PDF/Office exporters.
    text = text.replace("\u00a0", " ").replace("\u202f", " ")
    text = _ZERO_WIDTH_RE.sub("", text)

    if remove_control_chars:
        text = _CONTROL_CHARS_RE.sub("", text)

    applied = 0
    if rules:
        for rule in rules:
            text2 = re.sub(rule.pattern, rule.repl, text, flags=rule.flags)
            if text2 != text:
                applied += 1
                text = text2

    if remove_toc_lines or remove_noise_lines or unwrap_lines or remove_common_lines:
        lines = text.split("\n")
        if remove_noise_lines and _detect_leading_line_numbers(lines):
            lines = _strip_leading_line_numbers(lines)
        lines = _filter_lines(
            lines,
            remove_toc_lines=remove_toc_lines,
            remove_noise_lines=remove_noise_lines,
            remove_common_lines=remove_common_lines,
            common_lines=common_lines,
            noise_min_chars=noise_min_chars,
            noise_ratio_threshold=noise_ratio_threshold,
        )
        if unwrap_lines:
            lines = _unwrap_soft_line_breaks(lines, max_line_length=unwrap_max_line_length)
        text = "\n".join(lines)

    if trim_trailing_spaces:
        text = _TRAILING_SPACES_RE.sub("\n", text)

    if collapse_blank_lines:
        text = _MANY_BLANK_LINES_RE.sub("\n\n", text)

    return CleaningResult(markdown=text, applied_rules=applied, changed=(text != original))


def build_common_line_signatures(
    texts: Sequence[str],
    *,
    min_docs: int = 3,
    min_ratio: float = 0.35,
    max_line_length: int = 120,
) -> set[str]:
    doc_count = len(texts)
    if doc_count < min_docs:
        return set()

    line_docs: dict[str, int] = {}
    for text in texts:
        seen: set[str] = set()
        for line in text.splitlines():
            key = _normalize_line_signature(line)
            if not key:
                continue
            if len(key) > max_line_length:
                continue
            seen.add(key)
        for key in seen:
            line_docs[key] = line_docs.get(key, 0) + 1

    common: set[str] = set()
    for key, count in line_docs.items():
        if count >= min_docs and (count / doc_count) >= min_ratio:
            common.add(key)
    return common


def build_repeated_line_signatures(
    text: str,
    *,
    min_occurrences: int = 3,
    max_line_length: int = 120,
) -> set[str]:
    if not text:
        return set()

    counts: dict[str, int] = {}
    in_code = False
    for raw_line in text.splitlines():
        if _CODE_FENCE_RE.match(raw_line):
            in_code = not in_code
            continue
        if in_code:
            continue
        if _is_structural_line(raw_line):
            continue
        key = _normalize_line_signature(raw_line)
        if not key:
            continue
        if len(key) > max_line_length:
            continue
        counts[key] = counts.get(key, 0) + 1

    return {k for k, c in counts.items() if c >= max(2, int(min_occurrences))}


def _normalize_line_signature(line: str) -> str:
    text = line.strip()
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    text = _TRAILING_PAGE_OF_RE.sub("", text)
    text = _TRAILING_PAGE_WORD_RE.sub("", text)
    text = _TRAILING_PAGE_NUM_RE.sub("", text)
    return text.strip().casefold()


def _filter_lines(
    lines: list[str],
    *,
    remove_toc_lines: bool,
    remove_noise_lines: bool,
    remove_common_lines: bool,
    common_lines: Optional[set[str]],
    noise_min_chars: int,
    noise_ratio_threshold: float,
) -> list[str]:
    filtered: list[str] = []
    in_code = False

    for line in lines:
        if _CODE_FENCE_RE.match(line):
            in_code = not in_code
            filtered.append(line)
            continue
        if in_code:
            filtered.append(line)
            continue

        stripped = line.strip()
        if not stripped:
            filtered.append(line)
            continue

        if remove_common_lines and common_lines:
            signature = _normalize_line_signature(line)
            if signature and signature in common_lines:
                continue

        if remove_toc_lines and (_TOC_HEADER_RE.match(stripped) or _TOC_LINE_RE.match(stripped)):
            continue

        if remove_noise_lines and _is_noise_line(stripped, noise_min_chars, noise_ratio_threshold):
            continue

        filtered.append(line)

    return filtered


def _detect_leading_line_numbers(lines: list[str], *, min_ratio: float = 0.6, min_lines: int = 20) -> bool:
    considered = 0
    matched = 0
    in_code = False
    for line in lines:
        if _CODE_FENCE_RE.match(line):
            in_code = not in_code
            continue
        if in_code:
            continue
        stripped = line.strip()
        if not stripped:
            continue
        if _is_structural_line(line):
            continue
        considered += 1
        if _LEADING_LINE_NUMBER_RE.match(line):
            matched += 1

    if considered < min_lines:
        return False
    return (matched / considered) >= min_ratio


def _strip_leading_line_numbers(lines: list[str]) -> list[str]:
    in_code = False
    output: list[str] = []
    for line in lines:
        if _CODE_FENCE_RE.match(line):
            in_code = not in_code
            output.append(line)
            continue
        if in_code:
            output.append(line)
            continue
        output.append(_LEADING_LINE_NUMBER_RE.sub(r"\1", line, count=1))
    return output


def _unwrap_soft_line_breaks(lines: list[str], *, max_line_length: int) -> list[str]:
    merged: list[str] = []
    in_code = False
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if _CODE_FENCE_RE.match(line):
            in_code = not in_code
            merged.append(line)
            i += 1
            continue
        if in_code or not stripped:
            merged.append(line)
            i += 1
            continue

        j = i + 1
        current = line
        while j < len(lines) and _should_merge(current, lines[j], max_line_length=max_line_length):
            current = _merge_lines(current, lines[j])
            j += 1
        merged.append(current)
        i = j

    return merged


def _should_merge(line: str, next_line: str, *, max_line_length: int) -> bool:
    if not line.strip() or not next_line.strip():
        return False
    if len(line.strip()) >= max_line_length:
        return False
    if _is_structural_line(line) or _is_structural_line(next_line):
        return False
    if _SENT_END_RE.search(line.rstrip()):
        return False
    if line.rstrip().endswith("|") or next_line.lstrip().startswith("|"):
        return False
    return True


def _merge_lines(line: str, next_line: str) -> str:
    left = line.rstrip()
    right = next_line.lstrip()
    if left.endswith(("-", "\u2013", "\u2014")) and right and right[0].isalpha():
        return f"{left[:-1]}{right}"
    joiner = "" if _is_cjk(left[-1:]) and _is_cjk(right[:1]) else " "
    return f"{left}{joiner}{right}"


def _is_structural_line(line: str) -> bool:
    return bool(
        _HEADING_RE.match(line)
        or _LIST_RE.match(line)
        or _BLOCKQUOTE_RE.match(line)
        or _TABLE_ROW_RE.match(line)
    )


def _is_noise_line(line: str, min_chars: int, ratio_threshold: float) -> bool:
    if _is_structural_line(line):
        return False
    alnum = _ALNUM_CJK_RE.findall(line)
    count = len(alnum)
    if count == 0:
        return True
    if count < min_chars and len(line) <= 6:
        return True
    return (count / len(line)) < ratio_threshold


def _is_cjk(text: str) -> bool:
    if not text:
        return False
    ch = text[0]
    code = ord(ch)
    return (
        0x4E00 <= code <= 0x9FFF
        or 0x3400 <= code <= 0x4DBF
        or 0xF900 <= code <= 0xFAFF
    )
