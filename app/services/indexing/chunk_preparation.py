"""Owned chunk preparation operations for indexing."""

import hashlib
import logging
import uuid
from pathlib import Path
from typing import Any
from uuid import UUID

from app.core.config import settings
from app.query.normalize import normalize_query
from app.rag.core.metadata import ensure_hierarchy_overlay_metadata, normalize_image_metadata
from app.rag.pipeline_plugins.contracts import (
    RETRIEVAL_DISPLAY_CONTENT_METADATA_KEY,
    RETRIEVAL_TEXT_METADATA_KEY,
)
from app.rag.preprocessing.normalization import normalize_text
from app.types.indexing import (
    ChunkInput,
)

logger = logging.getLogger("indexer")


def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _metadata_flag_enabled(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _safe_uuid(value: Any) -> UUID | None:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except ValueError:
        return None


def _ensure_chunk_metadata(
    meta: dict[str, Any],
    *,
    content: str,
    document_id: UUID,
    chunk_index: int,
    total_chunks: int | None = None,
) -> dict[str, Any]:
    """Ensure stable per-chunk metadata fields exist (used across DB/vector/BM25)."""
    meta.setdefault("chunk_key", f"{str(document_id)}:{int(chunk_index)}")

    normalized = normalize_text(content or "", normalize_line_endings=True, remove_control_chars=True)
    stripped = (normalized or "").strip()
    meta.setdefault("content_len", int(len(stripped)))

    raw_hash = meta.get("content_hash")
    if not isinstance(raw_hash, str) or not raw_hash.strip():
        meta["content_hash"] = hashlib.sha256(stripped.encode("utf-8", "ignore")).hexdigest()
        meta.setdefault("content_hash_algo", "sha256")

    ensure_hierarchy_overlay_metadata(
        meta,
        document_id=str(document_id),
        chunk_index=int(chunk_index),
        total_chunks=(int(total_chunks) if total_chunks is not None else None),
    )

    return meta


def _chunk_index_content(content: str, metadata: dict[str, Any] | None) -> tuple[str, dict[str, Any]]:
    """
    Return text used for retrieval indexes while preserving clean display content.

    Business plugins may produce a recall-optimized `_retrieval_text` that includes
    labels/aliases/structured fields. The stored chunk body remains the clean content.
    """
    meta = dict(metadata or {})
    display_content = str(content or "")
    raw_index_text = meta.get(RETRIEVAL_TEXT_METADATA_KEY)
    index_text = str(raw_index_text or "").strip() if isinstance(raw_index_text, str) else ""
    if not index_text:
        index_text = display_content

    prefix, prefix_fields = _build_retrieval_metadata_prefix(meta)
    if prefix and not bool(meta.get("rich_metadata_header_applied")):
        index_text = f"{prefix}\n\n{index_text}" if index_text else prefix
        meta["retrieval_metadata_prefix_applied"] = True
        meta["retrieval_metadata_prefix_fields"] = prefix_fields

    normalized = normalize_query(index_text)
    meta[RETRIEVAL_TEXT_METADATA_KEY] = normalized.normalized_text
    if normalized.applied_rules:
        meta["retrieval_normalization_rules"] = list(normalized.applied_rules)
    if normalized.normalized_text != display_content:
        meta.setdefault(RETRIEVAL_DISPLAY_CONTENT_METADATA_KEY, display_content)
    return normalized.normalized_text, meta


def _should_prefix_embedding(meta: dict[str, Any]) -> bool:
    """Best-effort filter: avoid prefixing non-text assets (images/tables)."""
    doc_type = str(meta.get("doc_type_kwd") or "").strip().lower()
    if doc_type in {"image", "table"}:
        return False
    if meta.get("image") is not None:
        return False
    if meta.get("img_id") or meta.get("image_id") or meta.get("image_url"):
        return False
    return True


def _build_embedding_text(content: str, meta: dict[str, Any], *, max_prefix_chars: int = 180) -> str:
    """
    Build the text used for embedding (vector similarity).

    Rationale: add lightweight structural context (e.g. header_path/outline path) to reduce
    "contextless fragments" without changing stored chunk content (DB) or offsets.
    """
    if not content:
        return content
    if not _should_prefix_embedding(meta):
        return content

    header = meta.get("header_path") or meta.get("outline_path_str") or meta.get("header_context") or None
    if header is None:
        # Some chunkers store outline/header as list.
        header_list = meta.get("outline_path") or meta.get("header_path_list") or None
        if isinstance(header_list, list) and header_list:
            header = " / ".join([str(x).strip() for x in header_list if str(x).strip()][:10])

    header_str = str(header or "").strip()
    if not header_str:
        return content

    header_str = header_str[: max(20, int(max_prefix_chars or 0))]
    prefix = f"[Section] {header_str}\n"
    return prefix + content


def _coerce_short_text(value: Any, *, max_chars: int) -> str | None:
    s = str(value or "").strip()
    if not s:
        return None
    if len(s) > int(max_chars or 0) > 0:
        s = s[: int(max_chars or 0)]
    return s or None


def _title_from_document_metadata(doc_metadata: Any) -> str | None:
    if not isinstance(doc_metadata, dict):
        return None
    for key in ("document_title", "doc_title", "title", "name"):
        value = doc_metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _title_from_filename(filename: str | None) -> str | None:
    raw = (filename or "").strip()
    if not raw:
        return None
    base = Path(raw).name
    return Path(base).stem or base


def _derive_document_title(filename: Any, doc_metadata: Any, *, max_chars: int = 120) -> str | None:
    """
    Best-effort derive a human-ish document title for embedding prefixes.

    Prefer explicit metadata when available; fall back to filename stem.
    """
    title = _title_from_document_metadata(doc_metadata) or _title_from_filename(filename)
    return _coerce_short_text(title, max_chars=int(max_chars or 0)) if title else None


def _extract_title_for_embedding(meta: dict[str, Any]) -> str | None:
    """
    Best-effort extract a document "title" string for field-aware embeddings.

    This is intentionally heuristic and safe:
    - we do not assume a single canonical metadata key across parsers/connectors
    - we bound the length to keep vector writes cheap and stable
    """
    if not isinstance(meta, dict):
        return None
    for key in (
        # Prefer record-level titles over the enclosing document filename.
        "service_name",
        "document_title",
        "doc_title",
        "title",
        "name",
        "filename",
    ):
        v = _coerce_short_text(meta.get(key), max_chars=200)
        if v:
            return v
    # Fallback: source usually contains the filename (already present in vector metadata).
    return _coerce_short_text(meta.get("source"), max_chars=200)


def _extract_heading_for_embedding(meta: dict[str, Any]) -> str | None:
    """Best-effort extract a section heading/path string for field-aware embeddings."""
    if not isinstance(meta, dict):
        return None

    header = meta.get("header_path") or meta.get("outline_path_str") or meta.get("header_context") or None
    if isinstance(header, list):
        header = " / ".join([str(x).strip() for x in header if str(x).strip()][:10])
    elif header is None:
        header_list = meta.get("outline_path") or meta.get("header_path_list") or None
        if isinstance(header_list, list) and header_list:
            header = " / ".join([str(x).strip() for x in header_list if str(x).strip()][:10])
        else:
            header = meta.get("section") or meta.get("section_title") or meta.get("knowledge_section")

    header_str = _coerce_short_text(header, max_chars=280)
    return header_str


def _append_metadata_prefix_line(
    *,
    lines: list[str],
    fields: list[str],
    field_name: str,
    label: str,
    value: str | list[str] | None,
    joiner: str | None = None,
) -> None:
    if isinstance(value, list):
        if not value:
            return
        rendered = joiner.join(value) if joiner is not None else ""
    else:
        rendered = str(value or "").strip()
    if not rendered:
        return
    lines.append(f"[{label}] {rendered}")
    fields.append(field_name)


def _build_retrieval_metadata_prefix(meta: dict[str, Any]) -> tuple[str, list[str]]:
    """Build a bounded, deterministic index-only prefix from existing metadata."""
    if not isinstance(meta, dict):
        return "", []

    def _values(value: Any, *, max_items: int, max_chars: int) -> list[str]:
        raw = value if isinstance(value, (list, tuple, set)) else [value]
        out: list[str] = []
        seen: set[str] = set()
        for item in raw:
            text = str(item or "").strip()
            if not text:
                continue
            text = text[:max_chars]
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            out.append(text)
            if len(out) >= max_items:
                break
        return out

    lines: list[str] = []
    fields: list[str] = []
    title = _extract_title_for_embedding(meta)
    if str(title or "").strip().casefold() in {"unknown", "untitled"}:
        title = None
    _append_metadata_prefix_line(lines=lines, fields=fields, field_name="title", label="Title", value=title)
    _append_metadata_prefix_line(
        lines=lines,
        fields=fields,
        field_name="section",
        label="Section",
        value=_extract_heading_for_embedding(meta),
    )

    keywords = _values(
        meta.get("document_keywords") or meta.get("keywords"),
        max_items=12,
        max_chars=64,
    )
    _append_metadata_prefix_line(
        lines=lines,
        fields=fields,
        field_name="keywords",
        label="Keywords",
        value=keywords,
        joiner=", ",
    )

    questions = _values(
        meta.get("document_questions")
        or meta.get("questions")
        or meta.get("question")
        or meta.get("hypothetical_questions"),
        max_items=5,
        max_chars=200,
    )
    _append_metadata_prefix_line(
        lines=lines,
        fields=fields,
        field_name="questions",
        label="Questions",
        value=questions,
        joiner=" | ",
    )

    return "\n".join(lines), fields


def _build_llm_contextual_summary(
    *,
    raw_body: str,
    document_title: str | None,
    meta: dict[str, Any],
) -> str | None:
    """
    Best-effort short summary for contextual embedding prefixes.

    Safe-by-default behavior:
    - Disabled unless CONTEXTUAL_RETRIEVAL_LLM_ENRICHMENT_ENABLED=true.
    - Any failure falls back to deterministic prefixing.
    """
    limits = _contextual_summary_limits()
    if limits is None:
        return None
    text = str(raw_body or "").strip()
    if not text:
        return None
    max_input_chars, max_summary_chars = limits
    sample = text[:max_input_chars] if max_input_chars else text
    section = _extract_heading_for_embedding(meta) or ""
    title = str(document_title or "").strip()
    try:
        summary = _invoke_contextual_summary_llm(
            title=title,
            section=section,
            sample=sample,
            max_summary_chars=max_summary_chars,
        )
    except Exception:
        return None

    if not summary:
        return None
    if len(summary) > max_summary_chars:
        summary = summary[:max_summary_chars].rstrip()
    return summary or None


def _contextual_summary_limits() -> tuple[int, int] | None:
    if not settings.CONTEXTUAL_RETRIEVAL_LLM_ENRICHMENT_ENABLED:
        return None
    max_input_chars = max(0, (settings.CONTEXTUAL_RETRIEVAL_LLM_MAX_INPUT_CHARS or 2400))
    max_summary_chars = max(0, (settings.CONTEXTUAL_RETRIEVAL_LLM_MAX_SUMMARY_CHARS or 180))
    return (max_input_chars, max_summary_chars) if max_summary_chars > 0 else None


def _invoke_contextual_summary_llm(
    *,
    title: str,
    section: str,
    sample: str,
    max_summary_chars: int,
) -> str:
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_openai import ChatOpenAI

    llm = ChatOpenAI(
        model=settings.LLM_MODEL,
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_API_BASE,
        temperature=0,
        timeout=max(5, (settings.LLM_TIMEOUT or 60)),
        max_retries=0,
        streaming=False,
    )
    system = SystemMessage(
        content=(
            "Write one concise retrieval-oriented summary sentence for embedding enrichment. "
            "Output plain text only. No markdown. No lists."
        )
    )
    human = HumanMessage(
        content=(
            f"Title: {title or 'N/A'}\n"
            f"Section: {section or 'N/A'}\n"
            f"Chunk:\n{sample}\n\n"
            f"Constraints: <= {max_summary_chars} chars, factual, no speculation."
        )
    )
    resp = llm.invoke([system, human])
    return str(resp.content or "").strip()


def _build_contextual_prefix_for_chunk(
    *,
    raw_body: str,
    document_title: str | None,
    meta: dict[str, Any],
) -> str | None:
    from app.rag.chunking.contextual_enrichment import build_context_prefix

    summary = _build_llm_contextual_summary(raw_body=raw_body, document_title=document_title, meta=meta)
    if summary:
        return summary

    return build_context_prefix(
        raw_body,
        document_title=document_title,
        meta=meta,
        max_prefix_chars=(settings.CONTEXTUAL_RETRIEVAL_PREFIX_MAX_CHARS or 240),
        keywords_top_k=(settings.CONTEXTUAL_RETRIEVAL_KEYWORDS_TOP_K or 6),
        keywords_max_chars=(settings.CONTEXTUAL_RETRIEVAL_KEYWORDS_MAX_CHARS or 2000),
    )


def _should_apply_contextual_retrieval_prefix(meta: dict[str, Any], *, lazy_mode: bool) -> bool:
    if not lazy_mode:
        return True
    if bool((meta or {}).get("contextual_enrichment_required")):
        return True
    evidence_gap = (meta or {}).get("evidence_gap")
    if isinstance(evidence_gap, dict):
        if bool(evidence_gap.get("has_gap")):
            return True
        if int(evidence_gap.get("anchor_missing_any") or 0) > 0:
            return True
        if evidence_gap.get("missing_source_keys"):
            return True
    return False


def _normalized_vector_ids(vector_ids: list[str | None] | None, *, chunks_count: int) -> list[str | None]:
    if vector_ids is None:
        return [None] * chunks_count
    if len(vector_ids) != chunks_count:
        raise ValueError(f"vector_ids length {len(vector_ids)} != chunks length {chunks_count}")
    return vector_ids


def _normalized_chunk_ids(chunk_ids: list[UUID] | None, *, chunks_count: int) -> list[UUID]:
    if chunk_ids is None:
        return [uuid.uuid4() for _ in range(chunks_count)]
    if len(chunk_ids) != chunks_count:
        raise ValueError(f"chunk_ids length {len(chunk_ids)} != chunks length {chunks_count}")
    return chunk_ids


def _document_chunk_metadata(
    chunk: ChunkInput,
    *,
    document_id: UUID,
    tenant_id: UUID,
    chunk_index: int,
    total_chunks: int,
    chunk_id: UUID,
) -> dict[str, Any]:
    meta = dict(chunk.metadata or {})
    normalize_image_metadata(meta)
    meta.setdefault("tenant_id", str(tenant_id))
    meta.setdefault("document_id", str(document_id))
    meta.setdefault("chunk_index", chunk_index)
    pipeline_hash = str(meta.get("pipeline_hash") or "").strip()
    if pipeline_hash:
        meta.setdefault("doc_pipeline_key", f"{document_id}:{pipeline_hash}")
    meta = _ensure_chunk_metadata(
        meta,
        content=chunk.content or "",
        document_id=document_id,
        chunk_index=chunk_index,
        total_chunks=total_chunks,
    )
    meta["chunk_id"] = str(chunk_id)
    return meta


def _chunk_position_values(chunk: ChunkInput, meta: dict[str, Any]) -> tuple[int | None, int | None, int | None]:
    page_number = (
        _safe_int(chunk.page_number)
        if chunk.page_number is not None
        else _safe_int(meta.get("page") or meta.get("page_number"))
    )
    start_char = _safe_int(chunk.start_char) if chunk.start_char is not None else _safe_int(meta.get("start_char"))
    end_char = _safe_int(chunk.end_char) if chunk.end_char is not None else _safe_int(meta.get("end_char"))
    return page_number, start_char, end_char
