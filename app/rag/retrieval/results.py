"""Shared document identity, scalar coercion and retrieval fallback logging."""

import logging
from typing import Any

from langchain_core.documents import Document

from app.infrastructure.hashing import stable_hash

# Keep the historical logger name so log routing/filters observe no change.
logger = logging.getLogger("app.rag.retrieval.orchestrator")


def _log_orchestrator_fallback(context: str, exc: BaseException) -> None:
    logger.debug("retrieval orchestrator fallback failed in %s: %s", context, exc, exc_info=True)


def _safe_int(value: Any, *, default: int = 0, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        out = int(value) if value is not None else default
    except (OverflowError, TypeError, ValueError):
        out = default
    if minimum is not None:
        out = max(minimum, out)
    if maximum is not None:
        out = min(maximum, out)
    return out


def _safe_float(
    value: Any, *, default: float = 0.0, minimum: float | None = None, maximum: float | None = None
) -> float:
    try:
        out = float(value) if value is not None else default
    except (OverflowError, TypeError, ValueError):
        out = default
    if minimum is not None:
        out = max(minimum, out)
    if maximum is not None:
        out = min(maximum, out)
    return out


def document_key(doc: Document) -> str:
    meta = doc.metadata
    doc_id = meta.get("document_id")
    chunk_index = meta.get("chunk_index")
    if doc_id is not None and chunk_index is not None:
        return f"{doc_id}:{chunk_index}"
    cid = doc.id or meta.get("chunk_id")
    if cid:
        return str(cid)
    content = doc.page_content.strip()
    return f"content:{stable_hash(content)}"


_RETRIEVAL_ORCHESTRATOR_FALLBACK_LOG_MESSAGE = "Ignoring non-critical retrieval orchestrator fallback failure: %s"
