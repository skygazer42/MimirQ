"""
Simple Milvus adapter for SAG entities/events, reusing the project's embedding setup.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.storage.vector.milvus import milvus_store
from app.core.config import settings


class MilvusAdapter:
    def __init__(self, collection_name: str, vector_field: str = "embedding"):
        self.collection_name = collection_name
        self.vector_field = vector_field
        self._store = None
        self._embedding_model = None

    def _ensure_store(self):
        if self._store is not None:
            return

        if self._embedding_model is None:
            # reuse the embedding provider initialized in milvus_store
            self._embedding_model = milvus_store._init_embedding_model()  # noqa: SLF001

        from langchain_community.vectorstores import Milvus as LCMilvus

        connection_args = {
            "host": settings.MILVUS_HOST,
            "port": str(settings.MILVUS_PORT),
            "user": settings.MILVUS_USER,
            "password": settings.MILVUS_PASSWORD,
        }

        index_params = {
            "metric_type": "COSINE",
            "index_type": "IVF_FLAT",
            "params": {"nlist": 1024},
        }
        search_params = {"metric_type": "COSINE", "params": {"nprobe": 10}}

        self._store = LCMilvus(
            embedding_function=self._embedding_model,
            collection_name=self.collection_name,
            connection_args=connection_args,
            index_params=index_params,
            search_params=search_params,
            auto_id=False,
            primary_field="id",
            text_field="content",
            vector_field=self.vector_field,
        )

    def add_vectors(self, items: List[Dict[str, Any]]) -> List[str]:
        """
        items: [{"id": str, "content": str, "metadata": dict}]
        """
        if not items:
            return []
        self._ensure_store()
        assert self._store is not None

        texts = []
        metadatas = []
        ids = []
        for item in items:
            ids.append(item["id"])
            texts.append(item.get("content", "")[:65_000])
            meta = item.get("metadata") or {}
            meta.setdefault("id", item.get("id"))
            meta.setdefault("content", item.get("content"))
            metadatas.append(meta)

        pks = self._store.add_texts(texts=texts, metadatas=metadatas, ids=ids)
        return [str(pk) for pk in pks]

    def delete(self, ids: List[str]):
        if not ids:
            return
        self._ensure_store()
        assert self._store is not None
        self._store.delete(ids)

    def search(
        self,
        query_vector: List[float],
        top_k: int = 10,
        expr: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        self._ensure_store()
        assert self._store is not None

        results = self._store.similarity_search_with_score_by_vector(
            embedding=query_vector,
            k=top_k,
            expr=expr,
        )
        formatted: List[Dict[str, Any]] = []
        for doc, score in results:
            formatted.append(
                {
                    "id": doc.id,
                    "metadata": doc.metadata or {},
                    "score": float(score),
                    "content": doc.page_content,
                }
            )
        return formatted
