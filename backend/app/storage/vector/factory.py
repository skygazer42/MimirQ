"""
Vector store 路由器：支持多后端占位，当前实现 Milvus，其他后端留作扩展。
在配置 VECTOR_BACKEND 切换，确保知识库检索路径集中管理。
"""
from typing import List, Dict, Any, Optional, Tuple
from uuid import UUID
import logging
import math
import os

from app.core.config import settings
from app.storage.vector.milvus import milvus_store
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_community.vectorstores import Chroma


logger = logging.getLogger(__name__)


class BaseVectorStore:
    """统一接口定义，便于未来扩展 FAISS/Chroma/Memory。"""

    def add_documents(self, docs: List[Dict[str, Any]], document_id: UUID, tenant_id: UUID):
        raise NotImplementedError

    def search(
        self,
        query: str,
        top_k: int,
        score_threshold: float,
        document_ids: Optional[List[UUID]],
        tenant_id: Optional[UUID],
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def delete_by_document_id(self, document_id: UUID, tenant_id: Optional[UUID] = None) -> None:
        raise NotImplementedError


class MilvusVectorStore(BaseVectorStore):
    """Milvus 后端封装。"""

    def add_documents(self, docs: List[Dict[str, Any]], document_id: UUID, tenant_id: UUID):
        return milvus_store.add_documents(docs, document_id, tenant_id)

    def search(
        self,
        query: str,
        top_k: int,
        score_threshold: float,
        document_ids: Optional[List[UUID]],
        tenant_id: Optional[UUID],
    ) -> List[Dict[str, Any]]:
        return milvus_store.search(
            query=query,
            top_k=top_k,
            score_threshold=score_threshold,
            document_ids=document_ids,
            tenant_id=tenant_id,
        )

    def delete_by_document_id(self, document_id: UUID, tenant_id: Optional[UUID] = None) -> None:
        milvus_store.delete_by_document_id(document_id, tenant_id=tenant_id)


class StubVectorStore(BaseVectorStore):
    """占位实现，便于未来接入其他后端。"""

    def add_documents(self, docs: List[Dict[str, Any]], document_id: UUID, tenant_id: UUID):
        raise RuntimeError("Vector backend not implemented")

    def search(
        self,
        query: str,
        top_k: int,
        score_threshold: float,
        document_ids: Optional[List[UUID]],
        tenant_id: Optional[UUID],
    ) -> List[Dict[str, Any]]:
        return []

    def delete_by_document_id(self, document_id: UUID, tenant_id: Optional[UUID] = None) -> None:
        return


class MemoryVectorStore(BaseVectorStore):
    """
    轻量内存向量库：便于本地测试或无 Milvus 场景。
    使用 OpenAI 兼容 Embeddings（需配置 EMBEDDING_API_KEY/LLM_API_KEY）。
    """

    def __init__(self):
        api_key = settings.EMBEDDING_API_KEY or settings.LLM_API_KEY or ""
        base_url = settings.EMBEDDING_API_BASE or settings.LLM_API_BASE or ""
        model = settings.EMBEDDING_MODEL or "text-embedding-3-small"
        if not api_key:
            raise RuntimeError("MemoryVectorStore requires EMBEDDING_API_KEY or LLM_API_KEY")
        self.emb = OpenAIEmbeddings(api_key=api_key, base_url=base_url, model=model)
        self.storage: List[Tuple[List[float], Dict[str, Any]]] = []

    def add_documents(self, docs: List[Dict[str, Any]], document_id: UUID, tenant_id: UUID):
        texts = [d.get("content", "") for d in docs]
        vectors = self.emb.embed_documents(texts)
        for vec, doc in zip(vectors, docs):
            meta = dict(doc.get("metadata") or {})
            meta.setdefault("document_id", str(document_id))
            meta.setdefault("tenant_id", str(tenant_id))
            meta.setdefault("content", doc.get("content", ""))
            self.storage.append((vec, meta))
        # 内存场景不返回真实向量 ID，用占位
        return [f"{document_id}_mem_{i}" for i in range(len(texts))]

    def search(
        self,
        query: str,
        top_k: int,
        score_threshold: float,
        document_ids: Optional[List[UUID]],
        tenant_id: Optional[UUID],
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


class FAISSVectorStore(BaseVectorStore):
    """
    FAISS 后端：适合单机/本地开发。支持可选持久化到路径。
    """

    def __init__(self):
        api_key = settings.EMBEDDING_API_KEY or settings.LLM_API_KEY or ""
        base_url = settings.EMBEDDING_API_BASE or settings.LLM_API_BASE or ""
        model = settings.EMBEDDING_MODEL or "text-embedding-3-small"
        if not api_key:
            raise RuntimeError("FAISSVectorStore requires EMBEDDING_API_KEY or LLM_API_KEY")
        self.emb = OpenAIEmbeddings(api_key=api_key, base_url=base_url, model=model)
        self.store_by_tenant: Dict[str, FAISS] = {}
        self.persist_path = settings.FAISS_STORE_PATH
        self.allow_dangerous_deserialization = bool(
            getattr(settings, "FAISS_ALLOW_DANGEROUS_DESERIALIZATION", False)
        )
        self._warned_dangerous_deserialization = False

    def _get_store(self, tenant_id: Optional[UUID]) -> Tuple[str, Optional[FAISS]]:
        key = str(tenant_id or settings.DEFAULT_TENANT_ID)
        store = self.store_by_tenant.get(key)
        # 若存在持久化路径且内存中未加载，则尝试加载
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
                store = FAISS.load_local(
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
            metadatas.append(meta)
            ids.append(f"{document_id}_{idx}")

        key, store = self._get_store(tenant_id)
        if store is None:
            store = FAISS.from_texts(texts=texts, embedding=self.emb, metadatas=metadatas, ids=ids)
        else:
            store.add_texts(texts=texts, metadatas=metadatas, ids=ids)

        self.store_by_tenant[key] = store
        # 持久化（每次全量保存）
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

        # 持久化（覆盖保存）
        if self.persist_path:
            os.makedirs(self.persist_path, exist_ok=True)
            store.save_local(self.persist_path, index_name=key)


class ChromaVectorStore(BaseVectorStore):
    """Chroma 后端，持久化到本地路径。"""

    def __init__(self):
        api_key = settings.EMBEDDING_API_KEY or settings.LLM_API_KEY or ""
        base_url = settings.EMBEDDING_API_BASE or settings.LLM_API_BASE or ""
        model = settings.EMBEDDING_MODEL or "text-embedding-3-small"
        if not api_key:
            raise RuntimeError("ChromaVectorStore requires EMBEDDING_API_KEY or LLM_API_KEY")
        self.emb = OpenAIEmbeddings(api_key=api_key, base_url=base_url, model=model)
        self.persist_path = settings.CHROMA_PERSIST_PATH
        os.makedirs(self.persist_path, exist_ok=True)
        self.store_by_tenant: Dict[str, Chroma] = {}

    def _get_store(self, tenant_id: Optional[UUID]) -> Tuple[str, Chroma]:
        key = str(tenant_id or settings.DEFAULT_TENANT_ID)
        store = self.store_by_tenant.get(key)
        if store is None:
            store = Chroma(
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
            metadatas.append(meta)
            ids.append(f"{document_id}_{idx}")
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
    ) -> List[Dict[str, Any]]:
        _, store = self._get_store(tenant_id)
        allowed = {str(did) for did in document_ids} if document_ids else None
        results = store.similarity_search_with_score(query, k=top_k * 2)
        out: List[Dict[str, Any]] = []
        for doc, score in results:
            meta = doc.metadata or {}
            if allowed and meta.get("document_id") not in allowed:
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
            # LangChain Chroma 没有稳定的 where delete API，这里使用底层 collection
            store._collection.delete(where={"document_id": target})  # type: ignore[attr-defined]
            store.persist()
        except Exception:
            return


_VECTOR_STORE_SINGLETONS: Dict[str, BaseVectorStore] = {}


def get_vector_store() -> BaseVectorStore:
    """
    返回当前配置的向量库后端（单例）。
    说明：memory/faiss 这类后端需要在进程内保留状态；用单例避免每次调用丢失数据。
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
