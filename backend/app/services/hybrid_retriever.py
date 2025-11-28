"""
混合检索器 (Hybrid Search)
结合向量检索和 BM25 关键词检索
"""
from typing import List, Dict, Any, Optional
from uuid import UUID
import jieba
from rank_bm25 import BM25Okapi
import numpy as np

from app.services.milvus_store import milvus_store
from app.models.document import DocumentChunk
from sqlalchemy.orm import Session


class HybridRetriever:
    """混合检索器：向量检索 + BM25"""

    def __init__(self):
        self.bm25_index = None
        self.corpus_chunks = []
        self.corpus_ids = []

    def build_bm25_index(self, chunks: List[DocumentChunk]):
        """
        构建 BM25 索引

        Args:
            chunks: 文档片段列表（从数据库读取）
        """
        if not chunks:
            return

        # 分词构建语料库
        self.corpus_chunks = chunks
        self.corpus_ids = [str(chunk.id) for chunk in chunks]

        tokenized_corpus = []
        for chunk in chunks:
            # 使用 jieba 分词（中文友好）
            tokens = list(jieba.cut_for_search(chunk.content))
            tokenized_corpus.append(tokens)

        # 构建 BM25 索引
        self.bm25_index = BM25Okapi(tokenized_corpus)
        print(f"✅ BM25 index built with {len(chunks)} chunks")

    def search_bm25(
        self,
        query: str,
        top_k: int = 10,
        document_ids: Optional[List[UUID]] = None
    ) -> List[Dict[str, Any]]:
        """
        BM25 关键词检索

        Args:
            query: 查询文本
            top_k: 返回 Top-K
            document_ids: 限定文档范围

        Returns:
            检索结果列表
        """
        if not self.bm25_index or not self.corpus_chunks:
            return []

        # 分词查询
        tokenized_query = list(jieba.cut_for_search(query))

        # BM25 打分
        scores = self.bm25_index.get_scores(tokenized_query)

        # 排序并过滤
        results = []
        for idx, score in enumerate(scores):
            chunk = self.corpus_chunks[idx]

            # 过滤文档范围
            if document_ids and chunk.document_id not in [str(doc_id) for doc_id in document_ids]:
                continue

            results.append({
                "chunk_id": str(chunk.id),
                "content": chunk.content,
                "metadata": {
                    "document_id": str(chunk.document_id),
                    "source": chunk.metadata.get('source', 'unknown'),
                    "page": chunk.page_number,
                    "chunk_index": chunk.chunk_index,
                    "bm25_score": float(score)
                },
                "score": float(score)
            })

        # 按 BM25 分数排序
        results.sort(key=lambda x: x['score'], reverse=True)
        return results[:top_k]

    def hybrid_search(
        self,
        query: str,
        top_k: int = 5,
        score_threshold: float = 0.7,
        document_ids: Optional[List[UUID]] = None,
        alpha: float = 0.5
    ) -> List[Dict[str, Any]]:
        """
        混合检索：向量检索 + BM25

        Args:
            query: 查询文本
            top_k: 返回 Top-K
            score_threshold: 向量相似度阈值
            document_ids: 限定文档范围
            alpha: 向量检索权重 (0-1)，BM25 权重为 1-alpha

        Returns:
            合并后的检索结果
        """
        # 1. 向量检索（语义相似）
        vector_results = milvus_store.search(
            query=query,
            top_k=top_k * 2,  # 多检索一些
            score_threshold=score_threshold,
            document_ids=document_ids
        )

        # 2. BM25 检索（关键词匹配）
        bm25_results = self.search_bm25(
            query=query,
            top_k=top_k * 2,
            document_ids=document_ids
        )

        # 3. 合并结果（Reciprocal Rank Fusion）
        merged_results = self._merge_results(
            vector_results,
            bm25_results,
            alpha=alpha
        )

        return merged_results[:top_k]

    def _merge_results(
        self,
        vector_results: List[Dict[str, Any]],
        bm25_results: List[Dict[str, Any]],
        alpha: float = 0.5
    ) -> List[Dict[str, Any]]:
        """
        合并向量检索和 BM25 结果
        使用 Reciprocal Rank Fusion (RRF) 算法

        Args:
            vector_results: 向量检索结果
            bm25_results: BM25 检索结果
            alpha: 向量检索权重

        Returns:
            合并后的结果
        """
        # 归一化分数
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

        # 归一化两种检索结果
        vector_norm = normalize_scores(vector_results)
        bm25_norm = normalize_scores(bm25_results)

        # 合并分数
        merged = {}
        all_chunk_ids = set(vector_norm.keys()) | set(bm25_norm.keys())

        for chunk_id in all_chunk_ids:
            vector_score = vector_norm.get(chunk_id, {}).get('score', 0.0)
            bm25_score = bm25_norm.get(chunk_id, {}).get('score', 0.0)

            # 加权融合
            final_score = alpha * vector_score + (1 - alpha) * bm25_score

            # 优先使用向量检索的数据（包含更完整的 metadata）
            data = vector_norm.get(chunk_id, {}).get('data') or bm25_norm.get(chunk_id, {}).get('data')

            if data:
                merged[chunk_id] = {
                    'score': final_score,
                    'vector_score': vector_score,
                    'bm25_score': bm25_score,
                    **data
                }

        # 按融合分数排序
        sorted_results = sorted(
            merged.values(),
            key=lambda x: x['score'],
            reverse=True
        )

        return sorted_results


# 全局实例
hybrid_retriever = HybridRetriever()
