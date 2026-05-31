"""
Milvus vector store service

Provides two usage modes:
1. Singleton mode - Used for document vector storage (fixed collection)
2. Multi-instance mode - Used for KG entities/events (customizable collection)
"""

import re
import threading
from typing import Any, Optional
from uuid import UUID

from app.core.config import settings
from app.core.constants import EmbeddingProviders, MilvusConfig
from app.rag.core.filters import match_metadata_filter as _match_metadata_filter
from app.rag.core.logging import get_logger

logger = get_logger("storage.vector.milvus")

_MILVUS_MAX_VARCHAR_BYTES = 65_535
_MILVUS_EXPR_MAX_CHARS = 8000
_MILVUS_EXPR_AND = " and "
_MILVUS_FALLBACK_LOG_MESSAGE = "Ignoring non-critical Milvus fallback failure: %s"
_MILVUS_FIELD_NAME_RE = re.compile(r"^[A-Za-z_]\w*$")
_MILVUS_WARNED_WRITE_COMPAT_FALLBACK = False
_MILVUS_WARNED_SEARCH_EXPR_FALLBACK = False

# Safe allowlist for metadata expr pushdown (must exist in collection schema).
_MILVUS_NUMERIC_FIELDS = frozenset({"chunk_index", "page_number"})
_MILVUS_STRING_FIELDS = frozenset(
    {
        "tenant_id",
        "dataset_id",
        "document_id",
        "embedding_space_hash",
        "chunk_id",
        # Versioning / rollback (stable composite key).
        "pipeline_hash",
        "doc_pipeline_key",
        "source",
        "file_type",
        "img_id",
        "image_id",
        "image_url",
        # KG (optional; depends on collection schema)
        "index_kind",
        "type",
        "name",
        "title",
    }
)
_MILVUS_ALLOWED_FILTER_FIELDS = _MILVUS_NUMERIC_FIELDS | _MILVUS_STRING_FIELDS

# Document collection (knowledge base chunks) stores a fixed subset of metadata fields.
# Keep this list in sync with MilvusVectorStore.add_documents().
_DOC_VECTOR_METADATA_FIELDS = frozenset(
    {
        "tenant_id",
        "dataset_id",
        "document_id",
        "embedding_space_hash",
        "chunk_index",
        "chunk_id",
        "pipeline_hash",
        "doc_pipeline_key",
        "page_number",
        "source",
        "file_type",
        "img_id",
        "image_id",
        "image_url",
    }
)

# Public-facing aliases commonly used in the retrieval layer.
_MILVUS_FILTER_KEY_ALIASES: dict[str, str] = {
    "page": "page_number",
    "img_url": "image_url",
}


def _sanitize_milvus_metadata_filter(
    metadata_filter: dict[str, Any] | None,
    *,
    allowed_fields: set[str] | None = None,
) -> dict[str, Any]:
    """
    Return a safe, best-effort filter spec that only contains supported keys.

    Notes:
    - Dotted (nested) keys are not supported in Milvus scalar expr and are dropped.
    - This is intentionally conservative: it prevents "missing-field" false negatives when
      callers include rich metadata filters that are only available in Postgres.
    """
    if not metadata_filter or not isinstance(metadata_filter, dict):
        return {}

    allowed = allowed_fields or set(_MILVUS_ALLOWED_FILTER_FIELDS)
    cleaned: dict[str, Any] = {}
    for raw_key, condition in metadata_filter.items():
        if not isinstance(raw_key, str):
            continue
        if "." in raw_key:
            continue
        key = _MILVUS_FILTER_KEY_ALIASES.get(raw_key, raw_key)
        if key not in allowed:
            continue
        if not _MILVUS_FIELD_NAME_RE.match(key):
            continue
        cleaned[key] = condition
    return cleaned


def _coerce_milvus_metadata_value(value: Any) -> Any:
    """Milvus does not support None values for scalar fields."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return bool(value)
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value)
    if isinstance(value, str):
        return value[:_MILVUS_MAX_VARCHAR_BYTES]
    return str(value)[:_MILVUS_MAX_VARCHAR_BYTES]


def _normalize_milvus_metadata_batch(metadatas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ensure consistent keys and Milvus-compatible values across a batch."""
    if not metadatas:
        return []

    schema_meta: dict[str, Any] = {}
    for k, v in (metadatas[0] or {}).items():
        schema_meta[str(k)] = _coerce_milvus_metadata_value(v)

    schema_keys = list(schema_meta.keys())
    normalized: list[dict[str, Any]] = []
    for meta in metadatas:
        normalized_meta = dict(meta or {})
        # Normalize values for known keys first.
        for k in list(normalized_meta.keys()):
            normalized_meta[k] = _coerce_milvus_metadata_value(normalized_meta.get(k))

        # Fill missing schema keys so insert columns remain aligned.
        for k in schema_keys:
            if k in normalized_meta and normalized_meta[k] != "":
                continue
            exemplar = schema_meta.get(k)
            if isinstance(exemplar, bool):
                normalized_meta[k] = False
            elif isinstance(exemplar, int):
                normalized_meta[k] = 0
            elif isinstance(exemplar, float):
                normalized_meta[k] = 0.0
            else:
                normalized_meta[k] = ""
        normalized.append(normalized_meta)

    return normalized


def _escape_milvus_string(value: str) -> str:
    # Milvus expr strings use double quotes; escape minimal set.
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _chunk_in_list_values(
    values: list[str],
    *,
    field: str,
    max_expr_chars: int,
    max_items: int,
) -> list[list[str]]:
    """
    Chunk a list of string values for a Milvus `field in ["..."]` expression.

    Constraints:
    - limit by item count (max_items)
    - limit by expr length (max_expr_chars) (best-effort; avoid server-side rejects)
    """
    safe_field = str(field or "").strip() or "id"
    cap_chars = max(256, int(max_expr_chars or 0))
    cap_items = max(1, int(max_items or 0))

    # Overhead: `field in [` + `]`
    overhead = len(safe_field) + len(' in [""]')

    batches: list[list[str]] = []
    cur: list[str] = []
    cur_len = overhead
    for raw in values or []:
        v = str(raw)
        # Each value contributes: quotes + escaped content + comma+space.
        escaped = _escape_milvus_string(v)
        item_len = len(escaped) + 4  # quotes + comma/space

        # Start a new batch when adding would exceed either cap.
        if cur and (len(cur) >= cap_items or (cur_len + item_len) > cap_chars):
            batches.append(cur)
            cur = []
            cur_len = overhead

        cur.append(v)
        cur_len += item_len

    if cur:
        batches.append(cur)

    return batches


def _milvus_value_expr(field: str, value: Any) -> str | None:
    if field in _MILVUS_NUMERIC_FIELDS:
        try:
            return str(int(value))
        except (TypeError, ValueError):
            return None
    if field in _MILVUS_STRING_FIELDS:
        return f"\"{_escape_milvus_string(str(value))}\""
    return None


def _milvus_in_list_expr(field: str, values: Any) -> str | None:
    if not isinstance(values, (list, tuple, set)):
        return None
    items: list[str] = []
    for v in values:
        expr = _milvus_value_expr(field, v)
        if expr is None:
            continue
        items.append(expr)
    if not items:
        return None
    return f"[{', '.join(items)}]"


def _build_milvus_metadata_expr(metadata_filter: dict[str, Any] | None) -> str | None:
    """Best-effort translation of metadata_filter into Milvus expr (AND semantics)."""
    if not metadata_filter or not isinstance(metadata_filter, dict):
        return None

    parts: list[str] = []
    for key, condition in metadata_filter.items():
        if not isinstance(key, str):
            continue
        if "." in key:
            continue
        key = _MILVUS_FILTER_KEY_ALIASES.get(key, key)
        if key not in _MILVUS_ALLOWED_FILTER_FIELDS:
            continue
        if not _MILVUS_FIELD_NAME_RE.match(key):
            continue

        if isinstance(condition, dict):
            for op, expected in condition.items():
                if op in ("$eq", "$ne"):
                    rhs = _milvus_value_expr(key, expected)
                    if rhs is None:
                        continue
                    parts.append(f"{key} {'==' if op == '$eq' else '!='} {rhs}")
                elif op in ("$gt", "$gte", "$lt", "$lte"):
                    if key not in _MILVUS_NUMERIC_FIELDS:
                        continue
                    rhs = _milvus_value_expr(key, expected)
                    if rhs is None:
                        continue
                    cmp_op = {  # noqa: RUF027
                        "$gt": ">",
                        "$gte": ">=",
                        "$lt": "<",
                        "$lte": "<=",
                    }.get(op)
                    if cmp_op:
                        parts.append(f"{key} {cmp_op} {rhs}")
                elif op in ("$in", "$nin"):
                    rhs = _milvus_in_list_expr(key, expected)
                    if rhs is None:
                        continue
                    parts.append(f"{key} {'in' if op == '$in' else 'not in'} {rhs}")
                else:
                    # Unsupported op (e.g. $contains): skip pushdown for this clause.
                    continue
        else:
            rhs = _milvus_value_expr(key, condition)
            if rhs is None:
                continue
            parts.append(f"{key} == {rhs}")

    if not parts:
        return None
    expr = _MILVUS_EXPR_AND.join(parts)
    if len(expr) > _MILVUS_EXPR_MAX_CHARS:
        return None
    return expr


# ========= Embedding initialization ==========

def _init_embedding_model():
    """Initialize embedding model using app.rag.embedding module."""
    from app.rag.embedding import create_langchain_embeddings_from_config

    provider = (settings.EMBEDDING_PROVIDER or "local").lower()
    logger.info("[*] Loading embedding provider: %s", provider)

    mapped_provider = EmbeddingProviders.PROVIDER_MAP.get(provider, "openai_compatible")
    api_key = settings.EMBEDDING_API_KEY or settings.LLM_API_KEY
    base_url = settings.EMBEDDING_API_BASE or settings.LLM_API_BASE

    return create_langchain_embeddings_from_config(
        provider=mapped_provider,
        model=settings.EMBEDDING_MODEL,
        api_key=api_key or "",
        base_url=base_url or "",
        dimension=None,  # Auto-detect
    )


def _get_milvus_connection_args() -> dict[str, Any]:
    """Get Milvus connection configuration."""
    return {
        "host": settings.MILVUS_HOST,
        "port": str(settings.MILVUS_PORT),
        "user": settings.MILVUS_USER,
        "password": settings.MILVUS_PASSWORD,
    }


def _get_milvus_index_params() -> dict[str, Any]:
    """Get Milvus index configuration."""
    return MilvusConfig.get_index_params()


def _get_milvus_search_params() -> dict[str, Any]:
    """Get Milvus search configuration."""
    return MilvusConfig.get_search_params()


# ========= Generic Milvus adapter ==========

class MilvusAdapter:
    """
    Generic Milvus adapter that supports custom collections.

    Used for KG entity/event vector storage with multiple collections.
    """

    def __init__(
        self,
        collection_name: str,
        vector_field: str = "embedding",
        text_field: str = "content",
    ):
        self.collection_name = collection_name
        self.vector_field = vector_field
        self.text_field = text_field
        self._store = None
        self._embedding_model = None

    def _ensure_store(self):
        if self._store is not None:
            return

        if self._embedding_model is None:
            self._embedding_model = _init_embedding_model()

        from langchain_community.vectorstores import Milvus as LCMilvus

        self._store = LCMilvus(
            embedding_function=self._embedding_model,
            collection_name=self.collection_name,
            connection_args=_get_milvus_connection_args(),
            index_params=_get_milvus_index_params(),
            search_params=_get_milvus_search_params(),
            auto_id=False,
            primary_field="id",
            text_field=self.text_field,
            vector_field=self.vector_field,
        )

    def add_vectors(
        self,
        items: list[dict[str, Any]],
        embeddings: list[list[float]] | None = None,
        *,
        batch_size: int = 1000,
        timeout: float | None = None,
        upsert: bool = True,
        **kwargs: Any,
    ) -> list[str]:
        """
        Batch write vectors (supports directly writing pre-computed embeddings to avoid duplicate embedding).

        Args:
            items: [{"id": str, "content": str, "metadata": dict}]
            embeddings: Optional, pre-computed vectors (List[List[float]]), corresponding to items.
                - When None: LangChain Embeddings auto-generates based on content
                - When not None: directly writes to Milvus (insert/upsert)
            batch_size: write batch size
            timeout: Milvus timeout
            upsert: True uses Milvus upsert; False uses insert

        Returns:
            List of vector IDs
        """
        if not items:
            return []

        self._ensure_store()
        assert self._store is not None

        reserved_fields = {
            getattr(self._store, "_primary_field", "id"),
            getattr(self._store, "_text_field", self.text_field),
            getattr(self._store, "_vector_field", self.vector_field),
        }

        texts: list[str] = []
        metadatas: list[dict[str, Any]] = []
        ids: list[str] = []
        for item in items:
            ids.append(str(item["id"]))
            texts.append((item.get("content") or "")[:65_000])
            meta = dict(item.get("metadata") or {})
            for key in reserved_fields:
                meta.pop(key, None)
            metadatas.append(meta)
        metadatas = _normalize_milvus_metadata_batch(metadatas)

        # Default path: let LangChain generate embeddings then insert.
        if embeddings is None:
            pks = self._store.add_texts(
                texts=texts,
                metadatas=metadatas,
                ids=ids,
                batch_size=batch_size,
                timeout=timeout,
                **kwargs,
            )
            return [str(pk) for pk in pks]

        if len(embeddings) != len(items):
            raise ValueError("embeddings length must match items length")

        from pymilvus import Collection, MilvusException

        # Ensure collection initialized (schema/index/search params/load).
        if not isinstance(getattr(self._store, "col", None), Collection):
            init_kwargs: dict[str, Any] = {"embeddings": embeddings, "metadatas": metadatas}
            partition_names = getattr(self._store, "partition_names", None)
            if partition_names:
                init_kwargs["partition_names"] = partition_names
            replica_number = getattr(self._store, "replica_number", None)
            if replica_number:
                init_kwargs["replica_number"] = replica_number
            store_timeout = getattr(self._store, "timeout", None)
            if store_timeout:
                init_kwargs["timeout"] = store_timeout
            # `_init` is the internal LangChain helper used by `add_texts`.
            self._store._init(**init_kwargs)  # type: ignore[attr-defined]

        # Build insert columns (match LangChain Milvus.insert behavior).
        insert_dict: dict[str, list[Any]] = {
            self._store._text_field: texts,  # type: ignore[attr-defined]
            self._store._vector_field: embeddings,  # type: ignore[attr-defined]
        }
        if not getattr(self._store, "auto_id", False):
            insert_dict[self._store._primary_field] = ids  # type: ignore[attr-defined]

        metadata_field = getattr(self._store, "_metadata_field", None)
        if metadata_field is not None:
            insert_dict[metadata_field] = metadatas
        else:
            fields = getattr(self._store, "fields", [])
            for d in metadatas:
                for key, value in d.items():
                    keys = (
                        [x for x in fields if x != self._store._primary_field]  # type: ignore[attr-defined]
                        if getattr(self._store, "auto_id", False)
                        else list(fields)
                    )
                    if key in keys:
                        insert_dict.setdefault(key, []).append(value)

        total_count = len(embeddings)
        pks: list[str] = []
        assert isinstance(self._store.col, Collection)
        for i in range(0, total_count, batch_size):
            end = min(i + batch_size, total_count)
            insert_list = [insert_dict[x][i:end] for x in self._store.fields if x in insert_dict]
            try:
                eff_timeout = getattr(self._store, "timeout", None) or timeout
                if upsert:
                    res = self._store.col.upsert(insert_list, timeout=eff_timeout, **kwargs)
                    pks.extend([str(pk) for pk in res.primary_keys])
                else:
                    res = self._store.col.insert(insert_list, timeout=eff_timeout, **kwargs)
                    pks.extend([str(pk) for pk in res.primary_keys])
            except MilvusException:
                logger.exception(
                    "Failed to write vectors batch: %s/%s collection=%s",
                    i,
                    total_count,
                    self.collection_name,
                )
                raise

        try:
            self._store.col.flush()
        except MilvusException:
            logger.exception("Failed to flush vector writes collection=%s", self.collection_name)
            raise

        return pks

    def delete(self, ids: list[str]) -> None:
        """Delete vectors with specified IDs."""
        if not ids:
            return
        self._ensure_store()
        assert self._store is not None
        self._store.delete(ids)

    def delete_by_document_id(self, document_id: UUID, tenant_id: UUID | None = None) -> None:
        """Delete all vectors for a document from this collection."""
        self._ensure_store()
        assert self._store is not None
        parts = []
        if tenant_id:
            parts.append(f'tenant_id == "{_escape_milvus_string(str(tenant_id))}"')
        parts.append(f'document_id == "{_escape_milvus_string(str(document_id))}"')
        expr = _MILVUS_EXPR_AND.join(parts)
        self._store.delete(expr=expr)
        try:
            self._store.col.flush()  # type: ignore[union-attr]
        except Exception as exc:
            logger.debug(_MILVUS_FALLBACK_LOG_MESSAGE, exc)

    def delete_by_document_id_and_filter(
        self,
        *,
        document_id: UUID,
        tenant_id: UUID | None = None,
        metadata_filter: dict[str, Any] | None = None,
    ) -> None:
        """Delete vectors for a document with an additional safe metadata filter."""
        metadata_expr = _build_milvus_metadata_expr(metadata_filter)
        if not metadata_expr:
            return
        self._ensure_store()
        assert self._store is not None
        parts = []
        if tenant_id:
            parts.append(f'tenant_id == "{_escape_milvus_string(str(tenant_id))}"')
        parts.append(f'document_id == "{_escape_milvus_string(str(document_id))}"')
        base_expr = _MILVUS_EXPR_AND.join(parts)
        expr = f"({base_expr}) and ({metadata_expr})"
        self._store.delete(expr=expr)
        try:
            self._store.col.flush()  # type: ignore[union-attr]
        except Exception as exc:
            logger.debug(_MILVUS_FALLBACK_LOG_MESSAGE, exc)

    def search(
        self,
        query_vector: list[float],
        top_k: int = 10,
        expr: str | None = None,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Vector similarity search.

        Args:
            query_vector: Query vector
            top_k: Number of results to return
            expr: Filter expression

        Returns:
            List of search results
        """
        self._ensure_store()
        assert self._store is not None

        supported_filter = _sanitize_milvus_metadata_filter(metadata_filter)
        metadata_expr = _build_milvus_metadata_expr(supported_filter)
        if expr and metadata_expr:
            combined_expr = f"({expr}) and ({metadata_expr})"
        else:
            combined_expr = expr or metadata_expr

        try:
            results = self._store.similarity_search_with_score_by_vector(
                embedding=query_vector,
                k=top_k,
                expr=combined_expr,
            )
        except Exception:
            # Fallback: ignore pushdown on schema/expr mismatch; still apply client-side filtering.
            results = self._store.similarity_search_with_score_by_vector(
                embedding=query_vector,
                k=top_k,
                expr=expr,
            )
        return [
            {
                "id": doc.id,
                "metadata": doc.metadata or {},
                "score": float(score),
                "content": doc.page_content,
            }
            for doc, score in results
            if not supported_filter or _match_metadata_filter(doc.metadata or {}, supported_filter)
        ]


_milvus_adapter_cache: dict[tuple[str, str, str], MilvusAdapter] = {}
_milvus_adapter_cache_lock = threading.Lock()


def resolve_collection_name(preferred: str) -> str:
    """Resolve canonical Milvus collection name."""
    return preferred


def get_milvus_adapter(
    collection_name: str,
    *,
    vector_field: str = "embedding",
    text_field: str = "content",
) -> MilvusAdapter:
    key = (collection_name, vector_field, text_field)
    with _milvus_adapter_cache_lock:
        cached = _milvus_adapter_cache.get(key)
        if cached is not None:
            return cached
        adapter = MilvusAdapter(collection_name=collection_name, vector_field=vector_field, text_field=text_field)
        _milvus_adapter_cache[key] = adapter
        return adapter


# ========= Document vector store (singleton) ==========

class MilvusVectorStore:
    """
    Milvus vector store service (document vectors, singleton).

    Used for knowledge base document vectors with a fixed collection name.
    """

    _instance: Optional["MilvusVectorStore"] = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                # Double-check locking pattern
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        self._embedding_provider = (settings.EMBEDDING_PROVIDER or "local").lower()
        self._embedding_model = None
        self._store = None
        self._embedding_space_hash = ""

    @staticmethod
    def _current_embedding_space_hash() -> str:
        try:
            from app.rag.embedding.utils import current_embedding_space_hash

            return str(current_embedding_space_hash() or "").strip()
        except Exception:
            return ""

    def _init_embedding_model(self):
        """Initialize embedding model."""
        return _init_embedding_model()

    def _ensure_store(self):
        current_space = self._current_embedding_space_hash()
        if self._store is not None and self._embedding_space_hash and current_space != self._embedding_space_hash:
            logger.info(
                "Embedding space changed; rebuilding Milvus vector store adapter (%s -> %s)",
                self._embedding_space_hash,
                current_space,
            )
            self._store = None
            self._embedding_model = None

        if self._store is not None:
            return

        if self._embedding_model is None:
            self._embedding_model = _init_embedding_model()

        from langchain_community.vectorstores import Milvus as LCMilvus

        self._store = LCMilvus(
            embedding_function=self._embedding_model,
            collection_name=settings.MILVUS_COLLECTION_NAME,
            connection_args=_get_milvus_connection_args(),
            index_params=_get_milvus_index_params(),
            search_params=_get_milvus_search_params(),
            auto_id=False,
            primary_field="id",
            text_field="content",
            vector_field="embedding",
        )
        self._embedding_space_hash = current_space

    def _build_expr(
        self,
        document_ids: list[UUID] | None = None,
        tenant_id: UUID | None = None,
    ) -> str | None:
        """Build a Milvus filter expression."""
        expr_parts: list[str] = []
        if tenant_id:
            expr_parts.append(f'tenant_id == "{str(tenant_id)}"')
        if document_ids:
            max_doc_ids = int(getattr(settings, "MILVUS_EXPR_MAX_DOC_IDS", 0) or 0)
            if max_doc_ids > 0 and len(document_ids) > max_doc_ids:
                # Fallback to tenant-only expr; caller/retriever can still post-filter by doc_ids.
                logger.info(
                    "Skipping Milvus document_id pushdown (too many ids: %s > %s)",
                    len(document_ids),
                    max_doc_ids,
                )
            else:
                doc_id_strs = [f'"{str(doc_id)}"' for doc_id in document_ids]
                expr_parts.append(f"document_id in [{', '.join(doc_id_strs)}]")
        return _MILVUS_EXPR_AND.join(expr_parts) if expr_parts else None

    def add_documents(
        self,
        documents: list[dict[str, Any]],
        document_id: UUID,
        tenant_id: UUID,
    ) -> list[str]:
        """Add document chunks to Milvus (returns vector id list)."""
        self._ensure_store()
        assert self._store is not None

        def _effective_write_batch_size(texts: list[str]) -> int:
            base = max(1, int(getattr(settings, "VECTOR_WRITE_BATCH_SIZE", 256) or 256))
            if not bool(getattr(settings, "VECTOR_WRITE_ADAPTIVE_BATCHING_ENABLED", True)):
                return base
            max_chars_per_batch = int(getattr(settings, "VECTOR_WRITE_BATCH_MAX_CHARS", 200_000) or 200_000)
            if max_chars_per_batch <= 0:
                return base
            if not texts:
                return base
            max_chunk_chars = max(len(t or "") for t in texts)
            if max_chunk_chars <= 0:
                return base
            budgeted = max(1, int(max_chars_per_batch // max_chunk_chars))
            return max(1, min(base, budgeted))

        def _add_texts_with_compat(*, texts: list[str], metadatas: list[dict[str, Any]], ids: list[str]) -> list[str]:
            # Normalize per-batch (Milvus expects aligned keys for each insert call).
            metadatas_norm = _normalize_milvus_metadata_batch(metadatas)
            try:
                pks = self._store.add_texts(texts=texts, metadatas=metadatas_norm, ids=ids)
            except Exception as exc:
                # Backward compatibility: older collections might not have new scalar fields.
                # Retry once with new optional fields dropped (safe, does not change retrieval semantics).
                global _MILVUS_WARNED_WRITE_COMPAT_FALLBACK
                if not _MILVUS_WARNED_WRITE_COMPAT_FALLBACK:
                    logger.warning(
                        "Milvus add_texts failed; retrying without dataset_id/embedding_space_hash (schema fallback). err=%s",
                        str(exc)[:200],
                    )
                    _MILVUS_WARNED_WRITE_COMPAT_FALLBACK = True
                try:
                    from app.storage.vector.milvus_prometheus_metrics import observe_milvus_write_compat_fallback

                    observe_milvus_write_compat_fallback(dropped_fields="dataset_id_embedding_space_hash")
                except Exception as exc:
                    logger.debug(_MILVUS_FALLBACK_LOG_MESSAGE, exc)
                for m in metadatas_norm:
                    m.pop("dataset_id", None)
                    m.pop("embedding_space_hash", None)
                pks = self._store.add_texts(texts=texts, metadatas=metadatas_norm, ids=ids)
            return [str(pk) for pk in pks]

        texts: list[str] = []
        metadatas: list[dict[str, Any]] = []
        ids: list[str] = []

        for idx, doc in enumerate(documents):
            content = (doc.get("content") or "")[:65_535]
            meta = doc.get("metadata") or {}

            # Prefer stable chunk_id (UUID string) when available to avoid collisions on re-index.
            chunk_id = meta.get("chunk_id")
            vector_id = str(chunk_id) if chunk_id else f"{document_id}_{idx}"
            ids.append(vector_id)
            texts.append(content)

            img_id = meta.get("img_id") or meta.get("image_id") or ""
            image_id = meta.get("image_id") or meta.get("img_id") or ""
            image_url = meta.get("image_url") or meta.get("img_url") or ""
            pipeline_hash = str(meta.get("pipeline_hash") or "")[:64]
            doc_pipeline_key = str(
                meta.get("doc_pipeline_key")
                or (f"{document_id}:{pipeline_hash}" if pipeline_hash else str(document_id))
            )[:256]

            metadatas.append(
                {
                    "tenant_id": str(tenant_id),
                    "dataset_id": str(meta.get("dataset_id") or "")[:_MILVUS_MAX_VARCHAR_BYTES],
                    "embedding_space_hash": str(meta.get("embedding_space_hash") or "")[:128],
                    "document_id": str(document_id),
                    "chunk_index": int(meta.get("chunk_index", idx)),
                    "chunk_id": str(chunk_id) if chunk_id else "",
                    "pipeline_hash": pipeline_hash,
                    "doc_pipeline_key": doc_pipeline_key,
                    "page_number": int(meta.get("page") or meta.get("page_number") or 0),
                    "source": str(meta.get("source", "unknown"))[:500],
                    "file_type": str(meta.get("file_type", "unknown"))[:20],
                    "img_id": str(img_id)[:500],
                    "image_id": str(image_id)[:500],
                    "image_url": str(image_url)[:2000],
                }
            )

        batch_size = _effective_write_batch_size(texts)
        if batch_size >= len(texts):
            return _add_texts_with_compat(texts=texts, metadatas=metadatas, ids=ids)

        pks: list[str] = []
        for start in range(0, len(texts), batch_size):
            pks.extend(
                _add_texts_with_compat(
                    texts=texts[start : start + batch_size],
                    metadatas=metadatas[start : start + batch_size],
                    ids=ids[start : start + batch_size],
                )
            )
        return pks

    def search(
        self,
        query: str,
        top_k: int = 5,
        score_threshold: float = 0.7,
        document_ids: list[UUID] | None = None,
        tenant_id: UUID | None = None,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Vector similarity search (text query)."""
        self._ensure_store()
        assert self._store is not None

        supported_filter = _sanitize_milvus_metadata_filter(
            metadata_filter,
            allowed_fields=set(_DOC_VECTOR_METADATA_FIELDS),
        )
        base_expr = self._build_expr(document_ids=document_ids, tenant_id=tenant_id)
        metadata_expr = _build_milvus_metadata_expr(supported_filter)
        if base_expr and metadata_expr:
            combined_expr = f"({base_expr}) and ({metadata_expr})"
        else:
            combined_expr = base_expr or metadata_expr

        try:
            results = self._store.similarity_search_with_score(query, k=top_k * 2, expr=combined_expr)
        except Exception as exc:
            # Fallback for legacy collections / unsupported expr clauses.
            global _MILVUS_WARNED_SEARCH_EXPR_FALLBACK
            if not _MILVUS_WARNED_SEARCH_EXPR_FALLBACK:
                logger.warning(
                    "Milvus search expr failed; retrying without metadata expr pushdown. err=%s",
                    str(exc)[:200],
                )
                _MILVUS_WARNED_SEARCH_EXPR_FALLBACK = True
            try:
                from app.storage.vector.milvus_prometheus_metrics import observe_milvus_search_expr_fallback

                observe_milvus_search_expr_fallback(
                    has_metadata_expr=bool(metadata_expr),
                    has_base_expr=bool(base_expr),
                )
            except Exception as exc:
                logger.debug(_MILVUS_FALLBACK_LOG_MESSAGE, exc)
            results = self._store.similarity_search_with_score(query, k=top_k * 2, expr=base_expr)

        formatted: list[dict[str, Any]] = []
        for doc, score in results:
            if score < score_threshold:
                continue
            meta = doc.metadata or {}
            if supported_filter and not _match_metadata_filter(meta, supported_filter):
                continue
            chunk_id = meta.get("chunk_id")
            formatted.append(
                {
                    "chunk_id": chunk_id,
                    "content": doc.page_content,
                    "metadata": {
                        "tenant_id": meta.get("tenant_id"),
                        "dataset_id": meta.get("dataset_id"),
                        "embedding_space_hash": meta.get("embedding_space_hash"),
                        "document_id": meta.get("document_id"),
                        "source": meta.get("source", "unknown"),
                        "page": meta.get("page_number"),
                        "page_number": meta.get("page_number"),
                        "chunk_index": meta.get("chunk_index"),
                        "chunk_id": chunk_id,
                        "pipeline_hash": meta.get("pipeline_hash"),
                        "doc_pipeline_key": meta.get("doc_pipeline_key"),
                        "img_id": meta.get("img_id") or meta.get("image_id"),
                        "image_id": meta.get("image_id") or meta.get("img_id"),
                        "image_url": meta.get("image_url") or meta.get("img_url"),
                        "score": float(score),
                    },
                    "score": float(score),
                }
            )
            if len(formatted) >= top_k:
                break

        return formatted

    def delete_by_document_id(self, document_id: UUID, tenant_id: UUID | None = None) -> None:
        """Delete all vectors for a given document."""
        self._ensure_store()
        assert self._store is not None

        expr = self._build_expr(document_ids=[document_id], tenant_id=tenant_id)
        if expr:
            self._store.delete(expr=expr)
            try:
                self._store.col.flush()  # type: ignore[union-attr]
            except Exception as exc:
                logger.debug(_MILVUS_FALLBACK_LOG_MESSAGE, exc)

    def delete_by_document_id_and_filter(
        self,
        *,
        document_id: UUID,
        tenant_id: UUID | None = None,
        metadata_filter: dict[str, Any] | None = None,
    ) -> None:
        """
        Delete vectors for a given document, scoped by a metadata_filter (best-effort).

        Safety notes:
        - If the filter cannot be translated into a safe Milvus expr, this is a no-op (never "delete all").
        - Caller can still fall back to full delete_by_document_id when appropriate.
        """
        self._ensure_store()
        assert self._store is not None

        base_expr = self._build_expr(document_ids=[document_id], tenant_id=tenant_id)
        metadata_expr = _build_milvus_metadata_expr(metadata_filter)
        if not metadata_expr:
            return

        expr = f"({base_expr}) and ({metadata_expr})" if base_expr else metadata_expr
        self._store.delete(expr=expr)
        try:
            self._store.col.flush()  # type: ignore[union-attr]
        except Exception as exc:
            logger.debug(_MILVUS_FALLBACK_LOG_MESSAGE, exc)

    def get_collection_count(self) -> int:
        """Return document count in the vector collection."""
        self._ensure_store()
        assert self._store is not None
        try:
            return int(self._store.col.num_entities)  # type: ignore[union-attr]
        except Exception:
            return 0

    def fetch_existing_ids(
        self,
        ids: list[str],
        *,
        max_ids_per_query: int = 256,
        timeout: float | None = None,
    ) -> set[str]:
        """
        Best-effort existence check for a list of vector primary keys.

        Used by index audit / troubleshooting to detect missing vectors when the DB
        still references a vector_id.

        Notes:
        - Uses Milvus `query()` with an `id in [...]` expr.
        - Batches by both item count and expr length to reduce server-side rejects.
        - Returns an empty set on any failure (audit should degrade gracefully).
        """
        raw_ids = [str(x) for x in (ids or []) if isinstance(x, str) and x.strip()]
        if not raw_ids:
            return set()

        self._ensure_store()
        assert self._store is not None

        col = getattr(self._store, "col", None)
        if col is None or not hasattr(col, "query"):
            return set()

        primary_field = str(getattr(self._store, "_primary_field", "id") or "id").strip() or "id"

        # De-dup while preserving stable ordering (helps reproducible audits).
        seen: set[str] = set()
        uniq: list[str] = []
        for rid in raw_ids:
            if rid in seen:
                continue
            seen.add(rid)
            uniq.append(rid)

        existing: set[str] = set()
        for batch in _chunk_in_list_values(
            uniq,
            field=primary_field,
            max_expr_chars=_MILVUS_EXPR_MAX_CHARS,
            max_items=int(max_ids_per_query or 0),
        ):
            items = [f"\"{_escape_milvus_string(str(x))}\"" for x in batch]
            if not items:
                continue
            expr = f"{primary_field} in [{', '.join(items)}]"
            try:
                rows = col.query(expr=expr, output_fields=[primary_field], timeout=timeout)  # type: ignore[call-arg]
            except Exception:
                return set()
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                val = row.get(primary_field)
                if val is None:
                    continue
                existing.add(str(val))

        return existing

    def fetch_vectors_by_ids(
        self,
        ids: list[str],
        *,
        max_ids_per_query: int = 128,
        timeout: float | None = None,
    ) -> dict[str, list[float]]:
        """
        Best-effort fetch of stored vectors by primary key.

        Used by offline diagnostics (e.g. embedding drift monitor). This is intentionally
        bounded and fail-open: returns an empty mapping on any failure.

        Notes:
        - Uses Milvus `query()` with an `id in [...]` expr.
        - Batches by both item count and expr length to reduce server-side rejects.
        """
        raw_ids = [str(x) for x in (ids or []) if isinstance(x, str) and x.strip()]
        if not raw_ids:
            return {}

        self._ensure_store()
        assert self._store is not None

        col = getattr(self._store, "col", None)
        if col is None or not hasattr(col, "query"):
            return {}

        primary_field = str(getattr(self._store, "_primary_field", "id") or "id").strip() or "id"
        vector_field = str(getattr(self._store, "_vector_field", "embedding") or "embedding").strip() or "embedding"

        # De-dup while preserving stable ordering (helps reproducible audits).
        seen: set[str] = set()
        uniq: list[str] = []
        for rid in raw_ids:
            if rid in seen:
                continue
            seen.add(rid)
            uniq.append(rid)

        out: dict[str, list[float]] = {}
        for batch in _chunk_in_list_values(
            uniq,
            field=primary_field,
            max_expr_chars=_MILVUS_EXPR_MAX_CHARS,
            max_items=int(max_ids_per_query or 0),
        ):
            items = [f"\"{_escape_milvus_string(str(x))}\"" for x in batch]
            if not items:
                continue
            expr = f"{primary_field} in [{', '.join(items)}]"
            try:
                rows = col.query(  # type: ignore[call-arg]
                    expr=expr,
                    output_fields=[primary_field, vector_field],
                    timeout=timeout,
                )
            except Exception:
                return {}

            if not isinstance(rows, list):
                continue

            for row in rows:
                if not isinstance(row, dict):
                    continue
                pk = row.get(primary_field)
                vec = row.get(vector_field)
                if pk is None or vec is None:
                    continue

                vector: list[float] | None = None
                if isinstance(vec, (list, tuple)):
                    if all(isinstance(v, (int, float)) for v in vec):
                        vector = [float(v) for v in vec]
                elif hasattr(vec, "tolist"):
                    try:
                        as_list = vec.tolist()  # type: ignore[attr-defined]
                        if isinstance(as_list, list) and all(isinstance(v, (int, float)) for v in as_list):
                            vector = [float(v) for v in as_list]
                    except Exception:
                        vector = None

                if vector:
                    out[str(pk)] = vector

        return out

    def list_ids_by_dataset(
        self,
        *,
        tenant_id: UUID,
        dataset_id: UUID,
        limit: int = 2000,
        offset: int = 0,
        timeout: float | None = None,
    ) -> list[str]:
        """
        Best-effort listing of vector ids for a dataset.

        This is intentionally bounded (limit/offset) and should only be used for
        troubleshooting/audits (not hot path retrieval).
        """
        self._ensure_store()
        assert self._store is not None

        col = getattr(self._store, "col", None)
        if col is None or not hasattr(col, "query"):
            return []

        primary_field = str(getattr(self._store, "_primary_field", "id") or "id").strip() or "id"

        lim = max(0, int(limit or 0))
        if lim <= 0:
            return []
        off = max(0, int(offset or 0))

        expr = (
            f'tenant_id == "{_escape_milvus_string(str(tenant_id))}" '
            f'and dataset_id == "{_escape_milvus_string(str(dataset_id))}"'
        )
        if len(expr) > _MILVUS_EXPR_MAX_CHARS:
            return []

        try:
            rows = col.query(  # type: ignore[call-arg]
                expr=expr,
                output_fields=[primary_field],
                limit=lim,
                offset=off,
                timeout=timeout,
            )
        except Exception:
            return []

        out: list[str] = []
        if not isinstance(rows, list):
            return out
        for row in rows:
            if not isinstance(row, dict):
                continue
            v = row.get(primary_field)
            if v is None:
                continue
            out.append(str(v))

        return out


# ========= Global instances ==========

# Document vector store (singleton)
milvus_store = MilvusVectorStore()
