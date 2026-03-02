"""
Chunk-level quality scoring (heuristics; best-effort).

Goal:
- Provide a lightweight per-chunk signal for "noise/boilerplate" detection.
- Keep dependency-light and JSON-safe so it can be stored in doc_metadata and used by UI/retrieval.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from app.rag.preprocessing.boilerplate import remove_markdown_boilerplate
from app.rag.preprocessing.normalization import normalize_text

_PAGE_MARKER_RE = re.compile(r"(?i)^\s*page\s+\d+(?:\s+of\s+\d+)?\s*$")


def score_chunk_quality(text: str, *, meta: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """
    Score chunk quality in [0,1] and emit a small, explainable payload.

    Output schema (JSON-safe):
      {
        "schema": "mimirq.chunk_quality.v1",
        "score": 0.0-1.0,
        "grade": "good"|"ok"|"bad",
        "labels": [..],
        "signals": {..}
      }
    """
    meta = meta or {}
    norm = normalize_text(text or "", normalize_line_endings=True, remove_control_chars=True).strip()

    labels: list[str] = []
    signals: dict[str, Any] = {}

    if not norm:
        return {
            "schema": "mimirq.chunk_quality.v1",
            "score": 0.0,
            "grade": "bad",
            "labels": ["empty"],
            "signals": {"chars": 0, "lines": 0},
        }

    chars = len(norm)
    lines = norm.count("\n") + 1
    signals["chars"] = int(chars)
    signals["lines"] = int(lines)

    letters = 0
    digits = 0
    symbols = 0
    for ch in norm:
        if ch.isalpha():
            letters += 1
            continue
        if ch.isdigit():
            digits += 1
            continue
        if ch.isspace():
            continue
        symbols += 1

    alpha_ratio = float(letters) / float(chars) if chars else 0.0
    digit_ratio = float(digits) / float(chars) if chars else 0.0
    symbol_ratio = float(symbols) / float(chars) if chars else 0.0
    signals.update(
        {
            "alpha_ratio": round(alpha_ratio, 3),
            "digit_ratio": round(digit_ratio, 3),
            "symbol_ratio": round(symbol_ratio, 3),
        }
    )

    # Boilerplate detection signals (conservative).
    boiler = remove_markdown_boilerplate(norm)
    if getattr(boiler, "changed", False):
        removed_sections = int(getattr(boiler, "removed_sections", 0) or 0)
        removed_lines = int(getattr(boiler, "removed_lines", 0) or 0)
        if removed_sections > 0 or removed_lines > 0:
            labels.append("boilerplate_removed")
        signals["boilerplate_removed_sections"] = removed_sections
        signals["boilerplate_removed_lines"] = removed_lines

    if _PAGE_MARKER_RE.match(norm):
        labels.append("boilerplate_page_marker")

    # Repetition (line-level).
    if lines >= 6:
        ln = [x.strip() for x in norm.splitlines() if x.strip()]
        if ln:
            unique = len(set(ln))
            unique_ratio = float(unique) / float(len(ln))
            signals["unique_line_ratio"] = round(unique_ratio, 3)
            if unique_ratio < 0.5:
                labels.append("repetitive_lines")

    # Score composition (multiplicative, bounded).
    score = 1.0
    if chars < 30:
        score *= 0.2
        labels.append("too_short")
    elif chars < 60:
        score *= 0.7
        labels.append("short")

    if "boilerplate_page_marker" in labels:
        score *= 0.2
    if "boilerplate_removed" in labels:
        score *= 0.5
    if "repetitive_lines" in labels:
        score *= 0.8

    if symbol_ratio > 0.35 and alpha_ratio < 0.25:
        score *= 0.6
        labels.append("noisy_symbols")

    # Clamp and grade.
    score = max(0.0, min(float(score), 1.0))
    if score >= 0.7:
        grade = "good"
    elif score >= 0.4:
        grade = "ok"
    else:
        grade = "bad"

    return {
        "schema": "mimirq.chunk_quality.v1",
        "score": round(float(score), 3),
        "grade": grade,
        "labels": labels,
        "signals": signals,
    }


__all__ = ["score_chunk_quality"]
