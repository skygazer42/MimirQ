"""
LangGraph pipeline for RAG (retrieve -> generate).

This module is the canonical home for the non-streaming LangGraph-based runner.
`app.rag.graph` remains as a backward-compatible import path.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
import concurrent.futures
from functools import partial
import time

from app.rag.core.citations import build_citations_from_docs
from app.rag.core.conversation import format_history_text
from app.rag.retriever import hybrid_retriever
from app.rag.engine import get_rag_engine
from app.core.config import settings
from app.services.prompt_template_selector import resolve_prompt_template


class RAGState(Dict[str, Any]):
    """Graph state: question, history, docs, citations, answer, meta."""


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
    return format_history_text(history, window=settings.CHAT_HISTORY_WINDOW)


def _run_with_retry(node_name: str, func, state: RAGState) -> RAGState:
    """节点级重试 + 超时（秒）。"""
    retries = max(settings.RAG_GRAPH_MAX_RETRIES, 0)
    timeout = max(settings.RAG_GRAPH_TIMEOUT_SEC, 0) or None
    last_exc: Optional[Exception] = None
    attempts = 0
    for _ in range(retries + 1):
        attempts += 1
        try:
            if timeout:
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    fut = pool.submit(func, state)
                    result = fut.result(timeout=timeout)
            else:
                result = func(state)
            metrics = dict(result.get("metrics") or state.get("metrics") or {})
            metrics[f"{node_name}_attempts"] = attempts
            metrics[f"{node_name}_retries"] = max(attempts - 1, 0)
            result["metrics"] = metrics
            return result
        except Exception as exc:  # noqa: BLE001
            last_exc = exc

    if last_exc:
        metrics = dict(state.get("metrics") or {})
        metrics[f"{node_name}_attempts"] = attempts
        metrics[f"{node_name}_retries"] = max(attempts - 1, 0)
        metrics[f"{node_name}_last_error"] = str(last_exc)
        state["metrics"] = metrics
        raise last_exc
    return state


def _retrieve_node(state: RAGState) -> RAGState:
    question = state["question"]
    history_text = _build_history_text(state.get("history"))
    query_for_retrieval = question
    rewrite_elapsed = 0.0
    rewrite_used = False
    rewrite_model_used = None

    if (
        settings.ENABLE_QUERY_REWRITE
        and history_text != "（无历史对话）"
        and len(question) <= settings.QUERY_REWRITE_MAX_CHARS
    ):
        engine = get_rag_engine()
        rewrite_llm = engine.models.get("fast") or engine.models.get("default")  # type: ignore[attr-defined]
        rewrite_model_used = getattr(rewrite_llm, "model_name", None) or getattr(rewrite_llm, "model", None)
        try:
            rewrite_chain = (
                engine.rewrite_prompt  # type: ignore[attr-defined]
                | rewrite_llm.bind(temperature=settings.QUERY_REWRITE_TEMPERATURE)
                | StrOutputParser()
            )
            rw_start = time.time()
            rewritten = rewrite_chain.invoke({"history": history_text, "question": question})
            rewrite_elapsed = time.time() - rw_start
            rewritten = (rewritten or "").strip().strip('"')
            if rewritten:
                query_for_retrieval = rewritten
        except Exception:  # noqa: BLE001
            query_for_retrieval = question
            rewrite_elapsed = 0.0

        rewrite_used = query_for_retrieval != question

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
            "enable_reranker": state.get("enable_reranker", settings.ENABLE_RERANKER),
            "reranker_provider": state.get("reranker_provider", settings.RERANKER_PROVIDER),
            "reranker_top_n": state.get("reranker_top_n", settings.RERANKER_TOP_N),
            "tenant_id": state.get("tenant_id"),
            "document_ids": state.get("document_ids"),
        }
    )
    start = time.time()
    docs = retriever.invoke(query_for_retrieval)
    retrieval_elapsed = time.time() - start

    citations = build_citations_from_docs(
        docs,
        retrieval_elapsed_sec=retrieval_elapsed,
        retrieval_mode=state.get("retrieval_mode", "hybrid"),
    )

    metrics = dict(state.get("metrics") or {})
    metrics["retrieval_elapsed_sec"] = round(retrieval_elapsed, 3)
    metrics["retrieval_mode"] = state.get("retrieval_mode", "hybrid")
    metrics["vector_backend"] = settings.VECTOR_BACKEND
    metrics["query_rewrite_enabled"] = settings.ENABLE_QUERY_REWRITE
    metrics["rewrite_used"] = bool(rewrite_used)
    metrics["rewrite_elapsed_sec"] = round(rewrite_elapsed, 3)
    metrics["rewrite_model_used"] = rewrite_model_used
    return {**state, "docs": docs, "citations": citations, "metrics": metrics}


def _generate_node(state: RAGState) -> RAGState:
    engine = get_rag_engine()
    llm, route, reason = engine._select_llm(state["question"], state.get("history"))  # type: ignore[attr-defined]
    prompt_obj = engine.prompt_template
    prompt_content = state.get("prompt_template_content")
    if prompt_content:
        try:
            prompt_obj = ChatPromptTemplate.from_template(str(prompt_content))
        except Exception:
            prompt_obj = engine.prompt_template

    chain = prompt_obj | llm | StrOutputParser()
    format_instructions = state.get("format_instructions", "")

    ctx = _build_context(state.get("docs") or [])
    hist_text = _build_history_text(state.get("history"))

    start = time.time()
    answer = chain.invoke(
        {
            "context": ctx,
            "history": hist_text,
            "question": state["question"],
            "format_instructions": format_instructions,
        }
    )
    generation_elapsed = time.time() - start

    # 将引用图片以内嵌 Markdown 的形式追加到正文（仅非结构化输出，可配置）
    if not bool(state.get("structured_output")) and bool(settings.SHOW_IMAGE_IN_ANSWER) and settings.IMAGE_APPEND_MAX > 0:
        citations = state.get("citations") or []
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
            parts = ["\n\n---\n\n### 相关图片\n"]
            for i, url in enumerate(image_urls, 1):
                parts.append(f"![引用图片 {i}]({url})")
            answer = (answer or "") + "\n\n".join(parts) + "\n"

    metrics = dict(state.get("metrics") or {})
    metrics["generation_elapsed_sec"] = round(generation_elapsed, 3)
    base = generation_elapsed
    base += float(metrics.get("retrieval_elapsed_sec", 0.0) or 0.0)
    base += float(metrics.get("rewrite_elapsed_sec", 0.0) or 0.0)
    metrics["elapsed_sec"] = round(base, 3)
    metrics["model_route"] = route
    metrics["model_used"] = getattr(llm, "model_name", None) or getattr(llm, "model", None)
    metrics["llm_max_retries"] = settings.LLM_MAX_RETRIES
    metrics["prompt_template_id"] = state.get("prompt_template_id")
    metrics["prompt_template_key"] = state.get("prompt_template_key")
    metrics["prompt_ab_experiment_key"] = state.get("prompt_ab_experiment_key")
    metrics["prompt_ab_variant"] = state.get("prompt_ab_variant")
    return {
        **state,
        "answer": answer,
        "route": route,
        "model_used": getattr(llm, "model_name", None) or getattr(llm, "model", None),
        "routing_reason": reason,
        "metrics": metrics,
    }


def _run_rag_sequential(state: RAGState) -> RAGState:
    state = _run_with_retry("retrieve", _retrieve_node, state)
    state = _run_with_retry("generate", _generate_node, state)
    return state


def build_rag_graph() -> Any:
    """构建一个最小 RAG 流程图：检索 -> 生成 -> 结束。"""
    try:
        from langgraph.graph import StateGraph, END
        from langgraph.checkpoint.memory import MemorySaver
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "LangGraph pipeline is unavailable. "
            "Please install/fix the `langgraph` dependency to use `use_graph=true`."
        ) from exc

    graph = StateGraph(RAGState)

    graph.add_node("retrieve", partial(_run_with_retry, "retrieve", _retrieve_node))
    graph.add_node("generate", partial(_run_with_retry, "generate", _generate_node))
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
    enable_reranker: bool = settings.ENABLE_RERANKER,
    reranker_provider: Optional[str] = settings.RERANKER_PROVIDER,
    reranker_top_n: int = settings.RERANKER_TOP_N,
    structured_output: bool = False,
    structured_preset: Optional[str] = None,
    prompt_template_id: Optional[UUID] = None,
    prompt_template_key: Optional[str] = None,
    prompt_ab_experiment_key: Optional[str] = None,
    ab_user_key: Optional[str] = None,
    db: Optional[Any] = None,
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

    prompt_template_content = None
    selected_prompt_template_id = None
    selected_prompt_template_key = None
    selected_prompt_ab_experiment_key = None
    selected_prompt_ab_variant = None
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
            prompt_template_content = chosen.content
            selected_prompt_template_id = str(chosen.id)
            selected_prompt_template_key = getattr(chosen, "template_key", None)
            selected_prompt_ab_experiment_key = getattr(chosen, "ab_experiment_key", None)
            selected_prompt_ab_variant = getattr(chosen, "ab_variant", None)
            chosen.usage_count += 1
            db.commit()

    state = {
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
        "enable_reranker": enable_reranker,
        "reranker_provider": reranker_provider,
        "reranker_top_n": reranker_top_n,
        "format_instructions": format_instructions,
        "structured_output": bool(structured_output),
        "prompt_template_content": prompt_template_content,
        "prompt_template_id": selected_prompt_template_id,
        "prompt_template_key": selected_prompt_template_key,
        "prompt_ab_experiment_key": selected_prompt_ab_experiment_key,
        "prompt_ab_variant": selected_prompt_ab_variant,
    }

    try:
        app = build_rag_graph()
    except RuntimeError as exc:
        if "LangGraph pipeline is unavailable" not in str(exc):
            raise
        result = _run_rag_sequential(state)
    else:
        result = app.invoke(state)
    return {
        "answer": result.get("answer", ""),
        "citations": result.get("citations", []),
        "model_used": result.get("model_used"),
        "route": result.get("route"),
        "routing_reason": result.get("routing_reason"),
        "metrics": result.get("metrics", {}),
    }
