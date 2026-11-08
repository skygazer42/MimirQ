"""
Vector store router for Milvus, memory, Qdrant and pgvector.
Switch via VECTOR_BACKEND to keep the retrieval path centralized.
"""

import json
import math
import threading
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any
from uuid import UUID

from app.core.config import settings
from app.core.constants import EmbeddingProviders
from app.rag.core.filters import match_metadata_filter as _match_metadata_filter
from app.rag.core.hashing import stable_hash
from app.rag.core.logging import get_logger
from app.rag.embedding import create_langchain_embeddings_from_config
from app.storage.vector.milvus import milvus_store
from app.storage.vector.pgvector import PGVectorStore
from app.storage.vector.qdrant import QdrantVectorStore

if TYPE_CHECKING:
    from app.rag.embedding.adapter import LangChainEmbeddingsAdapter

logger = get_logger("storage.vector.factory")


class BaseVectorStore:
    """Unified interface for vector storage backends."""

    def add_documents(self, docs: list[dict[str, Any]], document_id: UUID, tenant_id: UUID) -> list[str]:
        raise NotImplementedError

    def search(
        self,
        query: str,
        top_k: int,
        score_threshold: float,
        document_ids: list[UUID] | None,
        tenant_id: UUID | None,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError

    def delete_by_document_id(self, document_id: UUID, tenant_id: UUID | None = None) -> None:
        raise NotImplementedError

    def delete_by_document_id_and_filter(
        self,
        *,
        document_id: UUID,
        tenant_id: UUID | None,
        metadata_filter: dict[str, Any],
    ) -> None:
        """
        Best-effort selective delete for a single document.

        Used for versioned re-indexing/rollback (e.g. delete only the target pipeline version).
        Backends that cannot support this should raise NotImplementedError.
        """
        raise NotImplementedError

    def get_embedding_client(self) -> "LangChainEmbeddingsAdapter":
        raise NotImplementedError


class MilvusVectorStore(BaseVectorStore):
    """Milvus backend wrapper."""

    def add_documents(self, docs: list[dict[str, Any]], document_id: UUID, tenant_id: UUID) -> list[str]:
        return milvus_store.add_documents(docs, document_id, tenant_id)

    def search(
        self,
        query: str,
        top_k: int,
        score_threshold: float,
        document_ids: list[UUID] | None,
        tenant_id: UUID | None,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        return milvus_store.search(
            query=query,
            top_k=top_k,
            score_threshold=score_threshold,
            document_ids=document_ids,
            tenant_id=tenant_id,
            metadata_filter=metadata_filter,
        )

    def delete_by_document_id(self, document_id: UUID, tenant_id: UUID | None = None) -> None:
        milvus_store.delete_by_document_id(document_id, tenant_id=tenant_id)

    def delete_by_document_id_and_filter(
        self,
        *,
        document_id: UUID,
        tenant_id: UUID | None,
        metadata_filter: dict[str, Any],
    ) -> None:
        milvus_store.delete_by_document_id_and_filter(
            document_id=document_id, tenant_id=tenant_id, metadata_filter=metadata_filter
        )

    def get_embedding_client(self) -> "LangChainEmbeddingsAdapter":
        return milvus_store.get_embedding_model()


class StubVectorStore(BaseVectorStore):
    """Placeholder implementation for future backends."""

    def add_documents(self, docs: list[dict[str, Any]], document_id: UUID, tenant_id: UUID) -> list[str]:
        raise RuntimeError("Vector backend not implemented")

    def search(
        self,
        query: str,
        top_k: int,
        score_threshold: float,
        document_ids: list[UUID] | None,
        tenant_id: UUID | None,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        return []

    def delete_by_document_id(self, document_id: UUID, tenant_id: UUID | None = None) -> None:
        return

    def delete_by_document_id_and_filter(
        self,
        *,
        document_id: UUID,
        tenant_id: UUID | None,
        metadata_filter: dict[str, Any],
    ) -> None:
        raise NotImplementedError("Vector backend not implemented")

    def get_embedding_client(self) -> "LangChainEmbeddingsAdapter":
        raise RuntimeError("Vector backend does not expose an embedding client")


class MemoryVectorStore(BaseVectorStore):
    """
    Lightweight in-memory vector store for local testing or no-Milvus scenarios.
    Uses OpenAI-compatible embeddings (requires EMBEDDING_API_KEY/LLM_API_KEY).
    """

    def __init__(self) -> None:
        provider = EmbeddingProviders.PROVIDER_MAP.get(
            (settings.EMBEDDING_PROVIDER or "openai_compatible").lower(), "openai_compatible"
        )
        api_key = settings.EMBEDDING_API_KEY or settings.LLM_API_KEY or ""
        base_url = settings.EMBEDDING_API_BASE or settings.LLM_API_BASE or ""
        model = settings.EMBEDDING_MODEL or "text-embedding-3-small"
        self.emb = create_langchain_embeddings_from_config(
            provider=provider,
            model=model,
            api_key=api_key or "",
            base_url=base_url or "",
            dimension=None,
        )
        self.storage: list[tuple[list[float], dict[str, Any]]] = []
        self._lock = threading.RLock()

    def add_documents(self, docs: list[dict[str, Any]], document_id: UUID, tenant_id: UUID) -> list[str]:
        with self._lock:
            texts = [d.get("content", "") for d in docs]
            vectors = self.emb.embed_documents(texts)
            for vec, doc in zip(vectors, docs, strict=False):
                meta = dict(doc.get("metadata") or {})
                meta.setdefault("document_id", str(document_id))
                meta.setdefault("tenant_id", str(tenant_id))
                if meta.get("chunk_id"):
                    meta["chunk_id"] = str(meta.get("chunk_id"))
                meta.setdefault("content", doc.get("content", ""))
                self.storage.append((vec, meta))
            # In-memory mode uses placeholder IDs instead of real vector IDs.
            ids: list[str] = []
            for i, d in enumerate(docs):
                meta = dict(d.get("metadata") or {})
                cid = meta.get("chunk_id")
                ids.append(str(cid) if cid else f"{document_id}_mem_{i}")
            return ids

    def search(
        self,
        query: str,
        top_k: int,
        score_threshold: float,
        document_ids: list[UUID] | None,
        tenant_id: UUID | None,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            if not self.storage:
                return []
            qvec = self.emb.embed_query(query)
            allowed_ids = {str(did) for did in document_ids} if document_ids else None
            allowed_tenant = str(tenant_id) if tenant_id else None

            def cosine(a: list[float], b: list[float]) -> float:
                num = sum(x * y for x, y in zip(a, b, strict=False))
                denom = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
                return num / denom if denom else 0.0

            results: list[dict[str, Any]] = []
            for vec, meta in self.storage:
                if allowed_tenant and meta.get("tenant_id") != allowed_tenant:
                    continue
                if allowed_ids and meta.get("document_id") not in allowed_ids:
                    continue
                if metadata_filter and not _match_metadata_filter(meta, metadata_filter):
                    continue
                score = cosine(qvec, vec)
                if score < score_threshold:
                    continue
                results.append(
                    {
                        "chunk_id": meta.get("chunk_id"),
                        "content": meta.get("content") or meta.get("text") or "",
                        "metadata": meta,
                        "score": score,
                        "vector_score": score,
                    }
                )
            results.sort(key=lambda x: x["score"], reverse=True)
            return results[:top_k]

    def delete_by_document_id(self, document_id: UUID, tenant_id: UUID | None = None) -> None:
        with self._lock:
            doc_id = str(document_id)
            tenant = str(tenant_id) if tenant_id else None
            self.storage = [
                (vec, meta)
                for (vec, meta) in self.storage
                if not (meta.get("document_id") == doc_id and (tenant is None or meta.get("tenant_id") == tenant))
            ]

    def delete_by_document_id_and_filter(
        self,
        *,
        document_id: UUID,
        tenant_id: UUID | None,
        metadata_filter: dict[str, Any],
    ) -> None:
        with self._lock:
            doc_id = str(document_id)
            tenant = str(tenant_id) if tenant_id else None
            if not metadata_filter or not isinstance(metadata_filter, dict):
                return self.delete_by_document_id(document_id, tenant_id=tenant_id)
            self.storage = [
                (vec, meta)
                for (vec, meta) in self.storage
                if not (
                    meta.get("document_id") == doc_id
                    and (tenant is None or meta.get("tenant_id") == tenant)
                    and _match_metadata_filter(meta, metadata_filter)
                )
            ]

    def get_embedding_client(self) -> "LangChainEmbeddingsAdapter":
        return self.emb


_VECTOR_STORE_SINGLETONS: dict[str, BaseVectorStore] = {}
_VECTOR_STORE_SINGLETONS_LOCK = threading.RLock()
_EMBEDDING_AWARE_VECTOR_BACKENDS = frozenset({"memory", "qdrant", "pgvector"})


def _normalize_region(region: str | None = None) -> str:
    selected_region = settings.DATA_REGION if region is None else region
    return selected_region.strip().lower()


def _load_vector_region_backends() -> dict[str, str]:
    raw = settings.VECTOR_REGION_BACKENDS or ""
    if isinstance(raw, Mapping):
        source = dict(raw)
    else:
        text = str(raw).strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except Exception:
            return {}
        source = dict(parsed) if isinstance(parsed, dict) else {}

    out: dict[str, str] = {}
    for key, value in source.items():
        region = str(key or "").strip().lower()
        backend = str(value or "").strip().lower()
        if not region or not backend:
            continue
        out[region] = backend
    return out


def _resolve_vector_backend(*, backend: str | None = None, region: str | None = None) -> tuple[str, str | None]:
    region_key = _normalize_region(region)
    selected_backend = settings.VECTOR_BACKEND if backend is None else backend
    requested = selected_backend.strip().lower()
    if region_key:
        requested = _load_vector_region_backends().get(region_key, requested)
    if requested == "faiss":
        raise ValueError("FAISS vector backend has been retired. Select a supported backend explicitly.")
    if requested == "chroma":
        raise ValueError("Chroma vector backend has been retired. Select a supported backend explicitly.")
    return requested, (region_key if region_key else None)


def _embedding_client_cache_token() -> str:
    provider = EmbeddingProviders.PROVIDER_MAP.get(
        str(settings.EMBEDDING_PROVIDER or "openai_compatible").strip().lower(),
        "openai_compatible",
    )
    model = str(settings.EMBEDDING_MODEL or "text-embedding-3-small").strip()
    api_base = str(settings.EMBEDDING_API_BASE or settings.LLM_API_BASE or "").strip()
    api_key = str(settings.EMBEDDING_API_KEY or settings.LLM_API_KEY or "").strip()
    api_key_hash = stable_hash(api_key, length=16) if api_key else ""
    return stable_hash(f"{provider}|{model}|{api_base}|{api_key_hash}", length=24)


def _vector_store_cache_key(*, backend_name: str, region_key: str | None) -> str:
    key = f"{region_key}:{backend_name}" if region_key else backend_name
    if backend_name in _EMBEDDING_AWARE_VECTOR_BACKENDS:
        key = f"{key}:{_embedding_client_cache_token()}"
    return key


def reset_vector_store_singletons() -> None:
    with _VECTOR_STORE_SINGLETONS_LOCK:
        _VECTOR_STORE_SINGLETONS.clear()


def get_vector_store(*, backend: str | None = None, region: str | None = None) -> BaseVectorStore:
    """
    Return the configured vector store backend (singleton).
    The memory backend keeps state in-process; its singleton preserves that state.
    """
    backend_name, region_key = _resolve_vector_backend(backend=backend, region=region)
    cache_key = _vector_store_cache_key(backend_name=backend_name, region_key=region_key)
    with _VECTOR_STORE_SINGLETONS_LOCK:
        cached = _VECTOR_STORE_SINGLETONS.get(cache_key)
        if cached is not None:
            return cached

        if backend_name == "milvus":
            store: BaseVectorStore = MilvusVectorStore()
        elif backend_name == "memory":
            store = MemoryVectorStore()
        elif backend_name == "qdrant":
            store = QdrantVectorStore()
        elif backend_name == "pgvector":
            store = PGVectorStore()
        else:
            store = StubVectorStore()

        _VECTOR_STORE_SINGLETONS[cache_key] = store
        return store


def get_embedding_client(*, backend: str | None = None, region: str | None = None) -> "LangChainEmbeddingsAdapter":
    store = get_vector_store(backend=backend, region=region)
    return store.get_embedding_client()
