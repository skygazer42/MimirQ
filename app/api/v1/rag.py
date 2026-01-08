"""
RAG debug/preview API.

For debugging and validating:
- Retrieval parameters (top_k/threshold/mode/weight)
- Access control (tenant + account + document_ids)
"""


from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.chat import ChatRAGConfig, HistoryMessage
from app.core.config import settings
from app.core.database import get_db
from app.services.dataset_service import DatasetService
from app.services.document_access import filter_allowed_document_ids, list_accessible_document_ids

router = APIRouter()


class RetrievePreviewRequest(BaseModel):
    query: str = Field(min_length=1)
    history: List[HistoryMessage] = Field(default_factory=list)
    document_ids: List[UUID] = Field(default_factory=list)
    rag_config: ChatRAGConfig = Field(default_factory=ChatRAGConfig)


class RetrievePreviewResponse(BaseModel):
    query_for_retrieval: str
    citations: List[Dict[str, Any]]
    metrics: Dict[str, Any] = Field(default_factory=dict)


@router.post("/retrieve-preview", response_model=RetrievePreviewResponse)
async def retrieve_preview(
    body: RetrievePreviewRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """Execute retrieval only (no answer generation); for parameter tuning and retrieval quality debugging."""
    DatasetService.ensure_member(db, tenant_id, account_id)

    if body.document_ids:
        allowed_doc_ids = filter_allowed_document_ids(db, tenant_id, account_id, body.document_ids)
    else:
        allowed_doc_ids = list_accessible_document_ids(db, tenant_id, account_id, status="completed")

    if not allowed_doc_ids:
        raise HTTPException(status_code=400, detail="No accessible documents for retrieval")

    from app.rag.pipelines.langgraph import _retrieve_node  # internal reuse

    state: Dict[str, Any] = {
        "question": body.query,
        "history": [m.model_dump() for m in body.history],
        "document_ids": allowed_doc_ids,
        "tenant_id": tenant_id,
        "top_k": body.rag_config.top_k,
        "score_threshold": body.rag_config.score_threshold,
        "retrieval_mode": body.rag_config.retrieval_mode,
        "alpha": body.rag_config.alpha,
        "enable_weight_rerank": body.rag_config.enable_weight_rerank,
        "vector_weight": body.rag_config.vector_weight,
        "keyword_weight": body.rag_config.keyword_weight,
        "mmr_lambda": body.rag_config.mmr_lambda,
        "enable_reranker": body.rag_config.enable_reranker,
        "reranker_provider": body.rag_config.reranker_provider,
        "reranker_top_n": body.rag_config.reranker_top_n,
    }

    result = _retrieve_node(state) or {}
    citations = result.get("citations") or []
    metrics = result.get("metrics") or {}
    query_for_retrieval = (result.get("query_for_retrieval") or body.query or "").strip()

    # Ensure minimum fields exist for UI debugging.
    metrics = dict(metrics)
    metrics.setdefault("vector_backend", settings.VECTOR_BACKEND)
    metrics.setdefault("requested_retrieval_mode", body.rag_config.retrieval_mode)

    return RetrievePreviewResponse(
        query_for_retrieval=query_for_retrieval,
        citations=citations,
        metrics=metrics,
    )


class PromptPreviewRequest(BaseModel):
    query: str = Field(min_length=1)
    history: List[HistoryMessage] = Field(default_factory=list)
    document_ids: List[UUID] = Field(default_factory=list)
    rag_config: ChatRAGConfig = Field(default_factory=ChatRAGConfig)
    structured_output: bool = False
    structured_preset: Optional[str] = None
    prompt_template_id: Optional[UUID] = None
    prompt_template_key: Optional[str] = None
    prompt_ab_experiment_key: Optional[str] = None


class PromptPreviewResponse(BaseModel):
    query_for_retrieval: str
    prompt_messages: List[Dict[str, Any]]
    prompt_text: str
    variables: Dict[str, Any]
    citations: List[Dict[str, Any]] = Field(default_factory=list)
    metrics: Dict[str, Any] = Field(default_factory=dict)
    prompt_template_id: Optional[str] = None
    prompt_template_key: Optional[str] = None
    prompt_ab_experiment_key: Optional[str] = None
    prompt_ab_variant: Optional[str] = None


@router.post("/prompt-preview", response_model=PromptPreviewResponse)
async def prompt_preview(
    body: PromptPreviewRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """Execute retrieval and return final prompt (no LLM call); for debugging prompt/context assembly."""
    DatasetService.ensure_member(db, tenant_id, account_id)

    if body.document_ids:
        allowed_doc_ids = filter_allowed_document_ids(db, tenant_id, account_id, body.document_ids)
    else:
        allowed_doc_ids = list_accessible_document_ids(db, tenant_id, account_id, status="completed")

    if not allowed_doc_ids:
        raise HTTPException(status_code=400, detail="No accessible documents for retrieval")

    from langchain_core.prompts import ChatPromptTemplate

    from app.rag.engine import get_rag_engine
    from app.rag.pipelines.langgraph import _build_context, _build_history_text, _retrieve_node, build_rag_state

    state = build_rag_state(
        question=body.query,
        history=[m.model_dump() for m in body.history],
        document_ids=allowed_doc_ids,
        tenant_id=tenant_id,
        top_k=body.rag_config.top_k,
        score_threshold=body.rag_config.score_threshold,
        retrieval_mode=body.rag_config.retrieval_mode,
        alpha=body.rag_config.alpha,
        enable_weight_rerank=body.rag_config.enable_weight_rerank,
        vector_weight=body.rag_config.vector_weight,
        keyword_weight=body.rag_config.keyword_weight,
        mmr_lambda=body.rag_config.mmr_lambda,
        enable_reranker=body.rag_config.enable_reranker,
        reranker_provider=body.rag_config.reranker_provider,
        reranker_top_n=body.rag_config.reranker_top_n,
        structured_output=body.structured_output,
        structured_preset=body.structured_preset,
        prompt_template_id=body.prompt_template_id,
        prompt_template_key=body.prompt_template_key,
        prompt_ab_experiment_key=body.prompt_ab_experiment_key,
        ab_user_key=account_id,
        db=db,
    )

    retrieved = _retrieve_node(state) or {}
    citations = retrieved.get("citations") or []
    docs = retrieved.get("docs") or []
    metrics = dict(retrieved.get("metrics") or {})
    query_for_retrieval = (retrieved.get("query_for_retrieval") or body.query or "").strip()

    ctx = _build_context(docs, query=query_for_retrieval or body.query)
    hist_text = _build_history_text(state.get("history"))
    format_instructions = state.get("format_instructions") or ""

    engine = get_rag_engine()
    prompt_obj = engine.prompt_template
    prompt_content = state.get("prompt_template_content")
    if prompt_content:
        try:
            prompt_obj = ChatPromptTemplate.from_template(str(prompt_content))
        except Exception:
            prompt_obj = engine.prompt_template

    variables: Dict[str, Any] = {
        "context": ctx,
        "history": hist_text,
        "question": body.query,
        "format_instructions": format_instructions,
    }

    try:
        prompt_value = prompt_obj.format_prompt(**variables)
        prompt_messages = []
        for msg in prompt_value.to_messages():
            prompt_messages.append(
                {
                    "type": getattr(msg, "type", msg.__class__.__name__),
                    "content": getattr(msg, "content", None),
                }
            )
        prompt_text = prompt_value.to_string()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Prompt render failed: {exc}") from exc

    metrics.setdefault("vector_backend", settings.VECTOR_BACKEND)
    metrics.setdefault("requested_retrieval_mode", body.rag_config.retrieval_mode)
    metrics["prompt_chars"] = len(prompt_text or "")
    metrics["context_chars"] = len(ctx or "")
    metrics["history_chars"] = len(hist_text or "")

    return PromptPreviewResponse(
        query_for_retrieval=query_for_retrieval,
        prompt_messages=prompt_messages,
        prompt_text=prompt_text,
        variables=variables,
        citations=citations,
        metrics=metrics,
        prompt_template_id=state.get("prompt_template_id"),
        prompt_template_key=state.get("prompt_template_key"),
        prompt_ab_experiment_key=state.get("prompt_ab_experiment_key"),
        prompt_ab_variant=state.get("prompt_ab_variant"),
    )
