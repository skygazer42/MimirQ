"""
混合检索器：向量检索 + BM25 + 可选 MMR 多样性重排。
参考示例仓库的 RAG_Agent，将检索模式和重排策略做成可配置化。
"""
from __future__ import annotations

from typing import List, Dict, Any, Optional
from uuid import UUID
import math
from collections import Counter
import jieba

from langchain_core.documents import Document
from langchain_core.callbacks import CallbackManagerForRetrieverRun, AsyncCallbackManagerForRetrieverRun
from langchain_core.retrievers import BaseRetriever
from langchain_community.retrievers.bm25 import BM25Retriever
from pydantic import PrivateAttr, ConfigDict

from app.services.vector_router import get_vector_store
from app.models.document import DocumentChunk
from app.core.config import settings


class HybridRetriever(BaseRetriever):
    """混合检索器：向量 + 关键词 BM25，可选 MMR 重排。"""

    k: int = 5
    score_threshold: float = settings.SIMILARITY_THRESHOLD
    alpha: float = 0.6
    retrieval_mode: str = "hybrid"  # hybrid | vector | keyword | mmr
    enable_weight_rerank: bool = True
    vector_weight: float = 0.6
    keyword_weight: float = 0.4
    mmr_lambda: float = settings.RETRIEVAL_MMR_LAMBDA
    tenant_id: Optional[UUID] = None
    document_ids: Optional[List[UUID]] = None

    model_config = ConfigDict(arbitrary_types_allowed=True)

    _bm25_retrievers: Dict[str, BM25Retriever] = PrivateAttr(default_factory=dict)
    _bm25_docs: Dict[str, List[Document]] = PrivateAttr(default_factory=dict)

    def _tenant_key(self, tenant_id: Optional[UUID]) -> str:
        return str(tenant_id or settings.DEFAULT_TENANT_ID)

    def build_bm25_index(self, chunks: List[DocumentChunk], tenant_id: Optional[UUID] = None):
        """构建/重建 BM25 索引。"""
        if not chunks:
            return

        tenant_key = self._tenant_key(tenant_id)
        docs: List[Document] = []
        for chunk in chunks:
            meta = dict(chunk.doc_metadata or {})
            meta.setdefault("tenant_id", str(chunk.tenant_id))
            meta.setdefault("document_id", str(chunk.document_id))
            meta.setdefault("chunk_index", chunk.chunk_index)
            meta.setdefault("source", meta.get("source", "unknown"))
            meta.setdefault("page", chunk.page_number or meta.get("page"))
            meta.setdefault("image_id", meta.get("image_id"))
            meta.setdefault("image_url", meta.get("image_url"))

            docs.append(Document(page_content=chunk.content, id=str(chunk.id), metadata=meta))

        retriever = BM25Retriever.from_documents(
            docs,
            preprocess_func=lambda text: list(jieba.cut_for_search(text)),
            k=10,
        )
        self._bm25_retrievers[tenant_key] = retriever
        self._bm25_docs[tenant_key] = docs
        print(f"[OK] BM25 index built with {len(docs)} chunks for tenant {tenant_key}")

    def _search_bm25(
        self,
        query: str,
        top_k: int = 10,
        document_ids: Optional[List[UUID]] = None,
        tenant_id: Optional[UUID] = None,
    ) -> List[Dict[str, Any]]:
        """BM25 关键词检索（内部使用，返回带分数的 dict）。"""
        tenant_key = self._tenant_key(tenant_id)
        retriever = self._bm25_retrievers.get(tenant_key)
        docs = self._bm25_docs.get(tenant_key)
        if retriever is None or docs is None:
            print("[WARN] BM25 index not initialized, skipping keyword search")
            return []

        allowed_ids = {str(doc_id) for doc_id in document_ids} if document_ids else None
        processed_query = retriever.preprocess_func(query)
        scores = retriever.vectorizer.get_scores(processed_query)  # type: ignore[attr-defined]

        results: List[Dict[str, Any]] = []
        for doc, score in zip(docs, scores):
            meta = doc.metadata or {}
            if allowed_ids and str(meta.get("document_id")) not in allowed_ids:
                continue
            results.append(
                {
                    "chunk_id": doc.id,
                    "content": doc.page_content,
                    "metadata": {
                        "tenant_id": meta.get("tenant_id"),
                        "document_id": meta.get("document_id"),
                        "source": meta.get("source", "unknown"),
                        "page": meta.get("page"),
                        "chunk_index": meta.get("chunk_index"),
                        "image_id": meta.get("image_id"),
                        "image_url": meta.get("image_url"),
                        "bm25_score": float(score),
                    },
                    "score": float(score),
                }
            )

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def _hybrid_search(
        self,
        query: str,
        top_k: int = 5,
        score_threshold: float = 0.7,
        document_ids: Optional[List[UUID]] = None,
        tenant_id: Optional[UUID] = None,
        alpha: float = 0.5,
        enable_weight_rerank: bool = True,
        vector_weight: float = 0.6,
        keyword_weight: float = 0.4,
        retrieval_mode: str = "hybrid",
        mmr_lambda: float = 0.7,
    ) -> List[Dict[str, Any]]:
        """混合检索：向量检索 + BM25，可选重排。"""
        retrieval_mode = (retrieval_mode or "hybrid").lower()

        # 1) 向量检索
        vector_results: List[Dict[str, Any]] = []
        if retrieval_mode in ("hybrid", "vector", "mmr"):
            vector_store = get_vector_store()
            try:
                vector_results = vector_store.search(
                    query=query,
                    top_k=top_k * 2,
                    score_threshold=score_threshold,
                    document_ids=document_ids,
                    tenant_id=tenant_id,
                )
            except Exception as exc:
                print(f"[WARN] Vector search failed: {exc}")
                vector_results = []

        # 2) BM25 检索
        bm25_results: List[Dict[str, Any]] = []
        if retrieval_mode in ("hybrid", "keyword", "mmr"):
            bm25_results = self._search_bm25(
                query=query,
                top_k=top_k * 2,
                document_ids=document_ids,
                tenant_id=tenant_id,
            )

        # 3) 分数归一 + 线性合并
        merged_results = self._merge_results(vector_results, bm25_results, alpha=alpha)

        # 4) 重排策略
        if retrieval_mode == "mmr" and merged_results:
            merged_results = self._mmr_rerank(merged_results, query=query, top_k=top_k, lambda_mult=mmr_lambda)
        elif enable_weight_rerank and merged_results:
            merged_results = self._weight_rerank(
                query=query,
                documents=merged_results,
                vector_weight=vector_weight,
                keyword_weight=keyword_weight,
            )

        return merged_results[:top_k]

    # ---- LangChain Retriever API ----

    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: CallbackManagerForRetrieverRun,
    ) -> List[Document]:
        results = self._hybrid_search(
            query=query,
            top_k=self.k,
            score_threshold=self.score_threshold,
            document_ids=self.document_ids,
            tenant_id=self.tenant_id,
            alpha=self.alpha,
            enable_weight_rerank=self.enable_weight_rerank,
            vector_weight=self.vector_weight,
            keyword_weight=self.keyword_weight,
            retrieval_mode=self.retrieval_mode,
            mmr_lambda=self.mmr_lambda,
        )
        docs: List[Document] = []
        for r in results:
            meta = dict(r.get("metadata") or {})
            meta["score"] = r.get("score")
            meta["vector_score"] = r.get("vector_score")
            meta["bm25_score"] = r.get("bm25_score")
            docs.append(Document(page_content=r.get("content", ""), metadata=meta, id=r.get("chunk_id")))
        return docs

    async def _aget_relevant_documents(
        self,
        query: str,
        *,
        run_manager: AsyncCallbackManagerForRetrieverRun,
    ) -> List[Document]:
        return self._get_relevant_documents(query, run_manager=CallbackManagerForRetrieverRun.get_noop_manager())

    def _result_key(self, result: Dict[str, Any]) -> str:
        meta = result.get("metadata") or {}
        doc_id = meta.get("document_id")
        chunk_index = meta.get("chunk_index")
        if doc_id is not None and chunk_index is not None:
            return f"{doc_id}:{chunk_index}"
        return str(result.get("chunk_id") or chunk_index or hash(result.get("content", "")))

    def _merge_results(
        self,
        vector_results: List[Dict[str, Any]],
        bm25_results: List[Dict[str, Any]],
        alpha: float = 0.5,
    ) -> List[Dict[str, Any]]:
        """归一化两路分数后线性合并。"""

        def normalize(results: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
            if not results:
                return {}
            scores = [r.get("score", 0.0) for r in results]
            min_score = min(scores)
            max_score = max(scores)
            rng = max_score - min_score if max_score > min_score else 1.0
            out: Dict[str, Dict[str, Any]] = {}
            for r in results:
                key = self._result_key(r)
                out[key] = {
                    "score": (r.get("score", 0.0) - min_score) / rng,
                    "data": r,
                }
            return out

        vector_norm = normalize(vector_results)
        bm25_norm = normalize(bm25_results)

        merged: Dict[str, Dict[str, Any]] = {}
        for key in set(vector_norm.keys()) | set(bm25_norm.keys()):
            v_score = vector_norm.get(key, {}).get("score", 0.0)
            b_score = bm25_norm.get(key, {}).get("score", 0.0)
            data = vector_norm.get(key, {}).get("data") or bm25_norm.get(key, {}).get("data")
            if not data:
                continue
            merged[key] = {
                **data,
                "vector_score": v_score,
                "bm25_score": b_score,
                "score": alpha * v_score + (1 - alpha) * b_score,
            }

        return sorted(merged.values(), key=lambda x: x["score"], reverse=True)

    def _weight_rerank(
        self,
        query: str,
        documents: List[Dict[str, Any]],
        vector_weight: float = 0.6,
        keyword_weight: float = 0.4,
    ) -> List[Dict[str, Any]]:
        """向量得分 + 关键词 TF-IDF cosine 线性加权。"""
        if not documents:
            return documents

        query_tokens = list(jieba.cut_for_search(query))
        doc_tokens_list = [list(jieba.cut_for_search(doc.get("content", ""))) for doc in documents]

        all_tokens = set(tok for tokens in doc_tokens_list for tok in tokens)
        if not all_tokens:
            return documents

        doc_count = len(documents)
        token_idf: Dict[str, float] = {}
        for tok in all_tokens:
            df = sum(1 for tokens in doc_tokens_list if tok in tokens)
            token_idf[tok] = math.log((1 + doc_count) / (1 + df)) + 1

        def tfidf_vec(tokens: List[str]) -> Dict[str, float]:
            tf = Counter(tokens)
            return {t: tf[t] * token_idf.get(t, 0.0) for t in tf}

        query_vec = tfidf_vec(query_tokens)
        doc_vecs = [tfidf_vec(tokens) for tokens in doc_tokens_list]

        def cosine(a: Dict[str, float], b: Dict[str, float]) -> float:
            if not a or not b:
                return 0.0
            common = set(a.keys()) & set(b.keys())
            num = sum(a[t] * b[t] for t in common)
            denom = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values()))
            return num / denom if denom else 0.0

        keyword_scores = [cosine(query_vec, v) for v in doc_vecs]

        reranked: List[Dict[str, Any]] = []
        for doc, kw_score in zip(documents, keyword_scores):
            vec_score = doc.get("vector_score", doc.get("score", 0.0))
            final_score = vector_weight * float(vec_score) + keyword_weight * float(kw_score)
            new_doc = dict(doc)
            new_doc["keyword_score"] = float(kw_score)
            new_doc["score"] = float(final_score)
            reranked.append(new_doc)

        reranked.sort(key=lambda x: x["score"], reverse=True)
        return reranked

    def _mmr_rerank(
        self,
        documents: List[Dict[str, Any]],
        query: str,
        top_k: int,
        lambda_mult: float = 0.7,
    ) -> List[Dict[str, Any]]:
        """
        简易 MMR（最大边际相关性）重排：
        max λ*sim(query, doc) - (1-λ)*max sim(doc, selected)
        使用词袋 Jaccard 近似，轻量且无额外依赖。
        """
        if not documents:
            return documents

        lambda_mult = max(min(lambda_mult, 1.0), 0.0)
        selected: List[Dict[str, Any]] = []
        candidates = list(documents)
        # 预先缓存 tokens，避免多次分词
        tokens_map = {id(doc): set(jieba.cut_for_search(doc.get("content", ""))) for doc in candidates}

        def doc_similarity(doc_a: Dict[str, Any], doc_b: Dict[str, Any]) -> float:
            tokens_a = tokens_map.get(id(doc_a), set())
            tokens_b = tokens_map.get(id(doc_b), set())
            if not tokens_a or not tokens_b:
                return 0.0
            inter = tokens_a & tokens_b
            union = tokens_a | tokens_b
            return len(inter) / len(union) if union else 0.0

        while candidates and len(selected) < top_k:
            best = None
            best_score = -1e9
            for i, doc in enumerate(candidates):
                relevance = float(doc.get("score", 0.0))
                diversity_penalty = 0.0
                if selected:
                    sel_sims = [doc_similarity(doc, s) for s in selected]
                    diversity_penalty = max(sel_sims) if sel_sims else 0.0
                mmr_score = lambda_mult * relevance - (1 - lambda_mult) * diversity_penalty
                if mmr_score > best_score:
                    best_score = mmr_score
                    best = (i, doc)

            if best is None:
                break
            idx, doc = best
            selected.append(doc)
            candidates.pop(idx)

        return selected


# 全局实例
hybrid_retriever = HybridRetriever()
