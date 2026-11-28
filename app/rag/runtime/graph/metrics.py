"""Measure generation quality and populate the existing response metrics."""

from typing import Any

from langchain_core.documents import Document

from app.infrastructure.config import settings
from app.infrastructure.tokens import num_tokens_from_string
from app.rag.llm.prompts.metrics import compute_context_cliff_metrics
from app.rag.runtime.graph.state import RAGState
from app.rag.safety.answer_quality import compute_confidence_score, compute_faithfulness_score


def _generation_evidence_text(docs: list[Document]) -> str:
    evidence_text = "\n".join(doc.page_content for doc in docs if doc.page_content.strip())
    max_evidence_chars = max(0, settings.FAITHFULNESS_SCORE_MAX_EVIDENCE_CHARS)
    if max_evidence_chars and len(evidence_text) > max_evidence_chars:
        return evidence_text[:max_evidence_chars]
    return evidence_text


def _compute_generation_faithfulness(
    *,
    answer: str,
    docs: list[Document],
    verifier_mode: str,
    verifier_enable_contradiction_check: bool,
) -> dict[str, Any]:
    faithfulness_meta: dict[str, Any] = {
        "score": None,
        "supported_claims": 0,
        "total_claims": 0,
        "unsupported_claims": [],
        "method": "claim_support_ratio",
    }
    if not settings.FAITHFULNESS_SCORE_ENABLED:
        return faithfulness_meta
    return compute_faithfulness_score(
        answer=answer,
        evidence_text=_generation_evidence_text(docs),
        max_claims=max(1, int(settings.FAITHFULNESS_SCORE_MAX_CLAIMS)),
        verifier_mode=verifier_mode,
        verifier_enable_contradiction_check=bool(verifier_enable_contradiction_check),
        use_nli_fallback=bool(settings.RAG_CLAIM_NLI_VERIFIER_ENABLED),
        nli_provider=str(settings.RAG_CLAIM_NLI_VERIFIER_PROVIDER),
        nli_model_name=str(settings.RAG_CLAIM_NLI_VERIFIER_MODEL),
        nli_timeout_sec=settings.RAG_CLAIM_NLI_VERIFIER_TIMEOUT_SEC,
    )


def _retrieval_gap(metrics: dict[str, Any]) -> dict[str, Any] | None:
    gap = metrics.get("iterative_pass_gap")
    if isinstance(gap, dict):
        return gap
    fallback_gap = metrics.get("evidence_gap")
    return fallback_gap if isinstance(fallback_gap, dict) else None


def _generation_confidence_meta(
    *,
    metrics: dict[str, Any],
    faithfulness_meta: dict[str, Any],
) -> dict[str, Any]:
    return compute_confidence_score(
        faithfulness_score=faithfulness_meta.get("score"),
        claim_total=faithfulness_meta.get("total_claims"),
        claim_supported=faithfulness_meta.get("supported_claims"),
        evidence_gap=_retrieval_gap(metrics),
    )


def _apply_common_generation_metrics(
    *,
    metrics: dict[str, Any],
    faithfulness_meta: dict[str, Any],
    confidence_meta: dict[str, Any],
    followup_questions: list[str],
    route: str | None,
    model_used: str | None,
    generation_elapsed: float,
    prompt_state: RAGState,
) -> None:
    metrics["generation_elapsed_sec"] = round(float(generation_elapsed), 3)
    metrics["context_evidence_enabled"] = bool(settings.RAG_CONTEXT_EVIDENCE_ENABLED)
    metrics["context_evidence_max_sentences_per_chunk"] = (
        int(settings.RAG_CONTEXT_EVIDENCE_MAX_SENTENCES_PER_CHUNK)
        if bool(settings.RAG_CONTEXT_EVIDENCE_ENABLED)
        else None
    )
    metrics["context_evidence_min_sentence_chars"] = (
        int(settings.RAG_CONTEXT_EVIDENCE_MIN_SENTENCE_CHARS) if bool(settings.RAG_CONTEXT_EVIDENCE_ENABLED) else None
    )
    metrics["faithfulness_score_enabled"] = bool(settings.FAITHFULNESS_SCORE_ENABLED)
    metrics["faithfulness_score_method"] = str(faithfulness_meta.get("method") or "claim_support_ratio")
    metrics["faithfulness_score"] = faithfulness_meta.get("score")
    metrics["faithfulness_supported_claims"] = int(faithfulness_meta.get("supported_claims") or 0)
    metrics["faithfulness_total_claims"] = int(faithfulness_meta.get("total_claims") or 0)
    metrics["faithfulness_unsupported_claims"] = list(faithfulness_meta.get("unsupported_claims") or [])
    metrics["confidence_score"] = confidence_meta.get("score")
    metrics["confidence_band"] = confidence_meta.get("band")
    metrics["confidence_reasons"] = list(confidence_meta.get("reasons") or [])
    metrics["followup_questions"] = list(followup_questions)
    metrics["elapsed_sec"] = round(
        float(generation_elapsed)
        + float(metrics.get("retrieval_elapsed_sec", 0.0) or 0.0)
        + float(metrics.get("rewrite_elapsed_sec", 0.0) or 0.0)
        + float(metrics.get("multi_query_elapsed_sec", 0.0) or 0.0)
        + float(metrics.get("hyde_elapsed_sec", 0.0) or 0.0)
        + float(metrics.get("decompose_elapsed_sec", 0.0) or 0.0),
        3,
    )
    metrics["model_route"] = route
    metrics["model_used"] = model_used
    metrics["llm_max_retries"] = settings.LLM_MAX_RETRIES
    metrics["prompt_template_id"] = prompt_state.get("prompt_template_id")
    metrics["prompt_template_key"] = prompt_state.get("prompt_template_key")
    metrics["prompt_ab_experiment_key"] = prompt_state.get("prompt_ab_experiment_key")
    metrics["prompt_ab_variant"] = prompt_state.get("prompt_ab_variant")


def _populate_standard_generation_metrics(
    *,
    metrics: dict[str, Any],
    state: RAGState,
    ctx: str,
    hist_text: str,
    route: str | None,
    model_used: str | None,
    generation_elapsed: float,
    generation_max_tokens: int,
    claim_ctx: dict[str, Any],
    claim_meta: dict[str, Any],
    claim_evidence: list[dict[str, Any]],
    sentence_meta: dict[str, Any],
    faithfulness_meta: dict[str, Any],
    followup_questions: list[str],
    source_identification_answer_used: bool,
) -> None:
    _apply_common_generation_metrics(
        metrics=metrics,
        faithfulness_meta=faithfulness_meta,
        confidence_meta=_generation_confidence_meta(metrics=metrics, faithfulness_meta=faithfulness_meta),
        followup_questions=followup_questions,
        route=route,
        model_used=model_used,
        generation_elapsed=generation_elapsed,
        prompt_state=state,
    )
    metrics["context_chars"] = len(ctx)
    metrics["context_tokens"] = num_tokens_from_string(ctx)
    metrics.update(
        compute_context_cliff_metrics(
            context_tokens=metrics["context_tokens"],
            threshold_tokens=int(settings.RAG_CONTEXT_CLIFF_THRESHOLD_TOKENS),
        )
    )
    metrics["history_chars"] = len(hist_text)
    metrics["history_tokens"] = num_tokens_from_string(hist_text)
    metrics["question_chars"] = len(state["question"])
    metrics["question_tokens"] = num_tokens_from_string(state["question"])
    metrics["context_limit_total_chars"] = int(settings.RAG_CONTEXT_MAX_TOTAL_CHARS)
    metrics["context_limit_total_tokens"] = int(settings.RAG_CONTEXT_MAX_TOTAL_TOKENS)
    metrics["context_limit_per_chunk_chars"] = int(settings.RAG_CONTEXT_MAX_CHARS_PER_CHUNK)
    metrics["context_limit_per_chunk_tokens"] = int(settings.RAG_CONTEXT_MAX_TOKENS_PER_CHUNK)
    metrics["claim_check_enabled"] = bool(claim_ctx["claim_check_applied"])
    metrics["claim_check_mode"] = claim_ctx["claim_check_mode"]
    metrics["claim_verifier_mode"] = claim_ctx["claim_verifier_mode"]
    metrics["claim_verifier_enable_contradiction_check"] = bool(claim_ctx["claim_verifier_enable_contradiction_check"])
    metrics["claim_check_removed"] = int(claim_meta.get("claim_check_removed") or 0)
    metrics["claim_check_total"] = int(claim_meta.get("claim_check_total") or 0)
    metrics["claim_check_removed_reasons"] = list(claim_meta.get("claim_check_removed_reasons") or [])
    metrics["claim_check_max_claims"] = (
        int(claim_ctx["claim_check_max_claims"]) if claim_ctx["claim_check_configured"] else None
    )
    metrics["claim_nli_verifier"] = {
        "enabled": bool(settings.RAG_CLAIM_NLI_VERIFIER_ENABLED),
        "provider": str(settings.RAG_CLAIM_NLI_VERIFIER_PROVIDER),
        "model_name": str(settings.RAG_CLAIM_NLI_VERIFIER_MODEL),
    }
    metrics["claim_evidence"] = claim_evidence
    metrics["sentence_citations_count"] = len(claim_evidence)
    metrics["sentence_citations"] = claim_evidence
    metrics["sentence_citations_inline_enabled"] = bool(sentence_meta["enabled"])
    metrics["sentence_citations_inline_style"] = str(sentence_meta["style"])
    metrics["sentence_citations_inline_used"] = bool(sentence_meta["used"])
    metrics["sentence_citations_inline_count"] = int(sentence_meta["count"] or 0)
    metrics["sentence_citations_inline_fallback_reason"] = sentence_meta["fallback_reason"]
    metrics["visible_evidence_only_enabled"] = bool(claim_ctx["strict_visible"])
    metrics["visible_evidence_only_requested"] = bool(state.get("visible_evidence_only"))
    metrics["generation_max_tokens"] = generation_max_tokens
    metrics["source_identification_answer_used"] = bool(source_identification_answer_used)
