"""
Vector store router: supports multiple backends.
Milvus is implemented today; other backends are placeholders for extension.
Switch via VECTOR_BACKEND to keep the retrieval path centralized.
"""
import json
import math
import os
import threading
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from app.core.config import settings
from app.core.constants import EmbeddingProviders
from app.rag.core.filters import match_metadata_filter
from app.rag.core.hashing import stable_hash
from app.rag.core.logging import get_logger
from app.rag.embedding import create_langchain_embeddings_from_config
from app.storage.vector.milvus import milvus_store
from app.storage.vector.pgvector import PGVectorStore
from app.storage.vector.qdrant import QdrantVectorStore

logger = get_logger("storage.vector.factory")

_FAISS_CLS = None
_CHROMA_CLS = None


def _get_faiss_cls():
    global _FAISS_CLS
    if _FAISS_CLS is not None:
        return _FAISS_CLS
    try:
        # `langchain_community.vectorstores.FAISS` lazily imports `faiss` in some code paths,
        # which can make optional-dependency failures surface later (and break tests that
        # only probe `_get_faiss_cls`). Import `faiss` eagerly so callers can reliably
        # detect availability and skip gracefully when the binary is broken (e.g. numpy ABI mismatch).
        import faiss  # noqa: F401
        from langchain_community.vectorstores import FAISS

        _FAISS_CLS = FAISS
        return _FAISS_CLS
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "FAISS vector backend requires optional dependencies. "
            "Install `faiss-cpu` and `langchain-community`."
        ) from exc


def _get_chroma_cls():
    global _CHROMA_CLS
    if _CHROMA_CLS is not None:
        return _CHROMA_CLS
    try:
        # `Chroma` wrappers may import `chromadb` lazily at instance-construction time.
        # Import it eagerly so optional-dependency problems are surfaced deterministically
        # when callers probe backend availability.
        import chromadb  # noqa: F401

        chromadb_file = getattr(chromadb, "__file__", None)
        # In unit tests we often monkeypatch a tiny `chromadb` stub module without a backing file;
        # skip deep optional-dependency validation in that case so preference/fallback behavior
        # can still be tested independently from the host environment.
        if chromadb_file:
            import pypika  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "Chroma vector backend requires optional dependencies. "
            "Ensure `chromadb` is installed and importable, and install "
            "`langchain-chroma` (preferred) or `langchain-community`."
        ) from exc
    try:
        # Prefer the dedicated package to avoid upstream deprecations.
        from langchain_chroma import Chroma  # type: ignore[import-not-found]

        _CHROMA_CLS = Chroma
        return _CHROMA_CLS
    except Exception:  # noqa: BLE001
        try:
            from langchain_community.vectorstores import Chroma

            _CHROMA_CLS = Chroma
            return _CHROMA_CLS
        except Exception as exc2:  # noqa: BLE001
            raise RuntimeError(
                "Chroma vector backend requires optional dependencies. "
                "Install `chromadb` and `langchain-chroma` (preferred) or `langchain-community`."
            ) from exc2


def _match_metadata_filter(meta: dict[str, Any], filter_spec: dict[str, Any]) -> bool:
    """Metadata filter matcher (supports operators)."""
    return match_metadata_filter(meta, filter_spec)


class BaseVectorStore:
    """Unified interface for future FAISS/Chroma/Memory extensions."""

    def add_documents(self, docs: list[dict[str, Any]], document_id: UUID, tenant_id: UUID):
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


class MilvusVectorStore(BaseVectorStore):
    """Milvus backend wrapper."""

    def add_documents(self, docs: list[dict[str, Any]], document_id: UUID, tenant_id: UUID):
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
        milvus_store.delete_by_document_id_and_filter(document_id=document_id, tenant_id=tenant_id, metadata_filter=metadata_filter)


class StubVectorStore(BaseVectorStore):
    """Placeholder implementation for future backends."""

    def add_documents(self, docs: list[dict[str, Any]], document_id: UUID, tenant_id: UUID):
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


class MemoryVectorStore(BaseVectorStore):
    """
    Lightweight in-memory vector store for local testing or no-Milvus scenarios.
    Uses OpenAI-compatible embeddings (requires EMBEDDING_API_KEY/LLM_API_KEY).
    """

    def __init__(self):
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

    def add_documents(self, docs: list[dict[str, Any]], document_id: UUID, tenant_id: UUID):
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


class FAISSVectorStore(BaseVectorStore):
    """
    FAISS backend for single-node/local development with optional persistence.
    """

    def __init__(self):
        api_key = settings.EMBEDDING_API_KEY or settings.LLM_API_KEY or ""
        base_url = settings.EMBEDDING_API_BASE or settings.LLM_API_BASE or ""
        model = settings.EMBEDDING_MODEL or "text-embedding-3-small"
        provider = EmbeddingProviders.PROVIDER_MAP.get(
            (settings.EMBEDDING_PROVIDER or "openai_compatible").lower(), "openai_compatible"
        )
        self.emb = create_langchain_embeddings_from_config(
            provider=provider,
            model=model,
            api_key=api_key or "",
            base_url=base_url or "",
            dimension=None,
        )
        self.store_by_tenant: dict[str, Any] = {}
        self.persist_path = settings.FAISS_STORE_PATH
        self.allow_dangerous_deserialization = bool(
            getattr(settings, "FAISS_ALLOW_DANGEROUS_DESERIALIZATION", False)
        )
        self._warned_dangerous_deserialization = False

    def _get_store(self, tenant_id: UUID | None) -> tuple[str, Any | None]:
        key = str(tenant_id or settings.DEFAULT_TENANT_ID)
        store = self.store_by_tenant.get(key)
        # If a persistence path exists and memory isn't loaded, try loading it.
        if store is None and self.persist_path and os.path.isdir(self.persist_path):
            if not self.allow_dangerous_deserialization:
                if not self._warned_dangerous_deserialization:
                    logger.warning(
                        "FAISS persistence found at %s but loading is disabled. "
                        "Set FAISS_ALLOW_DANGEROUS_DESERIALIZATION=true only if the directory is trusted.",
                        self.persist_path,
                    )
                    self._warned_dangerous_deserialization = True
                return key, None
            try:
                faiss_cls = _get_faiss_cls()
                store = faiss_cls.load_local(
                    folder_path=self.persist_path,
                    embeddings=self.emb,
                    index_name=key,
                    allow_dangerous_deserialization=True,
                )
                self.store_by_tenant[key] = store
            except Exception:
                store = None
        return key, store

    def add_documents(self, docs: list[dict[str, Any]], document_id: UUID, tenant_id: UUID):
        texts = [d.get("content", "") for d in docs]
        metadatas = []
        ids = []
        for idx, doc in enumerate(docs):
            meta = dict(doc.get("metadata") or {})
            meta.setdefault("document_id", str(document_id))
            meta.setdefault("tenant_id", str(tenant_id))
            meta.setdefault("chunk_index", idx)
            if meta.get("chunk_id"):
                meta["chunk_id"] = str(meta.get("chunk_id"))
            if "img_id" in meta and "image_id" not in meta:
                meta["image_id"] = meta.get("img_id")
            if "image_url" not in meta:
                meta.setdefault("image_url", meta.get("img_url"))
            metadatas.append(meta)
            ids.append(str(meta.get("chunk_id")) if meta.get("chunk_id") else f"{document_id}_{idx}")

        key, store = self._get_store(tenant_id)
        if store is None:
            faiss_cls = _get_faiss_cls()
            store = faiss_cls.from_texts(texts=texts, embedding=self.emb, metadatas=metadatas, ids=ids)
        else:
            store.add_texts(texts=texts, metadatas=metadatas, ids=ids)

        self.store_by_tenant[key] = store
        # Persist (full save each time).
        if self.persist_path:
            os.makedirs(self.persist_path, exist_ok=True)
            store.save_local(self.persist_path, index_name=key)
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
        _key, store = self._get_store(tenant_id)
        if store is None:
            return []
        allowed = {str(did) for did in document_ids} if document_ids else None
        results = store.similarity_search_with_score(query, k=top_k * 2)
        out: list[dict[str, Any]] = []
        for doc, score in results:
            meta = doc.metadata or {}
            if allowed and meta.get("document_id") not in allowed:
                continue
            if metadata_filter and not _match_metadata_filter(meta, metadata_filter):
                continue
            similarity = 1.0 / (1.0 + float(score))
            if similarity < score_threshold:
                continue
            out.append(
                {
                    "chunk_id": doc.id,
                    "content": doc.page_content,
                    "metadata": meta,
                    "score": similarity,
                    "vector_score": similarity,
                }
            )
        out.sort(key=lambda x: x["score"], reverse=True)
        return out[:top_k]

    def delete_by_document_id(self, document_id: UUID, tenant_id: UUID | None = None) -> None:
        key, store = self._get_store(tenant_id)
        if store is None:
            return
        target = str(document_id)
        ids_to_delete = []
        try:
            for doc_id, doc in getattr(store.docstore, "_dict", {}).items():
                if str((doc.metadata or {}).get("document_id")) == target:
                    ids_to_delete.append(str(doc_id))
        except Exception:
            ids_to_delete = []

        if ids_to_delete and hasattr(store, "delete"):
            try:
                store.delete(ids_to_delete)
            except Exception as exc:
                logger.debug("Ignoring FAISS delete-by-document-id failure: %s", exc)

        # Persist (overwrite save).
        if self.persist_path:
            os.makedirs(self.persist_path, exist_ok=True)
            store.save_local(self.persist_path, index_name=key)

    def delete_by_document_id_and_filter(
        self,
        *,
        document_id: UUID,
        tenant_id: UUID | None,
        metadata_filter: dict[str, Any],
    ) -> None:
        """
        Best-effort selective delete for FAISS.

        LangChain's FAISS wrapper supports delete-by-id (docstore keys), but does not provide
        a stable "where" API. We implement selective delete by scanning the in-memory docstore
        metadata for matches and deleting those doc IDs.
        """
        if not metadata_filter or not isinstance(metadata_filter, dict):
            return self.delete_by_document_id(document_id, tenant_id=tenant_id)

        key, store = self._get_store(tenant_id)
        if store is None:
            return

        target = str(document_id)
        ids_to_delete: list[str] = []
        try:
            for doc_id, doc in getattr(store.docstore, "_dict", {}).items():
                meta = getattr(doc, "metadata", None) or {}
                if str(meta.get("document_id") or "") != target:
                    continue
                if _match_metadata_filter(meta, metadata_filter):
                    ids_to_delete.append(str(doc_id))
        except Exception:
            ids_to_delete = []

        if not ids_to_delete:
            return

        if not hasattr(store, "delete"):
            raise NotImplementedError("Selective delete is not supported for FAISS backend")
        try:
            store.delete(ids_to_delete)
        except Exception as exc:
            raise NotImplementedError("Selective delete is not supported for FAISS backend") from exc

        # Persist (overwrite save) if enabled.
        if self.persist_path:
            os.makedirs(self.persist_path, exist_ok=True)
            store.save_local(self.persist_path, index_name=key)


class ChromaVectorStore(BaseVectorStore):
    """Chroma backend persisted to a local path."""

    def __init__(self):
        api_key = settings.EMBEDDING_API_KEY or settings.LLM_API_KEY or ""
        base_url = settings.EMBEDDING_API_BASE or settings.LLM_API_BASE or ""
        model = settings.EMBEDDING_MODEL or "text-embedding-3-small"
        provider = EmbeddingProviders.PROVIDER_MAP.get(
            (settings.EMBEDDING_PROVIDER or "openai_compatible").lower(), "openai_compatible"
        )
        self.emb = create_langchain_embeddings_from_config(
            provider=provider,
            model=model,
            api_key=api_key or "",
            base_url=base_url or "",
            dimension=None,
        )
        # Empty path => in-memory Chroma (useful for unit tests / ephemeral runs).
        self.persist_path = str(settings.CHROMA_PERSIST_PATH or "").strip()
        if self.persist_path:
            os.makedirs(self.persist_path, exist_ok=True)
        self.store_by_tenant: dict[str, Any] = {}

    def _get_store(self, tenant_id: UUID | None) -> tuple[str, Any]:
        key = str(tenant_id or settings.DEFAULT_TENANT_ID)
        store = self.store_by_tenant.get(key)
        if store is None:
            chroma_cls = _get_chroma_cls()
            kwargs: dict[str, Any] = {"collection_name": key, "embedding_function": self.emb}
            if self.persist_path:
                kwargs["persist_directory"] = self.persist_path
            store = chroma_cls(**kwargs)
            self.store_by_tenant[key] = store
        return key, store

    def add_documents(self, docs: list[dict[str, Any]], document_id: UUID, tenant_id: UUID):
        texts = [d.get("content", "") for d in docs]
        metadatas = []
        ids = []
        for idx, doc in enumerate(docs):
            meta = dict(doc.get("metadata") or {})
            meta.setdefault("document_id", str(document_id))
            meta.setdefault("tenant_id", str(tenant_id))
            meta.setdefault("chunk_index", idx)
            if meta.get("chunk_id"):
                meta["chunk_id"] = str(meta.get("chunk_id"))
            if "img_id" in meta and "image_id" not in meta:
                meta["image_id"] = meta.get("img_id")
            meta.setdefault("image_url", meta.get("img_url"))
            metadatas.append(meta)
            ids.append(str(meta.get("chunk_id")) if meta.get("chunk_id") else f"{document_id}_{idx}")
        _key, store = self._get_store(tenant_id)
        store.add_texts(texts=texts, metadatas=metadatas, ids=ids)
        # Chroma (0.4+) persists automatically; manual persist is deprecated/no-op.
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
        _, store = self._get_store(tenant_id)
        allowed = {str(did) for did in document_ids} if document_ids else None
        results = store.similarity_search_with_score(query, k=top_k * 2)
        out: list[dict[str, Any]] = []
        for doc, score in results:
            meta = doc.metadata or {}
            if allowed and meta.get("document_id") not in allowed:
                continue
            if metadata_filter and not _match_metadata_filter(meta, metadata_filter):
                continue
            similarity = 1.0 / (1.0 + float(score))
            if similarity < score_threshold:
                continue
            out.append(
                {
                    "chunk_id": doc.id,
                    "content": doc.page_content,
                    "metadata": meta,
                    "score": similarity,
                    "vector_score": similarity,
                }
            )
        out.sort(key=lambda x: x["score"], reverse=True)
        return out[:top_k]

    def delete_by_document_id(self, document_id: UUID, tenant_id: UUID | None = None) -> None:
        _, store = self._get_store(tenant_id)
        target = str(document_id)
        try:
            # LangChain Chroma lacks a stable where delete API; use the underlying collection.
            store._collection.delete(where={"document_id": target})  # type: ignore[attr-defined]
            # Chroma (0.4+) persists automatically; manual persist is deprecated/no-op.
        except Exception:
            return

    def delete_by_document_id_and_filter(
        self,
        *,
        document_id: UUID,
        tenant_id: UUID | None,
        metadata_filter: dict[str, Any],
    ) -> None:
        if not metadata_filter or not isinstance(metadata_filter, dict):
            return self.delete_by_document_id(document_id, tenant_id=tenant_id)

        _, store = self._get_store(tenant_id)
        target = str(document_id)

        # Chroma's where spec isn't compatible with our generic filter syntax.
        # Instead: fetch all rows for this document_id (which is cheap for typical local-dev usage),
        # then filter in Python with our matcher and delete by explicit IDs.
        try:
            collection = store._collection  # type: ignore[attr-defined]
            # Note: Chroma's `include` does not accept "ids" (they are always returned).
            got = collection.get(where={"document_id": target}, include=["metadatas"])
            ids = got.get("ids") or []
            metas = got.get("metadatas") or []
            ids_to_delete: list[str] = []
            for cid, meta in zip(ids, metas, strict=False):
                if not isinstance(meta, dict):
                    continue
                if _match_metadata_filter(meta, metadata_filter):
                    ids_to_delete.append(str(cid))
            if not ids_to_delete:
                return
            collection.delete(ids=ids_to_delete)
        except Exception as exc:
            raise NotImplementedError("Selective delete is not supported for Chroma backend") from exc


_VECTOR_STORE_SINGLETONS: dict[str, BaseVectorStore] = {}
_VECTOR_STORE_SINGLETONS_LOCK = threading.RLock()
_EMBEDDING_AWARE_VECTOR_BACKENDS = frozenset({"memory", "faiss", "chroma", "qdrant", "pgvector"})


def _normalize_region(region: str | None = None) -> str:
    return str(region or getattr(settings, "DATA_REGION", "") or "").strip().lower()


def _load_vector_region_backends() -> dict[str, str]:
    raw = getattr(settings, "VECTOR_REGION_BACKENDS", "") or ""
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
    requested = str(backend or settings.VECTOR_BACKEND or "milvus").strip().lower()
    if region_key:
        requested = _load_vector_region_backends().get(region_key, requested)
    return requested, (region_key or None)


def _embedding_client_cache_token() -> str:
    provider = EmbeddingProviders.PROVIDER_MAP.get(
        str(getattr(settings, "EMBEDDING_PROVIDER", "openai_compatible") or "openai_compatible").strip().lower(),
        "openai_compatible",
    )
    model = str(getattr(settings, "EMBEDDING_MODEL", "") or "text-embedding-3-small").strip()
    api_base = str(getattr(settings, "EMBEDDING_API_BASE", "") or getattr(settings, "LLM_API_BASE", "") or "").strip()
    api_key = str(getattr(settings, "EMBEDDING_API_KEY", "") or getattr(settings, "LLM_API_KEY", "") or "").strip()
    dimension = str(getattr(settings, "EMBEDDING_DIMENSION", "") or "").strip()
    api_key_hash = stable_hash(api_key, length=16) if api_key else ""
    return stable_hash(f"{provider}|{model}|{api_base}|{api_key_hash}|{dimension}", length=24)


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
    Note: memory/faiss backends keep state in-process; singleton avoids losing data on each call.
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
        elif backend_name == "faiss":
            store = FAISSVectorStore()
        elif backend_name == "chroma":
            store = ChromaVectorStore()
        elif backend_name == "qdrant":
            store = QdrantVectorStore()
        elif backend_name == "pgvector":
            store = PGVectorStore()
        else:
            store = StubVectorStore()

        _VECTOR_STORE_SINGLETONS[cache_key] = store
        return store
