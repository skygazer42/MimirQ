"""
Vector store router: supports multiple backends.
Milvus is implemented today; other backends are placeholders for extension.
Switch via VECTOR_BACKEND to keep the retrieval path centralized.
"""
from typing import List, Dict, Any, Optional, Tuple, TYPE_CHECKING
from uuid import UUID
import logging
import math
import os

from app.core.config import settings
from app.core.constants import EmbeddingProviders
from app.storage.vector.milvus import milvus_store
from app.rag.embedding import create_langchain_embeddings_from_config
from app.rag.core.filters import match_metadata_filter


logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    pass

_FAISS_CLS = None
_CHROMA_CLS = None


def _get_faiss_cls():
    global _FAISS_CLS
    if _FAISS_CLS is not None:
        return _FAISS_CLS
    try:
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
        from langchain_community.vectorstores import Chroma

        _CHROMA_CLS = Chroma
        return _CHROMA_CLS
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "Chroma vector backend requires optional dependencies. "
            "Install `chromadb` and `langchain-community`."
        ) from exc


def _match_metadata_filter(meta: Dict[str, Any], filter_spec: Dict[str, Any]) -> bool:
    """Metadata filter matcher (supports operators)."""
    return match_metadata_filter(meta, filter_spec)


class BaseVectorStore:
    """Unified interface for future FAISS/Chroma/Memory extensions."""

    def add_documents(self, docs: List[Dict[str, Any]], document_id: UUID, tenant_id: UUID):
        raise NotImplementedError

    def search(
        self,
        query: str,
        top_k: int,
        score_threshold: float,
        document_ids: Optional[List[UUID]],
        tenant_id: Optional[UUID],
        metadata_filter: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def delete_by_document_id(self, document_id: UUID, tenant_id: Optional[UUID] = None) -> None:
        raise NotImplementedError

    def delete_by_document_id_and_filter(
        self,
        *,
        document_id: UUID,
        tenant_id: Optional[UUID],
        metadata_filter: Dict[str, Any],
    ) -> None:
        """
        Best-effort selective delete for a single document.

        Used for versioned re-indexing/rollback (e.g. delete only the target pipeline version).
        Backends that cannot support this should raise NotImplementedError.
        """
        raise NotImplementedError


class MilvusVectorStore(BaseVectorStore):
    """Milvus backend wrapper."""

    def add_documents(self, docs: List[Dict[str, Any]], document_id: UUID, tenant_id: UUID):
        return milvus_store.add_documents(docs, document_id, tenant_id)

    def search(
        self,
        query: str,
        top_k: int,
        score_threshold: float,
        document_ids: Optional[List[UUID]],
        tenant_id: Optional[UUID],
        metadata_filter: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        return milvus_store.search(
            query=query,
            top_k=top_k,
            score_threshold=score_threshold,
            document_ids=document_ids,
            tenant_id=tenant_id,
            metadata_filter=metadata_filter,
        )

    def delete_by_document_id(self, document_id: UUID, tenant_id: Optional[UUID] = None) -> None:
        milvus_store.delete_by_document_id(document_id, tenant_id=tenant_id)

    def delete_by_document_id_and_filter(
        self,
        *,
        document_id: UUID,
        tenant_id: Optional[UUID],
        metadata_filter: Dict[str, Any],
    ) -> None:
        milvus_store.delete_by_document_id_and_filter(document_id=document_id, tenant_id=tenant_id, metadata_filter=metadata_filter)


class StubVectorStore(BaseVectorStore):
    """Placeholder implementation for future backends."""

    def add_documents(self, docs: List[Dict[str, Any]], document_id: UUID, tenant_id: UUID):
        raise RuntimeError("Vector backend not implemented")

    def search(
        self,
        query: str,
        top_k: int,
        score_threshold: float,
        document_ids: Optional[List[UUID]],
        tenant_id: Optional[UUID],
        metadata_filter: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        return []

    def delete_by_document_id(self, document_id: UUID, tenant_id: Optional[UUID] = None) -> None:
        return

    def delete_by_document_id_and_filter(
        self,
        *,
        document_id: UUID,
        tenant_id: Optional[UUID],
        metadata_filter: Dict[str, Any],
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
        self.storage: List[Tuple[List[float], Dict[str, Any]]] = []

    def add_documents(self, docs: List[Dict[str, Any]], document_id: UUID, tenant_id: UUID):
        texts = [d.get("content", "") for d in docs]
        vectors = self.emb.embed_documents(texts)
        for vec, doc in zip(vectors, docs):
            meta = dict(doc.get("metadata") or {})
            meta.setdefault("document_id", str(document_id))
            meta.setdefault("tenant_id", str(tenant_id))
            if meta.get("chunk_id"):
                meta["chunk_id"] = str(meta.get("chunk_id"))
            meta.setdefault("content", doc.get("content", ""))
            self.storage.append((vec, meta))
        # In-memory mode uses placeholder IDs instead of real vector IDs.
        ids: List[str] = []
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
        document_ids: Optional[List[UUID]],
        tenant_id: Optional[UUID],
        metadata_filter: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        if not self.storage:
            return []
        qvec = self.emb.embed_query(query)
        allowed_ids = {str(did) for did in document_ids} if document_ids else None
        allowed_tenant = str(tenant_id) if tenant_id else None

        def cosine(a: List[float], b: List[float]) -> float:
            num = sum(x * y for x, y in zip(a, b))
            denom = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
            return num / denom if denom else 0.0

        results: List[Dict[str, Any]] = []
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

    def delete_by_document_id(self, document_id: UUID, tenant_id: Optional[UUID] = None) -> None:
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
        tenant_id: Optional[UUID],
        metadata_filter: Dict[str, Any],
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
        self.store_by_tenant: Dict[str, Any] = {}
        self.persist_path = settings.FAISS_STORE_PATH
        self.allow_dangerous_deserialization = bool(
            getattr(settings, "FAISS_ALLOW_DANGEROUS_DESERIALIZATION", False)
        )
        self._warned_dangerous_deserialization = False

    def _get_store(self, tenant_id: Optional[UUID]) -> Tuple[str, Optional[Any]]:
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

    def add_documents(self, docs: List[Dict[str, Any]], document_id: UUID, tenant_id: UUID):
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
        document_ids: Optional[List[UUID]],
        tenant_id: Optional[UUID],
        metadata_filter: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        key, store = self._get_store(tenant_id)
        if store is None:
            return []
        allowed = {str(did) for did in document_ids} if document_ids else None
        results = store.similarity_search_with_score(query, k=top_k * 2)
        out: List[Dict[str, Any]] = []
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

    def delete_by_document_id(self, document_id: UUID, tenant_id: Optional[UUID] = None) -> None:
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
            except Exception:
                pass

        # Persist (overwrite save).
        if self.persist_path:
            os.makedirs(self.persist_path, exist_ok=True)
            store.save_local(self.persist_path, index_name=key)

    def delete_by_document_id_and_filter(
        self,
        *,
        document_id: UUID,
        tenant_id: Optional[UUID],
        metadata_filter: Dict[str, Any],
    ) -> None:
        # FAISS wrapper doesn't support metadata-where deletes reliably; fail closed.
        raise NotImplementedError("Selective delete is not supported for FAISS backend")


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
        self.persist_path = settings.CHROMA_PERSIST_PATH
        os.makedirs(self.persist_path, exist_ok=True)
        self.store_by_tenant: Dict[str, Any] = {}

    def _get_store(self, tenant_id: Optional[UUID]) -> Tuple[str, Any]:
        key = str(tenant_id or settings.DEFAULT_TENANT_ID)
        store = self.store_by_tenant.get(key)
        if store is None:
            chroma_cls = _get_chroma_cls()
            store = chroma_cls(
                collection_name=key,
                embedding_function=self.emb,
                persist_directory=self.persist_path,
            )
            self.store_by_tenant[key] = store
        return key, store

    def add_documents(self, docs: List[Dict[str, Any]], document_id: UUID, tenant_id: UUID):
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
        key, store = self._get_store(tenant_id)
        store.add_texts(texts=texts, metadatas=metadatas, ids=ids)
        store.persist()
        return ids

    def search(
        self,
        query: str,
        top_k: int,
        score_threshold: float,
        document_ids: Optional[List[UUID]],
        tenant_id: Optional[UUID],
        metadata_filter: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        _, store = self._get_store(tenant_id)
        allowed = {str(did) for did in document_ids} if document_ids else None
        results = store.similarity_search_with_score(query, k=top_k * 2)
        out: List[Dict[str, Any]] = []
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

    def delete_by_document_id(self, document_id: UUID, tenant_id: Optional[UUID] = None) -> None:
        _, store = self._get_store(tenant_id)
        target = str(document_id)
        try:
            # LangChain Chroma lacks a stable where delete API; use the underlying collection.
            store._collection.delete(where={"document_id": target})  # type: ignore[attr-defined]
            store.persist()
        except Exception:
            return

    def delete_by_document_id_and_filter(
        self,
        *,
        document_id: UUID,
        tenant_id: Optional[UUID],
        metadata_filter: Dict[str, Any],
    ) -> None:
        # The underlying Chroma where spec is not compatible with our generic filter syntax.
        # Avoid surprising deletes; callers should fall back to full delete or rebuild.
        raise NotImplementedError("Selective delete is not supported for Chroma backend")


_VECTOR_STORE_SINGLETONS: Dict[str, BaseVectorStore] = {}


def get_vector_store() -> BaseVectorStore:
    """
    Return the configured vector store backend (singleton).
    Note: memory/faiss backends keep state in-process; singleton avoids losing data on each call.
    """
    backend = (settings.VECTOR_BACKEND or "milvus").lower()
    cached = _VECTOR_STORE_SINGLETONS.get(backend)
    if cached is not None:
        return cached

    if backend == "milvus":
        store: BaseVectorStore = MilvusVectorStore()
    elif backend == "memory":
        store = MemoryVectorStore()
    elif backend == "faiss":
        store = FAISSVectorStore()
    elif backend == "chroma":
        store = ChromaVectorStore()
    else:
        store = StubVectorStore()

    _VECTOR_STORE_SINGLETONS[backend] = store
    return store
