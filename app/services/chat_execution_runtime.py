from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
import time
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.openai_compat import normalize_openai_compatible_base_url
from app.rag.core.http import httpx_trust_env


@dataclass(frozen=True)
class ExecutedGraphChatOnceResult:
    content: str
    citations: list[dict[str, Any]]
    metrics: dict[str, Any]
    structured_data: object | None


_MODEL_PROVIDER_UNAVAILABLE_MARKERS = (
    "arrearage",
    "overdue-payment",
    "access denied",
    "insufficient_quota",
    "quota exceeded",
    "billing",
    "payment required",
    "rate limit",
    "rate_limit",
    "api key",
    "unauthorized",
    "authentication",
    "model does not exist",
    "connection error",
    "connecttimeout",
    "readtimeout",
    "timed out",
)
_MODEL_PROVIDER_UNAVAILABLE_UNTIL = 0.0
_MODEL_PROVIDER_AVAILABLE_UNTIL = 0.0
_MODEL_PROVIDER_CIRCUIT_KEY = ""
_MODEL_PROVIDER_UNAVAILABLE_TTL_SEC = 300.0
_MODEL_PROVIDER_AVAILABLE_TTL_SEC = 60.0


def is_model_provider_unavailable_error(exc: BaseException) -> bool:
    """Return true only for upstream model/provider failures that can be safely degraded."""
    text = f"{exc.__class__.__name__}: {exc}".casefold()
    return any(marker in text for marker in _MODEL_PROVIDER_UNAVAILABLE_MARKERS)


def _model_provider_circuit_key() -> str:
    api_key = str(getattr(settings, "LLM_API_KEY", "") or "").strip()
    model = str(getattr(settings, "LLM_MODEL", "") or "").strip()
    api_base = str(getattr(settings, "LLM_API_BASE", "") or "").strip()
    digest = hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:12] if api_key else ""
    return "|".join((api_base, model, digest))


def _ensure_model_provider_circuit_key() -> str:
    global _MODEL_PROVIDER_AVAILABLE_UNTIL, _MODEL_PROVIDER_CIRCUIT_KEY, _MODEL_PROVIDER_UNAVAILABLE_UNTIL
    key = _model_provider_circuit_key()
    if key != _MODEL_PROVIDER_CIRCUIT_KEY:
        _MODEL_PROVIDER_CIRCUIT_KEY = key
        _MODEL_PROVIDER_UNAVAILABLE_UNTIL = 0.0
        _MODEL_PROVIDER_AVAILABLE_UNTIL = 0.0
    return key


def mark_model_provider_unavailable(*, ttl_sec: float = _MODEL_PROVIDER_UNAVAILABLE_TTL_SEC) -> None:
    """Open a short in-process circuit after a provider outage to avoid repeated slow failures."""
    global _MODEL_PROVIDER_UNAVAILABLE_UNTIL
    _ensure_model_provider_circuit_key()
    _MODEL_PROVIDER_UNAVAILABLE_UNTIL = max(_MODEL_PROVIDER_UNAVAILABLE_UNTIL, time.monotonic() + max(1.0, ttl_sec))


def is_model_provider_unavailable_circuit_open() -> bool:
    _ensure_model_provider_circuit_key()
    return time.monotonic() < _MODEL_PROVIDER_UNAVAILABLE_UNTIL


async def preflight_model_provider_fast() -> tuple[bool, str | None]:
    """Return provider availability using a bounded OpenAI-compatible smoke request.

    This prevents the first chat request after a restart from paying the full
    graph/generation timeout when the configured provider is already known to be
    unavailable, such as account arrearage or invalid credentials.
    """
    global _MODEL_PROVIDER_AVAILABLE_UNTIL

    _ensure_model_provider_circuit_key()
    now = time.monotonic()
    if now < _MODEL_PROVIDER_UNAVAILABLE_UNTIL:
        return False, "model_provider_circuit_open"
    if now < _MODEL_PROVIDER_AVAILABLE_UNTIL:
        return True, None

    api_key = str(getattr(settings, "LLM_API_KEY", "") or "").strip()
    model = str(getattr(settings, "LLM_MODEL", "") or "").strip()
    api_base = str(getattr(settings, "LLM_API_BASE", "") or "").strip()
    if not api_key or not model or not api_base:
        mark_model_provider_unavailable()
        return False, "LLM_API_KEY/LLM_API_BASE/LLM_MODEL is not configured"

    try:
        base_url = normalize_openai_compatible_base_url(api_base).rstrip("/")
        timeout = httpx.Timeout(1.5, connect=1.0, read=1.5, write=1.0, pool=0.5)
        async with httpx.AsyncClient(trust_env=httpx_trust_env(), timeout=timeout) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "Say 1"}],
                    "temperature": 0,
                    "max_tokens": 1,
                    "stream": False,
                },
            )
        if 200 <= response.status_code < 300:
            _MODEL_PROVIDER_AVAILABLE_UNTIL = time.monotonic() + _MODEL_PROVIDER_AVAILABLE_TTL_SEC
            return True, None
        detail = response.text[:400]
        exc = RuntimeError(f"LLM preflight failed HTTP {response.status_code}: {detail}")
        if response.status_code in {400, 401, 402, 403, 408, 409, 429, 500, 502, 503, 504} or is_model_provider_unavailable_error(exc):
            mark_model_provider_unavailable()
            return False, str(exc)[:400]
        return True, None
    except Exception as exc:  # noqa: BLE001
        if is_model_provider_unavailable_error(exc):
            mark_model_provider_unavailable()
            return False, str(exc)[:400]
        return True, None


def _clean_snippet(value: Any, *, max_chars: int = 320) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 1)].rstrip() + "..."


def build_extractive_fallback_answer(
    *,
    question: str,
    citations: list[dict[str, Any]],
    max_items: int = 4,
    reason: str = "model_provider_unavailable",
) -> str:
    """Build a deterministic answer from retrieved evidence when generation is unavailable."""
    usable: list[str] = []
    for idx, citation in enumerate(citations[: max(1, max_items)], start=1):
        if not isinstance(citation, dict):
            continue
        doc_name = (
            citation.get("document_name")
            or citation.get("filename")
            or citation.get("source")
            or citation.get("metadata", {}).get("document_name")
            or citation.get("metadata", {}).get("source")
            or f"引用 {idx}"
        )
        content = (
            citation.get("chunk_content")
            or citation.get("content")
            or citation.get("text")
            or citation.get("metadata", {}).get("chunk_content")
        )
        snippet = _clean_snippet(content)
        if not snippet:
            continue
        usable.append(f"{idx}. {doc_name}: {snippet}")

    explicit_mode = reason == "explicit_extractive_answer_mode"
    if not usable:
        if explicit_mode:
            return (
                "已按抽取式回答模式检索知识库，但没有找到可用于回答的引用证据。"
                "请检查当前数据集是否已经完成入库和索引。"
            )
        return (
            "模型服务当前不可用，系统已尝试检索知识库，但没有找到可用于回答的引用证据。"
            "请稍后重试，或检查当前数据集是否已经完成入库和索引。"
        )

    question_text = _clean_snippet(question, max_chars=180)
    evidence_lines = "\n".join(usable)
    prefix = "以下为基于已检索引用生成的抽取式可审计摘要。" if explicit_mode else "模型服务当前不可用，以下为基于已检索引用生成的可审计摘要。"
    suffix = "说明：该回答按抽取式模式生成，未调用外部大模型；请以引用内容作为最终核验依据。" if explicit_mode else "说明：该回答未调用外部大模型生成，仅基于返回引用做抽取式摘要；请以引用内容作为最终核验依据。"
    return (
        f"{prefix}\n\n"
        f"问题：{question_text}\n\n"
        "检索证据要点：\n"
        f"{evidence_lines}\n\n"
        f"{suffix}"
    )


def execute_extractive_fallback_once(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    request: Any,
    doc_ids_to_use: list[UUID],
    history_for_llm: list[dict[str, Any]],
    scope_dataset_id: UUID | None,
    dataset_id_used: UUID | None,
    effective_rag_config: Any,
    original_error: BaseException | None = None,
    reason: str = "model_provider_unavailable",
) -> ExecutedGraphChatOnceResult:
    """Run retrieval-only chat degradation for temporary LLM/provider outages."""
    from app.rag.pipelines.langgraph import build_rag_state
    from app.rag.retrieval.orchestrator import run_retrieval

    top_k = max(1, min(int(getattr(effective_rag_config, "top_k", 6) or 6), 6))
    retrieval_mode = str(getattr(effective_rag_config, "retrieval_mode", "hybrid") or "hybrid")
    state = build_rag_state(
        question=request.message,
        history=history_for_llm,
        document_ids=doc_ids_to_use,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=dataset_id_used or scope_dataset_id,
        top_k=top_k,
        score_threshold=getattr(effective_rag_config, "score_threshold", 0.0),
        retrieval_mode=retrieval_mode,
        retrieval_profile=None,
        enable_multi_query=False,
        enable_hyde=False,
        enable_query_rewrite=False,
        enable_reranker=False,
        alpha=getattr(effective_rag_config, "alpha", None),
        fusion_strategy=getattr(effective_rag_config, "fusion_strategy", None),
        fusion_budgets=getattr(effective_rag_config, "fusion_budgets", None),
        fusion_min_scores=getattr(effective_rag_config, "fusion_min_scores", None),
        fusion_weights=getattr(effective_rag_config, "fusion_weights", None),
        enable_weight_rerank=getattr(effective_rag_config, "enable_weight_rerank", None),
        vector_weight=getattr(effective_rag_config, "vector_weight", None),
        keyword_weight=getattr(effective_rag_config, "keyword_weight", None),
        mmr_lambda=getattr(effective_rag_config, "mmr_lambda", None),
        visible_evidence_only=getattr(effective_rag_config, "visible_evidence_only", None),
        metadata_filter=getattr(effective_rag_config, "metadata_filter", None),
        db=db,
    )
    result = run_retrieval(state) or {}
    citations = list(result.get("citations") or [])
    metrics = dict(result.get("metrics") or {})
    metrics.update(
        {
            "generation_fallback_used": True,
            "generation_fallback_kind": "extractive_retrieval_summary",
            "generation_fallback_reason": reason,
            "generation_fallback_top_k": top_k,
            "retrieval_profile": metrics.get("retrieval_profile"),
        }
    )
    if original_error is not None:
        metrics["generation_fallback_error"] = str(original_error)[:400]
    answer = build_extractive_fallback_answer(question=request.message, citations=citations, reason=reason)
    return ExecutedGraphChatOnceResult(
        content=answer,
        citations=citations,
        metrics=metrics,
        structured_data=None,
    )


def execute_graph_chat_once(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    request: Any,
    conversation_id: UUID | None,
    request_id: str,
    doc_ids_to_use: list[UUID],
    history_for_llm: list[dict[str, Any]],
    scope_dataset_id: UUID | None,
    dataset_id_used: UUID | None,
    effective_rag_config: Any,
    effective_prompt_template_id: UUID | None,
    effective_prompt_template_key: str | None,
    effective_prompt_ab_experiment_key: str | None,
    rag_config_template_meta: dict[str, Any] | None,
) -> ExecutedGraphChatOnceResult:
    from app.rag.core.text import parse_json_from_text
    from app.rag.pipelines.langgraph import build_rag_state, rag_workflow

    thread_id = str(conversation_id) if conversation_id else f"rag-{request_id}"
    runtime_context = {
        "request_id": str(request_id),
        "conversation_id": str(conversation_id) if conversation_id else None,
        "tenant_id": str(tenant_id) if tenant_id else None,
        "account_id": account_id,
    }

    state = build_rag_state(
        question=request.message,
        history=history_for_llm,
        document_ids=doc_ids_to_use,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=dataset_id_used or scope_dataset_id,
        top_k=effective_rag_config.top_k,
        score_threshold=effective_rag_config.score_threshold,
        retrieval_mode=effective_rag_config.retrieval_mode,
        retrieval_profile=effective_rag_config.retrieval_profile,
        retrieval_contract_mode=effective_rag_config.retrieval_contract_mode,
        must_recall=effective_rag_config.must_recall,
        must_recall_expected_source_keys=effective_rag_config.must_recall_expected_source_keys,
        must_recall_required_anchor_fields=effective_rag_config.must_recall_required_anchor_fields,
        intent_router=effective_rag_config.intent_router,
        intent_router_policy=effective_rag_config.intent_router_policy,
        enable_query_alias_expansion=effective_rag_config.enable_query_alias_expansion,
        query_aliases=effective_rag_config.query_aliases,
        query_alias_max_queries=effective_rag_config.query_alias_max_queries,
        enable_multi_query=effective_rag_config.enable_multi_query,
        multi_query_count=effective_rag_config.multi_query_count,
        multi_query_temperature=effective_rag_config.multi_query_temperature,
        multi_query_max_chars=effective_rag_config.multi_query_max_chars,
        enable_hyde=effective_rag_config.enable_hyde,
        enable_query_decomposition=effective_rag_config.enable_query_decomposition,
        enable_hierarchy_recall=effective_rag_config.enable_hierarchy_recall,
        hierarchy_family_collapse=effective_rag_config.hierarchy_family_collapse,
        hierarchy_family_aggregation=effective_rag_config.hierarchy_family_aggregation,
        hierarchy_tree_dedup=effective_rag_config.hierarchy_tree_dedup,
        hierarchy_parent_depth=effective_rag_config.hierarchy_parent_depth,
        hierarchy_sibling_window=effective_rag_config.hierarchy_sibling_window,
        hierarchy_overfetch_factor=effective_rag_config.hierarchy_overfetch_factor,
        alpha=effective_rag_config.alpha,
        fusion_strategy=effective_rag_config.fusion_strategy,
        fusion_budgets=effective_rag_config.fusion_budgets,
        fusion_min_scores=effective_rag_config.fusion_min_scores,
        fusion_weights=effective_rag_config.fusion_weights,
        enable_weight_rerank=effective_rag_config.enable_weight_rerank,
        vector_weight=effective_rag_config.vector_weight,
        keyword_weight=effective_rag_config.keyword_weight,
        mmr_lambda=effective_rag_config.mmr_lambda,
        enable_reranker=effective_rag_config.enable_reranker,
        reranker_provider=effective_rag_config.reranker_provider,
        reranker_top_n=effective_rag_config.reranker_top_n,
        metadata_filter=effective_rag_config.metadata_filter,
        max_tokens=effective_rag_config.max_tokens,
        structured_output=request.structured_output,
        structured_preset=request.structured_preset,
        visible_evidence_only=effective_rag_config.visible_evidence_only,
        prompt_template_id=effective_prompt_template_id,
        prompt_template_key=effective_prompt_template_key,
        prompt_ab_experiment_key=effective_prompt_ab_experiment_key,
        ab_user_key=account_id,
        db=db,
    )
    if rag_config_template_meta:
        state["rag_config_template"] = rag_config_template_meta

    multimodal_meta: dict[str, Any] = {"enabled": True, "modality": "text", "reasons": []}
    injected_docs: list[Any] = []

    tag_meta: dict[str, Any] = {"enabled": False, "used": False, "reason": "not_run"}
    image_meta: dict[str, Any] = {"enabled": False, "used": False, "reason": "not_run"}

    try:
        from app.rag.policy.modality_router import classify_query_modality

        modality, reasons = classify_query_modality(request.message)
        multimodal_meta["modality"] = modality
        multimodal_meta["reasons"] = reasons
    except Exception as exc:  # noqa: BLE001
        multimodal_meta["enabled"] = False
        multimodal_meta["modality"] = "text"
        multimodal_meta["reasons"] = [f"router_exception:{str(exc)[:80]}"]
        modality = "text"

    try:
        import inspect

        from app.services.chat_tag_service import build_chat_tag_context_docs

        tag_kwargs: dict[str, Any] = {
            "tenant_id": tenant_id,
            "document_ids": doc_ids_to_use,
            "question": request.message,
        }
        if "must_recall_expected_source_keys" in inspect.signature(build_chat_tag_context_docs).parameters:
            tag_kwargs["must_recall_expected_source_keys"] = (
                effective_rag_config.must_recall_expected_source_keys
            )

        tag_docs, tag_meta = build_chat_tag_context_docs(db, **tag_kwargs)
        if tag_docs:
            injected_docs.extend(tag_docs)
    except Exception as exc:  # noqa: BLE001
        tag_meta = {"enabled": False, "used": False, "reason": f"tag_exception:{str(exc)[:120]}"}

    try:
        if str(modality or "text").lower().strip() == "image":
            from app.services.chat_image_service import build_chat_image_context_docs

            ds_for_images = dataset_id_used or scope_dataset_id
            if ds_for_images is not None:
                image_docs, image_meta = build_chat_image_context_docs(
                    db,
                    tenant_id=tenant_id,
                    account_id=account_id,
                    dataset_id=ds_for_images,
                    question=request.message,
                    top_k=6,
                )
                if image_docs:
                    injected_docs.extend(image_docs)
            else:
                image_meta = {"enabled": False, "used": False, "reason": "missing_dataset_id"}
    except Exception as exc:  # noqa: BLE001
        image_meta = {"enabled": False, "used": False, "reason": f"image_exception:{str(exc)[:120]}"}

    if injected_docs:
        state["tag_docs"] = injected_docs

    state["tag_meta"] = tag_meta
    state["image_meta"] = image_meta
    state["multimodal_router"] = multimodal_meta

    recursion_limit = max(1, int(getattr(settings, "LANGGRAPH_RECURSION_LIMIT", 25) or 25))
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": recursion_limit}
    graph_result = rag_workflow.invoke(state, config=config, context=runtime_context) or {}

    citations_data = graph_result.get("citations") or []
    full_response = graph_result.get("answer") or ""
    metrics_data = dict(graph_result.get("metrics") or {})
    metrics_data.setdefault("multimodal_router", multimodal_meta)
    metrics_data.setdefault("tag", tag_meta)
    metrics_data.setdefault("image", image_meta)

    structured_data = None
    if request.structured_output:
        structured_data, structured_parse_meta = parse_json_from_text(full_response, expected="object")
        metrics_data["structured_parse_ok"] = bool(structured_parse_meta.get("ok"))
        metrics_data["structured_parse_method"] = structured_parse_meta.get("method")
        metrics_data["structured_parse_error"] = structured_parse_meta.get("error")
        metrics_data["structured_type"] = type(structured_data).__name__ if structured_data is not None else None
        metrics_data["structured_preset"] = request.structured_preset

    return ExecutedGraphChatOnceResult(
        content=full_response,
        citations=list(citations_data or []),
        metrics=metrics_data,
        structured_data=structured_data,
    )


async def execute_langchain_chat_once(
    *,
    engine: Any,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    request: Any,
    conversation_id: UUID | None,
    request_id: str,
    doc_ids_to_use: list[UUID],
    history_for_llm: list[dict[str, Any]],
    scope_dataset_id: UUID | None,
    dataset_id_used: UUID | None,
    effective_rag_config: Any,
    effective_prompt_template_id: UUID | None,
    effective_prompt_template_key: str | None,
    effective_prompt_ab_experiment_key: str | None,
    rag_config_template_meta: dict[str, Any] | None,
) -> ExecutedGraphChatOnceResult:
    citations_data: list[Any] = []
    full_response_parts: list[str] = []
    done_data: dict[str, Any] = {}

    async for event in engine.stream_chat(
        question=request.message,
        history=history_for_llm,
        conversation_id=conversation_id,
        document_ids=doc_ids_to_use,
        metadata_filter=effective_rag_config.metadata_filter,
        top_k=effective_rag_config.top_k,
        score_threshold=effective_rag_config.score_threshold,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=dataset_id_used or scope_dataset_id,
        structured_output=request.structured_output,
        retrieval_mode=effective_rag_config.retrieval_mode,
        retrieval_profile=effective_rag_config.retrieval_profile,
        retrieval_contract_mode=effective_rag_config.retrieval_contract_mode,
        must_recall=effective_rag_config.must_recall,
        must_recall_expected_source_keys=effective_rag_config.must_recall_expected_source_keys,
        must_recall_required_anchor_fields=effective_rag_config.must_recall_required_anchor_fields,
        intent_router=effective_rag_config.intent_router,
        intent_router_policy=effective_rag_config.intent_router_policy,
        enable_query_alias_expansion=effective_rag_config.enable_query_alias_expansion,
        query_aliases=effective_rag_config.query_aliases,
        query_alias_max_queries=effective_rag_config.query_alias_max_queries,
        enable_multi_query=effective_rag_config.enable_multi_query,
        multi_query_count=effective_rag_config.multi_query_count,
        multi_query_temperature=effective_rag_config.multi_query_temperature,
        multi_query_max_chars=effective_rag_config.multi_query_max_chars,
        enable_hyde=effective_rag_config.enable_hyde,
        enable_query_decomposition=effective_rag_config.enable_query_decomposition,
        enable_hierarchy_recall=effective_rag_config.enable_hierarchy_recall,
        hierarchy_family_collapse=effective_rag_config.hierarchy_family_collapse,
        hierarchy_family_aggregation=effective_rag_config.hierarchy_family_aggregation,
        hierarchy_tree_dedup=effective_rag_config.hierarchy_tree_dedup,
        hierarchy_parent_depth=effective_rag_config.hierarchy_parent_depth,
        hierarchy_sibling_window=effective_rag_config.hierarchy_sibling_window,
        hierarchy_overfetch_factor=effective_rag_config.hierarchy_overfetch_factor,
        alpha=effective_rag_config.alpha,
        fusion_strategy=effective_rag_config.fusion_strategy,
        fusion_budgets=effective_rag_config.fusion_budgets,
        fusion_min_scores=effective_rag_config.fusion_min_scores,
        fusion_weights=effective_rag_config.fusion_weights,
        enable_weight_rerank=effective_rag_config.enable_weight_rerank,
        vector_weight=effective_rag_config.vector_weight,
        keyword_weight=effective_rag_config.keyword_weight,
        mmr_lambda=effective_rag_config.mmr_lambda,
        enable_reranker=effective_rag_config.enable_reranker,
        reranker_provider=effective_rag_config.reranker_provider,
        reranker_top_n=effective_rag_config.reranker_top_n,
        max_tokens=effective_rag_config.max_tokens,
        structured_preset=request.structured_preset,
        visible_evidence_only=effective_rag_config.visible_evidence_only,
        prompt_template_id=effective_prompt_template_id,
        prompt_template_key=effective_prompt_template_key,
        prompt_ab_experiment_key=effective_prompt_ab_experiment_key,
        rag_config_template=rag_config_template_meta,
        ab_user_key=account_id,
        db=db,
        request_id=str(request_id),
    ):
        etype = event.get("type")
        if etype == "citations":
            citations_data = event.get("data") or []
        elif etype == "token":
            data = event.get("data") or {}
            full_response_parts.append(str(data.get("content") or ""))
        elif etype == "done":
            done_data = event.get("data") or {}
        elif etype == "error":
            data = event.get("data") if isinstance(event.get("data"), dict) else {}
            message = str(data.get("message") or event.get("message") or "RAG stream failed")
            raise RuntimeError(message)

    full_response = "".join(full_response_parts) if full_response_parts else ""
    metrics_data = dict(done_data.get("metrics") or {}) if isinstance(done_data, dict) else {}
    structured_data = done_data.get("structured_data") if isinstance(done_data, dict) else None

    return ExecutedGraphChatOnceResult(
        content=full_response,
        citations=list(citations_data or []),
        metrics=metrics_data,
        structured_data=structured_data,
    )
