"""
Lightweight helpers for representing extracted tables as Markdown pipe tables.

Goals:
- Preserve semantics: do not drop cell values; avoid re-ordering.
- Produce stable "table blocks" so markdown-aware chunkers can keep tables intact.
"""


import re

_WS_RE = re.compile(r"\s+")
_NUMERIC_RE = re.compile(r"^\s*[-+]?(\d+(\.\d+)?|\.\d+)\s*$")


def clean_table_cell(text: str) -> str:
    """
    Normalize a single table cell into a single-line string.

    This is intentionally conservative: it only collapses whitespace and removes
    line breaks, without rewriting content.
    """
    raw = str(text or "")
    raw = raw.replace("\r", " ").replace("\n", " ")
    raw = _WS_RE.sub(" ", raw).strip()
    # Escape pipes so we don't accidentally change the column structure.
    raw = raw.replace("|", r"\|")
    return raw


def _pad_rows(rows: list[list[str]], width: int) -> list[list[str]]:
    out: list[list[str]] = []
    for r in rows:
        rr = list(r) + [""] * max(0, width - len(r))
        out.append(rr[:width])
    return out


def infer_table_header(rows: list[list[str]]) -> tuple[list[str], list[list[str]]]:
    """
    Infer whether the first row is likely a header.

    Returns (header, body_rows). When unsure, we use synthetic column names and
    keep all rows in the body to avoid dropping/repurposing content.
    """
    if not rows:
        return [], []

    width = max((len(r) for r in rows), default=0)
    width = max(0, int(width))
    if width <= 0:
        return [], []

    padded = _pad_rows(rows, width)
    head = padded[0]
    body = padded[1:] if len(padded) > 1 else []

    # Heuristic: header cells should be mostly non-empty, mostly non-numeric, and unique.
    non_empty = [c for c in head if (c or "").strip()]
    if len(padded) >= 2 and len(non_empty) >= max(1, width // 2):
        keys = [(c or "").strip().casefold() for c in non_empty]
        unique = len(set(keys)) == len(keys)
        numeric = sum(1 for c in non_empty if _NUMERIC_RE.match(c or ""))
        avg_len = sum(len(c) for c in non_empty) / max(1, len(non_empty))
        if unique and numeric <= max(1, len(non_empty) // 3) and avg_len <= 40:
            return head, body

    # Fallback: synthetic header names, keep all rows.
    header = [f"col_{i + 1}" for i in range(width)]
    return header, padded


def build_markdown_table(*, header: list[str], rows: list[list[str]]) -> str:
    """
    Build a Markdown pipe table string.
    """
    width = max(len(header), max((len(r) for r in rows), default=0))
    if width <= 0:
        return ""

    header2 = _pad_rows([header], width)[0]
    rows2 = _pad_rows(rows, width)

    def _row(cells: list[str]) -> str:
        safe = [clean_table_cell(c) for c in cells]
        return "| " + " | ".join(safe) + " |"

    align = "| " + " | ".join(["---"] * width) + " |"
    out: list[str] = [_row(header2), align]
    for r in rows2:
        out.append(_row(r))
    return "\n".join(out).strip()


__all__ = ["build_markdown_table", "clean_table_cell", "infer_table_header"]

