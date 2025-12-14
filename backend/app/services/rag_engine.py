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

        http_client = httpx.Client(trust_env=trust_env)
        http_async_client = httpx.AsyncClient(trust_env=trust_env)

        try:
            from langchain_openai import ChatOpenAI
        except Exception as exc:
            raise RuntimeError(
                "langchain_openai ChatOpenAI is unavailable or incompatible. "
                "Please reinstall backend requirements in a clean venv."
            ) from exc

        self.llm = ChatOpenAI(
            model=settings.LLM_MODEL,
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_API_BASE,
            temperature=settings.LLM_TEMPERATURE,
            streaming=True,
            timeout=settings.LLM_TIMEOUT,
            max_retries=settings.LLM_MAX_RETRIES,
            http_client=http_client,
            http_async_client=http_async_client,
        )

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
3. 结合对话历史理解上下文，处理代词（如"它"、"这个"）和追问
4. 回答要准确、简洁、专业
5. 引用资料时可以提及来源文件名

【回答】"""
        )

        # LangChain Runnable chain: prompt -> llm -> string output
        self.chain = self.prompt_template | self.llm | StrOutputParser()

    async def stream_chat(
        self,
        question: str,
        history: Optional[List[Dict[str, str]]] = None,
        conversation_id: Optional[UUID] = None,
        document_ids: Optional[List[UUID]] = None,
        top_k: int = 5,
        score_threshold: float = 0.7,
        tenant_id: Optional[UUID] = None,
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
            # Step 1: 混合检索（LangChain Retriever）
            retriever = hybrid_retriever.model_copy(
                update={
                    "k": top_k,
                    "score_threshold": score_threshold,
                    "alpha": 0.6,
                    "tenant_id": tenant_id,
                    "document_ids": document_ids,
                }
            )
            docs = retriever.invoke(question)

            # 构建引用信息
            citations: List[Dict[str, Any]] = []
            for doc in docs:
                meta = doc.metadata or {}
                citations.append(
                    {
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
                for msg in history[-5:]:  # 只保留最近5轮对话
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
            async for token in self.chain.astream(
                {"context": context, "history": history_text, "question": question}
            ):
                if not token:
                    continue
                full_response += token
                yield {
                    "type": "token",
                    "data": {"content": token}
                }

            # Step 5: 发送完成信号
            yield {
                "type": "done",
                "data": {
                    "conversation_id": str(conversation_id) if conversation_id else None,
                    "total_tokens": len(full_response),
                    "citations_count": len(citations)
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
