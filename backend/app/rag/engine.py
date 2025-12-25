"""
RAG 对话引擎
"""
from __future__ import annotations

import os
from typing import AsyncGenerator, Dict, Any, List, Optional
from uuid import UUID
import json
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
import httpx
import time

from app.core.config import settings
from app.storage.search.hybrid_retriever import hybrid_retriever
from app.services.metrics_logger import log_metrics


class RAGEngine:
    """RAG 对话引擎"""

    def __init__(self):
        # LLM 配置
        proxy_candidates = [
            os.getenv("HTTPS_PROXY"),
            os.getenv("HTTP_PROXY"),
            os.getenv("ALL_PROXY"),
            os.getenv("https_proxy"),
            os.getenv("http_proxy"),
            os.getenv("all_proxy"),
        ]
        proxies = [p for p in proxy_candidates if p]
        trust_env = True
        socks_proxy = next((p for p in proxies if p.lower().startswith("socks")), None)
        if socks_proxy:
            print(
                f"[WARN] Unsupported SOCKS proxy for LLM detected: {socks_proxy}. "
                "Ignoring env proxies."
            )
            trust_env = False

        self.http_client = httpx.Client(trust_env=trust_env)
        self.http_async_client = httpx.AsyncClient(trust_env=trust_env)

        try:
            from langchain_openai import ChatOpenAI
        except Exception as exc:
            raise RuntimeError(
                "langchain_openai ChatOpenAI is unavailable or incompatible. "
                "Please reinstall backend requirements in a clean venv."
            ) from exc

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


    def _build_llm(self, chat_cls, model_name: str):
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

    async def stream_chat(
        self,
        question: str,
        history: Optional[List[Dict[str, str]]] = None,
        conversation_id: Optional[UUID] = None,
        document_ids: Optional[List[UUID]] = None,
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
                try:
                    from app.services.prompt_template_selector import resolve_prompt_template

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
                except Exception:
                    # 选模版失败时回退到默认 prompt，避免阻塞主链路
                    current_prompt_template = self.prompt_template

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
            if history and len(history) > 0:
                history_text = ""
                window = max(settings.CHAT_HISTORY_WINDOW, 0)
                hist_slice = history[-window:] if window else []
                for msg in hist_slice:  # 可配置的滑动窗口
                    if isinstance(msg, dict):
                        role_value = msg.get("role")
                        content_value = msg.get("content", "")
                    else:
                        role_value = getattr(msg, "role", None)
                        content_value = getattr(msg, "content", "")

                    role = "用户" if role_value == "user" else "助手"
                    history_text += f"{role}: {content_value}\n\n"
            else:
                history_text = "（无历史对话）"

            if not (history_text or "").strip():
                history_text = "（无历史对话）"

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

            request_retrieval_mode = retrieval_mode or "hybrid"
            request_alpha = alpha if alpha is not None else 0.6
            request_enable_weight_rerank = bool(enable_weight_rerank)
            request_vector_weight = vector_weight if vector_weight is not None else 0.6
            request_keyword_weight = keyword_weight if keyword_weight is not None else 0.4
            request_mmr_lambda = mmr_lambda if mmr_lambda is not None else settings.RETRIEVAL_MMR_LAMBDA
            request_enable_reranker = bool(enable_reranker)
            request_reranker_provider = reranker_provider or settings.RERANKER_PROVIDER or "llm"
            request_reranker_top_n = int(reranker_top_n or settings.RERANKER_TOP_N or 20)

            # Step 1: 混合检索（LangChain Retriever）
            retriever = hybrid_retriever.model_copy(
                update={
                    "k": top_k,
                    "score_threshold": score_threshold,
                    "alpha": request_alpha,
                    "tenant_id": tenant_id,
                    "document_ids": document_ids,
                    "retrieval_mode": request_retrieval_mode,
                    "enable_weight_rerank": request_enable_weight_rerank,
                    "vector_weight": request_vector_weight,
                    "keyword_weight": request_keyword_weight,
                    "mmr_lambda": request_mmr_lambda,
                    "enable_reranker": request_enable_reranker,
                    "reranker_provider": request_reranker_provider,
                    "reranker_top_n": request_reranker_top_n,
                }
            )
            t_retrieval_start = time.time()
            try:
                docs = retriever.invoke(query_for_retrieval)
            except Exception as exc:
                yield {
                    "type": "error",
                    "data": {"message": f"retrieval failed: {exc}"}
                }
                docs = []
            retrieval_elapsed = time.time() - t_retrieval_start

            # 构建引用信息
            citations: List[Dict[str, Any]] = []
            for doc in docs:
                meta = doc.metadata or {}
                v_score_raw = float(meta.get("vector_score", 0.0) or 0.0)
                b_score_raw = float(meta.get("bm25_score", 0.0) or 0.0)
                rerank_score = meta.get("rerank_score")
                retrieval_score = meta.get("retrieval_score")
                if request_retrieval_mode == "mmr":
                    hit_type = "mmr"
                elif v_score_raw > b_score_raw:
                    hit_type = "vector"
                elif b_score_raw > v_score_raw:
                    hit_type = "keyword"
                else:
                    hit_type = "hybrid"
                # 提取图片信息（如果有）
                img_id = meta.get("img_id")
                img_url = None
                if img_id:
                    # 生成图片访问 URL
                    img_url = f"/api/v1/documents/image-url/{img_id}"
                
                citation = {
                    "chunk_id": doc.id,
                    "document_id": meta.get("document_id"),
                    "document_name": meta.get("source", "Unknown"),
                    "chunk_content": doc.page_content[:200] + "...",
                    "page_number": meta.get("page"),
                    "relevance_score": round(float(meta.get("score", 0.0)), 2),
                    "vector_score": round(v_score_raw, 3),
                    "bm25_score": round(b_score_raw, 3),
                    "keyword_score": round(float(meta.get("keyword_score", 0.0) or 0.0), 3),
                    "rerank_score": round(float(rerank_score), 3) if rerank_score is not None else None,
                    "retrieval_score": round(float(retrieval_score), 3) if retrieval_score is not None else None,
                    "reranker_provider": meta.get("reranker_provider"),
                    "rerank_elapsed_sec": meta.get("rerank_elapsed_sec"),
                    "rerank_model_used": meta.get("rerank_model_used"),
                    "retrieval_mode": request_retrieval_mode,
                    "vector_backend": settings.VECTOR_BACKEND,
                    "retrieval_elapsed_sec": round(retrieval_elapsed, 3),
                    "hit_type": hit_type,
                }
                
                # 添加图片信息（如果存在）
                if img_id:
                    citation["img_id"] = img_id
                    citation["img_url"] = img_url
                    citation["has_image"] = True
                else:
                    citation["has_image"] = False
                
                citations.append(citation)

            # 发送引用信息
            yield {
                "type": "citations",
                "data": citations
            }

            # Step 2: 额外召回 SAG 事件（可选）
            sag_context = ""
            if settings.SAG_ENABLED and settings.SAG_CHAT_ENABLED and tenant_id and document_ids:
                try:
                    from app.kg.pipeline import sag_search

                    sag_result = await sag_search(
                        query=question,
                        tenant_id=tenant_id,
                        document_ids=document_ids,
                    )
                    events = (sag_result or {}).get("events") or []
                    if events:
                        parts = []
                        for idx, ev in enumerate(events[:5], 1):
                            title = (ev.get("title") or "").strip()
                            summary = (ev.get("summary") or "").strip()
                            if len(summary) > 600:
                                summary = summary[:600] + "..."
                            parts.append(f"[事件 {idx}] {title}\n{summary}")
                        sag_context = "\n\n".join(parts)
                except Exception:
                    sag_context = ""

            # Step 3: 构建上下文（文档切片 + 可选 SAG 事件）
            chunk_context = ""
            if docs:
                context_parts = []
                for idx, doc in enumerate(docs, 1):
                    meta = doc.metadata or {}
                    source = meta.get("source", "Unknown")
                    page = meta.get("page", "N/A")
                    context_parts.append(
                        f"[来源 {idx}: {source} - 第 {page} 页]\n{doc.page_content}"
                    )
                chunk_context = "\n\n".join(context_parts)

            context_sections = []
            if sag_context:
                context_sections.append(f"【SAG 事件检索】\n{sag_context}")
            if chunk_context:
                context_sections.append(f"【文档切片检索】\n{chunk_context}")
            context = "\n\n".join(context_sections) if context_sections else "没有找到相关的参考资料。"

            # Step 4: 流式生成回答
            full_response = ""
            gen_start = time.time()
            async for token in chain.astream(
                {
                    "context": context,
                    "history": history_text,
                    "question": question,
                    "format_instructions": format_instructions,
                }
            ):
                if not token:
                    continue
                full_response += token
                yield {
                    "type": "token",
                    "data": {"content": token}
                }

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
                    full_response += images_md
                    yield {"type": "token", "data": {"content": images_md}}

            # Step 5: 发送完成信号
            generation_elapsed = time.time() - gen_start
            t_total = time.time() - t_all_start
            structured_data = None
            if structured_output:
                try:
                    structured_data = json.loads(full_response)
                except Exception:
                    structured_data = None
            done_payload = {
                "type": "done",
                "data": {
                    "conversation_id": str(conversation_id) if conversation_id else None,
                    "total_tokens": len(full_response),
                    "citations_count": len(citations),
                    "model_used": getattr(llm, "model_name", None) or getattr(llm, "model", None),
                    "route": model_route,
                    "retrieval_mode": request_retrieval_mode,
                    "vector_backend": settings.VECTOR_BACKEND,
                    "metrics": {
                        "elapsed_sec": round(t_total, 3),
                        "retrieval_elapsed_sec": round(retrieval_elapsed, 3),
                        "generation_elapsed_sec": round(generation_elapsed, 3),
                        "retrieval_mode": request_retrieval_mode,
                        "vector_backend": settings.VECTOR_BACKEND,
                        "model_route": model_route,
                        "top_k": top_k,
                        "llm_max_retries": settings.LLM_MAX_RETRIES,
                        "query_rewrite_enabled": settings.ENABLE_QUERY_REWRITE,
                        "rewrite_used": bool(rewrite_used),
                        "rewrite_elapsed_sec": round(rewrite_elapsed, 3),
                        "rewrite_model_used": rewrite_model_used,
                        "structured_preset": structured_preset,
                        "prompt_template_id": str(selected_prompt_template_id) if selected_prompt_template_id else None,
                        "prompt_template_key": selected_prompt_template_key,
                        "prompt_ab_experiment_key": selected_prompt_ab_experiment_key,
                        "prompt_ab_variant": selected_prompt_ab_variant,
                    },
                    "structured": bool(structured_data),
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
                    "retrieval_mode": request_retrieval_mode,
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


def get_rag_engine() -> RAGEngine:
    """Lazily initialize the simple RAG engine."""
    global _rag_engine_instance
    if _rag_engine_instance is None:
        _rag_engine_instance = RAGEngine()
    return _rag_engine_instance
