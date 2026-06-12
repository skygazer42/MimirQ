"""
DocumentAnalytics - lightweight "document portrait" metrics for UI/observability.

This intentionally stays dependency-free (besides existing internal helpers) and
does not attempt to be a full document understanding pipeline. It provides stable
counts for common UI panels (parsing/governance/chunk-preview).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from typing import Any

from app.parsing.artifact_stats import compute_parsing_artifact_stats
from app.rag.preprocessing.language import detect_language as detect_language_fn

_HEADING_RE = re.compile(r"(?m)^(#{1,6})\s+\S+")


@dataclass(frozen=True)
class DocumentAnalytics:
    # Text counts
    char_count: int = 0
    line_count: int = 0
    heading_count: int = 0

    # Artifact-ish counts (best-effort; often from parser metadata)
    page_count: int = 0
    table_count: int = 0
    image_count: int = 0
    block_count: int = 0

    # Lightweight language signal (used by governance UI and tuning)
    language: str | None = None
    language_confidence: float | None = None
    cjk_chars: int | None = None
    latin_chars: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


def _count_lines(text: str) -> int:
    raw = text or ""
    if not raw:
        return 0
    # splitlines() ignores trailing newline and handles mixed newlines.
    return len(raw.splitlines())


def compute_document_analytics(
    *,
    markdown: str,
    documents: Iterable[Any] | None = None,
    pdf_quality: Mapping[str, Any] | None = None,
    detect_language: bool = False,
    language_min_chars: int = 40,
) -> DocumentAnalytics:
    raw = (markdown or "")

    # Reuse existing artifact stats helper to keep table/image/page/block counting consistent.
    artifact = compute_parsing_artifact_stats(
        documents=documents,
        original_markdown=raw,
        markdown=raw,
        pdf_quality=pdf_quality,
    )

    lang_val: str | None = None
    lang_conf: float | None = None
    cjk: int | None = None
    latin: int | None = None
    if detect_language:
        out = detect_language_fn(raw, min_chars=int(language_min_chars or 0))
        lang_val = str(getattr(out, "language", "") or "").strip() or None
        lang_conf = float(getattr(out, "confidence", 0.0) or 0.0)
        cjk = int(getattr(out, "cjk_chars", 0) or 0)
        latin = int(getattr(out, "latin_chars", 0) or 0)

    return DocumentAnalytics(
        char_count=len(raw),
        line_count=_count_lines(raw),
        heading_count=len(_HEADING_RE.findall(raw)) if raw else 0,
        page_count=int(artifact.get("page_count") or 0),
        table_count=int(artifact.get("table_count") or 0),
        image_count=int(artifact.get("image_count") or 0),
        block_count=int(artifact.get("block_count") or 0),
        language=lang_val,
        language_confidence=lang_conf,
        cjk_chars=cjk,
        latin_chars=latin,
    )


__all__ = [
    "DocumentAnalytics",
    "compute_document_analytics",
]
