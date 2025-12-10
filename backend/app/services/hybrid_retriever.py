"""
Hybrid retriever combining vector search (Milvus) and BM25 with tenant isolation.
"""
from typing import List, Dict, Any, Optional
from uuid import UUID
import jieba
from rank_bm25 import BM25Okapi
import numpy as np
import math
from collections import Counter

from app.services.milvus_store import milvus_store
from app.models.document import DocumentChunk
from app.core.config import settings


class HybridRetriever:
    """混合检索器：向量检索 + BM25"""

    def __init__(self):
        self.bm25_index: Dict[str, BM25Okapi] = {}
        self.corpus_chunks: Dict[str, List[DocumentChunk]] = {}
        self.corpus_ids: Dict[str, List[str]] = {}

    def _tenant_key(self, tenant_id: Optional[UUID]) -> str:
        return str(tenant_id or settings.DEFAULT_TENANT_ID)

    def build_bm25_index(self, chunks: List[DocumentChunk], tenant_id: Optional[UUID] = None):
        """构建 BM25 索引"""
        if not chunks:
            return

        tenant_key = self._tenant_key(tenant_id)
        self.corpus_chunks[tenant_key] = chunks
        self.corpus_ids[tenant_key] = [str(chunk.id) for chunk in chunks]

        tokenized_corpus = []
        for chunk in chunks:
            tokens = list(jieba.cut_for_search(chunk.content))
            tokenized_corpus.append(tokens)

        self.bm25_index[tenant_key] = BM25Okapi(tokenized_corpus)
        print(f"[OK] BM25 index built with {len(chunks)} chunks for tenant {tenant_key}")

    def search_bm25(
        self,
        query: str,
        top_k: int = 10,
        document_ids: Optional[List[UUID]] = None,
        tenant_id: Optional[UUID] = None
    ) -> List[Dict[str, Any]]:
        """BM25 关键词检索"""
        tenant_key = self._tenant_key(tenant_id)

        if tenant_key not in self.bm25_index or tenant_key not in self.corpus_chunks:
            print("[WARN]  BM25 index not initialized, skipping keyword search")
            return []

        tokenized_query = list(jieba.cut_for_search(query))
        scores = self.bm25_index[tenant_key].get_scores(tokenized_query)

        allowed_ids = {str(doc_id) for doc_id in document_ids} if document_ids else None

        results = []
        for idx, score in enumerate(scores):
            chunk = self.corpus_chunks[tenant_key][idx]
            if allowed_ids and str(chunk.document_id) not in allowed_ids:
                continue

            meta = chunk.doc_metadata or {}

            results.append({
                "chunk_id": str(chunk.id),
                "content": chunk.content,
                "metadata": {
                    "tenant_id": str(chunk.tenant_id),
                    "document_id": str(chunk.document_id),
                    "source": meta.get('source', 'unknown'),
                    "page": chunk.page_number or meta.get('page'),
                    "chunk_index": chunk.chunk_index,
                    "image_id": meta.get('image_id'),
                    "image_url": meta.get('image_url'),
                    "bm25_score": float(score)
                },
                "score": float(score)
            })

        results.sort(key=lambda x: x['score'], reverse=True)
        return results[:top_k]

    def hybrid_search(
        self,
        query: str,
        top_k: int = 5,
        score_threshold: float = 0.7,
        document_ids: Optional[List[UUID]] = None,
        tenant_id: Optional[UUID] = None,
        alpha: float = 0.5,
        enable_weight_rerank: bool = True,
        vector_weight: float = 0.6,
        keyword_weight: float = 0.4
    ) -> List[Dict[str, Any]]:
        """
        混合检索：向量检索 + BM25
        """
        # 1. 向量检索
        vector_results = milvus_store.search(
            query=query,
            top_k=top_k * 2,
            score_threshold=score_threshold,
            document_ids=document_ids,
            tenant_id=tenant_id
        )

        # 2. BM25 关键词检索
        bm25_results = self.search_bm25(
            query=query,
            top_k=top_k * 2,
            document_ids=document_ids,
            tenant_id=tenant_id
        )

        # 3. 合并（RRF）
        merged_results = self._merge_results(
            vector_results,
            bm25_results,
            alpha=alpha
        )

        # 4. 选配：向量+关键词权重重排
        if enable_weight_rerank and merged_results:
            merged_results = self._weight_rerank(
                query=query,
                documents=merged_results,
                vector_weight=vector_weight,
                keyword_weight=keyword_weight
            )

        return merged_results[:top_k]

    def _merge_results(
        self,
        vector_results: List[Dict[str, Any]],
        bm25_results: List[Dict[str, Any]],
        alpha: float = 0.5
    ) -> List[Dict[str, Any]]:
        """Reciprocal Rank Fusion 合并"""

        def normalize_scores(results):
            if not results:
                return {}
            scores = [r['score'] for r in results]
            min_score = min(scores)
            max_score = max(scores)
            score_range = max_score - min_score if max_score > min_score else 1.0
            normalized = {}
            for r in results:
                chunk_id = r.get('chunk_id') or r['metadata'].get('chunk_index')
                normalized_score = (r['score'] - min_score) / score_range
                normalized[str(chunk_id)] = {
                    'score': normalized_score,
                    'data': r
                }
            return normalized

        vector_norm = normalize_scores(vector_results)
        bm25_norm = normalize_scores(bm25_results)

        merged = {}
        all_chunk_ids = set(vector_norm.keys()) | set(bm25_norm.keys())
        for chunk_id in all_chunk_ids:
            vector_score = vector_norm.get(chunk_id, {}).get('score', 0.0)
            bm25_score = bm25_norm.get(chunk_id, {}).get('score', 0.0)
            final_score = alpha * vector_score + (1 - alpha) * bm25_score
            data = vector_norm.get(chunk_id, {}).get('data') or bm25_norm.get(chunk_id, {}).get('data')
            if data:
                merged[chunk_id] = {
                    'score': final_score,
                    'vector_score': vector_score,
                    'bm25_score': bm25_score,
                    **data
                }

        sorted_results = sorted(
            merged.values(),
            key=lambda x: x['score'],
            reverse=True
        )
        return sorted_results

    def _weight_rerank(
        self,
        query: str,
        documents: List[Dict[str, Any]],
        vector_weight: float = 0.6,
        keyword_weight: float = 0.4
    ) -> List[Dict[str, Any]]:
        """
        将向量得分与关键词 TF-IDF 得分线性加权重排。
        """
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
            vec_score = doc.get("score", 0.0)
            if "vector_score" in doc:
                vec_score = doc["vector_score"]
            final_score = vector_weight * vec_score + keyword_weight * kw_score
            new_doc = dict(doc)
            new_doc["keyword_score"] = kw_score
            new_doc["score"] = final_score
            reranked.append(new_doc)

        reranked.sort(key=lambda x: x["score"], reverse=True)
        return reranked


# 全局实例
hybrid_retriever = HybridRetriever()
