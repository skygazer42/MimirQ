"""
RAG 对话引擎
"""
from __future__ import annotations

import asyncio
import os
import threading
from typing import AsyncGenerator, Dict, Any, List, Optional, Type
from uuid import UUID
import json
from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
import httpx
import time

from app.core.config import settings
from app.core.token_utils import num_tokens_from_string
from app.rag.core.conversation import format_history_text
from app.rag.core.citations import build_citations_from_docs
from app.rag.core.http import httpx_trust_env
from app.rag.core.logging import get_logger
from app.rag.core.text import (
    parse_json_from_text,
    extract_evidence_text,
    guess_retrieval_mode,
    normalize_retrieval_mode,
    should_rewrite_query,
)
from app.rag.retriever import hybrid_retriever
from app.services.metrics_logger import log_metrics
from langchain_openai import ChatOpenAI
from app.services.prompt_resolver import resolve_prompt_template
from app.rag.kg.pipeline import kg_search

logger = get_logger("rag.engine")


class RAGEngine:
    """RAG 对话引擎"""

    def __init__(self) -> None:
        # LLM 配置
        trust_env = httpx_trust_env(logger=logger)
        self.http_client = httpx.Client(trust_env=trust_env)
        self.http_async_client = httpx.AsyncClient(trust_env=trust_env)

        # Build available models for dynamic routing (inspired by agent middleware pattern)
        default_model_name = settings.LLM_MODEL or "gpt-4-turbo-preview"
        self.models: Dict[str, Any] = {}
        self.models["default"] = self._build_llm(ChatOpenAI, default_model_name)
        if settings.ENABLE_DYNAMIC_MODEL_ROUTING:
            if settings.LLM_MODEL_FAST:
                self.models["fast"] = self._build_llm(ChatOpenAI, settings.LLM_MODEL_FAST or default_model_name)
            if settings.LLM_MODEL_HEAVY:
                self.models["heavy"] = self._build_llm(ChatOpenAI, settings.LLM_MODEL_HEAVY or default_model_name)

        # Prompt 模板（支持对话历史）
        self.prompt_template = ChatPromptTemplate.from_template(
            """你是一个专业的知识库助手。请基于以下参考资料和对话历史回答用户问题。

【参考资料】
{context}

【对话历史】
{history}

【当前问题】
{question}

【回答要求】
1. 仅基于参考资料回答，不要编造信息
2. 如果参考资料中没有相关信息，请明确告知用户"根据现有资料无法回答该问题"
3. 结合对话历史理解上下文，处理代词（如"它"、“这个”）和追问
4. 回答要准确、简洁、专业
5. 引用资料时可以提及来源文件名
6. 如指定输出格式，请严格遵守

【输出格式说明】
{format_instructions}

【回答】"""
        )

        # 结构化输出预设格式（可扩展）
        self.structured_presets: Dict[str, str] = {
            "faq": (
                "仅输出 JSON，结构："
                '{"answer": "string", "citations": [{"document_id": "...", "chunk_id": "..."}],'
                '"qa_pairs": [{"question": "string", "answer": "string"}]}'
                " 不要输出多余文本。"
            ),
            "summary": (
                "仅输出 JSON，结构："
                '{"answer": "string", "citations": [{"document_id": "...", "chunk_id": "..."}],'
                '"bullets": ["要点1", "要点2"], "summary": "简洁摘要"}'
                " 不要输出多余文本。"
            ),
            "action_items": (
                "仅输出 JSON，结构："
                '{"answer": "string", "citations": [{"document_id": "...", "chunk_id": "..."}],'
                '"actions": [{"item": "动作", "owner": "负责人", "due": "时间"}]}'
                " 不要输出多余文本。"
            ),
        }

        # Query Rewrite：将追问改写为“可检索”的独立问题（可选开启）
        self.rewrite_prompt = ChatPromptTemplate.from_template(
            """你是一个知识库检索助手。请把“当前问题”改写成一个独立、明确、适合检索的查询句。
要求：
1) 结合历史对话补全指代（如“它/这个/上面提到的”）
2) 保留关键实体、时间、范围、约束条件
3) 只输出改写后的查询句，不要输出解释

【历史对话】
{history}

【当前问题】
{question}

【改写后的检索查询】"""
        )


        # Multi-Query：生成多个表述/角度的检索查询（可选开启）
        self.multi_query_prompt = ChatPromptTemplate.from_template(
            """你是一个知识库检索 Query 扩展器。请基于以下“检索查询”生成 {n} 条不同表述/角度的检索查询，用于提升召回。
要求：
1) 仅输出 JSON 数组（array），元素都是字符串
2) 不要输出解释、不要 Markdown、不要多余字段
3) 每条尽量简短，保留关键实体/时间/限定条件
4) 避免与原查询完全重复

【检索查询】
{query}

【JSON 数组】"""
        )

        # HyDE：生成“假想的参考资料片段”用于向量检索增强（可选开启）
        self.hyde_prompt = ChatPromptTemplate.from_template(
            """你是一个知识库检索助手。请针对以下“问题”写一段“假想的参考资料片段”，用来帮助向量检索召回相关内容。
要求：
1) 只输出纯文本，不要 Markdown，不要标题/编号
2) 尽量包含可能出现的关键词、术语、实体、步骤、同义表达
3) 不要出现“无法回答/不知道”等否定句

【问题】
{query}

【假想片段】"""
        )

        # Query Decomposition：将复杂问题拆成多个子问题分别检索（可选开启）
        self.decompose_prompt = ChatPromptTemplate.from_template(
            """你是一个知识库检索问题拆解器。请把下面的“检索查询”拆解成最多 {n} 个子问题，用于分别检索并融合召回。
要求：
1) 仅输出 JSON 数组（array），元素都是字符串
2) 不要输出解释、不要 Markdown、不要多余字段
3) 子问题尽量覆盖不同方面/约束条件，避免重复
4) 每个子问题都应当是可检索、可独立理解的一句话

【检索查询】
{query}

【JSON 数组】"""
        )


    def _build_llm(self, chat_cls: Type[ChatOpenAI], model_name: str) -> ChatOpenAI:
        """Create a ChatOpenAI-compatible LLM with shared HTTP clients."""
        return chat_cls(
            model=model_name,
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_API_BASE,
            temperature=settings.LLM_TEMPERATURE,
            streaming=True,
            timeout=settings.LLM_TIMEOUT,
            max_retries=settings.LLM_MAX_RETRIES,
            http_client=self.http_client,
            http_async_client=self.http_async_client,
        )

    def _score_question_complexity(self, question: str, history: Optional[List[Dict[str, str]]]) -> float:
        """
        粗粒度复杂度评分：长度 + 历史长度 * 权重。
        简单且无依赖，便于保持现有接口兼容。
        """
        history = history or []
        history_len = sum(len(msg.get("content", "")) for msg in history if isinstance(msg, dict))
        return float(len(question)) + settings.MODEL_COMPLEXITY_HISTORY_WEIGHT * float(history_len)

    def _select_llm(self, question: str, history: Optional[List[Dict[str, str]]]) -> tuple[Any, str, str]:
        """
        动态模型路由：借鉴 agent/middleware 的动态选模模式。
        返回: (llm实例, 路由标识, 原因)
        """
        if not settings.ENABLE_DYNAMIC_MODEL_ROUTING:
            return self.models["default"], "default", "routing disabled"

        score = self._score_question_complexity(question, history)
        threshold = settings.MODEL_COMPLEXITY_THRESHOLD

        if "heavy" in self.models and score >= threshold:
            return self.models["heavy"], "heavy", f"score {score:.1f} >= threshold {threshold}"

        if "fast" in self.models:
            return self.models["fast"], "fast", f"score {score:.1f} < threshold {threshold}"

        return self.models["default"], "default", "fallback to default"

    @staticmethod
    def _doc_key(doc: Document) -> str:
        meta = doc.metadata or {}
        doc_id = meta.get("document_id")
        chunk_index = meta.get("chunk_index")
        if doc_id is not None and chunk_index is not None:
            return f"{doc_id}:{chunk_index}"
        cid = getattr(doc, "id", None) or meta.get("chunk_id")
        if cid:
            return str(cid)
        content = (doc.page_content or "").strip()
        return f"content:{hash(content)}"

    @staticmethod
    def _normalize_query_text(text: str) -> str:
        return " ".join((text or "").strip().split())

    @classmethod
    def _dedup_retrieval_queries(cls, queries: List[tuple[str, str]]) -> List[tuple[str, str]]:
        if not queries:
            return []
        seen: set[str] = set()
        out: list[tuple[str, str]] = []
        for kind, q in queries:
            norm = cls._normalize_query_text(q)
            if not norm:
                continue
            key = norm.casefold() if norm.isascii() else norm
            if key in seen:
                continue
            seen.add(key)
            out.append((kind, norm))
        return out

    @staticmethod
    def _annotate_docs_with_role(docs: List[Document], role: str) -> List[Document]:
        if not docs:
            return []
        out: List[Document] = []
        for d in docs:
            meta = dict(d.metadata or {})
            meta.setdefault("retrieval_role", role)
            out.append(
                Document(
                    page_content=d.page_content,
                    metadata=meta,
                    id=getattr(d, "id", None) or meta.get("chunk_id"),
                )
            )
        return out

    @staticmethod
    def _merge_meta(dst: Dict[str, Any], src: Dict[str, Any]) -> Dict[str, Any]:
        for k, v in (src or {}).items():
            if k not in dst or dst.get(k) in (None, "", [], {}):
                dst[k] = v
        return dst

    @staticmethod
    def _doc_is_reranked(doc: Document) -> bool:
        meta = doc.metadata or {}
        return meta.get("rerank_score") is not None

    @classmethod
    def _prefer_doc(cls, current: Document, candidate: Document) -> Document:
        if cls._doc_is_reranked(candidate) and not cls._doc_is_reranked(current):
            return candidate
        if cls._doc_is_reranked(current) and not cls._doc_is_reranked(candidate):
            return current
        a = float((current.metadata or {}).get("score", 0.0) or 0.0)
        b = float((candidate.metadata or {}).get("score", 0.0) or 0.0)
        return candidate if b > a else current

    @classmethod
    def fuse_docs_rrf(
        cls,
        docs_by_query: List[List[Document]],
        *,
        rrf_k: int | None = None,
        meta_prefix: str = "query_expansion",
    ) -> List[Document]:
        if not docs_by_query:
            return []

        k0 = int(rrf_k or 0) or int(settings.RETRIEVAL_RRF_K or 60)
        k0 = max(1, k0)

        score_map: Dict[str, float] = {}
        hit_counts: Dict[str, int] = {}
        best_docs: Dict[str, Document] = {}
        merged_meta: Dict[str, Dict[str, Any]] = {}

        for docs in docs_by_query:
            seen_in_query: set[str] = set()
            for rank, doc in enumerate(docs or [], 1):
                key = cls._doc_key(doc)
                if key in seen_in_query:
                    continue
                seen_in_query.add(key)

                score_map[key] = float(score_map.get(key, 0.0) or 0.0) + (1.0 / (k0 + rank))
                hit_counts[key] = int(hit_counts.get(key, 0) or 0) + 1

                meta = dict(doc.metadata or {})
                if key not in best_docs:
                    best_docs[key] = doc
                    merged_meta[key] = meta
                else:
                    merged_meta[key] = cls._merge_meta(merged_meta.get(key) or {}, meta)
                    best_docs[key] = cls._prefer_doc(best_docs[key], doc)

        if not score_map:
            return []

        raw_scores = list(score_map.values())
        min_s = min(raw_scores) if raw_scores else 0.0
        max_s = max(raw_scores) if raw_scores else 0.0
        rng = (max_s - min_s) if max_s > min_s else 1.0

        fused: List[Document] = []
        for key, doc in best_docs.items():
            meta = dict(merged_meta.get(key) or {})
            base_score = meta.get("score")
            if base_score is not None and f"{meta_prefix}_base_score" not in meta:
                meta[f"{meta_prefix}_base_score"] = base_score
            meta[f"{meta_prefix}_rrf_raw"] = float(score_map.get(key, 0.0) or 0.0)
            meta[f"{meta_prefix}_rrf_k"] = k0
            meta[f"{meta_prefix}_hits"] = int(hit_counts.get(key, 0) or 0)
            meta[f"{meta_prefix}_fused"] = True
            meta["score"] = (float(score_map.get(key, 0.0) or 0.0) - min_s) / rng
            fused.append(
                Document(
                    page_content=doc.page_content,
                    metadata=meta,
                    id=getattr(doc, "id", None) or meta.get("chunk_id"),
                )
            )

        fused.sort(key=lambda d: float((d.metadata or {}).get("score", 0.0) or 0.0), reverse=True)
        return fused

    async def stream_chat(
        self,
        question: str,
        history: Optional[List[Dict[str, str]]] = None,
        conversation_id: Optional[UUID] = None,
        document_ids: Optional[List[UUID]] = None,
        metadata_filter: Optional[Dict[str, Any]] = None,
        top_k: int = 5,
        score_threshold: float = 0.7,
        tenant_id: Optional[UUID] = None,
        structured_output: bool = False,
        structured_preset: Optional[str] = None,
        retrieval_mode: str = "hybrid",
        alpha: float = 0.6,
        enable_weight_rerank: bool = True,
        vector_weight: float = 0.6,
        keyword_weight: float = 0.4,
        mmr_lambda: float = settings.RETRIEVAL_MMR_LAMBDA,
        enable_reranker: bool = settings.ENABLE_RERANKER,
        reranker_provider: Optional[str] = settings.RERANKER_PROVIDER,
        reranker_top_n: int = settings.RERANKER_TOP_N,
        request_id: Optional[str] = None,
        prompt_template_id: Optional[UUID] = None,
        prompt_template_key: Optional[str] = None,
        prompt_ab_experiment_key: Optional[str] = None,
        ab_user_key: Optional[str] = None,
        db: Optional[Any] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        流式对话接口

        Args:
            question: 用户问题
            conversation_id: 对话 ID
            document_ids: 限定文档范围
            top_k: 检索 Top-K
            score_threshold: 相似度阈值

        Yields:
            流式事件: {"type": "citations|token|done|error", "data": ...}
        """
        try:
            llm, model_route, routing_reason = self._select_llm(question, history)

            # Load prompt template (id / key latest / A/B experiment)
            current_prompt_template = self.prompt_template
            selected_prompt_template_id: Optional[UUID] = None
            selected_prompt_template_key: Optional[str] = None
            selected_prompt_ab_experiment_key: Optional[str] = None
            selected_prompt_ab_variant: Optional[str] = None

            if db and tenant_id and (prompt_template_id or prompt_template_key or prompt_ab_experiment_key):
                chosen = resolve_prompt_template(
                    db=db,
                    tenant_id=tenant_id,
                    prompt_template_id=prompt_template_id,
                    template_key=prompt_template_key,
                    ab_experiment_key=prompt_ab_experiment_key,
                    ab_user_key=ab_user_key,
                )
                if chosen:
                    current_prompt_template = ChatPromptTemplate.from_template(chosen.content)
                    chosen.usage_count += 1
                    db.commit()
                    selected_prompt_template_id = chosen.id
                    selected_prompt_template_key = getattr(chosen, "template_key", None)
                    selected_prompt_ab_experiment_key = getattr(chosen, "ab_experiment_key", None)
                    selected_prompt_ab_variant = getattr(chosen, "ab_variant", None)

            chain = current_prompt_template | llm | StrOutputParser()

            format_instructions = ""
            if structured_output:
                preset_key = (structured_preset or "").lower()
                format_instructions = self.structured_presets.get(
                    preset_key,
                    (
                        "请仅返回 JSON，结构: "
                        '{"answer": "string", "citations": [{"document_id": "...", "chunk_id": "...", "page_number": null, "relevance_score": 0.0}]} '
                        "不要输出多余文本。"
                    ),
                )

            yield {
                    "type": "route",
                    "data": {
                        "model_used": getattr(llm, "model_name", None) or getattr(llm, "model", None),
                        "route": model_route,
                        "reason": routing_reason,
                        "prompt_template_id": str(selected_prompt_template_id) if selected_prompt_template_id else None,
                        "prompt_template_key": selected_prompt_template_key,
                        "prompt_ab_experiment_key": selected_prompt_ab_experiment_key,
                        "prompt_ab_variant": selected_prompt_ab_variant,
                    },
                }

            # 对话历史（用于 prompt + 可选 Query Rewrite）
            history_text = format_history_text(history, window=settings.CHAT_HISTORY_WINDOW)

            t_all_start = time.time()
            query_for_retrieval = question
            rewrite_elapsed = 0.0
            rewrite_used = False
            rewrite_model_used = None

            # Step 0: Query Rewrite（可选）
            if (
                settings.ENABLE_QUERY_REWRITE
                and history_text != "（无历史对话）"
                and len(question) <= settings.QUERY_REWRITE_MAX_CHARS
                and should_rewrite_query(question)
            ):
                rewrite_llm = self.models.get("fast") or llm
                rewrite_model_used = getattr(rewrite_llm, "model_name", None) or getattr(rewrite_llm, "model", None)
                try:
                    rewrite_chain = (
                        self.rewrite_prompt
                        | rewrite_llm.bind(temperature=settings.QUERY_REWRITE_TEMPERATURE)
                        | StrOutputParser()
                    )
                    rw_start = time.time()
                    rewritten = await rewrite_chain.ainvoke({"history": history_text, "question": question})
                    rewrite_elapsed = time.time() - rw_start
                    rewritten = (rewritten or "").strip().strip('"')
                    if rewritten:
                        query_for_retrieval = rewritten
                except Exception:
                    query_for_retrieval = question
                    rewrite_elapsed = 0.0

                rewrite_used = query_for_retrieval != question
                yield {
                    "type": "rewrite",
                    "data": {
                        "original": question,
                        "rewritten": query_for_retrieval,
                        "used": rewrite_used,
                        "elapsed_sec": round(rewrite_elapsed, 3),
                        "model_used": rewrite_model_used,
                    },
                }

            mode_req = retrieval_mode or "hybrid"
            mode_used = normalize_retrieval_mode(mode_req)
            mode_auto = False
            mode_norm = (mode_used or "hybrid").lower().strip()
            if mode_norm == "auto":
                mode_used = guess_retrieval_mode(query_for_retrieval)
                mode_auto = True
                mode_norm = mode_used.lower().strip()
            if mode_norm not in ("hybrid", "vector", "keyword", "mmr"):
                mode_used = "hybrid"
                mode_norm = "hybrid"
            alpha_val = alpha if alpha is not None else 0.6
            weight_rerank = bool(enable_weight_rerank)
            vec_w = vector_weight if vector_weight is not None else 0.6
            kw_w = keyword_weight if keyword_weight is not None else 0.4
            mmr_lambda_val = mmr_lambda if mmr_lambda is not None else settings.RETRIEVAL_MMR_LAMBDA
            rerank_on = bool(enable_reranker)
            rerank_provider = reranker_provider or settings.RERANKER_PROVIDER or "llm"
            rerank_top_n = int(reranker_top_n or settings.RERANKER_TOP_N or 20)

            # Step 0.5: Query Expansion（Multi-Query / HyDE，可选）
            multi_query_elapsed = 0.0
            multi_query_used = False
            multi_query_model_used = None
            multi_query_parse_meta: Dict[str, Any] = {"ok": False, "method": None, "error": None}
            multi_queries: List[str] = []

            mq_n = max(0, min(int(settings.MULTI_QUERY_COUNT or 0), 8))
            mq_max_chars = max(0, int(settings.MULTI_QUERY_MAX_CHARS or 0))
            if bool(settings.ENABLE_MULTI_QUERY) and mq_n > 0 and mq_max_chars > 0 and len(query_for_retrieval) <= mq_max_chars:
                mq_llm = self.models.get("fast") or llm
                multi_query_model_used = getattr(mq_llm, "model_name", None) or getattr(mq_llm, "model", None)
                try:
                    mq_chain = (
                        self.multi_query_prompt
                        | mq_llm.bind(temperature=settings.MULTI_QUERY_TEMPERATURE)
                        | StrOutputParser()
                    )
                    mq_start = time.time()
                    mq_raw = await mq_chain.ainvoke({"query": query_for_retrieval, "n": mq_n})
                    multi_query_elapsed = time.time() - mq_start
                    mq_data, multi_query_parse_meta = parse_json_from_text(mq_raw, expected="array")

                    if isinstance(mq_data, list):
                        seen: set[str] = set()
                        for item in mq_data:
                            if not isinstance(item, str):
                                continue
                            q = (item or "").strip().strip('"').strip()
                            if not q:
                                continue
                            if q == query_for_retrieval:
                                continue
                            if q in seen:
                                continue
                            if len(q) > 400:
                                q = q[:400] + "..."
                            seen.add(q)
                            multi_queries.append(q)
                            if len(multi_queries) >= mq_n:
                                break
                except Exception as exc:  # noqa: BLE001
                    multi_query_elapsed = 0.0
                    multi_query_parse_meta = {"ok": False, "method": None, "error": str(exc)[:200]}
                    multi_queries = []

            multi_query_used = bool(multi_queries)

            hyde_used = False
            hyde_elapsed = 0.0
            hyde_model_used = None
            hyde_text = ""
            hyde_max_chars = max(0, int(settings.HYDE_MAX_CHARS or 0))
            retrieval_mode_norm = (mode_used or "hybrid").lower()
            if bool(settings.ENABLE_HYDE) and retrieval_mode_norm not in ("keyword",) and hyde_max_chars > 0 and len(query_for_retrieval) <= hyde_max_chars:
                hyde_llm = self.models.get("fast") or llm
                hyde_model_used = getattr(hyde_llm, "model_name", None) or getattr(hyde_llm, "model", None)
                try:
                    hyde_chain = (
                        self.hyde_prompt
                        | hyde_llm.bind(temperature=settings.HYDE_TEMPERATURE)
                        | StrOutputParser()
                    )
                    hyde_start = time.time()
                    hyde_text = await hyde_chain.ainvoke({"query": query_for_retrieval})
                    hyde_elapsed = time.time() - hyde_start
                    hyde_text = (hyde_text or "").strip()
                    out_max = max(0, int(settings.HYDE_OUTPUT_MAX_CHARS or 0))
                    if out_max and len(hyde_text) > out_max:
                        hyde_text = hyde_text[:out_max] + "..."
                    hyde_used = bool(hyde_text)
                except Exception:  # noqa: BLE001
                    hyde_text = ""
                    hyde_elapsed = 0.0
                    hyde_used = False

            decompose_elapsed = 0.0
            decompose_used = False
            decompose_model_used = None
            decompose_parse_meta: Dict[str, Any] = {"ok": False, "method": None, "error": None}
            sub_questions: List[str] = []

            dq_n = max(0, min(int(settings.QUERY_DECOMPOSITION_MAX_SUBQUESTIONS or 0), 8))
            dq_min_chars = max(0, int(settings.QUERY_DECOMPOSITION_MIN_CHARS or 0))
            dq_max_chars = max(0, int(settings.QUERY_DECOMPOSITION_MAX_CHARS or 0))
            if (
                bool(settings.ENABLE_QUERY_DECOMPOSITION)
                and dq_n > 0
                and len(query_for_retrieval) >= dq_min_chars
                and (dq_max_chars <= 0 or len(query_for_retrieval) <= dq_max_chars)
            ):
                dq_llm = self.models.get("fast") or llm
                decompose_model_used = getattr(dq_llm, "model_name", None) or getattr(dq_llm, "model", None)
                try:
                    dq_chain = (
                        self.decompose_prompt
                        | dq_llm.bind(temperature=settings.QUERY_DECOMPOSITION_TEMPERATURE)
                        | StrOutputParser()
                    )
                    dq_start = time.time()
                    dq_raw = await dq_chain.ainvoke({"query": query_for_retrieval, "n": dq_n})
                    decompose_elapsed = time.time() - dq_start
                    dq_data, decompose_parse_meta = parse_json_from_text(dq_raw, expected="array")

                    if isinstance(dq_data, list):
                        seen: set[str] = set()
                        for item in dq_data:
                            if not isinstance(item, str):
                                continue
                            q = (item or "").strip().strip('"').strip()
                            if not q:
                                continue
                            if q == query_for_retrieval:
                                continue
                            if q in seen:
                                continue
                            if len(q) > 500:
                                q = q[:500] + "..."
                            seen.add(q)
                            sub_questions.append(q)
                            if len(sub_questions) >= dq_n:
                                break
                except Exception as exc:  # noqa: BLE001
                    decompose_elapsed = 0.0
                    decompose_parse_meta = {"ok": False, "method": None, "error": str(exc)[:200]}
                    sub_questions = []

            decompose_used = bool(sub_questions)

            # Step 1: 混合检索（LangChain Retriever）
            retriever = hybrid_retriever.model_copy(
                update={
                    "k": top_k,
                    "score_threshold": score_threshold,
                    "alpha": alpha_val,
                    "tenant_id": tenant_id,
                    "document_ids": document_ids,
                    "metadata_filter": metadata_filter,
                    "retrieval_mode": mode_used,
                    "enable_weight_rerank": weight_rerank,
                    "vector_weight": vec_w,
                    "keyword_weight": kw_w,
                    "mmr_lambda": mmr_lambda_val,
                    "enable_reranker": rerank_on,
                    "reranker_provider": rerank_provider,
                    "reranker_top_n": rerank_top_n,
                }
            )

            retrieval_queries: List[tuple[str, str]] = [("main", query_for_retrieval)]
            for q in multi_queries:
                retrieval_queries.append(("mq", q))
            for q in sub_questions:
                retrieval_queries.append(("subq", q))
            if hyde_used and hyde_text:
                retrieval_queries.append(("hyde", hyde_text))

            retrieval_queries = self._dedup_retrieval_queries(retrieval_queries)

            docs_by_query: List[List[Document]] = []
            t_retrieval_start = time.time()
            retrieval_parallelism = max(1, int(getattr(settings, "RETRIEVAL_QUERY_PARALLELISM", 1) or 1))
            retrieval_plan: List[tuple[str, str, Any]] = []
            for kind, q in retrieval_queries:
                r = retriever
                if kind != "main":
                    if kind == "hyde":
                        r = retriever.model_copy(
                            update={
                                "enable_reranker": False,
                                "retrieval_mode": "vector",
                                "enable_weight_rerank": False,
                            }
                        )
                    else:
                        r = retriever.model_copy(update={"enable_reranker": False})
                retrieval_plan.append((kind, q, r))

            retrieval_errors: List[str] = []
            retrieval_per_query: List[Dict[str, Any]] = []

            async def _run_one(kind: str, q: str, r: Any) -> tuple[str, List[Document], str | None, float]:
                t0 = time.time()
                try:
                    docs_i = await asyncio.to_thread(r.invoke, q)
                    return kind, (docs_i or []), None, time.time() - t0
                except Exception as exc:  # noqa: BLE001
                    return kind, [], str(exc)[:200], time.time() - t0

            if retrieval_parallelism <= 1 or len(retrieval_plan) <= 1:
                for kind, q, r in retrieval_plan:
                    t0 = time.time()
                    try:
                        docs_i = r.invoke(q)
                        err = None
                    except Exception as exc:  # noqa: BLE001
                        docs_i = []
                        err = str(exc)[:200]
                    elapsed_i = time.time() - t0
                    retrieval_per_query.append(
                        {"kind": kind, "query_chars": len(q or ""), "elapsed_sec": round(elapsed_i, 3), "ok": err is None}
                    )
                    if err:
                        retrieval_errors.append(f"{kind}:{err[:160]}")
                        if kind == "main":
                            yield {"type": "error", "data": {"message": f"retrieval failed: {err}"}}
                    docs_by_query.append(self._annotate_docs_with_role(docs_i or [], kind))
            else:
                sem = asyncio.Semaphore(retrieval_parallelism)

                async def _guarded(kind: str, q: str, r: Any) -> tuple[str, List[Document], str | None, float]:
                    async with sem:
                        return await _run_one(kind, q, r)

                results = await asyncio.gather(*[_guarded(kind, q, r) for kind, q, r in retrieval_plan])
                for (kind, docs_i, err, elapsed_i), (_, q, _) in zip(results, retrieval_plan):
                    retrieval_per_query.append(
                        {"kind": kind, "query_chars": len(q or ""), "elapsed_sec": round(elapsed_i, 3), "ok": err is None}
                    )
                    if err:
                        retrieval_errors.append(f"{kind}:{err[:160]}")
                        if kind == "main":
                            yield {"type": "error", "data": {"message": f"retrieval failed: {err}"}}
                    docs_by_query.append(self._annotate_docs_with_role(docs_i or [], kind))

            retrieval_elapsed = time.time() - t_retrieval_start
            if len(docs_by_query) <= 1:
                docs = docs_by_query[0] if docs_by_query else []
            else:
                docs = self.fuse_docs_rrf(docs_by_query, rrf_k=settings.RETRIEVAL_RRF_K, meta_prefix="query_expansion")
            docs = docs[: max(0, int(top_k or 0))] if docs else []

            # 构建引用信息
            citations: List[Dict[str, Any]] = build_citations_from_docs(
                docs,
                retrieval_elapsed_sec=retrieval_elapsed,
                retrieval_mode=mode_used,
                query=query_for_retrieval,
            )

            # 发送引用信息
            yield {
                "type": "citations",
                "data": citations
            }

            # Step 1.5: 无召回/低证据拒答（可选）
            abstain_enabled = bool(settings.RAG_ABSTAIN_ENABLED)
            abstain_triggered = False
            abstain_reason: str | None = None
            top_rel = 0.0
            if citations:
                try:
                    top_rel = max(float(c.get("relevance_score", 0.0) or 0.0) for c in citations)
                except Exception:
                    top_rel = 0.0

            if abstain_enabled:
                min_citations = max(0, int(settings.RAG_ABSTAIN_MIN_CITATIONS or 0))
                min_top_rel = float(settings.RAG_ABSTAIN_MIN_TOP_RELEVANCE_SCORE or 0.0)

                if min_citations > 0 and len(citations) < min_citations:
                    abstain_triggered = True
                    abstain_reason = "citations_lt_min"
                elif min_top_rel > 0 and top_rel < min_top_rel:
                    abstain_triggered = True
                    abstain_reason = "top_relevance_lt_min"

            if abstain_triggered:
                abstain_message = '根据现有资料无法回答该问题。你可以补充上传相关文档，或缩小问题范围后再问。'

                structured_data = None
                structured_parse_meta = {"ok": False, "method": None, "error": None}
                full_response = abstain_message

                if structured_output:
                    preset_key = (structured_preset or "").lower()
                    structured_citations: List[Dict[str, Any]] = []
                    for c in citations[: max(0, int(top_k or 0))] if citations else []:
                        structured_citations.append(
                            {
                                "document_id": c.get("document_id"),
                                "chunk_id": c.get("chunk_id"),
                                "page_number": c.get("page_number"),
                                "relevance_score": c.get("relevance_score"),
                            }
                        )
                    payload: Dict[str, Any] = {"answer": abstain_message, "citations": structured_citations}
                    if preset_key == "faq":
                        payload["qa_pairs"] = []
                    elif preset_key == "summary":
                        payload["bullets"] = []
                        payload["summary"] = ""
                    elif preset_key == "action_items":
                        payload["actions"] = []
                    structured_data = payload
                    structured_parse_meta = {"ok": True, "method": "abstain", "error": None}
                    full_response = json.dumps(payload, ensure_ascii=False)

                # 让前端/DB 有内容可保存
                yield {"type": "token", "data": {"content": full_response}}

                t_total = time.time() - t_all_start
                answer_chars = len(full_response or "")
                answer_tokens = num_tokens_from_string(full_response or "")
                done_payload = {
                    "type": "done",
                    "data": {
                        "conversation_id": str(conversation_id) if conversation_id else None,
                        "total_tokens": answer_tokens,
                        "total_chars": answer_chars,
                        "citations_count": len(citations),
                        "model_used": getattr(llm, "model_name", None) or getattr(llm, "model", None),
                        "route": model_route,
                        "retrieval_mode": mode_used,
                        "vector_backend": settings.VECTOR_BACKEND,
                        "metrics": {
                            "elapsed_sec": round(t_total, 3),
                            "retrieval_elapsed_sec": round(retrieval_elapsed, 3),
                            "generation_elapsed_sec": 0.0,
                            "retrieval_mode": mode_used,
                            "retrieval_mode_requested": mode_req,
                            "retrieval_mode_auto_routed": bool(mode_auto),
                            "vector_backend": settings.VECTOR_BACKEND,
                            "model_route": model_route,
                            "top_k": top_k,
                            "docs_returned": len(docs),
                            "distinct_documents": len({c.get("document_id") for c in citations if c.get("document_id")}),
                            "history_chars": len(history_text or ""),
                            "context_chars": 0,
                            "llm_max_retries": settings.LLM_MAX_RETRIES,
                            "abstain_enabled": bool(abstain_enabled),
                            "abstain_triggered": True,
                            "abstain_reason": abstain_reason,
                            "abstain_min_citations": int(settings.RAG_ABSTAIN_MIN_CITATIONS or 0),
                            "abstain_min_top_relevance_score": float(settings.RAG_ABSTAIN_MIN_TOP_RELEVANCE_SCORE or 0.0),
                            "top_relevance_score": round(float(top_rel or 0.0), 3),
                            "answer_chars": answer_chars,
                            "answer_tokens": answer_tokens,
                            "structured_parse_ok": bool(structured_parse_meta.get("ok")),
                            "structured_parse_method": structured_parse_meta.get("method"),
                            "structured_parse_error": structured_parse_meta.get("error"),
                            "structured_type": type(structured_data).__name__ if structured_data is not None else None,
                            "structured_preset": structured_preset,
                        },
                        "structured": bool(structured_data),
                        "structured_data": structured_data,
                    },
                }
                yield done_payload

                log_metrics(
                    {
                        "event": "rag_done",
                        "conversation_id": str(conversation_id) if conversation_id else None,
                        "tenant_id": str(tenant_id) if tenant_id else None,
                        "vector_backend": settings.VECTOR_BACKEND,
                        "retrieval_mode": mode_used,
                        "route": model_route,
                        "model_used": getattr(llm, "model_name", None) or getattr(llm, "model", None),
                        "metrics": done_payload["data"]["metrics"],
                        "request_id": request_id,
                    }
                )
                return

            # Step 2: 额外召回 KG 事件（可选）
            kg_context = ""
            if settings.KG_ENABLED and settings.KG_CHAT_ENABLED and tenant_id and document_ids:
                kg_result = await kg_search(
                    query=question,
                    tenant_id=tenant_id,
                    document_ids=document_ids,
                )
                events = (kg_result or {}).get("events") or []
                if events:
                    parts = []
                    for idx, ev in enumerate(events[:5], 1):
                        title = (ev.get("title") or "").strip()
                        summary = (ev.get("summary") or "").strip()
                        if len(summary) > 600:
                            summary = summary[:600] + "..."
                        parts.append(f"[事件 {idx}] {title}\n{summary}")
                    kg_context = "\n\n".join(parts)
                    if settings.RAG_CONTEXT_MAX_KG_CHARS > 0 and len(kg_context) > settings.RAG_CONTEXT_MAX_KG_CHARS:
                        kg_context = kg_context[: settings.RAG_CONTEXT_MAX_KG_CHARS] + "..."

            # Step 3: 构建上下文（文档切片 + 可选 KG 事件）
            chunk_context = ""
            if docs:
                max_per_chunk = max(0, int(settings.RAG_CONTEXT_MAX_CHARS_PER_CHUNK or 0))
                max_total = max(0, int(settings.RAG_CONTEXT_MAX_TOTAL_CHARS or 0))
                total_chars = 0
                context_parts = []
                for idx, doc in enumerate(docs, 1):
                    meta = doc.metadata or {}
                    source = meta.get("source", "Unknown")
                    page_info = None
                    page_raw = meta.get("page")
                    try:
                        page_int = int(page_raw) if page_raw is not None else None
                        if page_int and page_int > 0:
                            page_info = f"第{page_int}页"
                    except Exception:
                        page_info = None
                    header = meta.get("header_path") or meta.get("header_context")
                    retrieval_role = meta.get("retrieval_role")
                    role_info = None
                    if retrieval_role == "neighbor":
                        role_info = "邻接"
                    elif retrieval_role:
                        role_info = str(retrieval_role)
                    raw_content = (doc.page_content or "").strip()
                    content = raw_content
                    if bool(settings.RAG_CONTEXT_EVIDENCE_ENABLED):
                        content = extract_evidence_text(
                            raw_content,
                            query_for_retrieval,
                            max_chars=max_per_chunk,
                            max_sentences=settings.RAG_CONTEXT_EVIDENCE_MAX_SENTENCES_PER_CHUNK,
                            min_sentence_chars=settings.RAG_CONTEXT_EVIDENCE_MIN_SENTENCE_CHARS,
                        )
                    elif max_per_chunk and len(content) > max_per_chunk:
                        content = content[:max_per_chunk] + "..."
                    info_parts = [str(source)]
                    if page_info:
                        info_parts.append(page_info)
                    if header:
                        info_parts.append(str(header))
                    if role_info:
                        info_parts.append(str(role_info))
                    context_parts.append(
                        f"[来源 {idx}: {' | '.join(info_parts)}]\n{content}"
                    )
                    if max_total:
                        total_chars += len(context_parts[-1])
                        if total_chars >= max_total:
                            break
                chunk_context = "\n\n".join(context_parts)

            context_sections = []
            if kg_context:
                context_sections.append(f"【KG 事件检索】\n{kg_context}")
            if chunk_context:
                context_sections.append(f"【文档切片检索】\n{chunk_context}")
            context = "\n\n".join(context_sections) if context_sections else "没有找到相关的参考资料。"

            # Optional trace log for debugging/regression replay (guarded by ENABLE_METRICS_LOG).
            log_metrics(
                {
                    "event": "rag_trace",
                    "conversation_id": str(conversation_id) if conversation_id else None,
                    "tenant_id": str(tenant_id) if tenant_id else None,
                    "request_id": request_id,
                    "question": question,
                    "query_for_retrieval": query_for_retrieval,
                    "history_chars": len(history_text or ""),
                    "context_chars": len(context or ""),
                    "context_evidence": {
                        "enabled": bool(settings.RAG_CONTEXT_EVIDENCE_ENABLED),
                        "max_sentences_per_chunk": int(settings.RAG_CONTEXT_EVIDENCE_MAX_SENTENCES_PER_CHUNK or 0),
                        "min_sentence_chars": int(settings.RAG_CONTEXT_EVIDENCE_MIN_SENTENCE_CHARS or 0),
                    },
                    "query_expansion": {
                        "multi_query_enabled": bool(settings.ENABLE_MULTI_QUERY),
                        "multi_query_used": bool(multi_query_used),
                        "multi_query_count": len(multi_queries),
                        "multi_query_elapsed_sec": round(multi_query_elapsed, 3),
                        "multi_query_model_used": multi_query_model_used,
                        "multi_query_parse_ok": bool(multi_query_parse_meta.get("ok")),
                        "multi_query_parse_error": multi_query_parse_meta.get("error"),
                        "hyde_enabled": bool(settings.ENABLE_HYDE),
                        "hyde_used": bool(hyde_used),
                        "hyde_elapsed_sec": round(hyde_elapsed, 3),
                        "hyde_model_used": hyde_model_used,
                        "decompose_enabled": bool(settings.ENABLE_QUERY_DECOMPOSITION),
                        "decompose_used": bool(decompose_used),
                        "decompose_count": len(sub_questions),
                        "decompose_elapsed_sec": round(decompose_elapsed, 3),
                        "decompose_model_used": decompose_model_used,
                        "decompose_parse_ok": bool(decompose_parse_meta.get("ok")),
                        "decompose_parse_error": decompose_parse_meta.get("error"),
                    },
                    "retrieval": {
                        "mode": mode_used,
                        "requested_mode": mode_req,
                        "auto_routed": bool(mode_auto),
                        "alpha": alpha_val,
                        "enable_weight_rerank": weight_rerank,
                        "vector_weight": vec_w,
                        "keyword_weight": kw_w,
                        "mmr_lambda": mmr_lambda_val,
                        "enable_reranker": rerank_on,
                        "reranker_provider": rerank_provider,
                        "reranker_top_n": rerank_top_n,
                        "query_parallelism": retrieval_parallelism,
                        "query_count": len(retrieval_plan),
                        "per_query": retrieval_per_query[:8],
                        "errors": retrieval_errors[:5],
                    },
                    "citations": citations[: min(len(citations), int(top_k or 5))],
                    "prompt": {
                        "prompt_template_id": str(selected_prompt_template_id) if selected_prompt_template_id else None,
                        "prompt_template_key": selected_prompt_template_key,
                        "prompt_ab_experiment_key": selected_prompt_ab_experiment_key,
                        "prompt_ab_variant": selected_prompt_ab_variant,
                    },
                    "route": {
                        "model_route": model_route,
                        "model_used": getattr(llm, "model_name", None) or getattr(llm, "model", None),
                        "reason": routing_reason,
                    },
                }
            )

            # Step 4: 流式生成回答
            full_response = ""
            gen_start = time.time()
            pii_on = False
            redact_text = None  # type: ignore[assignment]
            try:
                from app.rag.middleware.pii import pii_enabled, redact_text as _redact_text

                pii_on = bool(pii_enabled())
                redact_text = _redact_text
            except Exception:  # noqa: BLE001
                pii_on = False
                redact_text = None  # type: ignore[assignment]

            holdback = max(0, int(getattr(settings, "PII_STREAM_HOLDBACK_CHARS", 128) or 128))
            context_for_model = redact_text(context) if pii_on and redact_text else context
            history_for_model = redact_text(history_text) if pii_on and redact_text else history_text
            question_for_model = redact_text(question) if pii_on and redact_text else question

            pending = ""
            async for token in chain.astream(
                {
                    "context": context_for_model,
                    "history": history_for_model,
                    "question": question_for_model,
                    "format_instructions": format_instructions,
                }
            ):
                if not token:
                    continue
                token_text = token if isinstance(token, str) else str(token)

                if not pii_on or not redact_text:
                    full_response += token_text
                    yield {"type": "token", "data": {"content": token_text}}
                    continue

                pending += token_text
                if holdback and len(pending) <= holdback:
                    continue

                emit_raw = pending[:-holdback] if holdback else pending
                pending = pending[-holdback:] if holdback else ""
                emit_safe = redact_text(emit_raw)
                if emit_safe:
                    full_response += emit_safe
                    yield {"type": "token", "data": {"content": emit_safe}}

            if pii_on and redact_text and pending:
                emit_safe = redact_text(pending)
                if emit_safe:
                    full_response += emit_safe
                    yield {"type": "token", "data": {"content": emit_safe}}

            # Step 4.5: 将引用图片以内嵌 Markdown 的形式追加到正文（仅非结构化输出，可配置）
            if (
                not structured_output
                and citations
                and bool(settings.SHOW_IMAGE_IN_ANSWER)
                and settings.IMAGE_APPEND_MAX > 0
            ):
                image_urls: List[str] = []
                for c in citations:
                    if not c.get("has_image"):
                        continue
                    url = c.get("img_url")
                    if not isinstance(url, str) or not url.strip():
                        continue
                    if url in image_urls:
                        continue
                    image_urls.append(url)
                    if len(image_urls) >= settings.IMAGE_APPEND_MAX:
                        break

                if image_urls:
                    images_md_parts = ["\n\n---\n\n### 相关图片\n"]
                    for i, url in enumerate(image_urls, 1):
                        images_md_parts.append(f"![引用图片 {i}]({url})")
                    images_md = "\n\n".join(images_md_parts) + "\n"
                    images_md_safe = redact_text(images_md) if pii_on and redact_text else images_md
                    full_response += images_md_safe
                    yield {"type": "token", "data": {"content": images_md_safe}}

            # Step 5: 发送完成信号
            generation_elapsed = time.time() - gen_start
            t_total = time.time() - t_all_start
            structured_data = None
            structured_parse_meta = {"ok": False, "method": None, "error": None}
            if structured_output:
                structured_data, structured_parse_meta = parse_json_from_text(full_response, expected="object")
            answer_chars = len(full_response or "")
            answer_tokens = num_tokens_from_string(full_response or "")
            done_payload = {
                "type": "done",
                "data": {
                    "conversation_id": str(conversation_id) if conversation_id else None,
                    "total_tokens": answer_tokens,
                    "total_chars": answer_chars,
                    "citations_count": len(citations),
                    "model_used": getattr(llm, "model_name", None) or getattr(llm, "model", None),
                    "route": model_route,
                    "retrieval_mode": mode_used,
                    "vector_backend": settings.VECTOR_BACKEND,
                    "metrics": {
                        "elapsed_sec": round(t_total, 3),
                        "retrieval_elapsed_sec": round(retrieval_elapsed, 3),
                        "generation_elapsed_sec": round(generation_elapsed, 3),
                        "retrieval_mode": mode_used,
                        "retrieval_mode_requested": mode_req,
                        "retrieval_mode_auto_routed": bool(mode_auto),
                        "retrieval_fusion_strategy": settings.RETRIEVAL_FUSION_STRATEGY,
                        "retrieval_rrf_k": settings.RETRIEVAL_RRF_K if settings.RETRIEVAL_FUSION_STRATEGY == "rrf" else None,
                        "retrieval_dedup_enabled": bool(settings.RETRIEVAL_DEDUP_ENABLED),
                        "retrieval_max_chunks_per_doc": int(settings.RETRIEVAL_MAX_CHUNKS_PER_DOC or 0),
                        "retrieval_min_distinct_docs": int(settings.RETRIEVAL_MIN_DISTINCT_DOCS or 0),
                        "vector_backend": settings.VECTOR_BACKEND,
                        "model_route": model_route,
                        "top_k": top_k,
                        "docs_returned": len(docs),
                        "distinct_documents": len({c.get("document_id") for c in citations if c.get("document_id")}),
                        "history_chars": len(history_text or ""),
                        "context_chars": len(context or ""),
                        "answer_chars": answer_chars,
                        "answer_tokens": answer_tokens,
                        "context_evidence_enabled": bool(settings.RAG_CONTEXT_EVIDENCE_ENABLED),
                        "context_evidence_max_sentences_per_chunk": (
                            int(settings.RAG_CONTEXT_EVIDENCE_MAX_SENTENCES_PER_CHUNK or 0)
                            if bool(settings.RAG_CONTEXT_EVIDENCE_ENABLED)
                            else None
                        ),
                        "context_evidence_min_sentence_chars": (
                            int(settings.RAG_CONTEXT_EVIDENCE_MIN_SENTENCE_CHARS or 0)
                            if bool(settings.RAG_CONTEXT_EVIDENCE_ENABLED)
                            else None
                        ),
                        "llm_max_retries": settings.LLM_MAX_RETRIES,
                        "query_rewrite_enabled": settings.ENABLE_QUERY_REWRITE,
                        "rewrite_used": bool(rewrite_used),
                        "rewrite_elapsed_sec": round(rewrite_elapsed, 3),
                        "rewrite_model_used": rewrite_model_used,
                        "multi_query_enabled": bool(settings.ENABLE_MULTI_QUERY),
                        "multi_query_used": bool(multi_query_used),
                        "multi_query_count": len(multi_queries),
                        "multi_query_elapsed_sec": round(multi_query_elapsed, 3),
                        "multi_query_model_used": multi_query_model_used,
                        "multi_query_parse_ok": bool(multi_query_parse_meta.get("ok")),
                        "multi_query_parse_method": multi_query_parse_meta.get("method"),
                        "multi_query_parse_error": multi_query_parse_meta.get("error"),
                        "hyde_enabled": bool(settings.ENABLE_HYDE),
                        "hyde_used": bool(hyde_used),
                        "hyde_elapsed_sec": round(hyde_elapsed, 3),
                        "hyde_model_used": hyde_model_used,
                        "decompose_enabled": bool(settings.ENABLE_QUERY_DECOMPOSITION),
                        "decompose_used": bool(decompose_used),
                        "decompose_count": len(sub_questions),
                        "decompose_elapsed_sec": round(decompose_elapsed, 3),
                        "decompose_model_used": decompose_model_used,
                        "decompose_parse_ok": bool(decompose_parse_meta.get("ok")),
                        "decompose_parse_method": decompose_parse_meta.get("method"),
                        "decompose_parse_error": decompose_parse_meta.get("error"),
                        "structured_parse_ok": bool(structured_parse_meta.get("ok")),
                        "structured_parse_method": structured_parse_meta.get("method"),
                        "structured_parse_error": structured_parse_meta.get("error"),
                        "structured_type": type(structured_data).__name__ if structured_data is not None else None,
                        "structured_preset": structured_preset,
                        "prompt_template_id": str(selected_prompt_template_id) if selected_prompt_template_id else None,
                        "prompt_template_key": selected_prompt_template_key,
                        "prompt_ab_experiment_key": selected_prompt_ab_experiment_key,
                        "prompt_ab_variant": selected_prompt_ab_variant,
                    },
                    "structured": bool(structured_parse_meta.get("ok")) and structured_data is not None,
                    "structured_data": structured_data,
                }
            }
            yield done_payload

            # 日志落地（可选）
            log_metrics(
                {
                    "event": "rag_done",
                    "conversation_id": str(conversation_id) if conversation_id else None,
                    "tenant_id": str(tenant_id) if tenant_id else None,
                    "vector_backend": settings.VECTOR_BACKEND,
                    "retrieval_mode": mode_used,
                    "route": model_route,
                    "model_used": getattr(llm, "model_name", None) or getattr(llm, "model", None),
                    "metrics": done_payload["data"]["metrics"],
                    "request_id": request_id,
                }
            )

        except Exception as e:
            # 错误处理
            log_metrics(
                {
                    "event": "rag_error",
                    "conversation_id": str(conversation_id) if conversation_id else None,
                    "tenant_id": str(tenant_id) if tenant_id else None,
                    "vector_backend": settings.VECTOR_BACKEND,
                    "retrieval_mode": retrieval_mode,
                    "request_id": request_id,
                    "error": str(e),
                }
            )
            yield {
                "type": "error",
                "data": {"message": str(e)}
            }


_rag_engine_instance: Optional[RAGEngine] = None
_rag_engine_lock: threading.Lock = threading.Lock()


def get_rag_engine() -> RAGEngine:
    """Lazily initialize the simple RAG engine (thread-safe)."""
    global _rag_engine_instance
    if _rag_engine_instance is None:
        with _rag_engine_lock:
            # Double-check locking pattern
            if _rag_engine_instance is None:
                _rag_engine_instance = RAGEngine()
    return _rag_engine_instance


def reset_rag_engine() -> None:
    """Reset the cached RAG engine so new settings take effect."""
    global _rag_engine_instance
    with _rag_engine_lock:
        _rag_engine_instance = None
