"""
Parsing benchmark helpers for text, table, reading-order, and image quality.

This module provides lightweight, dependency-free proxy metrics so we can
benchmark parsing backends in CI/nightly jobs without requiring heavyweight
evaluation packages in the core backend image.
"""


import difflib
import re
from collections import Counter
from typing import Any

from app.parsing.quality.grits import compute_table_collection_grits
from app.parsing.quality.reading_order import score_reading_order

_FENCE_RE = re.compile(r"^\s*(```+|~~~+)")
_MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_HTML_IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_HTML_IMG_ATTR_RE = re.compile(r"(src|alt)\s*=\s*([\"'])(.*?)\2", re.IGNORECASE)
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_HTML_TAG_RE = re.compile(r"(?is)<[^>]+>")
_WS_RE = re.compile(r"\s+")


def markdown_to_text(markdown: str) -> str:
    """
    Best-effort Markdown -> plain text (bounded, deterministic).
    """
    raw = str(markdown or "")
    if not raw.strip():
        return ""

    out_lines: list[str] = []
    in_fence = False
    for line in raw.splitlines():
        if _FENCE_RE.match(line or ""):
            in_fence = not in_fence
            continue
        if in_fence:
            continue

        s = str(line or "")
        s = _MD_IMAGE_RE.sub(" ", s)
        s = _HTML_TAG_RE.sub(" ", s)
        # Keep link label, drop URL.
        s = _MD_LINK_RE.sub(r"\1", s)
        s = s.replace("\u00ad", "")  # soft hyphen
        out_lines.append(s)

    text = "\n".join(out_lines)
    text = _WS_RE.sub(" ", text).strip()
    return text


def normalized_text_similarity(a: str, b: str) -> float:
    """
    Proxy metric for "text edit distance": SequenceMatcher ratio in [0, 1].
    """
    aa = markdown_to_text(a)
    bb = markdown_to_text(b)
    if not aa and not bb:
        return 1.0
    return float(difflib.SequenceMatcher(a=aa, b=bb).ratio())


def extract_markdown_images(markdown: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    raw = str(markdown or "")
    if not raw:
        return out

    for src in _MD_IMAGE_RE.findall(raw):
        out.append({"src": str(src or ""), "kind": "markdown"})

    for tag in _HTML_IMG_TAG_RE.findall(raw):
        src = ""
        alt = ""
        for key, _q, val in _HTML_IMG_ATTR_RE.findall(tag):
            k = (key or "").strip().lower()
            if k == "src":
                src = val
            elif k == "alt":
                alt = val
        if src or alt:
            out.append({"src": str(src or ""), "alt": str(alt or ""), "kind": "html"})

    return out


def extract_pipe_tables(markdown: str) -> list[list[list[str]]]:
    """
    Parse GitHub-flavored pipe tables into a list of matrices.

    This is intentionally simple; it is used as a fallback when true TEDS is not available.
    """
    raw = str(markdown or "")
    if not raw.strip():
        return []

    lines = raw.splitlines()
    tables: list[list[list[str]]] = []
    buf: list[str] = []

    def _flush() -> None:
        nonlocal buf
        if len(buf) < 2:
            buf = []
            return
        rows: list[list[str]] = []
        for line in buf:
            s = (line or "").strip()
            if not (s.startswith("|") and s.endswith("|") and s.count("|") >= 2):
                continue
            parts = [p.strip() for p in s.strip("|").split("|")]
            if parts and all(re.fullmatch(r"[:\s-]+", p or "") for p in parts):
                # separator line like | --- | --- |
                continue
            rows.append(parts)
        if rows:
            tables.append(rows)
        buf = []

    for line in lines:
        s = (line or "").strip()
        looks_like_row = s.startswith("|") and s.endswith("|") and s.count("|") >= 2
        if looks_like_row:
            buf.append(line)
        else:
            _flush()
    _flush()
    return tables


def table_cell_f1(pred_tables: list[list[list[str]]], gold_tables: list[list[list[str]]]) -> float | None:
    """
    Proxy table similarity metric.

    Returns:
    - None when both sides have no table cells.
    - F1 in [0, 1] for cell text overlap (multiset).
    """
    pred_cells: list[str] = []
    for t in pred_tables or []:
        for row in t:
            for cell in row:
                c = _WS_RE.sub(" ", str(cell or "")).strip().lower()
                if c:
                    pred_cells.append(c)

    gold_cells: list[str] = []
    for t in gold_tables or []:
        for row in t:
            for cell in row:
                c = _WS_RE.sub(" ", str(cell or "")).strip().lower()
                if c:
                    gold_cells.append(c)

    if not pred_cells and not gold_cells:
        return None

    pred_counter = Counter(pred_cells)
    gold_counter = Counter(gold_cells)
    overlap = sum(min(pred_counter[k], gold_counter.get(k, 0)) for k in pred_counter.keys())
    pred_total = sum(pred_counter.values())
    gold_total = sum(gold_counter.values())
    if pred_total <= 0 or gold_total <= 0:
        return 0.0
    precision = float(overlap) / float(pred_total)
    recall = float(overlap) / float(gold_total)
    if precision + recall <= 0:
        return 0.0
    return 2.0 * precision * recall / (precision + recall)


def compute_parsing_proxy_metrics(
    *,
    parsed_markdown: str,
    golden_markdown: str,
) -> dict[str, Any]:
    """
    Compute proxy metrics for parser benchmarking.
    """
    pred = str(parsed_markdown or "")
    gold = str(golden_markdown or "")

    text_sim = normalized_text_similarity(pred, gold)
    pred_tables = extract_pipe_tables(pred)
    gold_tables = extract_pipe_tables(gold)
    table_sim = table_cell_f1(pred_tables, gold_tables)
    table_grits = compute_table_collection_grits(pred_tables=pred_tables, gold_tables=gold_tables)

    pred_imgs = extract_markdown_images(pred)
    gold_imgs = extract_markdown_images(gold)
    gold_img_count = len(gold_imgs)
    image_recall: float | None = None
    if gold_img_count > 0:
        image_recall = min(1.0, float(len(pred_imgs)) / float(gold_img_count))

    ro = score_reading_order(pred)
    reading_order_score = None
    if isinstance(ro, dict):
        reading_order_score = ro.get("score")

    return {
        "text_similarity": round(float(text_sim), 4),
        "table_cell_f1": (None if table_sim is None else round(float(table_sim), 4)),
        "table_grits_topology": table_grits["topology"],
        "table_grits_content": table_grits["content"],
        "table_grits_f1": table_grits["f1"],
        "reading_order_score": (None if reading_order_score is None else round(float(reading_order_score), 4)),
        "images_pred": int(len(pred_imgs)),
        "images_gold": int(gold_img_count),
        "image_recall": (None if image_recall is None else round(float(image_recall), 4)),
    }


__all__ = [
    "compute_parsing_proxy_metrics",
    "extract_markdown_images",
    "extract_pipe_tables",
    "markdown_to_text",
    "normalized_text_similarity",
    "table_cell_f1",
]
