"""
Canonical Markdown normalization (idempotent).

Goal: provide a deterministic, semantics-preserving-ish formatting pass that makes
downstream governance/chunking more stable (less diff churn, better header/list cues).

Scope (conservative):
- Normalize line endings / Unicode whitespace artifacts (via normalize_text)
- Normalize heading spacing ("##Heading" -> "## Heading")
- Normalize list markers ("*" / "+" -> "-", "1)" -> "1.")
- Normalize fenced code block markers (``` python -> ```python; trim closing fences)
- Normalize Markdown pipe tables (reuses normalize_markdown_tables)

This module is intentionally dependency-free and line-oriented; it is NOT a full
Markdown parser.
"""


from dataclasses import dataclass

from app.rag.preprocessing.normalization import normalize_text
from app.rag.preprocessing.tables import normalize_markdown_tables


@dataclass(frozen=True)
class MarkdownCanonicalizeResult:
    text: str
    changed: bool

    headings_changed: int = 0
    list_markers_changed: int = 0
    ordered_list_markers_changed: int = 0
    code_fences_changed: int = 0

    tables: int = 0
    table_rows_changed: int = 0


@dataclass(frozen=True)
class _CanonicalLine:
    text: str
    in_fence: bool
    headings_changed: int = 0
    list_markers_changed: int = 0
    ordered_list_markers_changed: int = 0
    code_fences_changed: int = 0


def _split_blockquote_lead(line: str) -> tuple[str, str]:
    """
    Split a markdown blockquote prefix from a line.

    Equivalent to matching a repeating pattern like:
      [ \\t]*> [ \\t]* > [ \\t]* > ...

    Implemented without regex so it stays linear-time and avoids backtracking hotspots.
    """
    s = line or ""
    if not s:
        return "", ""

    i = 0
    n = len(s)
    lead_end = 0
    while i < n:
        # Consume optional whitespace.
        j = i
        while j < n and s[j] in (" ", "\t"):
            j += 1

        if j < n and s[j] == ">":
            j += 1
            while j < n and s[j] in (" ", "\t"):
                j += 1
            lead_end = j
            i = j
            continue
        break

    if lead_end <= 0:
        return "", s
    return s[:lead_end], s[lead_end:]


def _parse_code_fence(line: str) -> tuple[str, str, str] | None:
    """
    Parse a fenced code marker line of the form:
      [ \\t]* ```+ <rest>
    """
    s = line or ""
    if not s:
        return None

    i = 0
    n = len(s)
    while i < n and s[i] in (" ", "\t"):
        i += 1
    indent = s[:i]

    j = i
    while j < n and s[j] == "`":
        j += 1
    if (j - i) < 3:
        return None
    ticks = s[i:j]
    rest = s[j:]
    return indent, ticks, rest


def _parse_heading(line: str) -> tuple[str, str, str] | None:
    """
    Parse ATX headings (1-6 hashes), e.g.:
      '##Heading' or '##  Heading'
    """
    s = line or ""
    if not s:
        return None

    i = 0
    n = len(s)
    while i < n and s[i] in (" ", "\t"):
        i += 1
    indent = s[:i]

    j = i
    while j < n and j - i < 6 and s[j] == "#":
        j += 1
    if j == i:
        return None
    hashes = s[i:j]

    # Allow any amount of whitespace after hashes, but require a non-whitespace title.
    k = j
    while k < n and s[k] in (" ", "\t"):
        k += 1
    if k >= n or s[k].isspace():
        return None
    title = s[k:]
    return indent, hashes, title


def _parse_ulist(line: str) -> tuple[str, str] | None:
    s = line or ""
    if not s:
        return None

    i = 0
    n = len(s)
    while i < n and s[i] in (" ", "\t"):
        i += 1
    indent = s[:i]
    if i >= n or s[i] not in ("-", "*", "+"):
        return None
    i += 1

    if i >= n or s[i] not in (" ", "\t"):
        return None
    while i < n and s[i] in (" ", "\t"):
        i += 1

    return indent, s[i:]


def _parse_olist(line: str) -> tuple[str, str, str] | None:
    s = line or ""
    if not s:
        return None

    i = 0
    n = len(s)
    while i < n and s[i] in (" ", "\t"):
        i += 1
    indent = s[:i]

    start = i
    while i < n and i - start < 3 and s[i].isdigit():
        i += 1
    if i == start:
        return None
    num = s[start:i]

    if i >= n or s[i] not in (".", ")"):
        return None
    i += 1

    if i >= n or s[i] not in (" ", "\t"):
        return None
    while i < n and s[i] in (" ", "\t"):
        i += 1

    return indent, num, s[i:]


def _is_indented_code_line(line: str) -> bool:
    s = line or ""
    if len(s) < 2:
        return False
    if s[0] == "\t":
        return len(s) > 1 and (not s[1].isspace())
    if s.startswith("    "):
        i = 0
        n = len(s)
        while i < n and s[i] == " ":
            i += 1
        return i >= 4 and i < n and (not s[i].isspace())
    return False


def _canonicalize_fence_line(lead: str, body: str, in_fence: bool) -> _CanonicalLine | None:
    fence = _parse_code_fence(body)
    if fence is None:
        return None

    indent, ticks, rest = fence
    if in_fence:
        new_body = f"{indent}{ticks}"
    else:
        info = rest.strip()
        new_body = f"{indent}{ticks}{info}" if info else f"{indent}{ticks}"

    return _CanonicalLine(
        text=f"{lead}{new_body}",
        in_fence=not in_fence,
        code_fences_changed=int(new_body != body),
    )


def _canonicalize_body_line(lead: str, body: str) -> _CanonicalLine:
    head = _parse_heading(body)
    if head is not None:
        indent, hashes, title = head
        new_body = f"{indent}{hashes} {(title or '').rstrip()}"
        return _CanonicalLine(text=f"{lead}{new_body}", in_fence=False, headings_changed=int(new_body != body))

    unordered = _parse_ulist(body)
    if unordered is not None:
        indent, rest = unordered
        new_body = f"{indent}- {rest.lstrip()}"
        return _CanonicalLine(text=f"{lead}{new_body}", in_fence=False, list_markers_changed=int(new_body != body))

    ordered = _parse_olist(body)
    if ordered is not None:
        indent, num, rest = ordered
        new_body = f"{indent}{num or '1'}. {rest.lstrip()}"
        return _CanonicalLine(
            text=f"{lead}{new_body}",
            in_fence=False,
            ordered_list_markers_changed=int(new_body != body),
        )

    return _CanonicalLine(text=f"{lead}{body}", in_fence=False)


def _canonicalize_markdown_line(raw_line: str, in_fence: bool) -> _CanonicalLine:
    lead, body = _split_blockquote_lead(raw_line)
    fence_line = _canonicalize_fence_line(lead, body, in_fence)
    if fence_line is not None:
        return fence_line
    if in_fence:
        return _CanonicalLine(text=raw_line, in_fence=True)
    if _is_indented_code_line(body) and not (_parse_ulist(body) or _parse_olist(body) or _parse_heading(body)):
        return _CanonicalLine(text=raw_line, in_fence=False)
    return _canonicalize_body_line(lead, body)


def canonicalize_markdown(text: str) -> MarkdownCanonicalizeResult:
    original = text if isinstance(text, str) else ""
    if not original:
        return MarkdownCanonicalizeResult(text="", changed=False)

    # Newline normalization is part of the "canonical" contract (idempotent).
    normalized = normalize_text(original, normalize_line_endings=True, remove_control_chars=True)

    in_fence = False
    out_lines: list[str] = []
    headings_changed = 0
    list_markers_changed = 0
    olist_markers_changed = 0
    code_fences_changed = 0

    for raw_line in normalized.splitlines():
        line = _canonicalize_markdown_line(raw_line, in_fence)
        out_lines.append(line.text)
        in_fence = line.in_fence
        headings_changed += line.headings_changed
        list_markers_changed += line.list_markers_changed
        olist_markers_changed += line.ordered_list_markers_changed
        code_fences_changed += line.code_fences_changed

    rebuilt = "\n".join(out_lines)

    # Pipe table canonicalization (code-fence aware).
    tbl = normalize_markdown_tables(rebuilt)
    final = tbl.text

    return MarkdownCanonicalizeResult(
        text=final,
        changed=(final != original),
        headings_changed=int(headings_changed),
        list_markers_changed=int(list_markers_changed),
        ordered_list_markers_changed=int(olist_markers_changed),
        code_fences_changed=int(code_fences_changed),
        tables=int(tbl.tables or 0),
        table_rows_changed=int(tbl.rows_changed or 0),
    )


__all__ = ["MarkdownCanonicalizeResult", "canonicalize_markdown"]
