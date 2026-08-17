"""Shared scalar coercion, stable doc-key, and fallback-logging helpers.

Split out of ``app.rag.retrieval.orchestrator`` (see
``app.rag.retrieval.orchestration``). The orchestrator module re-imports these
private names for backwards compatibility.
"""

from typing import Any

from langchain_core.documents import Document

from app.rag.core.hashing import stable_hash
from app.rag.core.logging import get_logger

# Keep the historical logger name so log routing/filters observe no change.
logger = get_logger("app.rag.retrieval.orchestrator")


def _log_orchestrator_fallback(context: str, exc: BaseException) -> None:
    logger.debug("retrieval orchestrator fallback failed in %s: %s", context, exc, exc_info=True)


def _safe_int(value: Any, *, default: int = 0, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        out = int(value) if value is not None else int(default)
    except (TypeError, ValueError, AttributeError):
        out = int(default)
    if minimum is not None:
        out = max(int(minimum), out)
    if maximum is not None:
        out = min(int(maximum), out)
    return int(out)


def _safe_float(
    value: Any, *, default: float = 0.0, minimum: float | None = None, maximum: float | None = None
) -> float:
    try:
        out = float(value) if value is not None else float(default)
    except (TypeError, ValueError, AttributeError):
        out = float(default)
    if minimum is not None:
        out = max(float(minimum), out)
    if maximum is not None:
        out = min(float(maximum), out)
    return float(out)


def _doc_key(doc: Document) -> str:
    meta = doc.metadata or {}
    doc_id = meta.get("document_id")
    chunk_index = meta.get("chunk_index")
    if doc_id is not None and chunk_index is not None:
        return f"{doc_id}:{chunk_index}"
    cid = getattr(doc, "id", None) or meta.get("chunk_id")
    if cid:
        return str(cid)
    content = (doc.page_content or "").strip()
    return f"content:{stable_hash(content)}"


def _coerce_optional_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return bool(default)


def _coerce_optional_int(value: Any, *, default: int, minimum: int = 0, maximum: int | None = None) -> int:
    try:
        out = int(value) if value is not None else int(default)
    except (TypeError, ValueError, AttributeError):
        out = int(default)
    out = max(int(minimum), int(out))
    if maximum is not None:
        out = min(int(maximum), int(out))
    return out


def _coerce_optional_float(value: Any, *, default: float, minimum: float = 0.0, maximum: float | None = None) -> float:
    try:
        out = float(value) if value is not None else float(default)
    except (TypeError, ValueError, AttributeError):
        out = float(default)
    out = max(float(minimum), float(out))
    if maximum is not None:
        out = min(float(maximum), float(out))
    return out
