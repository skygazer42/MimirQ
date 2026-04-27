"""
Indexing service implementation.

Provides a unified interface for document chunk and event indexing.
"""
import hashlib
import logging
import time
import uuid
from collections.abc import Iterable, Sequence
from typing import Any
from uuid import UUID

from langchain_core.documents import Document as LCDocument
from sqlalchemy.orm import Session, aliased

from app.core.config import settings
from app.core.constants import EmbeddingProviders
from app.models.document import Document as DBDocument
from app.models.document import DocumentChunk
from app.rag.chunking.utils.hierarchical import apply_sequence_hierarchy_metadata
from app.rag.core.metadata import ensure_hierarchy_overlay_metadata, normalize_image_metadata
from app.rag.embedding import create_langchain_embeddings_from_config
from app.rag.embedding.utils import current_embedding_space_hash, embedding_space_hash_for_config
from app.rag.kg.models import KgEntity, KgEventEntity, KgRelation, KgSourceEvent
from app.rag.kg.provenance import build_event_entity_provenance
from app.rag.preprocessing.normalization import normalize_text
from app.rag.retriever import hybrid_retriever
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

_shadow_vector_writer_sig: str | None = None
_shadow_vector_writer: tuple[Any, Any, str] | None = None  # (embeddings, adapter, embedding_space_hash)
_SHADOW_VECTOR_WRITE_EVENT = "ingest.shadow_vector_write"


def _resolve_shadow_vector_writer() -> tuple[Any, Any, str] | None:
    """
    Best-effort resolve (embeddings, milvus_adapter, shadow_space_hash) for dual-write.

    This is used by Gap5 embedding blue-green migrations: when enabled, ingestion writes
    vectors into both the primary collection (settings.MILVUS_COLLECTION_NAME) and the
    shadow collection (settings.MILVUS_SHADOW_COLLECTION_NAME) using a potentially
    different embedding model.
    """
    if not bool(getattr(settings, "EMBEDDING_SHADOW_ENABLED", False)):
        return None

    if str(getattr(settings, "VECTOR_BACKEND", "milvus") or "milvus").strip().lower() != "milvus":
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
    sig = f"{mapped_provider}|{shadow_model}|{base_url}|{shadow_collection}"

    global _shadow_vector_writer_sig, _shadow_vector_writer
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
        _shadow_vector_writer_sig = sig
        _shadow_vector_writer = None
        return None

    try:
        adapter = get_milvus_adapter(resolve_collection_name(shadow_collection))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Shadow Milvus adapter init failed; dual-write disabled: %s", str(exc)[:200])
        _shadow_vector_writer_sig = sig
        _shadow_vector_writer = None
        return None

    try:
        shadow_space = embedding_space_hash_for_config(
            provider=mapped_provider,
            model=shadow_model,
            base_url=base_url,
            length=16,
        )
    except Exception:
        shadow_space = ""

    _shadow_vector_writer_sig = sig
    _shadow_vector_writer = (emb, adapter, shadow_space)
    return _shadow_vector_writer


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

    items: list[dict[str, Any]] = []
    texts: list[str] = []
    for doc in docs:
        meta0 = doc.get("metadata") if isinstance(doc, dict) else None
        meta = dict(meta0 or {}) if isinstance(meta0, dict) else {}
        chunk_id = str(meta.get("chunk_id") or "").strip()
        if not chunk_id:
            continue
        meta["embedding_space_hash"] = shadow_space
        items.append({"id": chunk_id, "content": str(doc.get("content") or ""), "metadata": meta})
        texts.append(str(doc.get("content") or ""))

    if not items:
        return

    try:
        vecs = embeddings.embed_documents(texts)
    except Exception as exc:  # noqa: BLE001
        log_metrics(
            {
                "event": _SHADOW_VECTOR_WRITE_EVENT,
                "ok": False,
                "reason": "embed_failed",
                "tenant_id": str(tenant_id),
                "document_id": str(document_id),
                "count": int(len(items)),
                "error": str(exc)[:200],
            }
        )
        return

    try:
        batch_size = int(getattr(settings, "VECTOR_WRITE_BATCH_SIZE", 256) or 256)
        adapter.add_vectors(items, embeddings=vecs, batch_size=batch_size, upsert=True)
        log_metrics(
            {
                "event": _SHADOW_VECTOR_WRITE_EVENT,
                "ok": True,
                "tenant_id": str(tenant_id),
                "document_id": str(document_id),
                "count": int(len(items)),
            }
        )
    except Exception as exc:  # noqa: BLE001
        log_metrics(
            {
                "event": _SHADOW_VECTOR_WRITE_EVENT,
                "ok": False,
                "reason": "milvus_write_failed",
                "tenant_id": str(tenant_id),
                "document_id": str(document_id),
                "count": int(len(items)),
                "error": str(exc)[:200],
            }
        )
        return


def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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


def _derive_document_title(filename: Any, doc_metadata: Any, *, max_chars: int = 120) -> str | None:
    """
    Best-effort derive a human-ish document title for embedding prefixes.

    Prefer explicit metadata when available; fall back to filename stem.
    """
    title: str | None = None
    if isinstance(doc_metadata, dict):
        for key in ("document_title", "doc_title", "title", "name"):
            v = doc_metadata.get(key)
            if isinstance(v, str) and v.strip():
                title = v.strip()
                break

    if not title:
        raw = str(filename or "").strip()
        if raw:
            try:
                from pathlib import Path

                base = Path(raw).name
                stem = Path(base).stem
                title = stem or base
            except Exception:
                title = raw

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
    if header is None:
        header_list = meta.get("outline_path") or meta.get("header_path_list") or None
        if isinstance(header_list, list) and header_list:
            header = " / ".join([str(x).strip() for x in header_list if str(x).strip()][:10])

    header_str = _coerce_short_text(header, max_chars=280)
    return header_str


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
    if not bool(getattr(settings, "CONTEXTUAL_RETRIEVAL_LLM_ENRICHMENT_ENABLED", False)):
        return None
    text = str(raw_body or "").strip()
    if not text:
        return None

    max_input_chars = max(0, int(getattr(settings, "CONTEXTUAL_RETRIEVAL_LLM_MAX_INPUT_CHARS", 2400) or 2400))
    max_summary_chars = max(0, int(getattr(settings, "CONTEXTUAL_RETRIEVAL_LLM_MAX_SUMMARY_CHARS", 180) or 180))
    if max_summary_chars <= 0:
        return None
    sample = text[:max_input_chars] if max_input_chars else text

    section = _extract_heading_for_embedding(meta) or ""
    title = str(document_title or "").strip()
    try:
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
        summary = str(getattr(resp, "content", "") or "").strip()
    except Exception:
        return None

    if not summary:
        return None
    if len(summary) > max_summary_chars:
        summary = summary[:max_summary_chars].rstrip()
    return summary or None


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
        file_type_str: str | None = None
        document_title: str | None = None
        embedding_space = current_embedding_space_hash()
        try:
            row = (
                self._db.query(DBDocument.dataset_id, DBDocument.file_type, DBDocument.filename, DBDocument.doc_metadata)
                .filter(DBDocument.tenant_id == tenant_id, DBDocument.id == document_id)
                .first()
            )
            if row:
                ds_id, ft, fn, doc_meta = row
                if ds_id is not None:
                    dataset_id_str = str(ds_id)
                if ft is not None:
                    file_type_str = str(ft)
                document_title = _derive_document_title(fn, doc_meta)
        except Exception:
            dataset_id_str = None
            file_type_str = None
            document_title = None

        source = str(default_source or "").strip() or "unknown"
        total_characters = sum(len(c.content or "") for c in chunks)

        # Tenant quotas (Wave22-T094): best-effort rolling cap on indexing/embedding volume.
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
        except Exception:
            # Fail open if quota checks are unavailable (misconfig/DB issues).
            pass

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
            if dataset_id_str:
                meta.setdefault("dataset_id", dataset_id_str)
            meta.setdefault("source", source)
            if file_type_str and not meta.get("file_type"):
                meta["file_type"] = file_type_str
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
            normalized_chunks.append(
                ChunkInput(
                    content=c.content,
                    metadata=meta,
                    page_number=c.page_number,
                    start_char=c.start_char,
                    end_char=c.end_char,
                )
            )
            raw_body = c.content or ""
            embed_text = raw_body
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
                        embed_text = prefix + "\n" + raw_body
                except Exception:
                    # Fail open: contextual prefixes are best-effort.
                    pass
            if embedding_prefix_enabled:
                embed_text = _build_embedding_text(embed_text, meta)
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
                    extra_vector_docs.append({"content": f"[Title] {title}", "metadata": meta_t})

                heading = _extract_heading_for_embedding(meta)
                if heading:
                    meta_h = dict(meta)
                    meta_h["chunk_id"] = f"{chunk_id}:heading"
                    extra_vector_docs.append({"content": f"[Heading] {heading}", "metadata": meta_h})

        vector_ids = self._index_chunk_vectors(
            vector_docs,
            document_id=document_id,
            tenant_id=tenant_id,
            enable_vectors=self._resolve_chunk_vector_enabled(options),
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
                )
            except Exception:
                pass
        db_chunks = self._persist_document_chunks(
            document_id=document_id,
            tenant_id=tenant_id,
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
                    except Exception:
                        pass
                if hasattr(ent, "evidence_end_char") and ent.evidence_end_char is not None:
                    try:
                        link_extra["evidence_end_char"] = int(ent.evidence_end_char)
                    except Exception:
                        pass

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
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("name") or "").strip()
            if not name:
                continue
            normalized_name = str(raw.get("normalized_name") or name).strip()
            if not normalized_name:
                continue
            type_ = str(raw.get("type") or "unknown").strip() or "unknown"

            desc_raw = raw.get("description")
            description = str(desc_raw).strip() if isinstance(desc_raw, str) else None

            vector = raw.get("vector") if isinstance(raw.get("vector"), list) else None
            extra_data = raw.get("extra_data") if isinstance(raw.get("extra_data"), dict) else None

            key = (normalized_name, type_)
            ent = unique.get(key)
            if ent is None:
                ent = self._get_or_create_entity(
                    tenant_id=tenant_id,
                    name=name,
                    normalized_name=normalized_name,
                    type_=type_,
                    description=description,
                )
                unique[key] = ent

            # Best-effort enrichment (avoid clobbering user edits).
            if description and not getattr(ent, "description", None):
                ent.description = description
            if vector and not getattr(ent, "vector", None):
                ent.vector = vector
            if extra_data and not getattr(ent, "extra_data", None):
                ent.extra_data = extra_data

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

    def delete_chunk_indexes(self, *, tenant_id: UUID, document_id: UUID) -> None:
        try:
            get_vector_store().delete_by_document_id(document_id, tenant_id=tenant_id)
        except Exception as exc:
            logger.warning("Failed to delete vectors: %s", exc)

        try:
            hybrid_retriever.remove_document_from_bm25_index(document_id, tenant_id=tenant_id)
        except Exception as exc:
            logger.warning("Failed to update BM25 index after deletion: %s", exc)

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

    def delete_event_indexes(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        commit: bool = True,
        prune_orphan_entities: bool = False,
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
        )

    def delete_event_indexes_for_chunks(
        self,
        *,
        tenant_id: UUID,
        chunk_ids: Sequence[UUID],
        commit: bool = True,
        exclude_event_ids: Sequence[UUID] | None = None,
        prune_orphan_entities: bool = False,
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
        )

    def prune_orphan_entities(
        self,
        *,
        tenant_id: UUID,
        entity_ids: Sequence[UUID] | None = None,
        commit: bool = True,
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

        deleted = int(query.delete(synchronize_session=False) or 0)
        if commit:
            self._db.commit()
        else:
            self._db.flush()

        pruned = 0
        if prune_orphan_entities and candidate_entity_ids:
            pruned = int(self.prune_orphan_entities(tenant_id=tenant_id, entity_ids=candidate_entity_ids, commit=commit))

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

    def _index_chunk_vectors(
        self,
        docs: list[dict],
        *,
        document_id: UUID,
        tenant_id: UUID,
        enable_vectors: bool,
    ) -> list[str | None]:
        if not docs:
            return []

        if not enable_vectors:
            return [None] * len(docs)

        vector_store = get_vector_store()
        try:
            batch_size = int(getattr(settings, "VECTOR_WRITE_BATCH_SIZE", 256) or 256)
            max_retries = int(getattr(settings, "VECTOR_WRITE_MAX_RETRIES", 1) or 1)
            backoff = float(getattr(settings, "VECTOR_WRITE_RETRY_BACKOFF_SEC", 0.5) or 0.5)

            out: list[str | None] = []
            for i in range(0, len(docs), batch_size):
                batch = docs[i : i + batch_size]
                last_exc: Exception | None = None
                for attempt in range(max_retries + 1):
                    try:
                        out.extend(list(vector_store.add_documents(batch, document_id, tenant_id)))
                        # Best-effort dual-write to the shadow collection (Gap5).
                        _dual_write_shadow_vectors_best_effort(batch, document_id=document_id, tenant_id=tenant_id)
                        last_exc = None
                        break
                    except Exception as exc:  # noqa: BLE001
                        last_exc = exc
                        if attempt < max_retries:
                            log_metrics(
                                {
                                    "event": "ingest.vector_write.retry",
                                    "tenant_id": str(tenant_id),
                                    "document_id": str(document_id),
                                    "attempt": attempt + 1,
                                    "max_retries": max_retries + 1,
                                    "batch_size": len(batch),
                                    "backoff_sec": round(float(backoff), 3),
                                    "error": str(exc)[:200],
                                }
                            )
                            logger.warning(
                                "Vector write failed (attempt %s/%s), retrying in %.2fs: %s",
                                attempt + 1,
                                max_retries + 1,
                                backoff,
                                str(exc)[:200],
                            )
                            time.sleep(backoff)
                            backoff *= 2
                        else:
                            raise

                if last_exc is not None:
                    raise last_exc

            if len(out) != len(docs):
                raise ValueError(f"vector ids length {len(out)} != docs length {len(docs)}")
            return out
        except Exception as exc:
            logger.warning("Failed to store vectors: %s", exc)
            logger.warning("Proceeding without vector ids; BM25-only retrieval will still work.")
            return [None] * len(docs)

    def _persist_document_chunks(
        self,
        *,
        document_id: UUID,
        tenant_id: UUID,
        chunks: list[ChunkInput],
        vector_ids: list[str | None] | None = None,
        chunk_ids: list[UUID] | None = None,
        commit: bool = True,
    ) -> list[DocumentChunk]:
        if not chunks:
            return []

        if vector_ids is None:
            vector_ids = [None] * len(chunks)
        if len(vector_ids) != len(chunks):
            raise ValueError(f"vector_ids length {len(vector_ids)} != chunks length {len(chunks)}")

        if chunk_ids is None:
            chunk_ids = [uuid.uuid4() for _ in chunks]
        if len(chunk_ids) != len(chunks):
            raise ValueError(f"chunk_ids length {len(chunk_ids)} != chunks length {len(chunks)}")

        db_chunks: list[DocumentChunk] = []
        total_chunks = len(chunks)
        for idx, (chunk, vector_id, chunk_id) in enumerate(zip(chunks, vector_ids, chunk_ids, strict=False)):
            meta = dict(chunk.metadata or {})
            normalize_image_metadata(meta)
            meta.setdefault("tenant_id", str(tenant_id))
            meta.setdefault("document_id", str(document_id))
            meta.setdefault("chunk_index", idx)
            # Versioning: keep a stable composite key so retrieval can filter the active
            # pipeline per document across multi-doc queries.
            pipeline_hash = str(meta.get("pipeline_hash") or "").strip()
            if pipeline_hash:
                meta.setdefault("doc_pipeline_key", f"{document_id}:{pipeline_hash}")
            meta = _ensure_chunk_metadata(
                meta,
                content=chunk.content or "",
                document_id=document_id,
                chunk_index=idx,
                total_chunks=total_chunks,
            )
            meta["chunk_id"] = str(chunk_id)
            page_number = (
                _safe_int(chunk.page_number)
                if chunk.page_number is not None
                else _safe_int(meta.get("page") or meta.get("page_number"))
            )
            start_char = _safe_int(chunk.start_char) if chunk.start_char is not None else _safe_int(meta.get("start_char"))
            end_char = _safe_int(chunk.end_char) if chunk.end_char is not None else _safe_int(meta.get("end_char"))

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
            bm25_docs.append(LCDocument(page_content=db_chunk.content, id=str(db_chunk.id), metadata=meta))

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
            if not ev.content_vector:
                continue
            refs = ev.references if isinstance(getattr(ev, "references", None), dict) else {}
            embeddings.append(list(ev.content_vector))
            pipeline_hash = str(getattr(ev, "pipeline_hash", None) or refs.get("pipeline_hash") or "").strip() or None
            if pipeline_hash and len(pipeline_hash) > 200:
                pipeline_hash = pipeline_hash[:200]
            meta: dict[str, Any] = {
                "tenant_id": str(ev.tenant_id),
                "document_id": str(ev.document_id) if ev.document_id else "",
                "chunk_id": str(ev.chunk_id) if ev.chunk_id else "",
                "title": ev.title,
                "summary": ev.summary,
                "index_kind": IndexKind.EVENT.value,
            }
            if pipeline_hash:
                meta["pipeline_hash"] = pipeline_hash
                if ev.document_id:
                    meta["doc_pipeline_key"] = f"{ev.document_id}:{pipeline_hash}"
            if isinstance(refs, dict):
                for k in (
                    "chunk_index",
                    "page",
                    "start_char",
                    "end_char",
                    "chunk_key",
                    "content_hash",
                    "content_len",
                    "source",
                ):
                    v = refs.get(k)
                    if v is None:
                        continue
                    meta[k] = v
            items.append(
                {
                    "id": str(ev.id),
                    "content": ev.content,
                    "metadata": meta,
                }
            )

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
