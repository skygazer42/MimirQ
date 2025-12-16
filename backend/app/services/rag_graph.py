"""
LangGraph 编排的 RAG 流程（检索 -> 重排 -> 生成）。
用于知识库场景的快捷非流式执行，灵感来自示例仓库 RAG_Agent。
"""
from __future__ import annotations

from typing import Dict, Any, List, Optional
from uuid import UUID

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
import concurrent.futures
from functools import partial

from app.services.hybrid_retriever import hybrid_retriever
from app.services.rag_engine import get_rag_engine
from app.core.config import settings


class RAGState(Dict[str, Any]):
    """Graph state: question, history, docs, citations, answer, meta."""
    pass


def _build_context(docs: List[Document]) -> str:
    """格式化检索到的文档上下文。"""
    if not docs:
        return "没有找到相关的参考资料。"
    parts = []
    for idx, doc in enumerate(docs, 1):
        meta = doc.metadata or {}
        source = meta.get("source", "Unknown")
        page = meta.get("page", "N/A")
        parts.append(f"[来源 {idx}: {source} - 第{page}页]\n{doc.page_content}")
    return "\n\n".join(parts)


def _build_history_text(history: Optional[List[Dict[str, str]]]) -> str:
    """压缩历史为可读文本，仅保留窗口。"""
    if not history:
        return "（无历史对话）"
    window = max(settings.CHAT_HISTORY_WINDOW, 0)
    hist_slice = history[-window:] if window else []
    lines = []
    for msg in hist_slice:
        role = "用户" if msg.get("role") == "user" else "助手"
        lines.append(f"{role}: {msg.get('content', '')}")
    return "\n\n".join(lines) if lines else "（无历史对话）"


def build_rag_graph() -> Any:
    """构建一个最小 RAG 流程图：检索 -> 生成 -> 结束。"""
    graph = StateGraph(RAGState)

    def run_with_retry(func, state: RAGState):
        """节点级重试 + 超时（秒）。"""
        retries = max(settings.RAG_GRAPH_MAX_RETRIES, 0)
        timeout = max(settings.RAG_GRAPH_TIMEOUT_SEC, 0) or None
        last_exc = None
        for _ in range(retries + 1):
            try:
                if timeout:
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                        fut = pool.submit(func, state)
                        return fut.result(timeout=timeout)
                else:
                    return func(state)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
        if last_exc:
            raise last_exc
        return state

    def retrieve_node(state: RAGState) -> RAGState:
        retriever = hybrid_retriever.model_copy(
            update={
                "k": state.get("top_k", settings.RETRIEVAL_TOP_K),
                "score_threshold": state.get("score_threshold", settings.SIMILARITY_THRESHOLD),
                "alpha": state.get("alpha", 0.6),
                "retrieval_mode": state.get("retrieval_mode", "hybrid"),
                "enable_weight_rerank": state.get("enable_weight_rerank", True),
                "vector_weight": state.get("vector_weight", 0.6),
                "keyword_weight": state.get("keyword_weight", 0.4),
                "mmr_lambda": state.get("mmr_lambda", settings.RETRIEVAL_MMR_LAMBDA),
                "tenant_id": state.get("tenant_id"),
                "document_ids": state.get("document_ids"),
            }
        )
        docs = retriever.invoke(state["question"])

        citations = []
        for doc in docs:
            meta = doc.metadata or {}
            citations.append(
                {
                    "chunk_id": doc.id,
                    "document_id": meta.get("document_id"),
                    "document_name": meta.get("source", "Unknown"),
                    "chunk_content": doc.page_content[:200] + "...",
                    "page_number": meta.get("page"),
                    "relevance_score": meta.get("score"),
                }
            )

        return {**state, "docs": docs, "citations": citations}

    def generate_node(state: RAGState) -> RAGState:
        engine = get_rag_engine()
        llm, route, reason = engine._select_llm(state["question"], state.get("history"))  # type: ignore[attr-defined]
        chain = engine.prompt_template | llm | StrOutputParser()
        format_instructions = state.get("format_instructions", "")

        ctx = _build_context(state.get("docs") or [])
        hist_text = _build_history_text(state.get("history"))

        answer = chain.invoke(
            {
                "context": ctx,
                "history": hist_text,
                "question": state["question"],
                "format_instructions": format_instructions,
            }
        )

        return {
            **state,
            "answer": answer,
            "route": route,
            "model_used": getattr(llm, "model_name", None) or getattr(llm, "model", None),
            "routing_reason": reason,
        }

    graph.add_node("retrieve", partial(run_with_retry, retrieve_node))
    graph.add_node("generate", partial(run_with_retry, generate_node))
    graph.set_entry_point("retrieve")
    graph.add_edge("retrieve", "generate")
    graph.add_edge("generate", END)

    memory = MemorySaver()
    return graph.compile(checkpointer=memory)


def run_rag_graph(
    question: str,
    history: Optional[List[Dict[str, str]]] = None,
    document_ids: Optional[List[UUID]] = None,
    tenant_id: Optional[UUID] = None,
    top_k: int = 5,
    score_threshold: float = 0.7,
    retrieval_mode: str = "hybrid",
    alpha: float = 0.6,
    enable_weight_rerank: bool = True,
    vector_weight: float = 0.6,
    keyword_weight: float = 0.4,
    mmr_lambda: float = settings.RETRIEVAL_MMR_LAMBDA,
    structured_output: bool = False,
    structured_preset: Optional[str] = None,
) -> Dict[str, Any]:
    """执行 LangGraph RAG 流程，返回 answer/citations/模型信息。"""
    engine = get_rag_engine()
    preset_key = (structured_preset or "").lower()
    format_instructions = ""
    if structured_output:
        format_instructions = engine.structured_presets.get(
            preset_key,
            (
                "请仅返回 JSON，结构: "
                '{"answer": "string", "citations": [{"document_id": "...", "chunk_id": "...", "page_number": null, "relevance_score": 0.0}]}'
                " 不要输出多余文本。"
            ),
        )

    app = build_rag_graph()
    result = app.invoke(
        {
            "question": question,
            "history": history or [],
            "document_ids": document_ids,
            "tenant_id": tenant_id,
            "top_k": top_k,
            "score_threshold": score_threshold,
            "retrieval_mode": retrieval_mode,
            "alpha": alpha,
            "enable_weight_rerank": enable_weight_rerank,
            "vector_weight": vector_weight,
            "keyword_weight": keyword_weight,
            "mmr_lambda": mmr_lambda,
            "format_instructions": format_instructions,
        }
    )
    return {
        "answer": result.get("answer", ""),
        "citations": result.get("citations", []),
        "model_used": result.get("model_used"),
        "route": result.get("route"),
        "routing_reason": result.get("routing_reason"),
    }
