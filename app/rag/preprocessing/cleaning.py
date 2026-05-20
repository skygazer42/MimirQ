import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, cast

from app.core.regex_runtime import RegexSubstitutionTimeoutError, safe_subn as safe_regex_subn
from app.rag.preprocessing.normalization import normalize_text
from app.rag.preprocessing.segmentation import limit_blank_lines


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
    # Per-regex-rule substitution counts (aligned with the input `rules` order).
    rule_hits: list[int] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CleaningOptions:
    rules: Iterable[RegexRule] | None = None
    regex_timeout_ms: int | None = None
    normalize_line_endings: bool = True
    trim_trailing_spaces: bool = True
    collapse_blank_lines: bool = True
    max_blank_lines: int = 1
    remove_control_chars: bool = True
    remove_toc_lines: bool = True
    remove_noise_lines: bool = True
    unwrap_lines: bool = True
    remove_common_lines: bool = True
    common_lines: set[str] | None = None
    unwrap_max_line_length: int = 120
    noise_min_chars: int = 2
    noise_ratio_threshold: float = 0.2


_MID_WS_RE = re.compile(r"(?<=\S)[ \t]{2,}(?=\S)")
_ALNUM_CJK_RE = re.compile(r"[A-Za-z0-9\u4e00-\u9fff]")
_UPPER_RUN_RE = re.compile(r"[A-Z]{3,}")
_TOC_HEADER_RE = re.compile(r"^\s*(?:table of contents|contents|\u76ee\s*\u5f55)\s*$", re.IGNORECASE)
_TOC_LINE_RE = re.compile(
    r"^\s*(?:\d+|[IVXLC]+|[\u4e00-\u9fff]+)[\.\-\u3001)]?\s+.+"
    r"(?:\.{2,}|\u00b7{2,}|\u2026{2,}|-{4,})\s*\d+\s*$"
)
_TOC_LINE_EN_RE = re.compile(
    r"^\s*(?:chapter|section)\s+\d+\b.+"
    r"(?:\.{2,}|\u00b7{2,}|\u2026{2,}|-{4,})\s*\d+\s*$",
    re.IGNORECASE,
)
_CODE_FENCE_RE = re.compile(r"^\s*```")
_HEADING_RE = re.compile(r"^\s*#{1,6}\s+")
_LIST_RE = re.compile(r"^\s*(?:[-*+]|\d{1,3}[.)])\s+")
_BLOCKQUOTE_RE = re.compile(r"^\s*>")
_INDENTED_CODE_RE = re.compile(r"^(?:\t| {4,})\S")
_SENT_END_RE = re.compile(r"[.!?\u3002\uff01\uff1f\uff1b;:\uff1a]\s*$")
_LEADING_LINE_NUMBER_RE = re.compile(r"^(\s*)\d{1,4}\s+(?=\S)")

_PDF_BULLETS: tuple[str, ...] = (
    "\u2022",  # •
    "\u25cf",  # ●
    "\u25aa",  # ▪
    "\u25a0",  # ■
    "\u25c6",  # ◆
    "\u25e6",  # ◦
    "\u2043",  # ⁃
    "\uf0b7",  #  (common private-use bullet from some PDF extractors)
)


def _trim_trailing_spaces(text: str) -> str:
    """Remove trailing ASCII spaces/tabs before newlines (linear time; no regex)."""
    if not text or "\n" not in text:
        return text
    out: list[str] = []
    for line in text.splitlines(keepends=True):
        if line.endswith("\n"):
            out.append(line[:-1].rstrip(" \t") + "\n")
        else:
            out.append(line)
    return "".join(out)


def _looks_like_pipe_table_row(line: str) -> bool:
    """
    Best-effort: treat any non-empty line containing a pipe as a table row.

    These lines are considered "structural" and should not be merged/rewritten by
    unwrap/noise filters.
    """
    stripped = (line or "").strip()
    return bool("|" in stripped and stripped != "|")


def _skip_spaces_left(text: str, idx: int) -> int:
    while idx > 0 and text[idx - 1].isspace():
        idx -= 1
    return idx


def _consume_digits_left(text: str, idx: int, *, max_digits: int) -> int:
    start = idx
    digits = 0
    while idx > 0 and text[idx - 1].isdigit():
        idx -= 1
        digits += 1
        if digits > max_digits:
            return start
    return idx if digits >= 1 else start


def _strip_trailing_page_of(text: str) -> str:
    # Equivalent to: r"\s+\d{1,4}\s*/\s*\d{1,4}\s*$"
    s = (text or "").rstrip()
    i = len(s)
    j = _consume_digits_left(s, i, max_digits=4)
    if j == i:
        return text
    k = _skip_spaces_left(s, j)
    if k <= 0 or s[k - 1] != "/":
        return text
    k -= 1
    k = _skip_spaces_left(s, k)
    k2 = _consume_digits_left(s, k, max_digits=4)
    if k2 == k:
        return text
    # Require whitespace before the first number (matches leading \s+)
    if k2 <= 0 or not s[k2 - 1].isspace():
        return text
    return s[:k2]


def _strip_trailing_page_word(text: str) -> str:
    # Equivalent to: r"\s+(?:page|p\.?)\s*\d{1,4}\s*$" (case-insensitive)
    s = (text or "").rstrip()
    i = len(s)
    j = _consume_digits_left(s, i, max_digits=4)
    if j == i:
        return text
    k = _skip_spaces_left(s, j)
    token_end = k
    token_start = token_end
    while token_start > 0 and (s[token_start - 1].isalpha() or s[token_start - 1] == "."):
        token_start -= 1
    token = s[token_start:token_end].casefold()
    if token not in {"page", "p", "p."}:
        return text
    if token_start <= 0 or not s[token_start - 1].isspace():
        return text
    return s[:token_start]


def _strip_trailing_page_num(text: str) -> str:
    # Equivalent to: r"\s+\d{1,4}\s*$"
    s = (text or "").rstrip()
    i = len(s)
    j = _consume_digits_left(s, i, max_digits=4)
    if j == i:
        return text
    if j <= 0 or not s[j - 1].isspace():
        return text
    return s[:j]


def _strip_trailing_page_cn_of(text: str) -> str:
    # Equivalent to: r"\s*第?\s*\d{1,4}\s*页\s*/\s*共?\s*\d{1,4}\s*页\s*$"
    s = (text or "").rstrip()
    i = _skip_spaces_left(s, len(s))
    if i <= 0 or s[i - 1] != "页":
        return text
    i -= 1
    i = _skip_spaces_left(s, i)
    i2 = _consume_digits_left(s, i, max_digits=4)
    if i2 == i:
        return text
    i = _skip_spaces_left(s, i2)
    if i > 0 and s[i - 1] == "共":
        i -= 1
        i = _skip_spaces_left(s, i)
    if i <= 0 or s[i - 1] != "/":
        return text
    i -= 1
    i = _skip_spaces_left(s, i)
    if i <= 0 or s[i - 1] != "页":
        return text
    i -= 1
    i = _skip_spaces_left(s, i)
    i3 = _consume_digits_left(s, i, max_digits=4)
    if i3 == i:
        return text
    i = _skip_spaces_left(s, i3)
    if i > 0 and s[i - 1] == "第":
        i -= 1
        i = _skip_spaces_left(s, i)
    return s[:i]


def _strip_trailing_page_cn(text: str) -> str:
    # Equivalent to: r"\s*第?\s*\d{1,4}\s*页\s*$"
    s = (text or "").rstrip()
    i = _skip_spaces_left(s, len(s))
    if i <= 0 or s[i - 1] != "页":
        return text
    i -= 1
    i = _skip_spaces_left(s, i)
    i2 = _consume_digits_left(s, i, max_digits=4)
    if i2 == i:
        return text
    i = _skip_spaces_left(s, i2)
    if i > 0 and s[i - 1] == "第":
        i -= 1
        i = _skip_spaces_left(s, i)
    return s[:i]


def _strip_trailing_page_markers(text: str) -> str:
    # Keep the same order as the legacy regex substitutions.
    out = _strip_trailing_page_of(text)
    if out != text:
        return out
    out = _strip_trailing_page_word(text)
    if out != text:
        return out
    out = _strip_trailing_page_num(text)
    if out != text:
        return out
    out = _strip_trailing_page_cn_of(text)
    if out != text:
        return out
    return _strip_trailing_page_cn(text)


def _resolve_cleaning_options(
    *,
    options: CleaningOptions | None,
    legacy_overrides: dict[str, Any],
) -> CleaningOptions:
    if options is None:
        return CleaningOptions(**legacy_overrides)
    if not legacy_overrides:
        return options
    return cast(CleaningOptions, replace(options, **legacy_overrides))


def clean_markdown(
    markdown: str,
    *,
    options: CleaningOptions | None = None,
    **legacy_overrides: Any,
) -> CleaningResult:
    """
    Lightweight Markdown cleaning used for "data governance" before chunking.

    Notes:
    - This is intentionally conservative (no semantic rewriting of Markdown).
    - More domain-specific transforms should be added as explicit RegexRule entries.
    """
    clean_options = _resolve_cleaning_options(options=options, legacy_overrides=legacy_overrides)
    rules = clean_options.rules
    regex_timeout_ms = clean_options.regex_timeout_ms
    normalize_line_endings = clean_options.normalize_line_endings
    trim_trailing_spaces = clean_options.trim_trailing_spaces
    collapse_blank_lines = clean_options.collapse_blank_lines
    max_blank_lines = clean_options.max_blank_lines
    remove_control_chars = clean_options.remove_control_chars
    remove_toc_lines = clean_options.remove_toc_lines
    remove_noise_lines = clean_options.remove_noise_lines
    unwrap_lines = clean_options.unwrap_lines
    remove_common_lines = clean_options.remove_common_lines
    common_lines = clean_options.common_lines
    unwrap_max_line_length = clean_options.unwrap_max_line_length
    noise_min_chars = clean_options.noise_min_chars
    noise_ratio_threshold = clean_options.noise_ratio_threshold

    original = markdown
    text = normalize_text(
        markdown,
        normalize_line_endings=bool(normalize_line_endings),
        remove_control_chars=bool(remove_control_chars),
    )

    applied = 0
    rule_hits: list[int] = []
    regex_timeout_rules: list[dict[str, Any]] = []
    if rules:
        for idx, rule in enumerate(rules):
            try:
                text2, n = safe_regex_subn(
                    pattern=rule.pattern,
                    repl=rule.repl,
                    text=text,
                    flags=rule.flags,
                    timeout_ms=regex_timeout_ms,
                    rule_index=int(idx),
                )
            except RegexSubstitutionTimeoutError as exc:
                detail = exc.to_detail()
                regex_timeout_rules.append(
                    {
                        "rule_index": int(detail.get("rule_index") or idx),
                        "timeout_ms": int(detail.get("timeout_ms") or regex_timeout_ms or 0),
                        "pattern": str(detail.get("pattern") or ""),
                    }
                )
                rule_hits.append(0)
                continue
            rule_hits.append(int(n or 0))
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
        # Post-process line-level artifacts typical for PDF/DOC exporters.
        lines = _normalize_text_lines(lines)
        text = "\n".join(lines)

    if trim_trailing_spaces:
        text = _trim_trailing_spaces(text)

    if collapse_blank_lines:
        text = limit_blank_lines(text, max_blank_lines=max_blank_lines)

    stats: dict[str, Any] = {
        "regex_timeout_count": len(regex_timeout_rules),
        "regex_timeout_rules": regex_timeout_rules,
    }
    return CleaningResult(
        markdown=text,
        applied_rules=applied,
        changed=(text != original),
        rule_hits=rule_hits,
        stats=stats,
    )


def build_common_line_signatures(
    texts: Sequence[str],
    *,
    min_docs: int = 3,
    min_ratio: float = 0.35,
    max_line_length: int = 120,
) -> set[str]:
    doc_count = len(texts)
    min_docs = max(2, int(min_docs or 0))
    if doc_count < min_docs:
        return set()

    line_docs: dict[str, int] = {}
    for text in texts:
        seen: set[str] = set()
        in_code = False
        for line in text.splitlines():
            if _CODE_FENCE_RE.match(line):
                in_code = not in_code
                continue
            if in_code:
                continue
            if _is_structural_line(line):
                continue
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


def _normalize_line_for_display(line: str) -> str:
    """
    Normalize a line for user-facing display (keeps original casing).

    Keep this aligned with _normalize_line_signature() so candidates map cleanly to signatures.
    """
    text = (line or "").strip()
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    text = _strip_trailing_page_markers(text)
    return text.strip()


def learn_common_line_candidates(
    texts: Sequence[str],
    *,
    min_docs: int = 3,
    min_ratio: float = 0.35,
    max_line_length: int = 120,
    max_candidates: int = 50,
) -> list[dict[str, object]]:
    """
    Suggest "common lines" across multiple documents (dataset-level learning mode).

    Returns a list of dicts with keys:
      - signature: normalized signature (casefolded)
      - sample: display text (original casing, whitespace collapsed)
      - docs: doc frequency
      - ratio: docs / total_docs

    Notes:
    - This is best-effort and intentionally conservative; it skips code fences and structural lines.
    - The consumer (UI) can convert `sample` into a regex rule (e.g. (?mi)^\\s*...\\s*$).
    """
    if not texts:
        return []

    doc_count = len(texts)
    min_docs_eff = max(2, int(min_docs or 0))
    if doc_count < min_docs_eff:
        return []

    max_line_length_eff = max(0, int(max_line_length or 0)) or 120

    line_docs: dict[str, int] = {}
    samples: dict[str, str] = {}

    for text in texts:
        seen: set[str] = set()
        in_code = False
        for raw_line in (text or "").splitlines():
            if _CODE_FENCE_RE.match(raw_line):
                in_code = not in_code
                continue
            if in_code:
                continue
            if _is_structural_line(raw_line):
                continue

            signature = _normalize_line_signature(raw_line)
            if not signature:
                continue
            if len(signature) > max_line_length_eff:
                continue

            seen.add(signature)
            if signature not in samples:
                samples[signature] = _normalize_line_for_display(raw_line) or signature

        for sig in seen:
            line_docs[sig] = line_docs.get(sig, 0) + 1

    min_ratio_eff = float(min_ratio or 0.0)
    min_ratio_eff = max(0.0, min(1.0, min_ratio_eff))

    out: list[dict[str, object]] = []
    for sig, count in line_docs.items():
        ratio = float(count) / float(doc_count) if doc_count else 0.0
        if count < min_docs_eff:
            continue
        if ratio < min_ratio_eff:
            continue
        out.append(
            {
                "signature": sig,
                "sample": samples.get(sig, sig),
                "docs": int(count),
                "ratio": float(ratio),
            }
        )

    out.sort(key=lambda it: (int(it.get("docs", 0) or 0), float(it.get("ratio", 0.0) or 0.0)), reverse=True)

    cap = max(1, int(max_candidates or 0)) if int(max_candidates or 0) else 50
    cap = max(1, min(cap, 200))
    return out[:cap]


def _normalize_line_signature(line: str) -> str:
    text = line.strip()
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    text = _strip_trailing_page_markers(text)
    return text.strip().casefold()


def _filter_lines(
    lines: list[str],
    *,
    remove_toc_lines: bool,
    remove_noise_lines: bool,
    remove_common_lines: bool,
    common_lines: set[str] | None,
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

        if remove_toc_lines and (
            _TOC_HEADER_RE.match(stripped) or _TOC_LINE_RE.match(stripped) or _TOC_LINE_EN_RE.match(stripped)
        ):
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


def _normalize_text_lines(lines: list[str]) -> list[str]:
    """
    Normalize per-line artifacts while preserving Markdown structure.

    - Collapses mid-line excessive whitespace (keeps leading indentation).
    - Repairs OCR/PDF "spaced letters" like "t h i s" -> "this" (conservative).
    """
    if not lines:
        return []

    out: list[str] = []
    in_code = False
    for line in lines:
        if _CODE_FENCE_RE.match(line):
            in_code = not in_code
            out.append(line)
            continue
        if in_code:
            out.append(line)
            continue

        bullet_normalized = _normalize_pdf_bullet_line(line)
        if bullet_normalized is not None:
            out.append(bullet_normalized)
            continue

        if not line.strip() or _is_structural_line(line):
            out.append(line)
            continue

        # Order matters:
        # - collapse OCR spaced letters first (to preserve intentional word boundaries)
        # - then collapse excessive mid-line whitespace from PDF exporters
        text = _collapse_spaced_letters(line)
        text = _MID_WS_RE.sub(" ", text)
        out.append(text)
    return out


def _normalize_pdf_bullet_line(line: str) -> str | None:
    """
    Normalize common PDF bullet characters to Markdown list syntax.

    This is intentionally conservative:
    - Only triggers when the bullet is the first visible character on the line.
    - Skips code fences/blocks (handled by caller).
    - Does not touch already-structured list lines.
    """
    if not line or not line.strip():
        return None

    prefix = line[: len(line) - len(line.lstrip(" \t"))]
    stripped = line.strip()
    for bullet in _PDF_BULLETS:
        if stripped.startswith(bullet):
            rest = stripped[len(bullet) :].lstrip()
            if not rest:
                return None
            return f"{prefix}- {rest}"
    return None


def _collapse_spaced_letters(line: str) -> str:
    """
    Collapse OCR-style spaced letters inside a single line.

    Example:
      "t h i s i s a t e s t" -> "this is a test"

    Safety:
      - Requires >=5 letters in the spaced sequence.
      - Skips ALL-CAPS sequences (e.g. "U S A F") to avoid mangling acronyms.
    """
    if not line or " " not in line:
        return line

    out: list[str] = []
    i = 0
    n = len(line)

    while i < n:
        ch = line[i]
        if ch.isalpha() and (i == 0 or not line[i - 1].isalpha()):
            # Capture sequences like "t h i s" (single spaces between letters).
            j = i
            letters = [ch]
            # Keep collapsing only when each letter is separated by spaces, i.e. avoid
            # accidentally consuming the first character of a normal word like "t e s t".
            while (
                j + 2 < n
                and line[j + 1] == " "
                and line[j + 2].isalpha()
                and (j + 3 >= n or line[j + 3] == " ")
            ):
                letters.append(line[j + 2])
                j += 2

            if len(letters) >= 5:
                word = "".join(letters)
                # Skip ALL-CAPS sequences to avoid mangling acronyms like "U S A F".
                if (
                    not word.isupper()
                    and not _UPPER_RUN_RE.search(word)
                    and sum(1 for c in word if c.islower()) >= 2
                ):
                    out.append(word)
                    i = j + 1
                    continue

            # Not a safe collapse target: keep original slice.
            out.append(line[i : j + 1])
            i = j + 1
            continue

        out.append(ch)
        i += 1

    return "".join(out)


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
    stripped = line.lstrip(" \t")
    if stripped:
        for bullet in _PDF_BULLETS:
            if stripped.startswith(bullet) and (len(stripped) == 1 or stripped[1].isspace()):
                return True

    return bool(
        _HEADING_RE.match(line)
        or _LIST_RE.match(line)
        or _BLOCKQUOTE_RE.match(line)
        or _looks_like_pipe_table_row(line)
        or _INDENTED_CODE_RE.match(line)
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
