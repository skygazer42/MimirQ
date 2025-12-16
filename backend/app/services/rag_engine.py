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

from app.core.config import settings
from app.services.hybrid_retriever import hybrid_retriever


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
            chain = self.prompt_template | llm | StrOutputParser()

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
                },
            }

            request_retrieval_mode = retrieval_mode or "hybrid"
            request_alpha = alpha if alpha is not None else 0.6
            request_enable_weight_rerank = bool(enable_weight_rerank)
            request_vector_weight = vector_weight if vector_weight is not None else 0.6
            request_keyword_weight = keyword_weight if keyword_weight is not None else 0.4
            request_mmr_lambda = mmr_lambda if mmr_lambda is not None else settings.RETRIEVAL_MMR_LAMBDA

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
                }
            )
            import time
            t0 = time.time()
            try:
                docs = retriever.invoke(question)
            except Exception as exc:
                yield {
                    "type": "error",
                    "data": {"message": f"retrieval failed: {exc}"}
                }
                docs = []

            # 构建引用信息
            citations: List[Dict[str, Any]] = []
            for doc in docs:
                meta = doc.metadata or {}
                citations.append(
                    {
                        "chunk_id": doc.id,
                        "document_id": meta.get("document_id"),
                        "document_name": meta.get("source", "Unknown"),
                        "chunk_content": doc.page_content[:200] + "...",
                        "page_number": meta.get("page"),
                        "relevance_score": round(float(meta.get("score", 0.0)), 2),
                    }
                )

            # 发送引用信息
            yield {
                "type": "citations",
                "data": citations
            }

            # Step 2: 额外召回 SAG 事件（可选）
            sag_context = ""
            if settings.SAG_ENABLED and settings.SAG_CHAT_ENABLED and tenant_id and document_ids:
                try:
                    from app.services.sag_pipeline import sag_search

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

            # 构建对话历史
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

            # Step 4: 流式生成回答
            full_response = ""
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

            # Step 5: 发送完成信号
            t_total = time.time() - t0
            structured_data = None
            if structured_output:
                try:
                    structured_data = json.loads(full_response)
                except Exception:
                    structured_data = None

            yield {
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
                        "retrieval_mode": request_retrieval_mode,
                        "vector_backend": settings.VECTOR_BACKEND,
                        "model_route": model_route,
                        "top_k": top_k,
                    },
                    "structured": bool(structured_data),
                    "structured_data": structured_data,
                }
            }

        except Exception as e:
            # 错误处理
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
