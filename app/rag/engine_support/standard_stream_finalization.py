"""Final event and metrics phases for standard RAG streaming."""

import time
from collections.abc import AsyncGenerator
from typing import Any

from app.core.config import settings
from app.rag.engine_support.standard_stream_state import (
    StandardStreamState,
    StreamOperation,
)


async def finalization_phase(runtime: StandardStreamState) -> AsyncGenerator[dict[str, Any], None]:
    # Step 5: Send completion signal.
    runtime.data.generation_elapsed = time.time() - runtime.data.gen_start
    runtime.data.t_total = time.time() - runtime.data.t_all_start
    runtime.data.structured_data = None
    runtime.data.structured_parse_meta = {"ok": False, "method": None, "error": None}
    if runtime.data.structured_output:
        runtime.data.structured_citations: list[dict[str, Any]] = []
        for runtime.data.c in (
            runtime.data.citations[: max(0, int(runtime.data.top_k or 0))] if runtime.data.citations else []
        ):
            runtime.data.structured_citations.append(
                {
                    "document_id": runtime.data.c.get("document_id"),
                    "chunk_id": runtime.data.c.get("chunk_id"),
                    "page_number": runtime.data.c.get("page_number"),
                    "relevance_score": runtime.data.c.get("relevance_score"),
                }
            )
        (
            runtime.data.structured_data,
            runtime.data.structured_parse_meta,
        ) = runtime.module.parse_and_repair_structured_output(
            runtime.data.full_response,
            preset=runtime.data.structured_preset,
            fallback_answer=runtime.module._UNABLE_TO_ANSWER_MESSAGE,
            fallback_citations=runtime.data.structured_citations,
        )
    runtime.data.done_payload = {
        "type": "done",
        "data": {
            "conversation_id": str(runtime.data.conversation_id) if runtime.data.conversation_id else None,
            "total_tokens": runtime.data.answer_tokens,
            "total_chars": runtime.data.answer_chars,
            "citations_count": len(runtime.data.citations),
            "model_used": runtime.data.llm_model_used,
            "route": runtime.data.model_route,
            "retrieval_mode": runtime.data.mode_used,
            "vector_backend": settings.VECTOR_BACKEND,
            "metrics": {
                "elapsed_sec": round(runtime.data.t_total, 3),
                "retrieval_elapsed_sec": round(runtime.data.retrieval_elapsed, 3),
                "generation_elapsed_sec": round(runtime.data.generation_elapsed, 3),
                "generation_max_tokens": runtime.data.generation_max_tokens or None,
                "retrieval_mode": runtime.data.mode_used,
                "retrieval_mode_requested": runtime.data.mode_req,
                "retrieval_mode_auto_routed": bool(runtime.data.mode_auto),
                "retrieval_profile": runtime.data.profile_norm or None,
                "retrieval_profile_requested": (
                    str(runtime.data.profile_req).strip().lower() if runtime.data.profile_req is not None else None
                ),
                "retrieval_contract_mode": runtime.data.retrieval_contract_mode_effective or None,
                "retrieval_contract_policy": dict(runtime.data.retrieval_contract_policy or {}),
                "intent_router_enabled": bool(runtime.data.intent_router_meta.get("enabled")),
                "intent_router_used": bool(runtime.data.intent_router_meta.get("used")),
                "intent_router": runtime.data.intent_router_meta,
                "complexity_score": round(float(runtime.data.complexity_score), 3),
                "adaptive_retrieval_used": bool(runtime.data.adaptive_retrieval_used),
                "adaptive_retrieval_overrides": dict(runtime.data.adaptive_retrieval_overrides),
                "input_guard": dict(runtime.data.input_guard_result),
                "corrective_enabled": bool(runtime.data.corrective_enabled),
                "corrective_used": bool(runtime.data.corrective_used),
                "corrective_attempt_count": int(runtime.data.corrective_attempt_count),
                "corrective_reason_codes": list(runtime.data.corrective_reason_codes or []),
                "corrective_attempts": list(runtime.data.corrective_attempts[:3]),
                "corrective_second_pass": {
                    "retrieval_profile": runtime.data.corrective_second_profile,
                    "enable_multi_query": bool(runtime.data.corrective_second_enable_mq),
                    "multi_query_count": int(runtime.data.corrective_second_mq_count),
                },
                "retrieval_fusion_strategy": settings.RETRIEVAL_FUSION_STRATEGY,
                "retrieval_rrf_k": (settings.RETRIEVAL_RRF_K if settings.RETRIEVAL_FUSION_STRATEGY == "rrf" else None),
                "retrieval_dedup_enabled": bool(settings.RETRIEVAL_DEDUP_ENABLED),
                "retrieval_max_chunks_per_doc": int(settings.RETRIEVAL_MAX_CHUNKS_PER_DOC or 0),
                "retrieval_min_distinct_docs": int(settings.RETRIEVAL_MIN_DISTINCT_DOCS or 0),
                "vector_backend": settings.VECTOR_BACKEND,
                "model_route": runtime.data.model_route,
                "llm_provider_fallback_used": bool(runtime.data.llm_invocation_meta.get("fallback_used")),
                "llm_provider_fallback_target": runtime.data.llm_invocation_meta.get("selected_model"),
                "llm_provider_fallback_failures": int(runtime.data.llm_invocation_meta.get("failure_count") or 0),
                "llm_provider_fallback_attempts": list(runtime.data.llm_invocation_meta.get("attempts") or []),
                "llm_prompt_cache_applied": bool(runtime.data.llm_invocation_meta.get("prompt_cache_applied")),
                "llm_prompt_cache_message_count": int(
                    runtime.data.llm_invocation_meta.get("prompt_cache_message_count") or 0
                ),
                "llm_provider_anthropic_compatible": bool(
                    runtime.data.llm_invocation_meta.get("provider_anthropic_compatible")
                ),
                "top_k": runtime.data.top_k,
                "docs_returned": len(runtime.data.docs),
                "retrieval_rail": dict(runtime.data.retrieval_rail_meta),
                "kg_chunks_injected": int(runtime.data.kg_chunks_injected or 0),
                "recall_bucket": runtime.data.recall_bucket,
                "temporal_intent_enabled": bool(runtime.data.temporal_intent_enabled),
                "temporal_intent_detected": bool(runtime.data.temporal_intent_meta.get("detected")),
                "temporal_intent_reason_codes": list(runtime.data.temporal_intent_meta.get("reason_codes") or []),
                "temporal_recency_rerank": (
                    dict(runtime.data.temporal_recency_meta)
                    if isinstance(runtime.data.temporal_recency_meta, dict)
                    else None
                ),
                "distinct_documents": len(
                    {c.get("document_id") for c in runtime.data.citations if c.get("document_id")}
                ),
                "history_chars": len(runtime.data.history_text or ""),
                "history_tokens": runtime.module.num_tokens_from_string(runtime.data.history_text or ""),
                "context_chars": len(runtime.data.context or ""),
                "context_tokens": runtime.module.num_tokens_from_string(runtime.data.context or ""),
                "tag_enabled": bool(runtime.data.tag_meta.get("enabled")),
                "tag_used": bool(runtime.data.tag_meta.get("used")),
                "tag_reason": runtime.data.tag_meta.get("reason"),
                "tag_tables_returned": int(runtime.data.tag_meta.get("returned") or 0),
                "tag_errors": runtime.data.tag_meta.get("errors"),
                "multimodal_modality": str(runtime.data.multimodal_modality or "text"),
                "multimodal_reasons": list(runtime.data.multimodal_reasons or []),
                "image_enabled": bool(runtime.data.image_meta.get("enabled")),
                "image_used": bool(runtime.data.image_meta.get("used")),
                "image_reason": runtime.data.image_meta.get("reason"),
                "image_hits": int(runtime.data.image_meta.get("hits") or 0),
                "image_docs_returned": int(runtime.data.image_meta.get("returned") or 0),
                "vision_reader_enabled": bool(runtime.data.vision_reader_meta.get("enabled")),
                "vision_reader_used": bool(runtime.data.vision_reader_meta.get("used")),
                "vision_reader_reason": runtime.data.vision_reader_meta.get("reason"),
                "vision_reader_attempted": int(runtime.data.vision_reader_meta.get("attempted") or 0),
                "vision_reader_docs_returned": int(runtime.data.vision_reader_meta.get("returned") or 0),
                "vision_reader_model": runtime.data.vision_reader_meta.get("model"),
                "vision_generation_enabled": bool(runtime.data.vision_generation_meta.get("enabled")),
                "vision_generation_used": bool(runtime.data.vision_generation_meta.get("used")),
                "vision_generation_reason": runtime.data.vision_generation_meta.get("reason"),
                "vision_generation_returned_images": int(
                    runtime.data.vision_generation_meta.get("returned_images") or 0
                ),
                "vision_generation_model": runtime.data.vision_generation_meta.get("model"),
                "context_limit_total_chars": int(settings.RAG_CONTEXT_MAX_TOTAL_CHARS or 0),
                "context_limit_total_tokens": int(getattr(settings, "RAG_CONTEXT_MAX_TOTAL_TOKENS", 0) or 0),
                "context_limit_per_chunk_chars": int(settings.RAG_CONTEXT_MAX_CHARS_PER_CHUNK or 0),
                "context_limit_per_chunk_tokens": int(getattr(settings, "RAG_CONTEXT_MAX_TOKENS_PER_CHUNK", 0) or 0),
                "answer_chars": runtime.data.answer_chars,
                "answer_tokens": runtime.data.answer_tokens,
                # Stable, numeric, PII-safe cost attribution.
                "cost_schema": str(runtime.data.cost_attribution.get("schema") or ""),
                "cost_llm_prompt_tokens": int(runtime.data.prompt_tokens_est),
                "cost_llm_completion_tokens": int(runtime.data.answer_tokens),
                "cost_llm_total_tokens": int(runtime.data.prompt_tokens_est + runtime.data.answer_tokens),
                "cost_llm_source": runtime.data.llm_source,
                "cost_embedding_query_tokens": int(runtime.data.embed_query_tokens),
                "cost_embedding_query_chars": int(runtime.data.embed_query_chars),
                "cost_embedding_query_count": int(len(runtime.data.retrieval_per_query or [])),
                "cost_embedding_provider": str(getattr(settings, "EMBEDDING_PROVIDER", "") or ""),
                "cost_embedding_model": str(getattr(settings, "EMBEDDING_MODEL", "") or ""),
                "cost_retrieval_elapsed_sec": round(float(runtime.data.retrieval_elapsed or 0.0), 3),
                "cost_rerank_elapsed_sec": (
                    round(float(runtime.data.rerank_elapsed_sec), 3)
                    if runtime.data.rerank_elapsed_sec is not None
                    else None
                ),
                "claim_check_enabled": bool(runtime.data.claim_check_applied),
                "claim_check_mode": runtime.data.claim_check_mode,
                "claim_verifier_mode": runtime.data.claim_verifier_mode,
                "claim_verifier_enable_contradiction_check": bool(
                    runtime.data.claim_verifier_enable_contradiction_check
                ),
                "claim_check_removed": int(runtime.data.claim_check_removed),
                "claim_check_total": int(runtime.data.claim_check_total),
                "claim_check_removed_reasons": runtime.data.claim_check_removed_reasons,
                "claim_check_max_claims": int(runtime.data.claim_check_max_claims)
                if runtime.data.claim_check_configured
                else None,
                "claim_nli_verifier": {
                    "enabled": bool(getattr(settings, "RAG_CLAIM_NLI_VERIFIER_ENABLED", False)),
                    "provider": str(getattr(settings, "RAG_CLAIM_NLI_VERIFIER_PROVIDER", "none") or "none"),
                    "model_name": str(getattr(settings, "RAG_CLAIM_NLI_VERIFIER_MODEL", "") or ""),
                },
                "claim_evidence": runtime.data.claim_evidence,
                "sentence_citations_count": int(len(runtime.data.claim_evidence or [])),
                "sentence_citations": runtime.data.claim_evidence,
                "sentence_citations_inline_enabled": bool(runtime.data.sentence_citations_inline_enabled),
                "sentence_citations_inline_style": str(runtime.data.sentence_citations_inline_style),
                "sentence_citations_inline_used": bool(runtime.data.sentence_citations_inline_used),
                "sentence_citations_inline_count": int(runtime.data.sentence_citations_inline_count or 0),
                "sentence_citations_inline_fallback_reason": runtime.data.sentence_citations_inline_fallback_reason,
                "faithfulness_score_enabled": bool(getattr(settings, "FAITHFULNESS_SCORE_ENABLED", True)),
                "faithfulness_score_method": str(runtime.data.faithfulness_meta.get("method") or "claim_support_ratio"),
                "faithfulness_score": runtime.data.faithfulness_meta.get("score"),
                "faithfulness_supported_claims": int(runtime.data.faithfulness_meta.get("supported_claims") or 0),
                "faithfulness_total_claims": int(runtime.data.faithfulness_meta.get("total_claims") or 0),
                "faithfulness_unsupported_claims": list(runtime.data.faithfulness_meta.get("unsupported_claims") or []),
                "confidence_score": runtime.data.confidence_meta.get("score"),
                "confidence_band": runtime.data.confidence_meta.get("band"),
                "confidence_reasons": list(runtime.data.confidence_meta.get("reasons") or []),
                "source_identification_answer_used": bool(runtime.data.source_identification_answer_used),
                "visible_evidence_only_enabled": bool(runtime.data.strict_visible),
                "visible_evidence_only_requested": bool(runtime.data.visible_evidence_only),
                "evidence_span_strict_enabled": bool(runtime.data.evidence_span_strict_enabled),
                "evidence_span_missing_citations": int(runtime.data.evidence_span_missing_citations or 0),
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
                "rewrite_used": bool(runtime.data.rewrite_used),
                "rewrite_elapsed_sec": round(runtime.data.rewrite_elapsed, 3),
                "rewrite_model_used": runtime.data.rewrite_model_used,
                "industry_rules_enabled": bool(runtime.data.industry_rules_meta.get("enabled")),
                "industry_rules_used": bool(runtime.data.industry_rules_meta.get("used")),
                "industry_rules": dict(runtime.data.industry_rules_meta),
                "alias_enabled": bool(runtime.data.alias_enabled),
                "alias_used": bool(runtime.data.alias_used),
                "alias_count": len(runtime.data.alias_queries),
                "alias_elapsed_sec": round(runtime.data.alias_elapsed, 3),
                "dict_enabled": bool(runtime.data.dict_meta.get("enabled")),
                "dict_used": bool(runtime.data.dict_used),
                "dict_count": len(runtime.data.dict_expansions),
                "dict_elapsed_sec": round(runtime.data.dict_elapsed, 3),
                "multi_query_enabled": bool(runtime.data.mq_enabled),
                "multi_query_used": bool(runtime.data.multi_query_used),
                "multi_query_count": len(runtime.data.multi_queries),
                "multi_query_elapsed_sec": round(runtime.data.multi_query_elapsed, 3),
                "multi_query_model_used": runtime.data.multi_query_model_used,
                "multi_query_parse_ok": bool(runtime.data.multi_query_parse_meta.get("ok")),
                "multi_query_parse_method": runtime.data.multi_query_parse_meta.get("method"),
                "multi_query_parse_error": runtime.data.multi_query_parse_meta.get("error"),
                "multi_query_diversify_enabled": bool(runtime.data.mq_diversify_enabled),
                "multi_query_diversify_budget": int(runtime.data.mq_diversify_budget or 0)
                if runtime.data.mq_diversify_enabled
                else 0,
                "multi_query_diversify_used": bool(runtime.data.mq_diversify_used),
                "multi_query_diversify_selected_mq": int(runtime.data.mq_diversify_selected_mq or 0),
                "multi_query_diversify_selected_non_mq": int(runtime.data.mq_diversify_selected_non_mq or 0),
                "multi_query_diversify_fill_from_fused": int(runtime.data.mq_diversify_fill_from_fused or 0),
                "step_back_enabled": bool(runtime.data.step_back_enabled),
                "step_back_used": bool(runtime.data.step_back_used),
                "step_back_elapsed_sec": round(runtime.data.step_back_elapsed, 3),
                "step_back_model_used": runtime.data.step_back_model_used,
                "step_back_parse_ok": bool(runtime.data.step_back_parse_meta.get("ok")),
                "step_back_parse_method": runtime.data.step_back_parse_meta.get("method"),
                "step_back_parse_error": runtime.data.step_back_parse_meta.get("error"),
                "kg_query_expansion_enabled": bool(runtime.data.kg_query_expansion_enabled),
                "kg_query_expansion_used": bool(runtime.data.kg_query_expansion_used),
                "kg_query_expansion_entities_total": int(runtime.data.kg_query_expansion_entities_total),
                "kg_query_expansion_entities_selected": int(runtime.data.kg_query_expansion_entities_selected),
                "kg_query_expansion_query_count": int(len(runtime.data.kg_query_expansion_queries)),
                "kg_query_expansion_elapsed_sec": round(float(runtime.data.kg_query_expansion_elapsed), 3),
                "kg_query_expansion_error": runtime.data.kg_query_expansion_error,
                "hyde_enabled": bool(runtime.data.hyde_enabled),
                "hyde_used": bool(runtime.data.hyde_used),
                "hyde_elapsed_sec": round(runtime.data.hyde_elapsed, 3),
                "hyde_model_used": runtime.data.hyde_model_used,
                "decompose_enabled": bool(runtime.data.dq_enabled),
                "decompose_used": bool(runtime.data.decompose_used),
                "decompose_count": len(runtime.data.sub_questions),
                "decompose_elapsed_sec": round(runtime.data.decompose_elapsed, 3),
                "decompose_model_used": runtime.data.decompose_model_used,
                "decompose_parse_ok": bool(runtime.data.decompose_parse_meta.get("ok")),
                "decompose_parse_method": runtime.data.decompose_parse_meta.get("method"),
                "decompose_parse_error": runtime.data.decompose_parse_meta.get("error"),
                "structured_parse_ok": bool(runtime.data.structured_parse_meta.get("ok")),
                "structured_parse_method": runtime.data.structured_parse_meta.get("method"),
                "structured_parse_error": runtime.data.structured_parse_meta.get("error"),
                "structured_type": type(runtime.data.structured_data).__name__
                if runtime.data.structured_data is not None
                else None,
                "structured_preset": runtime.data.structured_preset,
                "output_guard": dict(runtime.data.output_guard_result),
                "prompt_template_id": str(runtime.data.selected_prompt_template_id)
                if runtime.data.selected_prompt_template_id
                else None,
                "prompt_template_key": runtime.data.selected_prompt_template_key,
                "prompt_ab_experiment_key": runtime.data.selected_prompt_ab_experiment_key,
                "prompt_ab_variant": runtime.data.selected_prompt_ab_variant,
            },
            "structured": bool(runtime.data.structured_parse_meta.get("ok"))
            and runtime.data.structured_data is not None,
            "structured_data": runtime.data.structured_data,
        },
    }
    yield runtime.data.done_payload

    # Persist logs (optional).
    runtime.module.log_metrics(
        {
            "event": "rag_done",
            "conversation_id": str(runtime.data.conversation_id) if runtime.data.conversation_id else None,
            "tenant_id": str(runtime.data.tenant_id) if runtime.data.tenant_id else None,
            "vector_backend": settings.VECTOR_BACKEND,
            "retrieval_mode": runtime.data.mode_used,
            "route": runtime.data.model_route,
            "model_used": getattr(runtime.data.llm, "model_name", None) or getattr(runtime.data.llm, "model", None),
            "metrics": runtime.data.done_payload["data"]["metrics"],
            "request_id": runtime.data.request_id,
        }
    )


FINALIZATION_OPERATIONS = (StreamOperation(finalization_phase, streams=True),)

__all__ = ["FINALIZATION_OPERATIONS"]
