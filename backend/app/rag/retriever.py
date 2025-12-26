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
import time

from langchain_core.documents import Document
from langchain_core.callbacks import CallbackManagerForRetrieverRun, AsyncCallbackManagerForRetrieverRun
from langchain_core.retrievers import BaseRetriever
from langchain_community.retrievers.bm25 import BM25Retriever
from pydantic import PrivateAttr, ConfigDict

from app.storage.vector.factory import get_vector_store
from app.models.document import DocumentChunk
from app.core.config import settings
from app.core.database import SessionLocal
from app.rag.reranker.factory import get_reranker
from app.rag.reranker.types import RerankCandidate


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
    enable_reranker: bool = settings.ENABLE_RERANKER
    reranker_provider: str = settings.RERANKER_PROVIDER
    reranker_top_n: int = settings.RERANKER_TOP_N
    tenant_id: Optional[UUID] = None
    document_ids: Optional[List[UUID]] = None

    model_config = ConfigDict(arbitrary_types_allowed=True)

    _bm25_retrievers: Dict[str, BM25Retriever] = PrivateAttr(default_factory=dict)
    _bm25_docs: Dict[str, List[Document]] = PrivateAttr(default_factory=dict)
    _chunk_id_lookup: Dict[str, Dict[str, str]] = PrivateAttr(default_factory=dict)

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
        lookup: Dict[str, str] = {}
        for d in docs:
            meta = d.metadata or {}
            doc_id = meta.get("document_id")
            chunk_index = meta.get("chunk_index")
            if doc_id is None or chunk_index is None or d.id is None:
                continue
            lookup[f"{doc_id}:{chunk_index}"] = str(d.id)
        self._chunk_id_lookup[tenant_key] = lookup
        print(f"[OK] BM25 index built with {len(docs)} chunks for tenant {tenant_key}")

    def upsert_bm25_documents(self, docs: List[Document], tenant_id: Optional[UUID] = None):
        """
        增量更新 BM25 索引（避免每次从 DB 全量扫描）。
        注意：BM25Retriever 本身不可增量训练，这里用“在内存合并后重建”代替，
        但仍显著减少 DB 查询开销，适合知识库大规模场景。
        """
        if not docs:
            return
        tenant_key = self._tenant_key(tenant_id)
        existing = self._bm25_docs.get(tenant_key) or []
        merged: Dict[str, Document] = {str(d.id): d for d in existing if d.id is not None}
        for d in docs:
            if d.id is None:
                continue
            merged[str(d.id)] = d

        merged_docs = list(merged.values())
        retriever = BM25Retriever.from_documents(
            merged_docs,
            preprocess_func=lambda text: list(jieba.cut_for_search(text)),
            k=10,
        )
        self._bm25_retrievers[tenant_key] = retriever
        self._bm25_docs[tenant_key] = merged_docs
        lookup: Dict[str, str] = {}
        for d in merged_docs:
            meta = d.metadata or {}
            doc_id = meta.get("document_id")
            chunk_index = meta.get("chunk_index")
            if doc_id is None or chunk_index is None or d.id is None:
                continue
            lookup[f"{doc_id}:{chunk_index}"] = str(d.id)
        self._chunk_id_lookup[tenant_key] = lookup
        print(f"[OK] BM25 index updated to {len(merged_docs)} chunks for tenant {tenant_key}")

    def remove_document_from_bm25_index(self, document_id: UUID, tenant_id: Optional[UUID] = None):
        """从 BM25 索引移除指定文档的所有切片。"""
        tenant_key = self._tenant_key(tenant_id)
        existing = self._bm25_docs.get(tenant_key) or []
        if not existing:
            return
        filtered = [d for d in existing if str((d.metadata or {}).get("document_id")) != str(document_id)]
        retriever = BM25Retriever.from_documents(
            filtered,
            preprocess_func=lambda text: list(jieba.cut_for_search(text)),
            k=10,
        ) if filtered else None
        if retriever is None:
            self._bm25_retrievers.pop(tenant_key, None)
            self._bm25_docs.pop(tenant_key, None)
            self._chunk_id_lookup.pop(tenant_key, None)
            print(f"[OK] BM25 index cleared for tenant {tenant_key}")
            return
        self._bm25_retrievers[tenant_key] = retriever
        self._bm25_docs[tenant_key] = filtered
        lookup: Dict[str, str] = {}
        for d in filtered:
            meta = d.metadata or {}
            doc_id = meta.get("document_id")
            chunk_index = meta.get("chunk_index")
            if doc_id is None or chunk_index is None or d.id is None:
                continue
            lookup[f"{doc_id}:{chunk_index}"] = str(d.id)
        self._chunk_id_lookup[tenant_key] = lookup
        print(f"[OK] BM25 index removed document {document_id} for tenant {tenant_key}")

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
                        "img_id": meta.get("img_id"),
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

        # 尝试补全向量检索结果的 chunk_id（用于 citations / RAGAS contexts）
        if vector_results:
            tenant_key = self._tenant_key(tenant_id)
            lookup = self._chunk_id_lookup.get(tenant_key) or {}
            for r in vector_results:
                meta = r.get("metadata") or {}
                doc_id = meta.get("document_id")
                chunk_index = meta.get("chunk_index")
                if doc_id is None or chunk_index is None:
                    continue
                key = f"{doc_id}:{chunk_index}"
                mapped = lookup.get(key)
                if not mapped:
                    continue
                r["chunk_id"] = mapped
                meta["chunk_id"] = mapped
                r["metadata"] = meta

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

        # 5) 可选：LLM Reranker 精排（在最终截断前执行）
        if merged_results and bool(self.enable_reranker):
            provider = (self.reranker_provider or settings.RERANKER_PROVIDER or "llm").lower()
            if provider not in ("none", "off", "false", "0"):
                reranker = get_reranker(provider)
                candidates_n = int(self.reranker_top_n or settings.RERANKER_TOP_N or 20)
                candidates_n = max(candidates_n, top_k)
                candidates_n = min(candidates_n, len(merged_results))
                candidates: List[RerankCandidate] = []
                id_to_doc: Dict[str, Dict[str, Any]] = {}
                for doc in merged_results[:candidates_n]:
                    rid = self._result_key(doc)
                    text = (doc.get("content") or "").strip()
                    if not rid or not text:
                        continue
                    meta = dict(doc.get("metadata") or {})
                    meta["score"] = float(doc.get("score", 0.0) or 0.0)
                    candidates.append(RerankCandidate(id=rid, text=text, metadata=meta))
                    id_to_doc[rid] = doc

                if candidates:
                    start = time.time()
                    result = reranker.rerank(
                        query=query,
                        candidates=candidates,
                        top_n=candidates_n,
                    )
                    rerank_elapsed = result.elapsed_sec or (time.time() - start)
                    rerank_provider = result.provider or provider

                    ordered = []
                    used: set[str] = set()
                    for rid in result.ordered_ids:
                        d = id_to_doc.get(rid)
                        if not d or rid in used:
                            continue
                        used.add(rid)
                        new_doc = dict(d)
                        new_doc["retrieval_score"] = float(new_doc.get("score", 0.0) or 0.0)
                        if rid in result.score_map:
                            new_doc["rerank_score"] = float(result.score_map[rid])
                            new_doc["score"] = float(result.score_map[rid])
                        new_doc["reranker_provider"] = rerank_provider
                        new_doc["rerank_elapsed_sec"] = round(float(rerank_elapsed), 3)
                        new_doc["rerank_model_used"] = result.model_used
                        ordered.append(new_doc)

                    # 追加未被 LLM 返回的候选（保持原顺序）
                    for doc in merged_results[:candidates_n]:
                        rid = self._result_key(doc)
                        if rid in used:
                            continue
                        new_doc = dict(doc)
                        new_doc.setdefault("reranker_provider", rerank_provider)
                        new_doc.setdefault("rerank_elapsed_sec", round(float(rerank_elapsed), 3))
                        new_doc.setdefault("rerank_model_used", result.model_used)
                        ordered.append(new_doc)

                    merged_results = ordered + merged_results[candidates_n:]

        return merged_results[:top_k]

    # ---- LangChain Retriever API ----

    def _enrich_results_with_db_metadata(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        向量库返回的 metadata 可能是“裁剪版”（例如不含 img_id）。
        这里用 chunk_id / (document_id, chunk_index) 回查 DB，补全关键字段：
        - img_id：用于 MinIO 图片展示
        - page/source：用于上下文标注（尽量与 DB 保持一致）
        """
        if not results:
            return results

        db = SessionLocal()
        try:
            tenant_filter = self.tenant_id

            chunk_ids: List[UUID] = []
            # 先收集已有 chunk_id（优先用它回查）
            for r in results:
                cid = r.get("chunk_id")
                if not cid:
                    meta = r.get("metadata") or {}
                    cid = meta.get("chunk_id")
                if not cid:
                    continue
                try:
                    chunk_ids.append(UUID(str(cid)))
                except Exception:
                    continue

            chunks_by_id: Dict[str, DocumentChunk] = {}
            if chunk_ids:
                q = db.query(DocumentChunk).filter(DocumentChunk.id.in_(chunk_ids))
                if tenant_filter:
                    q = q.filter(DocumentChunk.tenant_id == tenant_filter)
                for ck in q.all():
                    chunks_by_id[str(ck.id)] = ck

            # 对缺失 chunk_id 的结果，尝试按 (document_id, chunk_index) 回查并补齐 chunk_id
            for r in results:
                cid = r.get("chunk_id")
                if cid and str(cid) in chunks_by_id:
                    continue
                meta = r.get("metadata") or {}
                doc_id = meta.get("document_id")
                chunk_index = meta.get("chunk_index")
                if doc_id is None or chunk_index is None:
                    continue
                try:
                    doc_uuid = UUID(str(doc_id))
                    chunk_idx = int(chunk_index)
                except Exception:
                    continue

                q = db.query(DocumentChunk).filter(
                    DocumentChunk.document_id == doc_uuid,
                    DocumentChunk.chunk_index == chunk_idx,
                )
                if tenant_filter:
                    q = q.filter(DocumentChunk.tenant_id == tenant_filter)
                ck = q.first()
                if not ck:
                    continue

                r["chunk_id"] = str(ck.id)
                meta = dict(meta)
                meta["chunk_id"] = str(ck.id)
                r["metadata"] = meta
                chunks_by_id[str(ck.id)] = ck

            # 合并 DB metadata（只补空缺字段，避免覆盖向量侧的 score 等）
            for r in results:
                meta = dict(r.get("metadata") or {})
                cid = r.get("chunk_id") or meta.get("chunk_id")
                ck = chunks_by_id.get(str(cid)) if cid else None
                if not ck:
                    continue

                stored_meta = dict(ck.doc_metadata or {})
                if stored_meta.get("img_id") and not meta.get("img_id"):
                    meta["img_id"] = stored_meta.get("img_id")
                if stored_meta.get("source") and not meta.get("source"):
                    meta["source"] = stored_meta.get("source")
                if (ck.page_number is not None) and not meta.get("page"):
                    meta["page"] = ck.page_number
                if stored_meta.get("parser_backend") and not meta.get("parser_backend"):
                    meta["parser_backend"] = stored_meta.get("parser_backend")
                if stored_meta.get("doc_type_kwd") and not meta.get("doc_type_kwd"):
                    meta["doc_type_kwd"] = stored_meta.get("doc_type_kwd")

                r["metadata"] = meta

            return results
        except Exception:
            return results
        finally:
            try:
                db.close()
            except Exception:
                pass

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
        results = self._enrich_results_with_db_metadata(results)
        docs: List[Document] = []
        for r in results:
            meta = dict(r.get("metadata") or {})
            meta["score"] = r.get("score")
            meta["vector_score"] = r.get("vector_score")
            meta["bm25_score"] = r.get("bm25_score")
            if "keyword_score" in r:
                meta["keyword_score"] = r.get("keyword_score")
            if "rerank_score" in r:
                meta["rerank_score"] = r.get("rerank_score")
            if "retrieval_score" in r:
                meta["retrieval_score"] = r.get("retrieval_score")
            if "reranker_provider" in r:
                meta["reranker_provider"] = r.get("reranker_provider")
            if "rerank_elapsed_sec" in r:
                meta["rerank_elapsed_sec"] = r.get("rerank_elapsed_sec")
            if "rerank_model_used" in r:
                meta["rerank_model_used"] = r.get("rerank_model_used")
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
            v_data = vector_norm.get(key, {}).get("data")
            b_data = bm25_norm.get(key, {}).get("data")
            data = v_data or b_data
            if not data:
                continue

            # 合并两路 metadata（例如 img_id 可能只存在于 BM25/DB metadata）
            if v_data and b_data:
                merged_meta = dict(v_data.get("metadata") or {})
                b_meta = b_data.get("metadata") or {}
                for k, v in b_meta.items():
                    if k not in merged_meta or merged_meta.get(k) in (None, "", [], {}):
                        merged_meta[k] = v
                merged_data = dict(v_data)
                merged_data["metadata"] = merged_meta
                if not merged_data.get("chunk_id") and b_data.get("chunk_id"):
                    merged_data["chunk_id"] = b_data.get("chunk_id")
                data = merged_data

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
