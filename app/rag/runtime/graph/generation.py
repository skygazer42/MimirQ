"""Generate abstention or standard answers from prepared evidence."""

import json
import time
from typing import Any

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from app.infrastructure.config import settings
from app.infrastructure.security.pii import pii_redaction_enabled, redact_text
from app.rag.llm.prompts.templates import format_history_text
from app.rag.llm.response_parsing import (
    build_abstain_answer_message,
    derive_followup_questions,
    extract_followup_questions_from_answer,
)
from app.rag.llm.structured_output import build_structured_abstain_payload
from app.rag.retrieval.evidence.source_labels import maybe_build_source_identification_answer
from app.rag.runtime.engine import get_rag_engine
from app.rag.runtime.graph.answers import (
    _apply_claim_check_to_answer,
    _build_claim_evidence_safe,
    _build_structured_citations,
    _generation_claim_context,
    _normalized_claim_verifier_mode,
    _render_generation_answer_extras,
)
from app.rag.runtime.graph.context import _build_context
from app.rag.runtime.graph.metrics import (
    _apply_common_generation_metrics,
    _compute_generation_faithfulness,
    _generation_confidence_meta,
    _populate_standard_generation_metrics,
)
from app.rag.runtime.graph.state import RAGState


def _generate_node(state: RAGState) -> RAGState:
    # Grounding guard: retrieval already decided to abstain, skip generation.
    if state.get("abstain_triggered"):
        return _generate_abstain_result(state)
    return _generate_standard_result(state)


def _generate_abstain_result(state: RAGState) -> RAGState:
    _engine, llm, route, reason, model_used = _prepare_generation_model(state)
    abstain_message = build_abstain_answer_message(state.get("abstain_reason"))
    answer = _abstain_answer_payload(state, abstain_message=abstain_message)
    metrics = dict(state.get("metrics") or {})
    followup_questions = derive_followup_questions(metrics.get("abstain_followup"))
    faithfulness_meta = _compute_generation_faithfulness(
        answer=answer,
        docs=state.get("docs") or [],
        verifier_mode=_normalized_claim_verifier_mode(),
        verifier_enable_contradiction_check=bool(settings.RAG_CLAIM_VERIFIER_ENABLE_CONTRADICTION_CHECK),
    )
    _apply_common_generation_metrics(
        metrics=metrics,
        faithfulness_meta=faithfulness_meta,
        confidence_meta=_generation_confidence_meta(metrics=metrics, faithfulness_meta=faithfulness_meta),
        followup_questions=followup_questions,
        route=route,
        model_used=model_used,
        generation_elapsed=0.0,
        prompt_state=state,
    )
    metrics["sentence_citations_count"] = 0
    metrics["sentence_citations"] = []
    metrics["sentence_citations_inline_enabled"] = bool(settings.SENTENCE_CITATIONS_INLINE_ENABLED)
    metrics["sentence_citations_inline_used"] = False
    metrics["sentence_citations_inline_count"] = 0
    return {
        **state,
        "answer": answer,
        "route": route,
        "model_used": model_used,
        "routing_reason": reason,
        "metrics": metrics,
        "followup_questions": followup_questions,
    }


def _generate_standard_result(state: RAGState) -> RAGState:
    engine, llm, route, reason, model_used = _prepare_generation_model(state)
    llm, generation_max_tokens = _apply_generation_max_tokens(llm, state)
    chain = _build_generation_chain(engine=engine, llm=llm, prompt_content=state.get("prompt_template_content"))
    ctx = _build_context(state.get("docs") or [], query=state.get("query_for_retrieval") or state.get("question"))
    hist_text = format_history_text(state.get("history"), window=settings.CHAT_HISTORY_WINDOW)
    pii_on = bool(pii_redaction_enabled())
    answer, generation_elapsed = _invoke_generation_chain(
        chain=chain,
        state=state,
        ctx=ctx,
        hist_text=hist_text,
        pii_on=pii_on,
    )
    answer, source_identification_answer_used, followup_questions = _prepare_generation_answer(
        answer=answer,
        state=state,
        pii_on=pii_on,
    )
    claim_ctx = _generation_claim_context(state=state, ctx=ctx, pii_on=pii_on)
    answer, claim_meta = _apply_claim_check_to_answer(
        answer=answer,
        state=state,
        claim_ctx=claim_ctx,
    )
    claim_evidence = _build_claim_evidence_safe(
        answer=answer,
        state=state,
        claim_ctx=claim_ctx,
    )
    answer, sentence_meta = _render_generation_answer_extras(
        answer=answer,
        state=state,
        pii_on=pii_on,
        claim_ctx=claim_ctx,
        claim_evidence=claim_evidence,
    )
    faithfulness_meta = _compute_generation_faithfulness(
        answer=answer,
        docs=state.get("docs") or [],
        verifier_mode=str(claim_ctx["claim_verifier_mode"]),
        verifier_enable_contradiction_check=bool(claim_ctx["claim_verifier_enable_contradiction_check"]),
    )
    metrics = dict(state.get("metrics") or {})
    _populate_standard_generation_metrics(
        metrics=metrics,
        state=state,
        ctx=ctx,
        hist_text=hist_text,
        route=route,
        model_used=model_used,
        generation_elapsed=generation_elapsed,
        generation_max_tokens=generation_max_tokens,
        claim_ctx=claim_ctx,
        claim_meta=claim_meta,
        claim_evidence=claim_evidence,
        sentence_meta=sentence_meta,
        faithfulness_meta=faithfulness_meta,
        followup_questions=followup_questions,
        source_identification_answer_used=source_identification_answer_used,
    )
    return {
        **state,
        "answer": answer,
        "route": route,
        "model_used": model_used,
        "routing_reason": reason,
        "metrics": metrics,
        "followup_questions": list(followup_questions),
    }


def _prepare_generation_model(state: RAGState) -> tuple[Any, Any, str | None, str | None, str | None]:
    engine = get_rag_engine()
    llm, route, reason = engine._select_llm(state["question"], state.get("history"))  # type: ignore[attr-defined]
    model_used = getattr(llm, "model_name", None) or getattr(llm, "model", None)
    return engine, llm, route, reason, model_used


def _apply_generation_max_tokens(llm: Any, state: RAGState) -> tuple[Any, int]:
    generation_max_tokens = max(0, int(state.get("max_tokens") or 0))
    if generation_max_tokens > 0:
        llm = llm.bind(max_tokens=generation_max_tokens)
    return llm, generation_max_tokens


def _abstain_answer_payload(state: RAGState, *, abstain_message: str) -> str:
    if not state.get("structured_output"):
        return abstain_message
    citations = state.get("citations") or []
    top_k = int(state.get("top_k", settings.RETRIEVAL_TOP_K) or settings.RETRIEVAL_TOP_K)
    payload = build_structured_abstain_payload(
        preset=state.get("structured_preset"),
        answer=abstain_message,
        citations=_build_structured_citations(citations, top_k=top_k),
    )
    return json.dumps(payload, ensure_ascii=False)


def _build_generation_chain(*, engine: Any, llm: Any, prompt_content: Any) -> Any:
    prompt_obj = engine.prompt_template
    if prompt_content is not None:
        prompt_obj = ChatPromptTemplate.from_template(prompt_content)
    return prompt_obj | llm | StrOutputParser()


def _invoke_generation_chain(
    *,
    chain: Any,
    state: RAGState,
    ctx: str,
    hist_text: str,
    pii_on: bool,
) -> tuple[str, float]:
    start = time.time()
    answer = chain.invoke(
        {
            "context": redact_text(ctx) if pii_on else ctx,
            "history": redact_text(hist_text) if pii_on else hist_text,
            "question": redact_text(state["question"]) if pii_on else state["question"],
            "format_instructions": state["format_instructions"],
        }
    )
    rendered = redact_text(str(answer)) if pii_on else str(answer)
    return rendered, time.time() - start


def _prepare_generation_answer(
    *,
    answer: str,
    state: RAGState,
    pii_on: bool,
) -> tuple[str, bool, list[str]]:
    if state.get("structured_output"):
        return answer, False, []

    deterministic_source_answer = maybe_build_source_identification_answer(
        question=state["question"],
        docs=list(state.get("docs") or []),
    )
    if deterministic_source_answer:
        answer = redact_text(deterministic_source_answer) if pii_on else deterministic_source_answer

    followup_questions: list[str] = []
    if settings.RAG_FOLLOWUP_SUGGESTIONS_ENABLED:
        answer, followup_questions = extract_followup_questions_from_answer(answer, max_items=3)
    return answer, bool(deterministic_source_answer), followup_questions
