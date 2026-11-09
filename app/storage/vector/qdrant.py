import math
from typing import TYPE_CHECKING, Any
from uuid import UUID

from app.core.config import settings
from app.core.constants import EmbeddingProviders
from app.rag.core.filters import match_metadata_filter
from app.rag.embedding import create_langchain_embeddings_from_config

if TYPE_CHECKING:
    from app.rag.embedding.adapter import LangChainEmbeddingsAdapter


class QdrantVectorStore:
    """
    Deterministic in-process Qdrant scaffold.

    Scope:
    - provides the same interface as other vector stores
    - keeps behavior dependency-light for local/backend development
    - can later be swapped to a real qdrant-client implementation
    """

    def __init__(self) -> None:
        provider = EmbeddingProviders.PROVIDER_MAP.get(
            (settings.EMBEDDING_PROVIDER or "openai_compatible").lower(), "openai_compatible"
        )
        api_key = settings.EMBEDDING_API_KEY or settings.LLM_API_KEY
        base_url = settings.EMBEDDING_API_BASE or settings.LLM_API_BASE
        model = settings.EMBEDDING_MODEL or "text-embedding-3-small"
        self.emb = create_langchain_embeddings_from_config(
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
            dimension=None,
        )
        self.storage: list[tuple[list[float], dict[str, Any]]] = []

    def add_documents(self, docs: list[dict[str, Any]], document_id: UUID, tenant_id: UUID) -> list[str]:
        texts = [d["content"] for d in docs]
        vectors = self.emb.embed_documents(texts)
        ids: list[str] = []
        for idx, (vec, doc) in enumerate(zip(vectors, docs, strict=False)):
            meta = dict(doc.get("metadata") or {})
            meta.setdefault("document_id", str(document_id))
            meta.setdefault("tenant_id", str(tenant_id))
            meta.setdefault("content", doc["content"])
            cid = str(meta.get("chunk_id") or f"{document_id}_qdrant_{idx}")
            meta["chunk_id"] = cid
            self.storage.append((vec, meta))
            ids.append(cid)
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

        out: list[dict[str, Any]] = []
        for vec, meta in self.storage:
            if allowed_tenant and meta["tenant_id"] != allowed_tenant:
                continue
            if allowed_ids and meta["document_id"] not in allowed_ids:
                continue
            if metadata_filter and not match_metadata_filter(meta, metadata_filter):
                continue
            score = cosine(qvec, vec)
            if score < score_threshold:
                continue
            out.append(
                {
                    "chunk_id": meta.get("chunk_id"),
                    "content": meta["content"],
                    "metadata": meta,
                    "score": score,
                    "vector_score": score,
                }
            )
        out.sort(key=lambda row: float(row.get("score") or 0.0), reverse=True)
        return out[:top_k]

    def delete_by_document_id(self, document_id: UUID, tenant_id: UUID | None = None) -> None:
        doc_id = str(document_id)
        tenant = str(tenant_id) if tenant_id else None
        self.storage = [
            (vec, meta)
            for vec, meta in self.storage
            if not (
                meta["document_id"] == doc_id
                and (tenant is None or meta["tenant_id"] == tenant)
            )
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
        self.storage = [
            (vec, meta)
            for vec, meta in self.storage
            if not (
                meta["document_id"] == doc_id
                and (tenant is None or meta["tenant_id"] == tenant)
                and match_metadata_filter(meta, metadata_filter)
            )
        ]

    def get_embedding_client(self) -> "LangChainEmbeddingsAdapter":
        return self.emb
