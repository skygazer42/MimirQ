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
from app.services.document_index_channel_service import (
    DOCUMENT_INDEX_CHANNEL_DISABLED,
    DOCUMENT_INDEX_CHANNEL_ERROR,
    DOCUMENT_INDEX_CHANNEL_PROCESSING,
    DOCUMENT_INDEX_CHANNEL_READY,
    DOCUMENT_INDEX_CHANNEL_SKIPPED,
    transition_document_index_channel,
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
_CHUNK_METADATA_SCAN_BATCH_SIZE = 256

_shadow_vector_writer_sig: str | None = None
_shadow_vector_writer: tuple[Any, Any, str] | None = None  # (embeddings, adapter, embedding_space_hash)
_SHADOW_VECTOR_WRITE_EVENT = "ingest.shadow_vector_write"
_INGEST_GATE_ACTION = "document.ingest_gate"


class DatasetScopedEmbeddingRuntimeResolutionError(RuntimeError):
    """Raised when a dataset-scoped document cannot safely resolve its embedding runtime."""


def _dataset_scoped_runtime_unavailable(
    *, document_id: UUID, tenant_id: UUID
) -> DatasetScopedEmbeddingRuntimeResolutionError:
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


def _tenant_quota_fail_closed_enabled() -> bool:
    return bool(getattr(settings, "TENANT_QUOTA_FAIL_CLOSED", False))


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _record_ingest_gate_outcome(
    metadata: dict[str, Any] | None,
    *,
    gate: str,
    outcome: str,
    reason: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out = dict(metadata or {})
    gates = out.get("ingest_gate_outcomes")
    gates = dict(gates) if isinstance(gates, dict) else {}
    entry: dict[str, Any] = {
        "gate": str(gate or "").strip() or "unknown",
        "outcome": str(outcome or "").strip() or "degraded",
        "reason": str(reason or "").strip() or "unknown",
        "recorded_at": _now_iso(),
    }
    if isinstance(details, dict):
        for key, value in details.items():
            if value not in (None, "", [], {}):
                entry[str(key)] = value
    gates[entry["gate"]] = entry
    out["ingest_gate_outcomes"] = gates
    return out


def _audit_ingest_gate_event(
    db: Session,
    *,
    tenant_id: UUID,
    document_id: UUID,
    gate: str,
    outcome: str,
    reason: str,
    details: dict[str, Any] | None = None,
) -> None:
    try:
        from app.services.audit_log_service import audit_log_event

        audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=None,
            action=_INGEST_GATE_ACTION,
            resource_type="document",
            resource_id=str(document_id),
            details={
                "gate": str(gate or "").strip() or "unknown",
                "outcome": str(outcome or "").strip() or "degraded",
                "reason": str(reason or "").strip() or "unknown",
                **(dict(details or {}) if isinstance(details, dict) else {}),
            },
        )
    except Exception as exc:
        logger.debug(_INDEXER_FALLBACK_LOG_MESSAGE, exc)


def _persist_ingest_gate_outcome_best_effort(
    db: Session,
    *,
    tenant_id: UUID,
    document_id: UUID,
    gate: str,
    outcome: str,
    reason: str,
    details: dict[str, Any] | None = None,
) -> None:
    try:
        db_document = (
            db.query(DBDocument).filter(DBDocument.tenant_id == tenant_id, DBDocument.id == document_id).first()
        )
        if db_document is not None:
            db_document.doc_metadata = _record_ingest_gate_outcome(
                dict(getattr(db_document, "doc_metadata", None) or {}),
                gate=gate,
                outcome=outcome,
                reason=reason,
                details=details,
            )
    except Exception as exc:
        logger.debug(_INDEXER_FALLBACK_LOG_MESSAGE, exc)


def _enforce_embedding_quota_gate(
    db: Session,
    *,
    tenant_id: UUID,
    document_id: UUID,
    additional_chars: int,
) -> dict[str, Any]:
    from app.services.tenant_quota_service import (
        TenantQuotaExceededError,
        enforce_tenant_embedding_char_quota,
    )

    try:
        return enforce_tenant_embedding_char_quota(
            db,
            tenant_id=tenant_id,
            additional_chars=int(additional_chars or 0),
        )
    except TenantQuotaExceededError:
        raise
    except Exception as exc:
        closed = _tenant_quota_fail_closed_enabled()
        outcome = "closed" if closed else "degraded"
        reason = "tenant_quota_gate_unavailable"
        details = {
            "quota": "embedding_chars",
            "additional_chars": max(0, int(additional_chars or 0)),
            "error": str(exc)[:200],
            "fail_closed": bool(closed),
        }
        log_metrics(
            {
                "event": "ingest.quota_gate",
                "tenant_id": str(tenant_id),
                "document_id": str(document_id),
                "quota": "embedding_chars",
                "outcome": outcome,
                "reason": reason,
                "fail_closed": bool(closed),
            }
        )
        _persist_ingest_gate_outcome_best_effort(
            db,
            tenant_id=tenant_id,
            document_id=document_id,
            gate="tenant_quota",
            outcome=outcome,
            reason=reason,
            details=details,
        )
        _audit_ingest_gate_event(
            db,
            tenant_id=tenant_id,
            document_id=document_id,
            gate="tenant_quota",
            outcome=outcome,
            reason=reason,
            details=details,
        )
        if closed:
            raise TenantQuotaExceededError(
                "embedding_chars_gate_unavailable",
                "Tenant embedding quota enforcement unavailable",
                meta={
                    **details,
                    "outcome": outcome,
                    "reason": reason,
                },
            ) from exc
        logger.warning("Tenant quota check degraded during indexing; continuing fail-open: %s", str(exc)[:200])
        return {
            "enabled": False,
            "mode": "warn",
            "limit_chars": 0,
            "used_chars": 0,
            "additional_chars": max(0, int(additional_chars or 0)),
            "would_exceed": False,
            "gate_outcome": outcome,
            "gate_reason": reason,
        }


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


_UNRESOLVED_ROW_VALUE = object()


def _mapping_row_value(row: Any, key: str) -> Any:
    mapping = getattr(row, "_mapping", None)
    if mapping is None:
        return _UNRESOLVED_ROW_VALUE
    if key in mapping:
        return mapping[key]
    metadata = mapping.get("metadata")
    if isinstance(metadata, dict) and key in metadata:
        return metadata.get(key)
    return _UNRESOLVED_ROW_VALUE


def _dict_row_value(row: Any, key: str) -> Any:
    if not isinstance(row, dict):
        return _UNRESOLVED_ROW_VALUE
    if key in row:
        return row.get(key)
    metadata = row.get("metadata")
    if isinstance(metadata, dict) and key in metadata:
        return metadata.get(key)
    return _UNRESOLVED_ROW_VALUE


def _sequence_row_value(row: Any, key: str) -> Any:
    if not isinstance(row, (tuple, list)):
        return _UNRESOLVED_ROW_VALUE
    value = row[0] if row else None
    if isinstance(value, dict):
        return value.get(key)
    return value


def _indexed_row_value(row: Any, key: str) -> Any:
    try:
        value = row[key]
        if isinstance(value, dict):
            return value.get(key)
        return value
    except (IndexError, KeyError, TypeError):
        return row


def _row_named_value(row: Any, key: str) -> Any:
    if row is None:
        return None
    for resolver in (_mapping_row_value, _dict_row_value):
        value = resolver(row, key)
        if value is not _UNRESOLVED_ROW_VALUE:
            return value
    if hasattr(row, key):
        return getattr(row, key)
    sequence_value = _sequence_row_value(row, key)
    if sequence_value is not _UNRESOLVED_ROW_VALUE:
        return sequence_value
    return _indexed_row_value(row, key)


def _iter_query_rows(query: Any, *, batch_size: int) -> Iterable[Any]:
    if hasattr(query, "yield_per"):
        query = query.yield_per(batch_size)
    if hasattr(query, "__iter__"):
        return query
    if hasattr(query, "all"):
        return query.all()
    return ()


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
        _safe_int(chunk.page_number)
        if chunk.page_number is not None
        else _safe_int(meta.get("page") or meta.get("page_number"))
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

    def _load_document_for_channel_tracking(self, *, tenant_id: UUID, document_id: UUID) -> DBDocument | None:
        return (
            self._db.query(DBDocument)
            .filter(
                DBDocument.tenant_id == tenant_id,
                DBDocument.id == document_id,
            )
            .first()
        )

    def _track_document_channel(
        self,
        *,
        document: DBDocument | None,
        channel: str,
        status: str,
        error: str | None = None,
        increment_attempt: bool = False,
    ) -> None:
        if document is None:
            return
        transition_document_index_channel(
            self._db,
            document=document,
            channel=channel,
            status=status,
            error=error,
            increment_attempt=increment_attempt,
            commit=False,
        )

    def _load_dataset_metadata(
        self,
        *,
        tenant_id: UUID,
        dataset_id: UUID | None,
        strict: bool = False,
    ) -> dict[str, Any]:
        if dataset_id is None:
            return {}
        try:
            row = (
                self._db.query(DBDataset.dataset_metadata)
                .filter(DBDataset.tenant_id == tenant_id, DBDataset.id == dataset_id)
                .first()
            )
            if row is None:
                if strict:
                    raise LookupError("dataset not found")
                return {}
            meta = row[0]
            if meta is None:
                return {}
            if isinstance(meta, dict):
                return dict(meta)
            if strict:
                raise TypeError("dataset metadata must be an object")
            return {}
        except Exception:
            if strict:
                raise
            return {}

    def _embedding_runtime_for_document(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        strict: bool = False,
    ) -> DatasetEmbeddingRuntimeConfig:
        try:
            row = (
                self._db.query(DBDocument.dataset_id)
                .filter(DBDocument.tenant_id == tenant_id, DBDocument.id == document_id)
                .first()
            )
            if row is None and strict:
                raise _dataset_scoped_runtime_unavailable(document_id=document_id, tenant_id=tenant_id)
            dataset_id = row[0] if row else None
            return resolve_dataset_embedding_runtime(
                self._load_dataset_metadata(
                    tenant_id=tenant_id,
                    dataset_id=dataset_id,
                    strict=strict,
                )
            )
        except DatasetScopedEmbeddingRuntimeResolutionError:
            raise
        except ValueError:
            raise
        except Exception as exc:
            if strict:
                raise _dataset_scoped_runtime_unavailable(
                    document_id=document_id,
                    tenant_id=tenant_id,
                ) from exc
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
            collection_name_column = DocumentChunk.doc_metadata["vector_collection_name"].astext.label(
                "vector_collection_name"
            )
            embedding_space_column = DocumentChunk.doc_metadata["embedding_space_hash"].astext.label(
                "embedding_space_hash"
            )
            dataset_scoped_column = DocumentChunk.doc_metadata["dataset_scoped"].astext.label("dataset_scoped")
            rows = self._db.query(
                collection_name_column,
                embedding_space_column,
                dataset_scoped_column,
            ).filter(
                DocumentChunk.tenant_id == tenant_id,
                DocumentChunk.document_id == document_id,
            )
        except Exception:
            return []

        collections: set[str] = set()
        derived_spaces: set[str] = set()
        for row in _iter_query_rows(rows, batch_size=_CHUNK_METADATA_SCAN_BATCH_SIZE):
            collection_name = str(_row_named_value(row, "vector_collection_name") or "").strip()
            if collection_name:
                collections.add(collection_name)
                continue
            space_hash = str(_row_named_value(row, "embedding_space_hash") or "").strip()
            if not space_hash:
                continue
            if assume_dataset_scoped or _metadata_flag_enabled(_row_named_value(row, "dataset_scoped")):
                derived_spaces.add(space_hash)
                continue
            if space_hash != default_runtime.embedding_space_hash:
                derived_spaces.add(space_hash)
                continue
            # Older chunk metadata may be missing the persisted dataset-scoped marker even
            # though vectors were written into the dataset-scoped collection for this
            # embedding space. Full document cleanup always deletes the default store
            # separately, so include the derived dataset-scoped collection here to clear
            # both plausible locations instead of leaving stale vectors behind.
            derived_spaces.add(space_hash)

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

    def delete_document_chunk_vectors(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        metadata_filter: dict[str, Any],
    ) -> None:
        if _milvus_backend_enabled():
            self._delete_dataset_scoped_chunk_vectors(
                tenant_id=tenant_id,
                document_id=document_id,
                metadata_filter=metadata_filter,
            )
        get_vector_store().delete_by_document_id_and_filter(
            document_id=document_id,
            tenant_id=tenant_id,
            metadata_filter=metadata_filter,
        )

    def upsert_document_chunk_vector(
        self,
        *,
        document_id: UUID,
        tenant_id: UUID,
        content: str,
        metadata: dict[str, Any],
    ) -> str | None:
        runtime = self._embedding_runtime_for_document(
            tenant_id=tenant_id,
            document_id=document_id,
            strict=True,
        )
        vector_metadata = dict(metadata or {})
        vector_metadata["embedding_space_hash"] = runtime.embedding_space_hash
        vector_metadata["dataset_scoped"] = bool(runtime.dataset_scoped)
        if runtime.dataset_scoped:
            vector_metadata["vector_collection_name"] = runtime.collection_name
        else:
            vector_metadata.pop("vector_collection_name", None)
        ids = self._index_chunk_vectors(
            [{"content": str(content or ""), "metadata": vector_metadata}],
            document_id=document_id,
            tenant_id=tenant_id,
            enable_vectors=True,
            embedding_runtime=runtime,
        )
        vector_id = ids[0] if ids else None
        if vector_id:
            metadata.clear()
            metadata.update(vector_metadata)
        return str(vector_id) if vector_id else None

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
            meta.get("doc_pipeline_key") or (f"{document_id}:{pipeline_hash}" if pipeline_hash else str(document_id))
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

    def _resolve_chunk_index_context(self, *, tenant_id: UUID, document_id: UUID) -> dict[str, Any]:
        try:
            embedding_runtime = self._embedding_runtime_for_document(
                tenant_id=tenant_id,
                document_id=document_id,
                strict=True,
            )
            db_document = self._load_document_for_channel_tracking(tenant_id=tenant_id, document_id=document_id)
            if db_document is None:
                raise _dataset_scoped_runtime_unavailable(document_id=document_id, tenant_id=tenant_id)
            doc_meta = db_document.doc_metadata
            return {
                "embedding_runtime": embedding_runtime,
                "embedding_space": embedding_runtime.embedding_space_hash,
                "db_document": db_document,
                "dataset_uuid": db_document.dataset_id,
                "dataset_id_str": str(db_document.dataset_id) if db_document.dataset_id is not None else None,
                "file_type_str": str(db_document.file_type) if db_document.file_type is not None else None,
                "document_title": _derive_document_title(db_document.filename, doc_meta),
                "document_retrieval_metadata": dict(doc_meta) if isinstance(doc_meta, dict) else {},
            }
        except ValueError:
            raise
        except DatasetScopedEmbeddingRuntimeResolutionError:
            raise
        except Exception as exc:
            raise _dataset_scoped_runtime_unavailable(document_id=document_id, tenant_id=tenant_id) from exc

    def _chunk_index_option_flags(self, options: IndexingOptions | None) -> dict[str, bool]:
        return {
            "embedding_prefix_enabled": bool(getattr(options, "embedding_context_prefix_enabled", False))
            if options
            else False,
            "contextual_retrieval_enabled": bool(getattr(options, "embedding_contextual_retrieval_enabled", False))
            if options
            else False,
            "contextual_retrieval_lazy_mode": bool(getattr(options, "embedding_contextual_retrieval_lazy_mode", False))
            if options
            else False,
            "field_aware_enabled": bool(getattr(options, "embedding_field_aware_enabled", False)) if options else False,
        }

    def _prepare_chunk_index_inputs(
        self,
        *,
        document_id: UUID,
        tenant_id: UUID,
        chunks: list[ChunkInput],
        source: str,
        context: dict[str, Any],
        flags: dict[str, bool],
    ) -> list[tuple[ChunkInput, dict[str, Any], UUID]]:
        prepared_chunks: list[tuple[ChunkInput, dict[str, Any], UUID]] = []
        embedding_runtime = context["embedding_runtime"]
        total_chunks = len(chunks)
        for idx, chunk in enumerate(chunks):
            meta = dict(chunk.metadata or {})
            meta.setdefault("index_kind", IndexKind.CHUNK.value)
            meta.setdefault("tenant_id", str(tenant_id))
            meta.setdefault("document_id", str(document_id))
            meta.setdefault("embedding_space_hash", context["embedding_space"])
            meta.setdefault("dataset_scoped", bool(embedding_runtime.dataset_scoped))
            if embedding_runtime.dataset_scoped:
                meta.setdefault("vector_collection_name", embedding_runtime.collection_name)
            if context["dataset_id_str"]:
                meta.setdefault("dataset_id", context["dataset_id_str"])
            meta.setdefault("source", source)
            if context["file_type_str"] and not meta.get("file_type"):
                meta["file_type"] = context["file_type_str"]
            if context["document_title"] and not meta.get("document_title"):
                meta["document_title"] = context["document_title"]
            for metadata_key in ("document_keywords", "document_questions"):
                value = context["document_retrieval_metadata"].get(metadata_key)
                if value not in (None, "", [], {}) and meta.get(metadata_key) in (None, "", [], {}):
                    meta[metadata_key] = value
            for flag_name in (
                "embedding_prefix_enabled",
                "contextual_retrieval_enabled",
                "contextual_retrieval_lazy_mode",
                "field_aware_enabled",
            ):
                if flags[flag_name]:
                    meta.setdefault(flag_name, True)
            meta = _ensure_chunk_metadata(
                meta,
                content=chunk.content or "",
                document_id=document_id,
                chunk_index=idx,
                total_chunks=total_chunks,
            )
            chunk_id = _safe_uuid(meta.get("chunk_id")) or uuid.uuid4()
            meta["chunk_id"] = str(chunk_id)
            prepared_chunks.append((chunk, meta, chunk_id))
        apply_sequence_hierarchy_metadata(
            [meta for _, meta, _ in prepared_chunks],
            document_id=str(document_id),
            basis="chunk_sequence",
            level="chunk",
        )
        return prepared_chunks

    def _chunk_embed_text(
        self,
        *,
        raw_body: str,
        embed_text: str,
        meta: dict[str, Any],
        document_title: str | None,
        flags: dict[str, bool],
    ) -> str:
        if (
            flags["contextual_retrieval_enabled"]
            and raw_body
            and _should_prefix_embedding(meta)
            and _should_apply_contextual_retrieval_prefix(meta, lazy_mode=flags["contextual_retrieval_lazy_mode"])
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
                logger.debug("Failed to build contextual embedding prefix; continuing without prefix: %s", exc)
        if flags["embedding_prefix_enabled"]:
            embed_text = _build_embedding_text(embed_text, meta)
        return normalize_query(embed_text).normalized_text

    def _chunk_extra_vector_docs(
        self, *, meta: dict[str, Any], chunk_id: UUID, field_aware_enabled: bool
    ) -> list[dict[str, Any]]:
        if not field_aware_enabled or not _should_prefix_embedding(meta):
            return []
        out: list[dict[str, Any]] = []
        title = _extract_title_for_embedding(meta)
        if title:
            meta_t = dict(meta)
            meta_t["chunk_id"] = f"{chunk_id}:title"
            out.append({"content": normalize_query(f"[Title] {title}").normalized_text, "metadata": meta_t})
        heading = _extract_heading_for_embedding(meta)
        if heading:
            meta_h = dict(meta)
            meta_h["chunk_id"] = f"{chunk_id}:heading"
            out.append({"content": normalize_query(f"[Heading] {heading}").normalized_text, "metadata": meta_h})
        return out

    def _build_chunk_vector_payloads(
        self,
        *,
        prepared_chunks: list[tuple[ChunkInput, dict[str, Any], UUID]],
        document_title: str | None,
        flags: dict[str, bool],
    ) -> tuple[list[ChunkInput], list[dict[str, Any]], list[dict[str, Any]], list[UUID]]:
        normalized_chunks: list[ChunkInput] = []
        vector_docs: list[dict[str, Any]] = []
        extra_vector_docs: list[dict[str, Any]] = []
        chunk_ids: list[UUID] = []
        for chunk, meta, chunk_id in prepared_chunks:
            chunk_ids.append(chunk_id)
            raw_body = chunk.content or ""
            embed_text, normalized_meta = _chunk_index_content(raw_body, meta)
            normalized_chunks.append(
                ChunkInput(
                    content=chunk.content,
                    metadata=normalized_meta,
                    page_number=chunk.page_number,
                    start_char=chunk.start_char,
                    end_char=chunk.end_char,
                )
            )
            vector_docs.append(
                {
                    "content": self._chunk_embed_text(
                        raw_body=raw_body,
                        embed_text=embed_text,
                        meta=normalized_meta,
                        document_title=document_title,
                        flags=flags,
                    ),
                    "metadata": normalized_meta,
                }
            )
            extra_vector_docs.extend(
                self._chunk_extra_vector_docs(
                    meta=normalized_meta,
                    chunk_id=chunk_id,
                    field_aware_enabled=flags["field_aware_enabled"],
                )
            )
        return normalized_chunks, vector_docs, extra_vector_docs, chunk_ids

    def _index_chunk_vectors_with_tracking(
        self,
        *,
        context: dict[str, Any],
        document_id: UUID,
        tenant_id: UUID,
        vector_docs: list[dict[str, Any]],
        extra_vector_docs: list[dict[str, Any]],
        vector_enabled: bool,
    ) -> list[str]:
        self._track_document_channel(
            document=context["db_document"],
            channel="vector",
            status=DOCUMENT_INDEX_CHANNEL_PROCESSING if vector_enabled else DOCUMENT_INDEX_CHANNEL_DISABLED,
            increment_attempt=vector_enabled,
        )
        try:
            vector_ids = self._index_chunk_vectors(
                vector_docs,
                document_id=document_id,
                tenant_id=tenant_id,
                enable_vectors=vector_enabled,
                embedding_runtime=context["embedding_runtime"],
            )
        except Exception as exc:
            self._track_document_channel(
                document=context["db_document"],
                channel="vector",
                status=DOCUMENT_INDEX_CHANNEL_ERROR,
                error=str(exc)[:2000],
            )
            raise
        if extra_vector_docs and vector_enabled:
            try:
                self._index_chunk_vectors(
                    extra_vector_docs,
                    document_id=document_id,
                    tenant_id=tenant_id,
                    enable_vectors=True,
                    embedding_runtime=context["embedding_runtime"],
                )
            except Exception as exc:
                logger.debug(_INDEXER_FALLBACK_LOG_MESSAGE, exc)
        self._track_document_channel(
            document=context["db_document"],
            channel="vector",
            status=DOCUMENT_INDEX_CHANNEL_READY if vector_enabled else DOCUMENT_INDEX_CHANNEL_DISABLED,
        )
        return vector_ids

    def _update_bm25_with_tracking(
        self,
        *,
        context: dict[str, Any],
        db_chunks: list[DocumentChunk],
        tenant_id: UUID,
        document_id: UUID,
        default_source: str,
        bm25_enabled: bool,
    ) -> None:
        self._track_document_channel(
            document=context["db_document"],
            channel="bm25",
            status=DOCUMENT_INDEX_CHANNEL_PROCESSING if bm25_enabled else DOCUMENT_INDEX_CHANNEL_DISABLED,
            increment_attempt=bm25_enabled,
        )
        try:
            self._update_bm25_for_chunks(
                db_chunks=db_chunks,
                tenant_id=tenant_id,
                document_id=document_id,
                default_source=default_source,
                enable_bm25=bm25_enabled,
            )
        except Exception as exc:
            self._track_document_channel(
                document=context["db_document"],
                channel="bm25",
                status=DOCUMENT_INDEX_CHANNEL_ERROR if bm25_enabled else DOCUMENT_INDEX_CHANNEL_DISABLED,
                error=str(exc)[:2000] if bm25_enabled else None,
            )
            logger.warning("Failed to update BM25 index incrementally: %s", exc)
            return
        self._track_document_channel(
            document=context["db_document"],
            channel="bm25",
            status=DOCUMENT_INDEX_CHANNEL_READY if bm25_enabled else DOCUMENT_INDEX_CHANNEL_DISABLED,
        )

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
        context = self._resolve_chunk_index_context(tenant_id=tenant_id, document_id=document_id)
        source = str(default_source or "").strip() or "unknown"
        total_characters = sum(len(c.content or "") for c in chunks)
        vector_enabled = self._resolve_chunk_vector_enabled(options)
        bm25_enabled = self._resolve_bm25_enabled(options)
        _enforce_embedding_quota_gate(
            self._db,
            tenant_id=tenant_id,
            document_id=document_id,
            additional_chars=int(total_characters or 0),
        )
        flags = self._chunk_index_option_flags(options)
        prepared_chunks = self._prepare_chunk_index_inputs(
            document_id=document_id,
            tenant_id=tenant_id,
            chunks=chunks,
            source=source,
            context=context,
            flags=flags,
        )
        normalized_chunks, vector_docs, extra_vector_docs, chunk_ids = self._build_chunk_vector_payloads(
            prepared_chunks=prepared_chunks,
            document_title=context["document_title"],
            flags=flags,
        )
        vector_ids = self._index_chunk_vectors_with_tracking(
            context=context,
            document_id=document_id,
            tenant_id=tenant_id,
            vector_docs=vector_docs,
            extra_vector_docs=extra_vector_docs,
            vector_enabled=vector_enabled,
        )
        db_chunks = self._persist_document_chunks(
            document_id=document_id,
            tenant_id=tenant_id,
            dataset_id=context["dataset_uuid"],
            chunks=normalized_chunks,
            vector_ids=vector_ids,
            chunk_ids=chunk_ids,
            commit=commit,
        )
        self._update_bm25_with_tracking(
            context=context,
            db_chunks=db_chunks,
            tenant_id=tenant_id,
            document_id=document_id,
            default_source=default_source,
            bm25_enabled=bm25_enabled,
        )

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

    def _tracked_document_for_events(self, *, tenant_id: UUID, events: Sequence[EventInput]) -> DBDocument | None:
        document_ids = {item.document_id for item in events if item.document_id is not None}
        if len(document_ids) != 1:
            return None
        return self._load_document_for_channel_tracking(tenant_id=tenant_id, document_id=next(iter(document_ids)))

    def _normalized_event_pipeline_hash(self, refs: dict[str, Any]) -> str | None:
        raw_pipeline_hash = refs.get("pipeline_hash")
        if not isinstance(raw_pipeline_hash, str):
            return None
        pipeline_hash = raw_pipeline_hash.strip() or None
        if pipeline_hash and len(pipeline_hash) > 200:
            return pipeline_hash[:200]
        return pipeline_hash

    def _event_link_extra(self, *, ent: Any, link_extra_data: dict[str, Any]) -> dict[str, Any]:
        link_extra = dict(link_extra_data or {})
        evidence_quote = (ent.evidence_quote or "").strip() if hasattr(ent, "evidence_quote") else ""
        if evidence_quote:
            link_extra["evidence_quote"] = evidence_quote[:240]
        evidence_source = (ent.evidence_source or "").strip() if hasattr(ent, "evidence_source") else ""
        if evidence_source:
            link_extra["evidence_source"] = evidence_source
        for field_name in ("evidence_start_char", "evidence_end_char"):
            value = getattr(ent, field_name, None) if hasattr(ent, field_name) else None
            if value is None:
                continue
            try:
                link_extra[field_name] = int(value)
            except Exception as exc:
                logger.debug(_INDEXER_FALLBACK_LOG_MESSAGE, exc)
        return link_extra

    def _entity_for_event(
        self,
        *,
        tenant_id: UUID,
        ent: Any,
        entity_cache: dict[tuple[str, str, str], KgEntity],
    ) -> KgEntity | None:
        name = ent.name.strip()
        if not name:
            return None
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
        return entity_obj

    def _materialize_index_events(
        self,
        *,
        tenant_id: UUID,
        events: Sequence[EventInput],
    ) -> tuple[list[KgSourceEvent], dict[tuple[str, str, str], KgEntity]]:
        entity_cache: dict[tuple[str, str, str], KgEntity] = {}
        db_events: list[KgSourceEvent] = []
        for item in events:
            refs = item.references if isinstance(getattr(item, "references", None), dict) else {}
            event_obj = KgSourceEvent(
                tenant_id=tenant_id,
                pipeline_hash=self._normalized_event_pipeline_hash(refs),
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
                entity_obj = self._entity_for_event(tenant_id=tenant_id, ent=ent, entity_cache=entity_cache)
                if entity_obj is None:
                    continue
                self._db.add(
                    KgEventEntity(
                        event=event_obj,
                        entity=entity_obj,
                        weight=1.0,
                        role=ent.role,
                        extra_data=(self._event_link_extra(ent=ent, link_extra_data=link_extra_data) or None),
                    )
                )
        return db_events, entity_cache

    def _track_index_vector_channel(
        self,
        *,
        document: DBDocument | None,
        channel: str,
        enabled: bool,
        items: Sequence[Any],
        candidates: Sequence[Any],
        writer,
        failure_error: str,
        commit: bool,
    ) -> list[str]:
        if not commit:
            return []
        if not enabled:
            self._track_document_channel(document=document, channel=channel, status=DOCUMENT_INDEX_CHANNEL_DISABLED)
            return []
        self._track_document_channel(
            document=document,
            channel=channel,
            status=DOCUMENT_INDEX_CHANNEL_PROCESSING,
            increment_attempt=True,
        )
        if not candidates:
            self._track_document_channel(document=document, channel=channel, status=DOCUMENT_INDEX_CHANNEL_SKIPPED)
            return []
        vector_ids = writer(list(items))
        success = len(vector_ids) == len(candidates)
        self._track_document_channel(
            document=document,
            channel=channel,
            status=DOCUMENT_INDEX_CHANNEL_READY if success else DOCUMENT_INDEX_CHANNEL_ERROR,
            error=None if success else failure_error,
        )
        return vector_ids

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
        db_events, entity_cache = self._materialize_index_events(tenant_id=tenant_id, events=events)
        tracked_document = self._tracked_document_for_events(tenant_id=tenant_id, events=events)
        event_vector_enabled = self._resolve_event_vector_enabled(options)
        entity_vector_enabled = self._resolve_entity_vector_enabled(options)

        if commit:
            self._db.commit()
        else:
            self._db.flush()

        event_vector_ids = self._track_index_vector_channel(
            document=tracked_document,
            channel="event_vector",
            enabled=event_vector_enabled,
            items=db_events,
            candidates=[event for event in db_events if getattr(event, "content_vector", None)],
            writer=self._index_event_vectors,
            failure_error="event_vector_write_failed",
            commit=commit,
        )
        entity_vector_ids = self._track_index_vector_channel(
            document=tracked_document,
            channel="entity_vector",
            enabled=entity_vector_enabled,
            items=list(entity_cache.values()),
            candidates=[entity for entity in entity_cache.values() if getattr(entity, "vector", None)],
            writer=self._index_entity_vectors,
            failure_error="entity_vector_write_failed",
            commit=commit,
        )

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
        except DatasetScopedEmbeddingRuntimeResolutionError as exc:
            if "cleanup target ambiguous" in str(exc) and not strict:
                logger.warning("Skipping ambiguous dataset-scoped vector cleanup: %s", exc)
            else:
                logger.warning("Failed to delete dataset-scoped vectors: %s", exc)
                failures.append(exc)
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

    def _orphan_entity_query(self, *, tenant_id: UUID):
        rel_as_subject = aliased(KgRelation)
        rel_as_object = aliased(KgRelation)
        return (
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

    def _delete_orphan_entity_batch(self, *, orphan_ids: list[UUID], commit: bool, strict: bool) -> None:
        try:
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
        except Exception:
            if commit and hasattr(self._db, "rollback"):
                self._db.rollback()
            raise

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
        q = self._orphan_entity_query(tenant_id=tenant_id)
        if entity_ids:
            entity_ids_norm = [eid for eid in (_safe_uuid(x) for x in entity_ids) if eid is not None]
            if not entity_ids_norm:
                return 0
            q = q.filter(KgEntity.id.in_(entity_ids_norm))
        batch_size = max(1, _vector_write_batch_size())
        last_entity_id: UUID | None = None
        deleted = 0
        while True:
            batch_query = q
            if last_entity_id is not None:
                batch_query = batch_query.filter(KgEntity.id > last_entity_id)
            batch_query = batch_query.order_by(KgEntity.id).limit(batch_size)
            orphan_ids = [row[0] for row in batch_query.all() if row and row[0]]
            if not orphan_ids:
                break
            self._delete_orphan_entity_batch(orphan_ids=orphan_ids, commit=commit, strict=strict)
            deleted += len(orphan_ids)
            last_entity_id = orphan_ids[-1]

        return deleted

    def _event_batch_ids(self, query: Any, *, last_id: UUID | None, batch_size: int) -> list[UUID]:
        query_ids = query.with_entities(KgSourceEvent.id)
        if last_id is not None:
            query_ids = query_ids.filter(KgSourceEvent.id > last_id)
        query_ids = query_ids.order_by(KgSourceEvent.id).limit(batch_size)
        return [row[0] for row in query_ids.all() if row and row[0]]

    def _candidate_entity_ids_for_events(self, *, event_ids: list[UUID], prune_orphan_entities: bool) -> list[UUID]:
        if not prune_orphan_entities:
            return []
        return [
            row[0]
            for row in (
                self._db.query(KgEventEntity.entity_id).filter(KgEventEntity.event_id.in_(event_ids)).distinct().all()
            )
            if row and row[0]
        ]

    def _delete_event_index_batch(
        self,
        *,
        tenant_id: UUID,
        event_ids: list[UUID],
        candidate_entity_ids: list[UUID],
        commit: bool,
        prune_orphan_entities: bool,
        strict: bool,
    ) -> tuple[int, int]:
        try:
            try:
                self._event_vector.delete([str(ev_id) for ev_id in event_ids])
            except Exception as exc:
                logger.warning("Failed to delete KG event vectors: %s", exc)
                if strict:
                    raise
            batch_deleted = int(
                self._db.query(KgSourceEvent).filter(KgSourceEvent.id.in_(event_ids)).delete(synchronize_session=False)
                or 0
            )
            if commit or candidate_entity_ids:
                self._db.flush()
            batch_pruned = 0
            if prune_orphan_entities and candidate_entity_ids:
                batch_pruned = int(
                    self.prune_orphan_entities(
                        tenant_id=tenant_id,
                        entity_ids=candidate_entity_ids,
                        commit=False,
                        strict=strict,
                    )
                )
            if commit:
                self._db.commit()
            elif not candidate_entity_ids:
                self._db.flush()
            return batch_deleted, batch_pruned
        except Exception:
            if commit and hasattr(self._db, "rollback"):
                self._db.rollback()
            raise

    def _delete_event_indexes(
        self,
        *,
        tenant_id: UUID,
        query,
        commit: bool,
        prune_orphan_entities: bool,
        strict: bool,
    ) -> dict[str, int]:
        batch_size = max(1, _vector_write_batch_size())
        deleted = 0
        pruned = 0
        last_event_id: UUID | None = None

        while True:
            event_ids = self._event_batch_ids(query, last_id=last_event_id, batch_size=batch_size)
            if not event_ids:
                break
            candidate_entity_ids = self._candidate_entity_ids_for_events(
                event_ids=event_ids,
                prune_orphan_entities=prune_orphan_entities,
            )
            batch_deleted, batch_pruned = self._delete_event_index_batch(
                tenant_id=tenant_id,
                event_ids=event_ids,
                candidate_entity_ids=candidate_entity_ids,
                commit=commit,
                prune_orphan_entities=prune_orphan_entities,
                strict=strict,
            )
            deleted += batch_deleted
            pruned += batch_pruned
            last_event_id = event_ids[-1]

        return {"events_deleted": deleted, "entities_pruned": pruned}

    def rebuild_chunk_indexes(
        self,
        *,
        tenant_id: UUID,
        document_ids: list[UUID] | None = None,
    ) -> None:
        if not bool(getattr(settings, "BM25_INDEX_ENABLED", True)):
            return
        count = hybrid_retriever.rebuild_bm25_index_for_operational_scope(
            self._db,
            tenant_id=tenant_id,
            document_ids=document_ids,
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
            self._db.query(KgEventEntity.entity_id).filter(KgEventEntity.event_id.in_(event_ids)).distinct().all()
        )
        entity_ids = [row[0] for row in entity_id_rows if row and row[0]]
        if not entity_ids:
            return

        entities = self._db.query(KgEntity).filter(KgEntity.tenant_id == tenant_id, KgEntity.id.in_(entity_ids)).all()
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
            self._db.query(DBDocument).filter(DBDocument.tenant_id == tenant_id, DBDocument.id == document_id).first()
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
        page_number = (
            record.page_number if record.page_number is not None else meta.get("page") or meta.get("page_number")
        )
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
        adapter: Any = None
        ids: list[str | None] = []
        try:
            embeddings = create_embeddings_for_runtime(runtime)
            adapter = get_milvus_adapter(resolve_collection_name(runtime.collection_name))
            max_retries, backoff = _vector_write_retry_policy()
            batch_size = max(1, _vector_write_batch_size())
            for batch_start in range(0, len(docs), batch_size):
                batch_docs = docs[batch_start : batch_start + batch_size]
                items = [
                    self._document_vector_item(
                        doc=doc,
                        document_id=document_id,
                        tenant_id=tenant_id,
                        index=batch_start + index,
                    )
                    for index, doc in enumerate(batch_docs)
                ]
                vectors = embeddings.embed_documents([str(doc.get("content") or "") for doc in batch_docs])
                batch_ids: list[str | None] = []
                attempt_backoff = backoff
                for attempt in range(max_retries + 1):
                    try:
                        batch_ids = adapter.add_vectors(
                            items,
                            embeddings=vectors,
                            batch_size=batch_size,
                            upsert=True,
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
                            backoff=attempt_backoff,
                            error=exc,
                        )
                        time.sleep(attempt_backoff)
                        attempt_backoff *= 2
                if len(batch_ids) != len(batch_docs):
                    raise ValueError(f"vector ids length {len(batch_ids)} != docs length {len(batch_docs)}")
                ids.extend(batch_ids)

            return ids
        except Exception as exc:
            logger.warning(
                "Dataset-scoped vector write failed collection=%s space=%s: %s",
                runtime.collection_name,
                runtime.embedding_space_hash,
                str(exc)[:200],
            )
            # Batched writes are not atomic: earlier batches are already committed to the
            # collection when a later batch fails. The caller treats this as a failed write
            # and will retry or mark the document failed, so drop the partial vectors instead
            # of leaving orphans that no chunk row points at.
            self._rollback_partial_dataset_scoped_vectors(
                adapter,
                ids,
                document_id=document_id,
                collection_name=runtime.collection_name,
            )
            raise

    def _rollback_partial_dataset_scoped_vectors(
        self,
        adapter: Any,
        written_ids: list[str | None],
        *,
        document_id: UUID,
        collection_name: str,
    ) -> None:
        stale_ids = [str(vector_id) for vector_id in written_ids if vector_id]
        if adapter is None or not stale_ids:
            return
        try:
            adapter.delete(stale_ids)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to roll back %s partial dataset-scoped vectors document=%s collection=%s: %s",
                len(stale_ids),
                str(document_id),
                collection_name,
                str(exc)[:200],
            )

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

        hybrid_retriever.upsert_bm25_documents(bm25_docs, tenant_id=tenant_id, db=self._db)

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
