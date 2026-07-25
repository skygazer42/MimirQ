"""
Indexing service implementation.

Provides a unified interface for document chunk and event indexing.
"""
import hashlib
import logging
import time
import uuid
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from langchain_core.documents import Document as LCDocument
from sqlalchemy.orm import Session, aliased

from app.core.config import settings
from app.core.constants import EmbeddingProviders
from app.models.dataset import Dataset as DBDataset
from app.models.document import Document as DBDocument
from app.models.document import DocumentChunk
from app.query.normalize import normalize_query
from app.rag.chunking.utils.hierarchical import apply_sequence_hierarchy_metadata
from app.rag.core.metadata import ensure_hierarchy_overlay_metadata, normalize_image_metadata
from app.rag.embedding import create_langchain_embeddings_from_config
from app.rag.embedding.utils import embedding_space_hash_for_config
from app.rag.kg.models import KgEntity, KgEventEntity, KgRelation, KgSourceEvent
from app.rag.kg.provenance import build_event_entity_provenance
from app.rag.pipeline_plugins.contracts import (
    RETRIEVAL_DISPLAY_CONTENT_METADATA_KEY,
    RETRIEVAL_TEXT_METADATA_KEY,
)
from app.rag.preprocessing.normalization import normalize_text
from app.rag.retriever import hybrid_retriever
from app.services.dataset_embedding_config import (
    DatasetEmbeddingRuntimeConfig,
    collection_name_for_embedding_space,
    create_embeddings_for_runtime,
    resolve_dataset_embedding_runtime,
)
from app.services.metrics_logger import log_metrics
from app.storage.vector.factory import get_vector_store
from app.storage.vector.milvus import get_milvus_adapter, resolve_collection_name
from app.types.indexing import (
    ChunkInput,
    EventInput,
    IndexBatchResult,
    IndexingOptions,
    IndexKind,
    IndexRecord,
    PersistChunksResult,
    PersistEventsResult,
)

logger = logging.getLogger("indexer")
_INDEXER_FALLBACK_LOG_MESSAGE = "Ignoring non-critical indexer fallback failure: %s"

_shadow_vector_writer_sig: str | None = None
_shadow_vector_writer: tuple[Any, Any, str] | None = None  # (embeddings, adapter, embedding_space_hash)
_SHADOW_VECTOR_WRITE_EVENT = "ingest.shadow_vector_write"


class DatasetScopedEmbeddingRuntimeResolutionError(RuntimeError):
    """Raised when a dataset-scoped document cannot safely resolve its embedding runtime."""


def _dataset_scoped_runtime_unavailable(*, document_id: UUID, tenant_id: UUID) -> DatasetScopedEmbeddingRuntimeResolutionError:
    return DatasetScopedEmbeddingRuntimeResolutionError(
        "dataset-scoped embedding runtime unavailable during indexing "
        f"(tenant_id={tenant_id}, document_id={document_id})"
    )


def _dataset_scoped_cleanup_ambiguous(
    *,
    document_id: UUID,
    tenant_id: UUID,
    embedding_space_hash: str,
) -> DatasetScopedEmbeddingRuntimeResolutionError:
    return DatasetScopedEmbeddingRuntimeResolutionError(
        "dataset-scoped vector cleanup target ambiguous from persisted metadata "
        f"(tenant_id={tenant_id}, document_id={document_id}, embedding_space_hash={embedding_space_hash})"
    )


def _milvus_backend_enabled() -> bool:
    return str(getattr(settings, "VECTOR_BACKEND", "milvus") or "milvus").strip().lower() == "milvus"


def _shadow_vector_config() -> tuple[str, str, str, str, str] | None:
    if not bool(getattr(settings, "EMBEDDING_SHADOW_ENABLED", False)):
        return None
    if not _milvus_backend_enabled():
        return None

    shadow_collection = str(getattr(settings, "MILVUS_SHADOW_COLLECTION_NAME", "") or "").strip()
    shadow_model = str(getattr(settings, "EMBEDDING_SHADOW_MODEL", "") or "").strip()
    if not shadow_collection or not shadow_model:
        return None

    provider_raw = (
        str(getattr(settings, "EMBEDDING_SHADOW_PROVIDER", "") or "").strip().lower()
        or str(getattr(settings, "EMBEDDING_PROVIDER", "openai_compatible") or "openai_compatible").strip().lower()
    )
    mapped_provider = EmbeddingProviders.PROVIDER_MAP.get(provider_raw, "openai_compatible")
    api_key = (
        str(getattr(settings, "EMBEDDING_SHADOW_API_KEY", "") or "").strip()
        or str(getattr(settings, "EMBEDDING_API_KEY", "") or "").strip()
        or str(getattr(settings, "LLM_API_KEY", "") or "").strip()
    )
    base_url = (
        str(getattr(settings, "EMBEDDING_SHADOW_API_BASE", "") or "").strip()
        or str(getattr(settings, "EMBEDDING_API_BASE", "") or "").strip()
        or str(getattr(settings, "LLM_API_BASE", "") or "").strip()
    )
    return mapped_provider, shadow_model, api_key, base_url, shadow_collection


def _cache_shadow_vector_writer(
    sig: str,
    writer: tuple[Any, Any, str] | None,
) -> tuple[Any, Any, str] | None:
    global _shadow_vector_writer_sig, _shadow_vector_writer
    _shadow_vector_writer_sig = sig
    _shadow_vector_writer = writer
    return writer


def _shadow_embedding_space_hash(*, provider: str, model: str, base_url: str) -> str:
    try:
        return embedding_space_hash_for_config(
            provider=provider,
            model=model,
            base_url=base_url,
            length=16,
        )
    except Exception:
        return ""


def _resolve_shadow_vector_writer() -> tuple[Any, Any, str] | None:
    """
    Best-effort resolve (embeddings, milvus_adapter, shadow_space_hash) for dual-write.

    This is used by Gap5 embedding blue-green migrations: when enabled, ingestion writes
    vectors into both the primary collection (settings.MILVUS_COLLECTION_NAME) and the
    shadow collection (settings.MILVUS_SHADOW_COLLECTION_NAME) using a potentially
    different embedding model.
    """
    config = _shadow_vector_config()
    if config is None:
        return None
    mapped_provider, shadow_model, api_key, base_url, shadow_collection = config
    sig = f"{mapped_provider}|{shadow_model}|{base_url}|{shadow_collection}"

    if _shadow_vector_writer is not None and _shadow_vector_writer_sig == sig:
        return _shadow_vector_writer

    try:
        emb = create_langchain_embeddings_from_config(
            provider=mapped_provider,
            model=shadow_model,
            api_key=api_key,
            base_url=base_url,
            dimension=None,  # Auto-detect
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Shadow embeddings init failed; dual-write disabled: %s", str(exc)[:200])
        return _cache_shadow_vector_writer(sig, None)

    try:
        adapter = get_milvus_adapter(resolve_collection_name(shadow_collection))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Shadow Milvus adapter init failed; dual-write disabled: %s", str(exc)[:200])
        return _cache_shadow_vector_writer(sig, None)

    shadow_space = _shadow_embedding_space_hash(provider=mapped_provider, model=shadow_model, base_url=base_url)
    return _cache_shadow_vector_writer(sig, (emb, adapter, shadow_space))


def _prepare_shadow_vector_items(
    docs: list[dict[str, Any]],
    *,
    shadow_space: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    items: list[dict[str, Any]] = []
    texts: list[str] = []
    for doc in docs:
        meta0 = doc.get("metadata") if isinstance(doc, dict) else None
        meta = dict(meta0 or {}) if isinstance(meta0, dict) else {}
        chunk_id = str(meta.get("chunk_id") or "").strip()
        if not chunk_id:
            continue
        content = str(doc.get("content") or "")
        meta["embedding_space_hash"] = shadow_space
        items.append({"id": chunk_id, "content": content, "metadata": meta})
        texts.append(content)
    return items, texts


def _log_shadow_vector_write(
    *,
    ok: bool,
    tenant_id: UUID,
    document_id: UUID,
    count: int,
    reason: str | None = None,
    error: Exception | None = None,
) -> None:
    payload: dict[str, Any] = {
        "event": _SHADOW_VECTOR_WRITE_EVENT,
        "ok": ok,
        "tenant_id": str(tenant_id),
        "document_id": str(document_id),
        "count": int(count),
    }
    if reason:
        payload["reason"] = reason
    if error is not None:
        payload["error"] = str(error)[:200]
    log_metrics(payload)


def _dual_write_shadow_vectors_best_effort(
    docs: list[dict[str, Any]],
    *,
    document_id: UUID,
    tenant_id: UUID,
) -> None:
    writer = _resolve_shadow_vector_writer()
    if writer is None:
        return
    embeddings, adapter, shadow_space = writer

    if not docs:
        return

    items, texts = _prepare_shadow_vector_items(docs, shadow_space=shadow_space)
    if not items:
        return

    try:
        vecs = embeddings.embed_documents(texts)
    except Exception as exc:  # noqa: BLE001
        _log_shadow_vector_write(
            ok=False,
            reason="embed_failed",
            tenant_id=tenant_id,
            document_id=document_id,
            count=len(items),
            error=exc,
        )
        return

    try:
        batch_size = int(getattr(settings, "VECTOR_WRITE_BATCH_SIZE", 256) or 256)
        adapter.add_vectors(items, embeddings=vecs, batch_size=batch_size, upsert=True)
        _log_shadow_vector_write(ok=True, tenant_id=tenant_id, document_id=document_id, count=len(items))
    except Exception as exc:  # noqa: BLE001
        _log_shadow_vector_write(
            ok=False,
            reason="milvus_write_failed",
            tenant_id=tenant_id,
            document_id=document_id,
            count=len(items),
            error=exc,
        )
        return


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


def _first_column_value(row: Any) -> Any:
    if row is None:
        return None
    if isinstance(row, dict):
        return row
    mapping = getattr(row, "_mapping", None)
    if mapping is not None:
        if "metadata" in mapping:
            return mapping["metadata"]
        values = list(mapping.values())
        if len(values) == 1:
            return values[0]
    if isinstance(row, (tuple, list)):
        return row[0] if row else None
    try:
        return row[0]
    except (IndexError, KeyError, TypeError):
        return row


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
    if not isinstance(meta, dict):
        meta = {}

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


def _title_from_filename(filename: Any) -> str | None:
    raw = str(filename or "").strip()
    if not raw:
        return None
    try:
        from pathlib import Path

        base = Path(raw).name
        return Path(base).stem or base
    except Exception:
        return raw


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
    if title:
        lines.append(f"[Title] {title}")
        fields.append("title")

    section = _extract_heading_for_embedding(meta)
    if section:
        lines.append(f"[Section] {section}")
        fields.append("section")

    keywords = _values(
        meta.get("document_keywords") or meta.get("keywords"),
        max_items=12,
        max_chars=64,
    )
    if keywords:
        lines.append(f"[Keywords] {', '.join(keywords)}")
        fields.append("keywords")

    questions = _values(
        meta.get("document_questions")
        or meta.get("questions")
        or meta.get("question")
        or meta.get("hypothetical_questions"),
        max_items=5,
        max_chars=200,
    )
    if questions:
        lines.append("[Questions] " + " | ".join(questions))
        fields.append("questions")

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
    if not bool(getattr(settings, "CONTEXTUAL_RETRIEVAL_LLM_ENRICHMENT_ENABLED", False)):
        return None
    max_input_chars = max(0, int(getattr(settings, "CONTEXTUAL_RETRIEVAL_LLM_MAX_INPUT_CHARS", 2400) or 2400))
    max_summary_chars = max(0, int(getattr(settings, "CONTEXTUAL_RETRIEVAL_LLM_MAX_SUMMARY_CHARS", 180) or 180))
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
        timeout=max(5, int(getattr(settings, "LLM_TIMEOUT", 60) or 60)),
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
    return str(getattr(resp, "content", "") or "").strip()


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
        max_prefix_chars=int(getattr(settings, "CONTEXTUAL_RETRIEVAL_PREFIX_MAX_CHARS", 240) or 240),
        keywords_top_k=int(getattr(settings, "CONTEXTUAL_RETRIEVAL_KEYWORDS_TOP_K", 6) or 6),
        keywords_max_chars=int(getattr(settings, "CONTEXTUAL_RETRIEVAL_KEYWORDS_MAX_CHARS", 2000) or 2000),
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


def _coerce_entity_upsert_input(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name") or "").strip()
    if not name:
        return None
    normalized_name = str(raw.get("normalized_name") or name).strip()
    if not normalized_name:
        return None
    return {
        "name": name,
        "normalized_name": normalized_name,
        "type": str(raw.get("type") or "unknown").strip() or "unknown",
        "description": str(raw.get("description")).strip() if isinstance(raw.get("description"), str) else None,
        "vector": raw.get("vector") if isinstance(raw.get("vector"), list) else None,
        "extra_data": raw.get("extra_data") if isinstance(raw.get("extra_data"), dict) else None,
    }


def _enrich_entity_best_effort(
    entity: KgEntity,
    *,
    description: str | None,
    vector: list[Any] | None,
    extra_data: dict[str, Any] | None,
) -> None:
    if description and not getattr(entity, "description", None):
        entity.description = description
    if vector and not getattr(entity, "vector", None):
        entity.vector = vector
    if extra_data and not getattr(entity, "extra_data", None):
        entity.extra_data = extra_data


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
        _safe_int(chunk.page_number) if chunk.page_number is not None else _safe_int(meta.get("page") or meta.get("page_number"))
    )
    start_char = _safe_int(chunk.start_char) if chunk.start_char is not None else _safe_int(meta.get("start_char"))
    end_char = _safe_int(chunk.end_char) if chunk.end_char is not None else _safe_int(meta.get("end_char"))
    return page_number, start_char, end_char


def _event_references(event: KgSourceEvent) -> dict[str, Any]:
    refs = getattr(event, "references", None)
    return refs if isinstance(refs, dict) else {}


def _event_pipeline_hash(event: KgSourceEvent, refs: dict[str, Any]) -> str | None:
    pipeline_hash = str(getattr(event, "pipeline_hash", None) or refs.get("pipeline_hash") or "").strip() or None
    return pipeline_hash[:200] if pipeline_hash and len(pipeline_hash) > 200 else pipeline_hash


def _event_vector_metadata(event: KgSourceEvent, refs: dict[str, Any]) -> dict[str, Any]:
    pipeline_hash = _event_pipeline_hash(event, refs)
    meta: dict[str, Any] = {
        "tenant_id": str(event.tenant_id),
        "document_id": str(event.document_id) if event.document_id else "",
        "chunk_id": str(event.chunk_id) if event.chunk_id else "",
        "title": event.title,
        "summary": event.summary,
        "index_kind": IndexKind.EVENT.value,
    }
    if pipeline_hash:
        meta["pipeline_hash"] = pipeline_hash
        if event.document_id:
            meta["doc_pipeline_key"] = f"{event.document_id}:{pipeline_hash}"
    for key in (
        "chunk_index",
        "page",
        "start_char",
        "end_char",
        "chunk_key",
        "content_hash",
        "content_len",
        "source",
    ):
        value = refs.get(key)
        if value is not None:
            meta[key] = value
    return meta


def _event_vector_item(event: KgSourceEvent) -> tuple[dict[str, Any], list[float]] | None:
    if not event.content_vector:
        return None
    refs = _event_references(event)
    return (
        {
            "id": str(event.id),
            "content": event.content,
            "metadata": _event_vector_metadata(event, refs),
        },
        list(event.content_vector),
    )


def _vector_write_batch_size() -> int:
    return int(getattr(settings, "VECTOR_WRITE_BATCH_SIZE", 256) or 256)


def _vector_write_retry_policy() -> tuple[int, float]:
    max_retries = int(getattr(settings, "VECTOR_WRITE_MAX_RETRIES", 1) or 1)
    backoff = float(getattr(settings, "VECTOR_WRITE_RETRY_BACKOFF_SEC", 0.5) or 0.5)
    return max_retries, backoff


def _log_chunk_vector_retry(
    *,
    tenant_id: UUID,
    document_id: UUID,
    attempt: int,
    max_attempts: int,
    batch_size: int,
    backoff: float,
    error: Exception,
) -> None:
    log_metrics(
        {
            "event": "ingest.vector_write.retry",
            "tenant_id": str(tenant_id),
            "document_id": str(document_id),
            "attempt": attempt,
            "max_retries": max_attempts,
            "batch_size": batch_size,
            "backoff_sec": round(float(backoff), 3),
            "error": str(error)[:200],
        }
    )
    logger.warning(
        "Vector write failed (attempt %s/%s), retrying in %.2fs: %s",
        attempt,
        max_attempts,
        backoff,
        str(error)[:200],
    )


class Indexer:
    """
    Unified Indexer for chunk/event indexing.

    - Chunk indexing: vector store + PostgreSQL + BM25
    - Event indexing: PostgreSQL + Milvus (events + entities)
    """

    def __init__(self, db: Session):
        self._db = db
        event_collection = resolve_collection_name("kg_events")
        entity_collection = resolve_collection_name("kg_entities")
        self._event_vector = get_milvus_adapter(collection_name=event_collection, vector_field="embedding")
        self._entity_vector = get_milvus_adapter(collection_name=entity_collection, vector_field="embedding")

    def _resolve_chunk_vector_enabled(self, options: IndexingOptions | None) -> bool:
        if options and options.chunk_vector_enabled is not None:
            return bool(options.chunk_vector_enabled)
        return bool(getattr(settings, "CHUNK_VECTOR_ENABLED", True))

    def _resolve_bm25_enabled(self, options: IndexingOptions | None) -> bool:
        if options and options.bm25_index_enabled is not None:
            return bool(options.bm25_index_enabled)
        return bool(getattr(settings, "BM25_INDEX_ENABLED", True))

    def _resolve_event_vector_enabled(self, options: IndexingOptions | None) -> bool:
        if options and options.event_vector_enabled is not None:
            return bool(options.event_vector_enabled)
        return bool(getattr(settings, "EVENT_VECTOR_ENABLED", True))

    def _resolve_entity_vector_enabled(self, options: IndexingOptions | None) -> bool:
        if options and options.entity_vector_enabled is not None:
            return bool(options.entity_vector_enabled)
        return bool(getattr(settings, "ENTITY_VECTOR_ENABLED", True))

    def _load_dataset_metadata(self, *, tenant_id: UUID, dataset_id: UUID | None) -> dict[str, Any]:
        if dataset_id is None:
            return {}
        try:
            row = (
                self._db.query(DBDataset.dataset_metadata)
                .filter(DBDataset.tenant_id == tenant_id, DBDataset.id == dataset_id)
                .first()
            )
            meta = row[0] if row else None
            return dict(meta or {}) if isinstance(meta, dict) else {}
        except Exception:
            return {}

    def _embedding_runtime_for_document(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
    ) -> DatasetEmbeddingRuntimeConfig:
        try:
            row = (
                self._db.query(DBDocument.dataset_id)
                .filter(DBDocument.tenant_id == tenant_id, DBDocument.id == document_id)
                .first()
            )
            dataset_id = row[0] if row else None
            return resolve_dataset_embedding_runtime(
                self._load_dataset_metadata(tenant_id=tenant_id, dataset_id=dataset_id)
            )
        except ValueError:
            raise
        except Exception:
            return resolve_dataset_embedding_runtime(None)

    def _dataset_scoped_vector_collections_for_document(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        assume_dataset_scoped: bool,
    ) -> list[str]:
        default_runtime = resolve_dataset_embedding_runtime(None)
        try:
            rows = (
                self._db.query(DocumentChunk.doc_metadata)
                .filter(
                    DocumentChunk.tenant_id == tenant_id,
                    DocumentChunk.document_id == document_id,
                )
                .all()
            )
        except Exception:
            return []

        collections: set[str] = set()
        derived_spaces: set[str] = set()
        for row in rows:
            meta = _first_column_value(row)
            if not isinstance(meta, dict):
                continue
            collection_name = str(meta.get("vector_collection_name") or "").strip()
            if collection_name:
                collections.add(collection_name)
                continue
            space_hash = str(meta.get("embedding_space_hash") or "").strip()
            if not space_hash:
                continue
            if assume_dataset_scoped or _metadata_flag_enabled(meta.get("dataset_scoped")):
                derived_spaces.add(space_hash)
                continue
            if space_hash != default_runtime.embedding_space_hash:
                derived_spaces.add(space_hash)
                continue
            raise _dataset_scoped_cleanup_ambiguous(
                tenant_id=tenant_id,
                document_id=document_id,
                embedding_space_hash=space_hash,
            )

        for space_hash in derived_spaces:
            collections.add(
                collection_name_for_embedding_space(
                    space_hash=space_hash,
                    dataset_scoped=True,
                )
            )
        return sorted(collections)

    def _delete_dataset_scoped_chunk_vectors(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        metadata_filter: dict[str, Any] | None = None,
    ) -> None:
        if str(getattr(settings, "VECTOR_BACKEND", "milvus") or "milvus").strip().lower() != "milvus":
            return
        try:
            runtime = self._embedding_runtime_for_document(tenant_id=tenant_id, document_id=document_id)
        except ValueError as exc:
            logger.warning("Skipping dataset-scoped vector cleanup for invalid embedding config: %s", exc)
            return
        collections = self._dataset_scoped_vector_collections_for_document(
            tenant_id=tenant_id,
            document_id=document_id,
            assume_dataset_scoped=bool(runtime.dataset_scoped),
        )
        if not collections and not runtime.dataset_scoped:
            return
        for collection_name in collections or [runtime.collection_name]:
            adapter = get_milvus_adapter(resolve_collection_name(collection_name))
            if metadata_filter:
                adapter.delete_by_document_id_and_filter(
                    document_id=document_id,
                    tenant_id=tenant_id,
                    metadata_filter=metadata_filter,
                )
            else:
                adapter.delete_by_document_id(document_id, tenant_id=tenant_id)

    def _document_vector_item(
        self,
        *,
        doc: dict[str, Any],
        document_id: UUID,
        tenant_id: UUID,
        index: int,
    ) -> dict[str, Any]:
        meta = dict(doc.get("metadata") or {})
        chunk_id = meta.get("chunk_id")
        pipeline_hash = str(meta.get("pipeline_hash") or "")[:64]
        doc_pipeline_key = str(
            meta.get("doc_pipeline_key")
            or (f"{document_id}:{pipeline_hash}" if pipeline_hash else str(document_id))
        )[:256]
        img_id = meta.get("img_id") or meta.get("image_id") or ""
        image_id = meta.get("image_id") or meta.get("img_id") or ""
        image_url = meta.get("image_url") or meta.get("img_url") or ""
        item_id = str(chunk_id) if chunk_id else f"{document_id}_{index}"
        return {
            "id": item_id,
            "content": str(doc.get("content") or ""),
            "metadata": {
                "tenant_id": str(tenant_id),
                "dataset_id": str(meta.get("dataset_id") or ""),
                "embedding_space_hash": str(meta.get("embedding_space_hash") or ""),
                "document_id": str(document_id),
                "chunk_index": int(meta.get("chunk_index", index) or 0),
                "chunk_id": str(chunk_id) if chunk_id else "",
                "pipeline_hash": pipeline_hash,
                "doc_pipeline_key": doc_pipeline_key,
                "page_number": int(meta.get("page") or meta.get("page_number") or 0),
                "source": str(meta.get("source", "unknown"))[:500],
                "file_type": str(meta.get("file_type", "unknown"))[:20],
                "img_id": str(img_id)[:500],
                "image_id": str(image_id)[:500],
                "image_url": str(image_url)[:2000],
            },
        }

    def index(self, kind: IndexKind, **kwargs):
        if kind == IndexKind.CHUNK:
            return self.index_chunks(**kwargs)
        if kind == IndexKind.EVENT:
            return self.index_events(**kwargs)
        raise ValueError(f"Unsupported index kind: {kind}")

    def upsert(
        self,
        *,
        tenant_id: UUID,
        records: Sequence[IndexRecord],
        default_source: str = "unknown",
        commit: bool = True,
        options: IndexingOptions | None = None,
    ) -> IndexBatchResult:
        start = time.time()
        if not records:
            return IndexBatchResult()

        chunk_records = [r for r in records if r.kind == IndexKind.CHUNK]
        event_records = [r for r in records if r.kind == IndexKind.EVENT]
        unknown_kinds = {r.kind for r in records if r.kind not in (IndexKind.CHUNK, IndexKind.EVENT)}
        if unknown_kinds:
            raise ValueError(f"Unsupported index kinds: {sorted(unknown_kinds)}")

        chunk_result: PersistChunksResult | None = None
        if chunk_records:
            doc_ids = {r.document_id for r in chunk_records if r.document_id is not None}
            if not doc_ids:
                raise ValueError("Chunk records require document_id")
            if len(doc_ids) != 1:
                raise ValueError("Chunk records must share a single document_id per upsert call")
            document_id = next(iter(doc_ids))
            chunk_inputs = [self._record_to_chunk_input(r) for r in chunk_records]
            chunk_result = self.index_chunks(
                document_id=document_id,
                tenant_id=tenant_id,
                chunks=chunk_inputs,
                default_source=default_source,
                commit=commit,
                options=options,
            )

        event_result: PersistEventsResult | None = None
        if event_records:
            event_inputs = [self._record_to_event_input(r) for r in event_records]
            event_result = self.index_events(
                tenant_id=tenant_id,
                events=event_inputs,
                commit=commit,
                options=options,
            )

        elapsed = time.time() - start
        logger.info(
            "indexer.upsert tenant=%s chunks=%s events=%s elapsed=%.3fs",
            tenant_id,
            len(chunk_records),
            len(event_records),
            elapsed,
        )
        return IndexBatchResult(chunk_result=chunk_result, event_result=event_result)

    def delete(self, kind: IndexKind, **kwargs) -> None:
        if kind == IndexKind.CHUNK:
            return self.delete_chunk_indexes(**kwargs)
        if kind == IndexKind.EVENT:
            return self.delete_event_indexes(**kwargs)
        raise ValueError(f"Unsupported index kind: {kind}")

    def delete_all(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        commit: bool = True,
    ) -> None:
        self.delete(IndexKind.CHUNK, tenant_id=tenant_id, document_id=document_id)
        self.delete(IndexKind.EVENT, tenant_id=tenant_id, document_id=document_id, commit=commit)

    def rebuild(self, kind: IndexKind, **kwargs) -> None:
        if kind == IndexKind.CHUNK:
            return self.rebuild_chunk_indexes(**kwargs)
        if kind == IndexKind.EVENT:
            return self.rebuild_event_indexes(**kwargs)
        raise ValueError(f"Unsupported index kind: {kind}")

    def rebuild_all(
        self,
        *,
        tenant_id: UUID,
        document_ids: list[UUID] | None = None,
    ) -> None:
        self.rebuild_tenant(tenant_id=tenant_id, document_ids=document_ids)

    def rebuild_tenant(
        self,
        *,
        tenant_id: UUID,
        document_ids: list[UUID] | None = None,
        kinds: Sequence[IndexKind] | None = None,
    ) -> None:
        active = set(kinds or (IndexKind.CHUNK, IndexKind.EVENT))
        if IndexKind.CHUNK in active:
            self.rebuild_chunk_indexes(tenant_id=tenant_id, document_ids=document_ids)
        if IndexKind.EVENT in active:
            self.rebuild_event_indexes(tenant_id=tenant_id, document_ids=document_ids)

    def index_chunks(
        self,
        *,
        document_id: UUID,
        tenant_id: UUID,
        chunks: list[ChunkInput],
        default_source: str = "unknown",
        commit: bool = True,
        options: IndexingOptions | None = None,
    ) -> PersistChunksResult:
        dataset_id_str: str | None = None
        dataset_uuid: UUID | None = None
        file_type_str: str | None = None
        document_title: str | None = None
        document_retrieval_metadata: dict[str, Any] = {}
        embedding_runtime = resolve_dataset_embedding_runtime(None)
        embedding_space = embedding_runtime.embedding_space_hash
        try:
            row = (
                self._db.query(DBDocument.dataset_id, DBDocument.file_type, DBDocument.filename, DBDocument.doc_metadata)
                .filter(DBDocument.tenant_id == tenant_id, DBDocument.id == document_id)
                .first()
            )
            if row is None:
                raise _dataset_scoped_runtime_unavailable(document_id=document_id, tenant_id=tenant_id)
            ds_id, ft, fn, doc_meta = row
            if ds_id is not None:
                dataset_uuid = ds_id
                dataset_id_str = str(ds_id)
            if ft is not None:
                file_type_str = str(ft)
            if isinstance(doc_meta, dict):
                document_retrieval_metadata = dict(doc_meta)
            document_title = _derive_document_title(fn, doc_meta)
            if dataset_uuid is not None:
                dataset_row = (
                    self._db.query(DBDataset.dataset_metadata)
                    .filter(DBDataset.tenant_id == tenant_id, DBDataset.id == dataset_uuid)
                    .first()
                )
                if dataset_row is None:
                    raise _dataset_scoped_runtime_unavailable(document_id=document_id, tenant_id=tenant_id)
                dataset_meta = dataset_row[0] if dataset_row else None
                if dataset_meta is not None and not isinstance(dataset_meta, dict):
                    raise _dataset_scoped_runtime_unavailable(document_id=document_id, tenant_id=tenant_id)
                embedding_runtime = resolve_dataset_embedding_runtime(dict(dataset_meta or {}))
            else:
                embedding_runtime = resolve_dataset_embedding_runtime(None)
            embedding_space = embedding_runtime.embedding_space_hash
        except ValueError:
            raise
        except DatasetScopedEmbeddingRuntimeResolutionError:
            raise
        except Exception as exc:
            if dataset_uuid is not None:
                raise _dataset_scoped_runtime_unavailable(document_id=document_id, tenant_id=tenant_id) from exc
            raise _dataset_scoped_runtime_unavailable(document_id=document_id, tenant_id=tenant_id) from exc

        source = str(default_source or "").strip() or "unknown"
        total_characters = sum(len(c.content or "") for c in chunks)

        # Best-effort tenant rolling cap on indexing and embedding volume.
        #
        # Note: this is deliberately enforced here (right before vector/BM25 writes) so any
        # ingestion path that calls Indexer will respect quotas.
        try:
            from app.services.tenant_quota_service import (
                TenantQuotaExceededError,
                enforce_tenant_embedding_char_quota,
            )

            enforce_tenant_embedding_char_quota(
                self._db,
                tenant_id=tenant_id,
                additional_chars=int(total_characters or 0),
            )
        except TenantQuotaExceededError:
            raise
        except Exception as exc:
            # Fail open if quota checks are unavailable (misconfig/DB issues).
            logger.debug("Tenant quota check failed during indexing; continuing fail-open: %s", exc)

        normalized_chunks: list[ChunkInput] = []
        vector_docs: list[dict[str, Any]] = []
        extra_vector_docs: list[dict[str, Any]] = []
        chunk_ids: list[UUID] = []
        prepared_chunks: list[tuple[ChunkInput, dict[str, Any], UUID]] = []
        embedding_prefix_enabled = bool(getattr(options, "embedding_context_prefix_enabled", False)) if options else False
        contextual_retrieval_enabled = bool(getattr(options, "embedding_contextual_retrieval_enabled", False)) if options else False
        contextual_retrieval_lazy_mode = (
            bool(getattr(options, "embedding_contextual_retrieval_lazy_mode", False)) if options else False
        )
        field_aware_enabled = bool(getattr(options, "embedding_field_aware_enabled", False)) if options else False
        total_chunks = len(chunks)
        for idx, c in enumerate(chunks):
            meta = dict(c.metadata or {})
            meta.setdefault("index_kind", IndexKind.CHUNK.value)
            meta.setdefault("tenant_id", str(tenant_id))
            meta.setdefault("document_id", str(document_id))
            meta.setdefault("embedding_space_hash", embedding_space)
            meta.setdefault("dataset_scoped", bool(embedding_runtime.dataset_scoped))
            if embedding_runtime.dataset_scoped:
                meta.setdefault("vector_collection_name", embedding_runtime.collection_name)
            if dataset_id_str:
                meta.setdefault("dataset_id", dataset_id_str)
            meta.setdefault("source", source)
            if file_type_str and not meta.get("file_type"):
                meta["file_type"] = file_type_str
            if document_title and not meta.get("document_title"):
                meta["document_title"] = document_title
            for metadata_key in ("document_keywords", "document_questions"):
                value = document_retrieval_metadata.get(metadata_key)
                if value not in (None, "", [], {}) and meta.get(metadata_key) in (None, "", [], {}):
                    meta[metadata_key] = value
            if embedding_prefix_enabled:
                meta.setdefault("embedding_context_prefix_enabled", True)
            if contextual_retrieval_enabled:
                meta.setdefault("embedding_contextual_retrieval_enabled", True)
            if contextual_retrieval_lazy_mode:
                meta.setdefault("embedding_contextual_retrieval_lazy_mode", True)
            if field_aware_enabled:
                meta.setdefault("embedding_field_aware_enabled", True)
            meta = _ensure_chunk_metadata(
                meta,
                content=c.content or "",
                document_id=document_id,
                chunk_index=idx,
                total_chunks=total_chunks,
            )
            # Ensure every chunk has a stable UUID for cross-system linking.
            chunk_id = _safe_uuid(meta.get("chunk_id")) or uuid.uuid4()
            meta["chunk_id"] = str(chunk_id)
            prepared_chunks.append((c, meta, chunk_id))

        apply_sequence_hierarchy_metadata(
            [meta for _, meta, _ in prepared_chunks],
            document_id=str(document_id),
            basis="chunk_sequence",
            level="chunk",
        )

        for c, meta, chunk_id in prepared_chunks:
            chunk_ids.append(chunk_id)
            raw_body = c.content or ""
            embed_text, meta = _chunk_index_content(raw_body, meta)
            normalized_chunks.append(
                ChunkInput(
                    content=c.content,
                    metadata=meta,
                    page_number=c.page_number,
                    start_char=c.start_char,
                    end_char=c.end_char,
                )
            )
            if (
                contextual_retrieval_enabled
                and raw_body
                and _should_prefix_embedding(meta)
                and _should_apply_contextual_retrieval_prefix(meta, lazy_mode=contextual_retrieval_lazy_mode)
            ):
                try:
                    title = document_title or _extract_title_for_embedding(meta)
                    prefix = _build_contextual_prefix_for_chunk(
                        raw_body=raw_body,
                        document_title=title,
                        meta=meta,
                    )
                    if prefix:
                        embed_text = prefix + "\n" + embed_text
                except Exception as exc:
                    # Fail open: contextual prefixes are best-effort.
                    logger.debug("Failed to build contextual embedding prefix; continuing without prefix: %s", exc)
            if embedding_prefix_enabled:
                embed_text = _build_embedding_text(embed_text, meta)
            embed_text = normalize_query(embed_text).normalized_text
            vector_docs.append({"content": embed_text, "metadata": meta})

            if field_aware_enabled and _should_prefix_embedding(meta):
                # Index additional embeddings for title/heading "fields" that map back to the same
                # (document_id, chunk_index) for retrieval-time collapse.
                #
                # These extra vectors deliberately use non-UUID chunk_id values so they don't collide
                # with the primary body vector ID in Milvus. The retriever later resolves the canonical
                # chunk UUID via DB enrichment and overrides chunk_id/content for citations.
                title = _extract_title_for_embedding(meta)
                if title:
                    meta_t = dict(meta)
                    meta_t["chunk_id"] = f"{chunk_id}:title"
                    extra_vector_docs.append(
                        {"content": normalize_query(f"[Title] {title}").normalized_text, "metadata": meta_t}
                    )

                heading = _extract_heading_for_embedding(meta)
                if heading:
                    meta_h = dict(meta)
                    meta_h["chunk_id"] = f"{chunk_id}:heading"
                    extra_vector_docs.append(
                        {"content": normalize_query(f"[Heading] {heading}").normalized_text, "metadata": meta_h}
                    )

        vector_ids = self._index_chunk_vectors(
            vector_docs,
            document_id=document_id,
            tenant_id=tenant_id,
            enable_vectors=self._resolve_chunk_vector_enabled(options),
            embedding_runtime=embedding_runtime,
        )
        if extra_vector_docs and self._resolve_chunk_vector_enabled(options):
            # Best-effort: do not fail ingest if extra vectors can't be written (legacy collections,
            # transient Milvus issues, etc.). The base body embedding is the compatibility path.
            try:
                self._index_chunk_vectors(
                    extra_vector_docs,
                    document_id=document_id,
                    tenant_id=tenant_id,
                    enable_vectors=True,
                    embedding_runtime=embedding_runtime,
                )
            except Exception as exc:
                logger.debug(_INDEXER_FALLBACK_LOG_MESSAGE, exc)
        db_chunks = self._persist_document_chunks(
            document_id=document_id,
            tenant_id=tenant_id,
            dataset_id=dataset_uuid,
            chunks=normalized_chunks,
            vector_ids=vector_ids,
            chunk_ids=chunk_ids,
            commit=commit,
        )

        try:
            self._update_bm25_for_chunks(
                db_chunks=db_chunks,
                tenant_id=tenant_id,
                document_id=document_id,
                default_source=default_source,
                enable_bm25=self._resolve_bm25_enabled(options),
            )
        except Exception as exc:
            logger.warning("Failed to update BM25 index incrementally: %s", exc)

        return PersistChunksResult(
            db_chunks=db_chunks,
            chunk_ids=[c.id for c in db_chunks],
            vector_ids=vector_ids,
            total_characters=total_characters,
        )

    async def index_chunks_async(
        self,
        *,
        document_id: UUID,
        tenant_id: UUID,
        chunks: list[ChunkInput],
        default_source: str = "unknown",
        commit: bool = True,
        options: IndexingOptions | None = None,
    ) -> PersistChunksResult:
        """
        Concurrently index document chunks (vector store, PostgreSQL, BM25).

        NOTE: This method is intentionally disabled.
        The previous implementation used `asyncio.to_thread(...)` while sharing a
        SQLAlchemy Session (`self._db`) across threads, which is not thread-safe.
        Prefer:
        - the synchronous `index_chunks(...)`, or
        - the task-queue based ingestion pipeline for async processing.
        """
        raise RuntimeError(
            "Indexer.index_chunks_async is disabled (thread-unsafe SQLAlchemy Session). "
            "Use index_chunks(...) or the task-queue ingestion pipeline."
        )

    def index_events(
        self,
        *,
        tenant_id: UUID,
        events: Sequence[EventInput],
        commit: bool = True,
        options: IndexingOptions | None = None,
    ) -> PersistEventsResult:
        if not events:
            return PersistEventsResult(
                events=[],
                entities=[],
                event_ids=[],
                entity_ids=[],
                event_vector_ids=[],
                entity_vector_ids=[],
            )

        entity_cache: dict[tuple[str, str, str], KgEntity] = {}
        db_events: list[KgSourceEvent] = []

        for item in events:
            refs = item.references if isinstance(getattr(item, "references", None), dict) else {}
            raw_ph = refs.get("pipeline_hash")
            pipeline_hash = None
            if isinstance(raw_ph, str):
                pipeline_hash = raw_ph.strip() or None
            if pipeline_hash and len(pipeline_hash) > 200:
                pipeline_hash = pipeline_hash[:200]

            event_obj = KgSourceEvent(
                tenant_id=tenant_id,
                pipeline_hash=pipeline_hash,
                document_id=item.document_id,
                chunk_id=item.chunk_id,
                title=item.title,
                summary=item.summary,
                content=item.content,
                content_vector=item.vector,
                references=refs or None,
                extra_data=item.extra_data,
            )
            self._db.add(event_obj)
            db_events.append(event_obj)

            link_extra_data = build_event_entity_provenance(
                document_id=item.document_id,
                chunk_id=item.chunk_id,
                references=refs,
            )

            for ent in item.entities:
                name = ent.name.strip()
                if not name:
                    continue
                normalized = (ent.normalized_name or name.lower()).strip()
                ent_type = (ent.type or "unknown").strip() or "unknown"
                cache_key = (str(tenant_id), normalized, ent_type)

                entity_obj = entity_cache.get(cache_key)
                if entity_obj is None:
                    entity_obj = self._get_or_create_entity(
                        tenant_id=tenant_id,
                        name=name,
                        normalized_name=normalized,
                        type_=ent_type,
                        description=ent.description,
                    )
                    entity_cache[cache_key] = entity_obj

                if ent.vector and not getattr(entity_obj, "vector", None):
                    entity_obj.vector = ent.vector

                # Attach entity-level evidence to the link (provenance is per event, evidence is per entity mention).
                link_extra = dict(link_extra_data or {})
                evidence_quote = (ent.evidence_quote or "").strip() if hasattr(ent, "evidence_quote") else ""
                if evidence_quote:
                    link_extra["evidence_quote"] = evidence_quote[:240]
                evidence_source = (ent.evidence_source or "").strip() if hasattr(ent, "evidence_source") else ""
                if evidence_source:
                    link_extra["evidence_source"] = evidence_source
                if hasattr(ent, "evidence_start_char") and ent.evidence_start_char is not None:
                    try:
                        link_extra["evidence_start_char"] = int(ent.evidence_start_char)
                    except Exception as exc:
                        logger.debug(_INDEXER_FALLBACK_LOG_MESSAGE, exc)
                if hasattr(ent, "evidence_end_char") and ent.evidence_end_char is not None:
                    try:
                        link_extra["evidence_end_char"] = int(ent.evidence_end_char)
                    except Exception as exc:
                        logger.debug(_INDEXER_FALLBACK_LOG_MESSAGE, exc)

                self._db.add(
                    KgEventEntity(
                        event=event_obj,
                        entity=entity_obj,
                        weight=1.0,
                        role=ent.role,
                        extra_data=(link_extra or None),
                    )
                )

        if commit:
            self._db.commit()
        else:
            self._db.flush()

        event_vector_ids: list[str] = []
        entity_vector_ids: list[str] = []
        if commit:
            if self._resolve_event_vector_enabled(options):
                event_vector_ids = self._index_event_vectors(db_events)
            if self._resolve_entity_vector_enabled(options):
                entity_vector_ids = self._index_entity_vectors(list(entity_cache.values()))

        return PersistEventsResult(
            events=db_events,
            entities=list(entity_cache.values()),
            event_ids=[ev.id for ev in db_events],
            entity_ids=[ent.id for ent in entity_cache.values()],
            event_vector_ids=event_vector_ids,
            entity_vector_ids=entity_vector_ids,
        )

    def upsert_entities(
        self,
        *,
        tenant_id: UUID,
        entities: Sequence[dict[str, Any]],
        commit: bool = True,
        options: IndexingOptions | None = None,
    ) -> list[KgEntity]:
        """
        Upsert entities without creating events.

        Intended for process knowledge nodes like Skill/SOP entities that should:
        - live in `kg_entities`,
        - be vector-indexed (optional), and
        - be linked to events (handled by caller).
        """
        if not entities:
            return []

        # Keep insertion order stable while deduplicating by (normalized_name, type).
        unique: dict[tuple[str, str], KgEntity] = {}

        for raw in entities:
            item = _coerce_entity_upsert_input(raw)
            if item is None:
                continue
            key = (item["normalized_name"], item["type"])
            ent = unique.get(key)
            if ent is None:
                ent = self._get_or_create_entity(
                    tenant_id=tenant_id,
                    name=item["name"],
                    normalized_name=item["normalized_name"],
                    type_=item["type"],
                    description=item["description"],
                )
                unique[key] = ent

            # Best-effort enrichment (avoid clobbering user edits).
            _enrich_entity_best_effort(
                ent,
                description=item["description"],
                vector=item["vector"],
                extra_data=item["extra_data"],
            )

        out = list(unique.values())
        if not out:
            return []

        if commit:
            self._db.commit()
        else:
            self._db.flush()

        if commit and self._resolve_entity_vector_enabled(options):
            self._index_entity_vectors(out)

        return out

    def delete_chunk_indexes(self, *, tenant_id: UUID, document_id: UUID, strict: bool = False) -> None:
        failures: list[Exception] = []
        try:
            self._delete_dataset_scoped_chunk_vectors(tenant_id=tenant_id, document_id=document_id)
        except Exception as exc:
            logger.warning("Failed to delete dataset-scoped vectors: %s", exc)
            failures.append(exc)

        try:
            get_vector_store().delete_by_document_id(document_id, tenant_id=tenant_id)
        except Exception as exc:
            logger.warning("Failed to delete vectors: %s", exc)
            failures.append(exc)

        try:
            hybrid_retriever.remove_document_from_bm25_index(document_id, tenant_id=tenant_id)
        except Exception as exc:
            logger.warning("Failed to update BM25 index after deletion: %s", exc)
            failures.append(exc)

        if hasattr(self, "_db"):
            try:
                self._touch_chunk_retrieval_scope(tenant_id=tenant_id, document_id=document_id)
                self._db.flush()
            except Exception as exc:
                logger.warning("Failed to touch retrieval scope after deletion: %s", exc)
                failures.append(exc)

        if strict and failures:
            raise RuntimeError("Document index cleanup failed") from failures[0]

    def delete_chunk_indexes_for_doc_pipeline_key(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        doc_pipeline_key: str,
    ) -> None:
        """
        Best-effort scoped delete for versioned documents.

        This avoids wiping the currently active pipeline when a *new* pipeline version
        is cancelled/failed mid-ingest.
        """
        filter_spec = {"doc_pipeline_key": {"$eq": str(doc_pipeline_key or "")}}
        try:
            self._delete_dataset_scoped_chunk_vectors(
                tenant_id=tenant_id,
                document_id=document_id,
                metadata_filter=filter_spec,
            )
        except Exception as exc:
            logger.warning("Failed to delete dataset-scoped vectors (scoped): %s", str(exc)[:200])

        try:
            get_vector_store().delete_by_document_id_and_filter(
                document_id=document_id,
                tenant_id=tenant_id,
                metadata_filter=filter_spec,
            )
        except NotImplementedError:
            logger.warning("Vector backend does not support selective delete; skipping scoped vector cleanup")
        except Exception as exc:
            logger.warning("Failed to delete vectors (scoped): %s", str(exc)[:200])

        try:
            hybrid_retriever.remove_from_bm25_index_by_metadata_filter(
                tenant_id=tenant_id,
                metadata_filter=filter_spec,
            )
        except Exception as exc:
            logger.warning("Failed to update BM25 index after scoped deletion: %s", str(exc)[:200])

        if hasattr(self, "_db"):
            try:
                self._touch_chunk_retrieval_scope(tenant_id=tenant_id, document_id=document_id)
                self._db.flush()
            except Exception as exc:
                logger.warning("Failed to touch retrieval scope after scoped deletion: %s", str(exc)[:200])

    def delete_event_indexes(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        commit: bool = True,
        prune_orphan_entities: bool = False,
        strict: bool = False,
    ) -> dict[str, int]:
        return self._delete_event_indexes(
            tenant_id=tenant_id,
            query=(
                self._db.query(KgSourceEvent).filter(
                    KgSourceEvent.tenant_id == tenant_id,
                    KgSourceEvent.document_id == document_id,
                )
            ),
            commit=commit,
            prune_orphan_entities=prune_orphan_entities,
            strict=strict,
        )

    def delete_event_indexes_for_chunks(
        self,
        *,
        tenant_id: UUID,
        chunk_ids: Sequence[UUID],
        commit: bool = True,
        exclude_event_ids: Sequence[UUID] | None = None,
        prune_orphan_entities: bool = False,
        strict: bool = False,
    ) -> dict[str, int]:
        """
        Delete KG events (and vectors) for a set of chunk_ids.

        This is primarily used to make KG extraction idempotent when re-running
        on the same chunks (avoid duplicate events).
        """
        chunk_ids_norm = [cid for cid in (_safe_uuid(x) for x in chunk_ids) if cid is not None]
        if not chunk_ids_norm:
            return {"events_deleted": 0, "entities_pruned": 0}

        query = self._db.query(KgSourceEvent).filter(
            KgSourceEvent.tenant_id == tenant_id,
            KgSourceEvent.chunk_id.in_(chunk_ids_norm),
        )
        if exclude_event_ids:
            exclude_norm = [eid for eid in (_safe_uuid(x) for x in exclude_event_ids) if eid is not None]
            if exclude_norm:
                query = query.filter(~KgSourceEvent.id.in_(exclude_norm))

        return self._delete_event_indexes(
            tenant_id=tenant_id,
            query=query,
            commit=commit,
            prune_orphan_entities=prune_orphan_entities,
            strict=strict,
        )

    def prune_orphan_entities(
        self,
        *,
        tenant_id: UUID,
        entity_ids: Sequence[UUID] | None = None,
        commit: bool = True,
        strict: bool = False,
    ) -> int:
        """
        Delete KG entities (and vectors) that have no remaining references.

        When `entity_ids` is provided, pruning is scoped to that candidate set.

        NOTE:
        - Entities can be referenced by multiple KG structures:
          - `kg_event_entities` (event <-> entity)
          - `kg_relations` (entity <-> entity)
        - Once `kg_relations` exists, pruning must consider both, otherwise we can
          delete Skill/SOP nodes or relation-only entities.
        """
        rel_as_subject = aliased(KgRelation)
        rel_as_object = aliased(KgRelation)
        q = (
            self._db.query(KgEntity.id)
            .outerjoin(KgEventEntity, KgEventEntity.entity_id == KgEntity.id)
            .outerjoin(rel_as_subject, rel_as_subject.subject_entity_id == KgEntity.id)
            .outerjoin(rel_as_object, rel_as_object.object_entity_id == KgEntity.id)
            .filter(KgEntity.tenant_id == tenant_id)
            .filter(KgEventEntity.entity_id.is_(None))
            .filter(rel_as_subject.id.is_(None))
            .filter(rel_as_object.id.is_(None))
            .distinct()
        )
        if entity_ids:
            entity_ids_norm = [eid for eid in (_safe_uuid(x) for x in entity_ids) if eid is not None]
            if entity_ids_norm:
                q = q.filter(KgEntity.id.in_(entity_ids_norm))
            else:
                return 0

        orphan_ids = [row[0] for row in q.all() if row and row[0]]
        if not orphan_ids:
            return 0

        try:
            self._entity_vector.delete([str(eid) for eid in orphan_ids])
        except Exception as exc:
            logger.warning("Failed to delete KG entity vectors: %s", exc)
            if strict:
                raise

        self._db.query(KgEntity).filter(KgEntity.id.in_(orphan_ids)).delete(synchronize_session=False)
        if commit:
            self._db.commit()
        else:
            self._db.flush()
        return len(orphan_ids)

    def _delete_event_indexes(
        self,
        *,
        tenant_id: UUID,
        query,
        commit: bool,
        prune_orphan_entities: bool,
        strict: bool,
    ) -> dict[str, int]:
        event_ids = [row[0] for row in query.with_entities(KgSourceEvent.id).all() if row and row[0]]
        if not event_ids:
            return {"events_deleted": 0, "entities_pruned": 0}

        candidate_entity_ids: list[UUID] = []
        if prune_orphan_entities:
            candidate_entity_ids = [
                row[0]
                for row in (
                    self._db.query(KgEventEntity.entity_id)
                    .filter(KgEventEntity.event_id.in_(event_ids))
                    .distinct()
                    .all()
                )
                if row and row[0]
            ]

        try:
            self._event_vector.delete([str(ev_id) for ev_id in event_ids])
        except Exception as exc:
            logger.warning("Failed to delete KG event vectors: %s", exc)
            if strict:
                raise

        deleted = int(query.delete(synchronize_session=False) or 0)
        if commit:
            self._db.commit()
        else:
            self._db.flush()

        pruned = 0
        if prune_orphan_entities and candidate_entity_ids:
            pruned = int(
                self.prune_orphan_entities(
                    tenant_id=tenant_id,
                    entity_ids=candidate_entity_ids,
                    commit=commit,
                    strict=strict,
                )
            )

        return {"events_deleted": deleted, "entities_pruned": pruned}

    def rebuild_chunk_indexes(
        self,
        *,
        tenant_id: UUID,
        document_ids: list[UUID] | None = None,
    ) -> None:
        if not bool(getattr(settings, "BM25_INDEX_ENABLED", True)):
            return
        count = hybrid_retriever.build_bm25_index_from_db(
            self._db,
            tenant_id=tenant_id,
            document_ids=document_ids,
            max_chunks=0,
            batch_size=2000,
        )
        if not count:
            logger.warning("No chunks found for BM25 index")
            return
        if document_ids:
            for document_id in list(dict.fromkeys(document_ids)):
                self._touch_chunk_retrieval_scope(tenant_id=tenant_id, document_id=document_id)
            self._db.flush()

    def rebuild_event_indexes(
        self,
        *,
        tenant_id: UUID,
        document_ids: list[UUID] | None = None,
    ) -> None:
        event_query = self._db.query(KgSourceEvent).filter(KgSourceEvent.tenant_id == tenant_id)
        if document_ids:
            event_query = event_query.filter(KgSourceEvent.document_id.in_(document_ids))
        events = event_query.all()
        if events and bool(getattr(settings, "EVENT_VECTOR_ENABLED", True)):
            self._index_event_vectors(events)

        event_ids = [ev.id for ev in events]
        if not event_ids:
            return

        entity_id_rows = (
            self._db.query(KgEventEntity.entity_id)
            .filter(KgEventEntity.event_id.in_(event_ids))
            .distinct()
            .all()
        )
        entity_ids = [row[0] for row in entity_id_rows if row and row[0]]
        if not entity_ids:
            return

        entities = (
            self._db.query(KgEntity)
            .filter(KgEntity.tenant_id == tenant_id, KgEntity.id.in_(entity_ids))
            .all()
        )
        if entities and bool(getattr(settings, "ENTITY_VECTOR_ENABLED", True)):
            self._index_entity_vectors(entities)

    def _touch_chunk_retrieval_scope(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        dataset_id: UUID | None = None,
    ) -> None:
        now = datetime.now(UTC)
        document = (
            self._db.query(DBDocument)
            .filter(DBDocument.tenant_id == tenant_id, DBDocument.id == document_id)
            .first()
        )
        resolved_dataset_id = dataset_id
        if document is not None:
            document.updated_at = now
            if resolved_dataset_id is None:
                resolved_dataset_id = _safe_uuid(getattr(document, "dataset_id", None))
        if resolved_dataset_id is None:
            return
        dataset = (
            self._db.query(DBDataset)
            .filter(DBDataset.tenant_id == tenant_id, DBDataset.id == resolved_dataset_id)
            .first()
        )
        if dataset is not None:
            dataset.updated_at = now

    def _record_to_chunk_input(self, record: IndexRecord) -> ChunkInput:
        meta = dict(record.metadata or {})
        page_number = record.page_number if record.page_number is not None else meta.get("page") or meta.get("page_number")
        start_char = record.start_char if record.start_char is not None else meta.get("start_char")
        end_char = record.end_char if record.end_char is not None else meta.get("end_char")
        return ChunkInput(
            content=record.content,
            metadata=meta,
            page_number=page_number,
            start_char=start_char,
            end_char=end_char,
        )

    def _record_to_event_input(self, record: IndexRecord) -> EventInput:
        title = (record.title or "").strip()
        summary = (record.summary or "").strip()
        content = (record.content or "").strip()
        if not content:
            content = summary or title
        if not title:
            title = (summary[:50] if summary else content[:50]).strip() or "Event"
        if not summary:
            summary = (content[:200] if content else title).strip() or "Event"
        return EventInput(
            title=title,
            summary=summary,
            content=content,
            document_id=record.document_id,
            chunk_id=record.chunk_id,
            references=record.references,
            extra_data=record.extra_data,
            vector=record.vector,
            entities=list(record.entities or []),
        )

    def _write_dataset_scoped_chunk_vectors(
        self,
        docs: list[dict[str, Any]],
        *,
        document_id: UUID,
        tenant_id: UUID,
        runtime: DatasetEmbeddingRuntimeConfig,
    ) -> list[str | None]:
        try:
            embeddings = create_embeddings_for_runtime(runtime)
            vectors = embeddings.embed_documents([str(doc.get("content") or "") for doc in docs])
            adapter = get_milvus_adapter(resolve_collection_name(runtime.collection_name))
            items = [
                self._document_vector_item(
                    doc=doc,
                    document_id=document_id,
                    tenant_id=tenant_id,
                    index=index,
                )
                for index, doc in enumerate(docs)
            ]
            # Retry the Milvus write on transient errors, mirroring the default
            # path (_write_chunk_vector_batch_with_retries). Embeddings are a pure
            # function of the input and already batched inside the provider, so we
            # only re-run the vector-store write, not the embedding step.
            max_retries, backoff = _vector_write_retry_policy()
            ids: list[str | None] = []
            for attempt in range(max_retries + 1):
                try:
                    ids = adapter.add_vectors(
                        items, embeddings=vectors, batch_size=_vector_write_batch_size(), upsert=True
                    )
                    break
                except Exception as exc:  # noqa: BLE001
                    if attempt >= max_retries:
                        raise
                    _log_chunk_vector_retry(
                        tenant_id=tenant_id,
                        document_id=document_id,
                        attempt=attempt + 1,
                        max_attempts=max_retries + 1,
                        batch_size=len(items),
                        backoff=backoff,
                        error=exc,
                    )
                    time.sleep(backoff)
                    backoff *= 2
            # Fail closed on a short/long id list so a partial Milvus write cannot
            # silently desynchronize chunk<->vector_id alignment downstream.
            if len(ids) != len(docs):
                raise ValueError(f"vector ids length {len(ids)} != docs length {len(docs)}")
            return ids
        except Exception as exc:
            logger.warning(
                "Dataset-scoped vector write failed collection=%s space=%s: %s",
                runtime.collection_name,
                runtime.embedding_space_hash,
                str(exc)[:200],
            )
            raise

    def _write_chunk_vector_batch_with_retries(
        self,
        batch: list[dict[str, Any]],
        *,
        document_id: UUID,
        tenant_id: UUID,
        max_retries: int,
        backoff: float,
    ) -> tuple[list[str | None], float]:
        vector_store = get_vector_store()
        for attempt in range(max_retries + 1):
            try:
                ids = list(vector_store.add_documents(batch, document_id, tenant_id))
                _dual_write_shadow_vectors_best_effort(batch, document_id=document_id, tenant_id=tenant_id)
                return ids, backoff
            except Exception as exc:  # noqa: BLE001
                if attempt >= max_retries:
                    raise
                _log_chunk_vector_retry(
                    tenant_id=tenant_id,
                    document_id=document_id,
                    attempt=attempt + 1,
                    max_attempts=max_retries + 1,
                    batch_size=len(batch),
                    backoff=backoff,
                    error=exc,
                )
                time.sleep(backoff)
                backoff *= 2
        return [], backoff

    def _write_default_chunk_vectors(
        self,
        docs: list[dict[str, Any]],
        *,
        document_id: UUID,
        tenant_id: UUID,
    ) -> list[str | None]:
        batch_size = _vector_write_batch_size()
        max_retries, backoff = _vector_write_retry_policy()
        out: list[str | None] = []
        for i in range(0, len(docs), batch_size):
            batch = docs[i : i + batch_size]
            ids, backoff = self._write_chunk_vector_batch_with_retries(
                batch,
                document_id=document_id,
                tenant_id=tenant_id,
                max_retries=max_retries,
                backoff=backoff,
            )
            out.extend(ids)
        return out

    def _index_chunk_vectors(
        self,
        docs: list[dict[str, Any]],
        *,
        document_id: UUID,
        tenant_id: UUID,
        enable_vectors: bool,
        embedding_runtime: DatasetEmbeddingRuntimeConfig | None = None,
    ) -> list[str | None]:
        if not docs:
            return []

        if not enable_vectors:
            return [None] * len(docs)

        runtime = embedding_runtime or resolve_dataset_embedding_runtime(None)
        if runtime.dataset_scoped and _milvus_backend_enabled():
            return self._write_dataset_scoped_chunk_vectors(
                docs,
                document_id=document_id,
                tenant_id=tenant_id,
                runtime=runtime,
            )

        try:
            out = self._write_default_chunk_vectors(docs, document_id=document_id, tenant_id=tenant_id)
            if len(out) != len(docs):
                raise ValueError(f"vector ids length {len(out)} != docs length {len(docs)}")
            return out
        except Exception as exc:
            logger.warning("Failed to store vectors: %s", exc)
            raise

    def _persist_document_chunks(
        self,
        *,
        document_id: UUID,
        tenant_id: UUID,
        dataset_id: UUID | None = None,
        chunks: list[ChunkInput],
        vector_ids: list[str | None] | None = None,
        chunk_ids: list[UUID] | None = None,
        commit: bool = True,
    ) -> list[DocumentChunk]:
        if not chunks:
            return []

        vector_ids = _normalized_vector_ids(vector_ids, chunks_count=len(chunks))
        chunk_ids = _normalized_chunk_ids(chunk_ids, chunks_count=len(chunks))
        db_chunks: list[DocumentChunk] = []
        total_chunks = len(chunks)
        for idx, (chunk, vector_id, chunk_id) in enumerate(zip(chunks, vector_ids, chunk_ids, strict=False)):
            meta = _document_chunk_metadata(
                chunk,
                document_id=document_id,
                tenant_id=tenant_id,
                chunk_index=idx,
                total_chunks=total_chunks,
                chunk_id=chunk_id,
            )
            page_number, start_char, end_char = _chunk_position_values(chunk, meta)

            db_chunks.append(
                DocumentChunk(
                    id=chunk_id,
                    tenant_id=tenant_id,
                    document_id=document_id,
                    chunk_index=idx,
                    content=chunk.content,
                    page_number=page_number,
                    start_char=start_char,
                    end_char=end_char,
                    doc_metadata=meta,
                    vector_id=vector_id,
                )
            )

        self._db.add_all(db_chunks)
        self._touch_chunk_retrieval_scope(
            tenant_id=tenant_id,
            document_id=document_id,
            dataset_id=dataset_id,
        )
        self._db.flush()
        if commit:
            self._db.commit()

        return db_chunks

    def _update_bm25_for_chunks(
        self,
        *,
        db_chunks: list[DocumentChunk],
        tenant_id: UUID,
        document_id: UUID,
        default_source: str = "unknown",
        enable_bm25: bool,
    ) -> None:
        if not db_chunks:
            return
        if not enable_bm25:
            return

        bm25_docs: list[LCDocument] = []
        total_chunks = len(db_chunks)
        for db_chunk in db_chunks:
            meta = dict(db_chunk.doc_metadata or {})
            normalize_image_metadata(meta)
            meta = _ensure_chunk_metadata(
                meta,
                content=db_chunk.content or "",
                document_id=document_id,
                chunk_index=int(db_chunk.chunk_index or 0),
                total_chunks=total_chunks,
            )
            meta.setdefault("index_kind", IndexKind.CHUNK.value)
            meta.setdefault("tenant_id", str(tenant_id))
            meta.setdefault("document_id", str(document_id))
            meta.setdefault("chunk_index", db_chunk.chunk_index)
            meta.setdefault("chunk_id", str(db_chunk.id))
            meta.setdefault("source", meta.get("source", default_source))
            meta.setdefault("page", db_chunk.page_number)
            meta.setdefault("image_id", meta.get("image_id"))
            meta.setdefault("image_url", meta.get("image_url"))
            page_content, meta = _chunk_index_content(db_chunk.content or "", meta)
            bm25_docs.append(LCDocument(page_content=page_content, id=str(db_chunk.id), metadata=meta))

        hybrid_retriever.upsert_bm25_documents(bm25_docs, tenant_id=tenant_id)

    def _get_or_create_entity(
        self,
        *,
        tenant_id: UUID,
        name: str,
        normalized_name: str,
        type_: str,
        description: str | None = None,
    ) -> KgEntity:
        existing = (
            self._db.query(KgEntity)
            .filter(
                KgEntity.tenant_id == tenant_id,
                KgEntity.normalized_name == normalized_name,
                KgEntity.type == type_,
            )
            .first()
        )
        if existing:
            return existing

        entity = KgEntity(
            tenant_id=tenant_id,
            name=name,
            normalized_name=normalized_name,
            type=type_,
            description=description,
            vector=None,
            extra_data=None,
        )
        self._db.add(entity)
        self._db.flush()
        return entity

    def _index_event_vectors(self, events: Iterable[KgSourceEvent]) -> list[str]:
        items: list[dict[str, Any]] = []
        embeddings: list[list[float]] = []
        for ev in events:
            vector_item = _event_vector_item(ev)
            if vector_item is None:
                continue
            item, vector = vector_item
            items.append(item)
            embeddings.append(vector)

        if not items:
            return []
        try:
            return self._event_vector.add_vectors(items, embeddings=embeddings)
        except Exception as exc:
            logger.warning("Failed to store KG event vectors: %s", exc)
            return []

    def _index_entity_vectors(self, entities: Iterable[KgEntity]) -> list[str]:
        items: list[dict[str, Any]] = []
        embeddings: list[list[float]] = []
        for ent in entities:
            if not ent.vector:
                continue
            embeddings.append(list(ent.vector))
            items.append(
                {
                    "id": str(ent.id),
                    "content": ent.name,
                    "metadata": {
                        "name": ent.name,
                        "normalized_name": ent.normalized_name,
                        "tenant_id": str(ent.tenant_id),
                        "type": ent.type,
                        "description": ent.description or "",
                        "index_kind": "entity",
                    },
                }
            )

        if not items:
            return []
        try:
            return self._entity_vector.add_vectors(items, embeddings=embeddings)
        except Exception as exc:
            logger.warning("Failed to store KG entity vectors: %s", exc)
            return []
