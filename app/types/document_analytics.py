"""
DocumentAnalytics - lightweight "document portrait" metrics for UI/observability.

This intentionally stays dependency-free (besides existing internal helpers) and
does not attempt to be a full document understanding pipeline. It provides stable
counts for common UI panels (parsing/governance/chunk-preview).
"""

import re
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, replace
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


def compute_document_analytics(
    *,
    markdown: str,
    documents: Iterable[Any] | None = None,
    pdf_quality: Mapping[str, Any] | None = None,
    detect_language: bool = False,
    language_min_chars: int = 40,
) -> DocumentAnalytics:
    # Reuse existing artifact stats helper to keep table/image/page/block counting consistent.
    artifact = compute_parsing_artifact_stats(
        documents=documents,
        original_markdown=markdown,
        markdown=markdown,
        pdf_quality=pdf_quality,
    )

    analytics = DocumentAnalytics(
        char_count=len(markdown),
        line_count=len(markdown.splitlines()),
        heading_count=len(_HEADING_RE.findall(markdown)),
        page_count=artifact["page_count"],
        table_count=artifact["table_count"],
        image_count=artifact["image_count"],
        block_count=artifact["block_count"],
    )
    if detect_language:
        language = detect_language_fn(markdown, min_chars=language_min_chars)
        analytics = replace(
            analytics,
            language=language.language,
            language_confidence=language.confidence,
            cjk_chars=language.cjk_chars,
            latin_chars=language.latin_chars,
        )
    return analytics


__all__ = [
    "DocumentAnalytics",
    "compute_document_analytics",
]
