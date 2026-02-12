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

from __future__ import annotations

import re
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


_BLOCKQUOTE_LEAD_RE = re.compile(r"^(?P<lead>[ \t]*>(?:[ \t]*>[ \t]*)*)(?P<body>.*)$")
_CODE_FENCE_RE = re.compile(r"^(?P<indent>[ \t]*)(?P<ticks>`{3,})(?P<rest>.*)$")
_HEADING_RE = re.compile(r"^(?P<indent>[ \t]*)(?P<hashes>#{1,6})(?P<space>[ \t]*)(?P<title>\S.*)$")
_ULIST_RE = re.compile(r"^(?P<indent>[ \t]*)(?P<marker>[-*+])(?P<space>[ \t]+)(?P<rest>.*)$")
_OLIST_RE = re.compile(r"^(?P<indent>[ \t]*)(?P<num>\d{1,3})(?P<delim>[.)])(?P<space>[ \t]+)(?P<rest>.*)$")
_INDENTED_CODE_RE = re.compile(r"^(?:\t| {4,})\S")


def _split_blockquote_lead(line: str) -> tuple[str, str]:
    m = _BLOCKQUOTE_LEAD_RE.match(line or "")
    if not m:
        return "", line or ""
    return (m.group("lead") or ""), (m.group("body") or "")


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
        lead, body = _split_blockquote_lead(raw_line)

        m_fence = _CODE_FENCE_RE.match(body)
        if m_fence:
            indent = m_fence.group("indent") or ""
            ticks = m_fence.group("ticks") or "```"
            rest = m_fence.group("rest") or ""

            if not in_fence:
                # Opening fence: strip leading/trailing whitespace in info string.
                info = rest.strip()
                new_body = f"{indent}{ticks}{info}" if info else f"{indent}{ticks}"
            else:
                # Closing fence: keep only the fence marker.
                new_body = f"{indent}{ticks}"

            if new_body != body:
                code_fences_changed += 1

            out_lines.append(f"{lead}{new_body}")
            in_fence = not in_fence
            continue

        if in_fence:
            out_lines.append(raw_line)
            continue

        # If this line is an indented code block (4+ spaces) and is NOT a list/heading,
        # do not attempt canonicalization (avoid accidental semantics changes).
        if _INDENTED_CODE_RE.match(body) and not (_ULIST_RE.match(body) or _OLIST_RE.match(body) or _HEADING_RE.match(body)):
            out_lines.append(raw_line)
            continue

        # Headings.
        m_head = _HEADING_RE.match(body)
        if m_head:
            indent = m_head.group("indent") or ""
            hashes = m_head.group("hashes") or ""
            title = (m_head.group("title") or "").rstrip()
            new_body = f"{indent}{hashes} {title}"
            if new_body != body:
                headings_changed += 1
            out_lines.append(f"{lead}{new_body}")
            continue

        # Unordered list markers.
        m_ul = _ULIST_RE.match(body)
        if m_ul:
            indent = m_ul.group("indent") or ""
            rest = (m_ul.group("rest") or "")
            new_body = f"{indent}- {rest.lstrip()}"
            if new_body != body:
                list_markers_changed += 1
            out_lines.append(f"{lead}{new_body}")
            continue

        # Ordered list markers.
        m_ol = _OLIST_RE.match(body)
        if m_ol:
            indent = m_ol.group("indent") or ""
            num = m_ol.group("num") or "1"
            rest = (m_ol.group("rest") or "")
            new_body = f"{indent}{num}. {rest.lstrip()}"
            if new_body != body:
                olist_markers_changed += 1
            out_lines.append(f"{lead}{new_body}")
            continue

        out_lines.append(raw_line)

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

