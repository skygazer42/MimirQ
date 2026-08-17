"""Evidence validation and context phases for standard RAG streaming."""

import json
import time
from collections.abc import AsyncGenerator
from typing import Any

from app.core.config import settings
from app.rag.engine_support.standard_stream_corrective import (
    stream_corrective_retrieval,
)
from app.rag.engine_support.standard_stream_state import (
    StandardStreamState,
    StreamOperation,
)


async def apply_temporal_rerank(runtime: StandardStreamState) -> None:
    # Optional: Temporal intent + recency-aware rerank (deterministic, feature-flagged).
    #
    # This does NOT filter documents; it only applies a small additive boost to more
    # recently updated documents when the query indicates freshness intent ("latest", "as of", "最新"...).
    if runtime.data.temporal_intent_enabled and runtime.data.docs:
        try:
            runtime.data.temporal_intent_meta = runtime.module.detect_temporal_intent(runtime.data.query_for_retrieval)
            runtime.data.temporal_boost_enabled = bool(
                getattr(settings, "RAG_TEMPORAL_INTENT_RECENCY_BOOST_ENABLED", True)
            )
            if (
                bool(runtime.data.temporal_intent_meta.get("detected"))
                and bool(runtime.data.temporal_boost_enabled)
                and runtime.data.tenant_id is not None
            ):
                # Extract candidate document ids (bounded).
                runtime.data.doc_ids: list[str] = []
                runtime.data.seen_doc_ids: set[str] = set()
                runtime.data.max_docs = max(0, int(getattr(settings, "RAG_TEMPORAL_INTENT_MAX_DOCS", 200) or 200))
                for runtime.data.d in runtime.data.docs:
                    runtime.data.meta = getattr(runtime.data.d, "metadata", None)
                    runtime.data.meta = runtime.data.meta if isinstance(runtime.data.meta, dict) else {}
                    runtime.data.did = runtime.data.meta.get("document_id")
                    runtime.data.did_s = str(runtime.data.did).strip() if runtime.data.did is not None else ""
                    if not runtime.data.did_s:
                        continue
                    if runtime.data.did_s in runtime.data.seen_doc_ids:
                        continue
                    runtime.data.seen_doc_ids.add(runtime.data.did_s)
                    runtime.data.doc_ids.append(runtime.data.did_s)
                    if runtime.data.max_docs and len(runtime.data.doc_ids) >= runtime.data.max_docs:
                        break

                runtime.data.updated_ts = runtime.module.fetch_document_updated_ts(
                    runtime.data.doc_ids,
                    tenant_id=runtime.data.tenant_id,
                    dataset_id=runtime.data.dataset_id,
                    max_docs=runtime.data.max_docs,
                )
                runtime.data.docs, runtime.data.temporal_recency_meta = runtime.module.apply_recency_boost(
                    runtime.data.docs,
                    updated_ts_by_document_id=runtime.data.updated_ts,
                    boost_max=float(getattr(settings, "RETRIEVAL_GOVERNANCE_LATEST_BOOST_MAX", 0.0) or 0.0),
                    window_days=int(getattr(settings, "RETRIEVAL_GOVERNANCE_LATEST_WINDOW_DAYS", 180) or 180),
                )
            else:
                runtime.data.temporal_recency_meta = {
                    "enabled": bool(runtime.data.temporal_boost_enabled),
                    "used": False,
                    "reason": "not_detected_or_missing_scope",
                }
        except Exception as exc:  # noqa: BLE001
            runtime.data.temporal_intent_meta = {"detected": False, "reason_codes": [], "error": str(exc)[:200]}
            runtime.data.temporal_recency_meta = {"enabled": True, "used": False, "reason": "exception"}


async def apply_rail_and_build_citations(runtime: StandardStreamState) -> AsyncGenerator[dict[str, Any], None]:

    if runtime.data.retrieval_rail_enabled and runtime.data.docs:
        try:
            from app.rag.safety.retrieval_rail import apply_retrieval_rail

            runtime.data.rail_result = apply_retrieval_rail(
                runtime.data.docs,
                mask_pii=settings.RAG_RETRIEVAL_RAIL_MASK_PII,
                pii_mask=settings.RAG_RETRIEVAL_RAIL_PII_MASK,
            )
            runtime.data.docs = list(runtime.data.rail_result.get("docs") or [])
            runtime.data.meta = dict(runtime.data.rail_result.get("meta") or {})
            runtime.data.retrieval_rail_meta = {
                "enabled": True,
                "used": bool(runtime.data.meta.get("used")),
                "blocked_docs": int(runtime.data.meta.get("blocked_docs") or 0),
                "masked_docs": int(runtime.data.meta.get("masked_docs") or 0),
            }
        except Exception as exc:  # noqa: BLE001
            runtime.module.logger.warning("Retrieval rail failed open: %s", str(exc)[:160])
            runtime.data.retrieval_rail_meta = {
                "enabled": True,
                "used": False,
                "blocked_docs": 0,
                "masked_docs": 0,
                "error": str(exc)[:160],
            }

    yield {
        "type": "event",
        "data": {
            "message": f"找到 {len(runtime.data.docs)} 条相关参考，正在整理回答..."
            + (f"（Image 注入 {len(runtime.data.image_docs)} 条）" if runtime.data.image_docs else "")
            + (f"（TAG 注入 {len(runtime.data.tag_docs)} 条）" if runtime.data.tag_docs else ""),
        },
    }

    # Build citation info.
    runtime.data.citations: list[dict[str, Any]] = runtime.module.build_citations_from_docs(
        runtime.data.docs,
        retrieval_elapsed_sec=runtime.data.retrieval_elapsed,
        retrieval_mode=runtime.data.mode_used,
        query=runtime.data.query_for_retrieval,
    )

    runtime.data.evidence_span_strict_enabled = bool(
        bool(getattr(settings, "RAG_EVIDENCE_REQUIRE_SPANS_ENABLED", False))
        or bool(runtime.data.retrieval_contract_policy.get("require_evidence_spans"))
    )
    runtime.data.evidence_span_missing_citations = 0
    if runtime.data.evidence_span_strict_enabled and runtime.data.citations:
        runtime.data.filtered_citations: list[dict[str, Any]] = []
        for runtime.data.item in runtime.data.citations:
            if not isinstance(runtime.data.item, dict):
                continue
            runtime.data.start = runtime.data.item.get("evidence_start_char")
            runtime.data.end = runtime.data.item.get("evidence_end_char")
            try:
                runtime.data.start_i = int(runtime.data.start) if runtime.data.start is not None else None
                runtime.data.end_i = int(runtime.data.end) if runtime.data.end is not None else None
            except Exception:
                runtime.data.start_i = None
                runtime.data.end_i = None
            if runtime.data.start_i is None or runtime.data.end_i is None or runtime.data.end_i <= runtime.data.start_i:
                runtime.data.evidence_span_missing_citations += 1
                continue
            runtime.data.filtered_citations.append(runtime.data.item)
        runtime.data.citations = runtime.data.filtered_citations

    # Send citation info.
    yield {"type": "citations", "data": runtime.data.citations}

    # Step 1.5: No-retrieval/low-evidence refusal (optional).
    #
    # Strict visible-evidence-only grounding treats missing evidence as non-existent:
    # abstain is a normal success path (no error).
    runtime.data.strict_visible = bool(
        bool(getattr(settings, "RAG_VISIBLE_EVIDENCE_ONLY_ENABLED", False))
        or bool(runtime.data.visible_evidence_only)
        or bool(runtime.data.retrieval_contract_policy.get("force_visible_evidence_only"))
    )
    runtime.data.abstain_enabled = (
        bool(settings.RAG_ABSTAIN_ENABLED)
        or runtime.data.strict_visible
        or bool(runtime.data.evidence_span_strict_enabled)
    )
    runtime.data.abstain_triggered = False
    runtime.data.abstain_reason: str | None = None
    runtime.data.top_rel = 0.0
    runtime.data.retrieval_info_event = None


async def evaluate_abstention(runtime: StandardStreamState) -> AsyncGenerator[dict[str, Any], None]:
    if runtime.data.citations:
        try:
            runtime.data.top_rel = max(
                float(
                    # Use final relevance score for abstain gate (post-rerank),
                    # not pre-rerank retrieval_score.
                    (c.get("relevance_score") if c.get("relevance_score") is not None else c.get("retrieval_score"))
                    or 0.0
                )
                for c in runtime.data.citations
            )
        except Exception:
            runtime.data.top_rel = 0.0

    if runtime.data.abstain_enabled:
        runtime.data.min_citations = max(0, int(settings.RAG_ABSTAIN_MIN_CITATIONS or 0))
        runtime.data.min_top_rel = float(settings.RAG_ABSTAIN_MIN_TOP_RELEVANCE_SCORE or 0.0)

        if runtime.data.min_citations > 0 and len(runtime.data.citations) < runtime.data.min_citations:
            runtime.data.abstain_triggered = True
            runtime.data.abstain_reason = "citations_lt_min"
        elif runtime.data.min_top_rel > 0 and runtime.data.top_rel < runtime.data.min_top_rel:
            runtime.data.abstain_triggered = True
            runtime.data.abstain_reason = "top_relevance_lt_min"

    runtime.data.out_of_scope_guard = runtime.module.maybe_apply_out_of_scope_live_guard(
        query=runtime.data.query_for_retrieval,
        enabled=bool(getattr(settings, "RAG_OUT_OF_SCOPE_LIVE_GUARD_ENABLED", False)),
        candidate=bool(runtime.data.abstain_triggered or not runtime.data.citations),
        current_triggered=bool(runtime.data.abstain_triggered),
        current_reason=runtime.data.abstain_reason,
        tenant_id=(str(runtime.data.tenant_id or "").strip() or None),
        dataset_id=(str(runtime.data.dataset_id or "").strip() or None),
        verifier=lambda: runtime.module.run_default_out_of_scope_live_guard(
            query=runtime.data.query_for_retrieval,
            tenant_id=str(runtime.data.tenant_id or ""),
            dataset_id=str(runtime.data.dataset_id or ""),
            ruleset_name=(str(getattr(settings, "RAG_OUT_OF_SCOPE_RULESET", "") or "").strip() or None),
            hyde_query=runtime.data.hyde_text if bool(runtime.data.hyde_used and runtime.data.hyde_text) else None,
            vector_similarity_threshold=float(getattr(settings, "RAG_OUT_OF_SCOPE_VECTOR_THRESHOLD", 0.35) or 0.35),
            hyde_similarity_threshold=float(getattr(settings, "RAG_OUT_OF_SCOPE_HYDE_THRESHOLD", 0.4) or 0.4),
        ),
    )
    runtime.data.abstain_triggered = bool(runtime.data.out_of_scope_guard.get("abstain_triggered"))
    runtime.data.abstain_reason = runtime.data.out_of_scope_guard.get("abstain_reason")
    runtime.data.retrieval_info_event = runtime.engine._build_retrieval_info_event(
        attempt=runtime.data.corrective_attempt_count,
        query_count=len(runtime.data.retrieval_queries),
        docs_count=len(runtime.data.docs),
        citations_count=len(runtime.data.citations),
        abstain_triggered=runtime.data.abstain_triggered,
        retrieval_profile=runtime.data.profile_norm or None,
    )
    if runtime.data.retrieval_info_event is not None:
        yield runtime.data.retrieval_info_event

    runtime.data.corrective_attempts.append(
        {
            "attempt": int(runtime.data.corrective_attempt_count),
            "retrieval_profile": runtime.data.profile_norm or None,
            "query_count": int(len(runtime.data.retrieval_queries)),
            "docs_count": int(len(runtime.data.docs)),
            "citations_count": int(len(runtime.data.citations)),
            "abstain_triggered": bool(runtime.data.abstain_triggered),
            "top_relevance_score": round(float(runtime.data.top_rel or 0.0), 3),
        }
    )


async def emit_abstention_result(runtime: StandardStreamState) -> AsyncGenerator[dict[str, Any], None]:

    if runtime.data.abstain_triggered:
        runtime.data.abstain_message = runtime.module.build_abstain_answer_message(runtime.data.abstain_reason)

        runtime.data.structured_data = None
        runtime.data.structured_parse_meta = {"ok": False, "method": None, "error": None}
        runtime.data.full_response = runtime.data.abstain_message

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
            runtime.data.payload = runtime.module.build_structured_abstain_payload(
                preset=runtime.data.structured_preset,
                answer=runtime.data.abstain_message,
                citations=runtime.data.structured_citations,
            )
            runtime.data.structured_data = runtime.data.payload
            runtime.data.structured_parse_meta = {"ok": True, "method": "abstain", "error": None}
            runtime.data.full_response = json.dumps(runtime.data.payload, ensure_ascii=False)

        # Ensure frontend/DB has content to persist.
        yield {"type": "token", "data": {"content": runtime.data.full_response}}

        runtime.data.t_total = time.time() - runtime.data.t_all_start
        runtime.data.answer_chars = len(runtime.data.full_response or "")
        runtime.data.answer_tokens = runtime.module.num_tokens_from_string(runtime.data.full_response or "")
        runtime.data.faithfulness_meta: dict[str, Any] = {
            "score": None,
            "supported_claims": 0,
            "total_claims": 0,
            "unsupported_claims": [],
            "method": "claim_support_ratio",
        }
        if bool(getattr(settings, "FAITHFULNESS_SCORE_ENABLED", True)):
            runtime.data.evidence_text = "\n".join(
                [
                    str(getattr(d, "page_content", "") or "")
                    for d in (runtime.data.docs or [])
                    if str(getattr(d, "page_content", "") or "").strip()
                ]
            )
            runtime.data.max_evidence_chars = max(
                0, int(getattr(settings, "FAITHFULNESS_SCORE_MAX_EVIDENCE_CHARS", 24_000) or 24_000)
            )
            if runtime.data.max_evidence_chars and len(runtime.data.evidence_text) > runtime.data.max_evidence_chars:
                runtime.data.evidence_text = runtime.data.evidence_text[: runtime.data.max_evidence_chars]
            runtime.data.faithfulness_meta = runtime.module.compute_faithfulness_score(
                answer=str(runtime.data.full_response or ""),
                evidence_text=runtime.data.evidence_text,
                max_claims=max(1, int(getattr(settings, "FAITHFULNESS_SCORE_MAX_CLAIMS", 24) or 24)),
                verifier_mode=(
                    str(getattr(settings, "RAG_CLAIM_VERIFIER_MODE", "token_overlap") or "token_overlap")
                    .strip()
                    .lower()
                ),
                verifier_enable_contradiction_check=bool(
                    getattr(settings, "RAG_CLAIM_VERIFIER_ENABLE_CONTRADICTION_CHECK", True)
                ),
                use_nli_fallback=bool(getattr(settings, "RAG_CLAIM_NLI_VERIFIER_ENABLED", False)),
                nli_provider=str(getattr(settings, "RAG_CLAIM_NLI_VERIFIER_PROVIDER", "none") or "none"),
                nli_model_name=str(getattr(settings, "RAG_CLAIM_NLI_VERIFIER_MODEL", "") or ""),
                nli_timeout_sec=float(getattr(settings, "RAG_CLAIM_NLI_VERIFIER_TIMEOUT_SEC", 8) or 8),
            )
        runtime.data.confidence_meta = runtime.module.compute_confidence_score(
            faithfulness_score=runtime.data.faithfulness_meta.get("score"),
            claim_total=runtime.data.faithfulness_meta.get("total_claims"),
            claim_supported=runtime.data.faithfulness_meta.get("supported_claims"),
            evidence_gap=None,
        )
        runtime.data.abstain_followup = runtime.module.build_abstain_followup(
            reason=runtime.data.abstain_reason, citations=runtime.data.citations
        )
        runtime.data.followup_questions = runtime.module.derive_followup_questions(runtime.data.abstain_followup)
        runtime.data.done_payload = {
            "type": "done",
            "data": {
                "conversation_id": str(runtime.data.conversation_id) if runtime.data.conversation_id else None,
                "total_tokens": runtime.data.answer_tokens,
                "total_chars": runtime.data.answer_chars,
                "citations_count": len(runtime.data.citations),
                "model_used": getattr(runtime.data.llm, "model_name", None) or getattr(runtime.data.llm, "model", None),
                "route": runtime.data.model_route,
                "retrieval_mode": runtime.data.mode_used,
                "vector_backend": settings.VECTOR_BACKEND,
                "metrics": {
                    "elapsed_sec": round(runtime.data.t_total, 3),
                    "retrieval_elapsed_sec": round(runtime.data.retrieval_elapsed, 3),
                    "generation_elapsed_sec": 0.0,
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
                    "industry_rules_enabled": bool(runtime.data.industry_rules_meta.get("enabled")),
                    "industry_rules_used": bool(runtime.data.industry_rules_meta.get("used")),
                    "industry_rules": dict(runtime.data.industry_rules_meta),
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
                    "vector_backend": settings.VECTOR_BACKEND,
                    "model_route": runtime.data.model_route,
                    "top_k": runtime.data.top_k,
                    "docs_returned": len(runtime.data.docs),
                    "retrieval_rail": dict(runtime.data.retrieval_rail_meta),
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
                    "kg_chunks_injected": int(runtime.data.kg_chunks_injected or 0),
                    "recall_bucket": runtime.data.recall_bucket,
                    "distinct_documents": len(
                        {c.get("document_id") for c in runtime.data.citations if c.get("document_id")}
                    ),
                    "history_chars": len(runtime.data.history_text or ""),
                    "context_chars": 0,
                    "llm_max_retries": settings.LLM_MAX_RETRIES,
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
                    "faithfulness_score_enabled": bool(getattr(settings, "FAITHFULNESS_SCORE_ENABLED", True)),
                    "faithfulness_score_method": str(
                        runtime.data.faithfulness_meta.get("method") or "claim_support_ratio"
                    ),
                    "faithfulness_score": runtime.data.faithfulness_meta.get("score"),
                    "faithfulness_supported_claims": int(runtime.data.faithfulness_meta.get("supported_claims") or 0),
                    "faithfulness_total_claims": int(runtime.data.faithfulness_meta.get("total_claims") or 0),
                    "faithfulness_unsupported_claims": list(
                        runtime.data.faithfulness_meta.get("unsupported_claims") or []
                    ),
                    "confidence_score": runtime.data.confidence_meta.get("score"),
                    "confidence_band": runtime.data.confidence_meta.get("band"),
                    "confidence_reasons": list(runtime.data.confidence_meta.get("reasons") or []),
                    "sentence_citations_count": 0,
                    "sentence_citations": [],
                    "sentence_citations_inline_enabled": bool(
                        getattr(settings, "SENTENCE_CITATIONS_INLINE_ENABLED", False)
                    ),
                    "sentence_citations_inline_used": False,
                    "sentence_citations_inline_count": 0,
                    "abstain_enabled": bool(runtime.data.abstain_enabled),
                    "abstain_triggered": True,
                    "abstain_reason": runtime.data.abstain_reason,
                    "abstain_followup": runtime.data.abstain_followup,
                    "followup_questions": runtime.data.followup_questions,
                    "abstain_min_citations": int(settings.RAG_ABSTAIN_MIN_CITATIONS or 0),
                    "abstain_min_top_relevance_score": float(settings.RAG_ABSTAIN_MIN_TOP_RELEVANCE_SCORE or 0.0),
                    "visible_evidence_only_enabled": bool(runtime.data.strict_visible),
                    "visible_evidence_only_requested": bool(runtime.data.visible_evidence_only),
                    "evidence_span_strict_enabled": bool(runtime.data.evidence_span_strict_enabled),
                    "evidence_span_missing_citations": int(runtime.data.evidence_span_missing_citations or 0),
                    "top_relevance_score": round(float(runtime.data.top_rel or 0.0), 3),
                    "answer_chars": runtime.data.answer_chars,
                    "answer_tokens": runtime.data.answer_tokens,
                    "structured_parse_ok": bool(runtime.data.structured_parse_meta.get("ok")),
                    "structured_parse_method": runtime.data.structured_parse_meta.get("method"),
                    "structured_parse_error": runtime.data.structured_parse_meta.get("error"),
                    "structured_type": type(runtime.data.structured_data).__name__
                    if runtime.data.structured_data is not None
                    else None,
                    "structured_preset": runtime.data.structured_preset,
                },
                "structured": bool(runtime.data.structured_data),
                "structured_data": runtime.data.structured_data,
            },
        }
        yield runtime.data.done_payload

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
        # Best-effort: sampled online evaluation (async, PII-minimal outputs).
        try:
            from app.services.online_eval_service import maybe_enqueue_online_eval

            maybe_enqueue_online_eval(
                tenant_id=runtime.data.tenant_id,
                dataset_id=runtime.data.dataset_id,
                request_id=str(runtime.data.request_id),
                answer=str(runtime.data.full_response or ""),
                contexts=[str(getattr(d, "page_content", "") or "") for d in (runtime.data.docs or [])],
                retrieval_mode=str(runtime.data.mode_used or "") or None,
                citations_count=int(len(runtime.data.citations or [])),
            )
        except Exception as exc:
            runtime.module.logger.debug(runtime.module._RAG_ENGINE_FALLBACK_LOG_MESSAGE, exc)
        runtime.finished = True
        return


async def recall_kg_context(runtime: StandardStreamState) -> None:
    # Step 2: Additional KG event recall (optional).
    runtime.data.kg_context = ""
    if (
        (not runtime.data.strict_visible)
        and settings.KG_ENABLED
        and settings.KG_CHAT_ENABLED
        and runtime.data.tenant_id
        and runtime.data.document_ids
    ):
        try:
            runtime.data.kg_result = runtime.data.kg_result_cached or await runtime.module.kg_search(
                query=runtime.data.question,
                tenant_id=runtime.data.tenant_id,
                document_ids=runtime.data.document_ids,
            )
            runtime.data.events = (runtime.data.kg_result or {}).get("events") or []
            if runtime.data.events:
                runtime.data.parts = []
                for runtime.data.idx, runtime.data.ev in enumerate(runtime.data.events[:5], 1):
                    runtime.data.title = (runtime.data.ev.get("title") or "").strip()
                    runtime.data.summary = (runtime.data.ev.get("summary") or "").strip()
                    if len(runtime.data.summary) > 600:
                        runtime.data.summary = runtime.data.summary[:600] + "..."
                    runtime.data.parts.append(
                        f"[Event {runtime.data.idx}] {runtime.data.title}\n{runtime.data.summary}"
                    )
                runtime.data.kg_context = "\n\n".join(runtime.data.parts)
                runtime.data.max_kg_tokens = max(0, int(getattr(settings, "RAG_CONTEXT_MAX_KG_TOKENS", 0) or 0))
                if runtime.data.max_kg_tokens:
                    runtime.data.kg_context = runtime.module.truncate(
                        runtime.data.kg_context,
                        runtime.data.max_kg_tokens,
                    )
                elif (
                    settings.RAG_CONTEXT_MAX_KG_CHARS > 0
                    and len(runtime.data.kg_context) > settings.RAG_CONTEXT_MAX_KG_CHARS
                ):
                    runtime.data.kg_context = runtime.data.kg_context[: settings.RAG_CONTEXT_MAX_KG_CHARS] + "..."
        except Exception:
            runtime.data.kg_context = ""

    # Step 3: Build context (document chunks + optional KG events).
    runtime.data.chunk_context = ""


def _context_page_info(metadata: dict[str, Any]) -> str | None:
    try:
        page = int(metadata.get("page")) if metadata.get("page") is not None else None
        if page and page > 0:
            return f"Page {page}"
    except Exception:
        return None
    return None


def _context_role_info(metadata: dict[str, Any]) -> str | None:
    retrieval_role = metadata.get("retrieval_role")
    if retrieval_role == "neighbor":
        return "neighbor"
    return str(retrieval_role) if retrieval_role else None


def _context_content(runtime: StandardStreamState, raw_content: str) -> str:
    content = raw_content
    evidence_on = bool(settings.RAG_CONTEXT_EVIDENCE_ENABLED)
    if evidence_on:
        try:
            content = runtime.module.extract_evidence_text(
                raw_content,
                runtime.data.query_for_retrieval,
                max_chars=(runtime.data.max_per_chunk_chars if not runtime.data.max_per_chunk_tokens else 0),
                max_sentences=settings.RAG_CONTEXT_EVIDENCE_MAX_SENTENCES_PER_CHUNK,
                min_sentence_chars=settings.RAG_CONTEXT_EVIDENCE_MIN_SENTENCE_CHARS,
            )
        except Exception:
            content = raw_content
            evidence_on = False
    if not evidence_on and runtime.data.max_per_chunk_tokens:
        return runtime.module.truncate(content, runtime.data.max_per_chunk_tokens)
    if not evidence_on and runtime.data.max_per_chunk_chars and len(content) > runtime.data.max_per_chunk_chars:
        return content[: runtime.data.max_per_chunk_chars] + "..."
    return content


def _context_info_parts(metadata: dict[str, Any]) -> list[str]:
    parts = [str(metadata.get("source", "Unknown"))]
    page_info = _context_page_info(metadata)
    header = metadata.get("header_path") or metadata.get("header_context")
    role_info = _context_role_info(metadata)
    if page_info:
        parts.append(page_info)
    if header:
        parts.append(str(header))
    if role_info:
        parts.append(role_info)
    return parts


def _append_context_part(runtime: StandardStreamState, part: str) -> bool:
    if runtime.data.max_total_tokens:
        part_tokens = runtime.module.num_tokens_from_string(part)
        if runtime.data.context_parts and runtime.data.total_tokens + part_tokens > runtime.data.max_total_tokens:
            return True
        runtime.data.context_parts.append(part)
        runtime.data.total_tokens += part_tokens
        return False
    runtime.data.context_parts.append(part)
    if runtime.data.max_total_chars:
        runtime.data.total_chars += len(part)
        return runtime.data.total_chars >= runtime.data.max_total_chars
    return False


def _build_context_parts(runtime: StandardStreamState) -> None:
    for index, document in enumerate(runtime.data.context_docs, 1):
        metadata = document.metadata or {}
        content = _context_content(runtime, (document.page_content or "").strip())
        part = f"[Source {index}: {' | '.join(_context_info_parts(metadata))}]\n{content}"
        if _append_context_part(runtime, part):
            break


async def build_chunk_context(runtime: StandardStreamState) -> None:
    if not runtime.data.docs:
        return
    try:
        from app.rag.core.context_denoise import denoise_context_docs

        runtime.data.context_docs = denoise_context_docs(runtime.data.docs)
    except Exception:  # noqa: BLE001
        runtime.data.context_docs = runtime.data.docs
    runtime.data.max_per_chunk_chars = max(0, int(settings.RAG_CONTEXT_MAX_CHARS_PER_CHUNK or 0))
    runtime.data.max_total_chars = max(0, int(settings.RAG_CONTEXT_MAX_TOTAL_CHARS or 0))
    runtime.data.max_per_chunk_tokens = max(0, int(getattr(settings, "RAG_CONTEXT_MAX_TOKENS_PER_CHUNK", 0) or 0))
    runtime.data.max_total_tokens = max(0, int(getattr(settings, "RAG_CONTEXT_MAX_TOTAL_TOKENS", 0) or 0))
    runtime.data.total_chars = 0
    runtime.data.total_tokens = 0
    runtime.data.context_parts = []
    _build_context_parts(runtime)
    runtime.data.chunk_context = "\n\n".join(runtime.data.context_parts)


async def join_context_sections(runtime: StandardStreamState) -> None:

    runtime.data.context_sections = []
    if runtime.data.kg_context:
        runtime.data.context_sections.append(f"[KG Event Retrieval]\n{runtime.data.kg_context}")
    if runtime.data.chunk_context:
        runtime.data.context_sections.append(f"[Document Chunk Retrieval]\n{runtime.data.chunk_context}")
    runtime.data.context = (
        "\n\n".join(runtime.data.context_sections)
        if runtime.data.context_sections
        else "No relevant reference materials found."
    )

    # Optional trace payload for debugging/regression replay (guarded by ENABLE_METRICS_LOG).
    # Claim-check stats are attached after generation completes (so we only emit one trace item).
    runtime.data.retrieval_config_hash: str | None = None


def _post_rerank_pipeline_summary() -> list[dict[str, Any]]:
    summary = []
    try:
        raw_pipeline = str(getattr(settings, "EVIDENCE_POST_RERANK_PIPELINE", "") or "").strip()
        pipeline = json.loads(raw_pipeline) if raw_pipeline else []
        if not isinstance(pipeline, list):
            return summary
        for stage in pipeline:
            if not isinstance(stage, dict):
                continue
            provider = str(stage.get("provider") or "").strip().lower()
            if not provider:
                continue
            try:
                top_n = int(stage.get("top_n")) if stage.get("top_n") is not None else 0
            except Exception:
                top_n = 0
            summary.append({"provider": provider, "top_n": max(0, top_n) or None})
            if len(summary) >= 4:
                break
    except Exception:
        return []
    return summary


def _rag_config_template_fingerprint(raw_template: Any) -> dict[str, Any] | None:
    if not isinstance(raw_template, dict) or not raw_template:
        return None
    fingerprint = {}
    template_key = str(raw_template.get("template_key") or "").strip()
    if template_key:
        fingerprint["template_key"] = template_key
    try:
        version = int(raw_template.get("version") or 0)
    except Exception:
        version = 0
    if version > 0:
        fingerprint["version"] = version
    experiment = str(raw_template.get("ab_experiment_key") or "").strip()
    if experiment:
        fingerprint["ab_experiment_key"] = experiment
    variant = str(raw_template.get("ab_variant") or "").strip()
    if variant:
        fingerprint["ab_variant"] = variant
    patch_hash = str(raw_template.get("patch_hash") or "").strip()
    if patch_hash:
        fingerprint["patch_hash"] = patch_hash
    return fingerprint or None


async def build_retrieval_config_trace(runtime: StandardStreamState) -> None:
    try:
        from app.rag.core.retrieval_config_fingerprint import build_retrieval_config_fingerprint

        runtime.data.pipe_summary = _post_rerank_pipeline_summary()
        runtime.data.rag_cfg_tpl_fp = _rag_config_template_fingerprint(runtime.data.rag_config_template)

        runtime.data.fp = build_retrieval_config_fingerprint(
            config={
                "requested_retrieval_mode": str(runtime.data.mode_req or ""),
                "retrieval_mode": str(runtime.data.mode_used or ""),
                "retrieval_mode_auto_routed": bool(runtime.data.mode_auto),
                "retrieval_profile": runtime.data.profile_norm or None,
                "rag_config_template": runtime.data.rag_cfg_tpl_fp,
                "top_k": int(runtime.data.top_k) if runtime.data.top_k is not None else None,
                "score_threshold": float(runtime.data.score_threshold_used or 0.0),
                "alpha": float(runtime.data.alpha_val or 0.0),
                "fusion_strategy": str(runtime.data.fusion_strategy or "").strip().lower()
                or settings.RETRIEVAL_FUSION_STRATEGY,
                "fusion_budgets": runtime.data.fusion_budgets,
                "fusion_min_scores": runtime.data.fusion_min_scores,
                "fusion_weights": runtime.data.fusion_weights,
                "enable_weight_rerank": bool(runtime.data.weight_rerank),
                "vector_weight": float(runtime.data.vec_w or 0.0),
                "keyword_weight": float(runtime.data.kw_w or 0.0),
                "mmr_lambda": float(runtime.data.mmr_lambda_val or 0.0),
                "enable_reranker": bool(runtime.data.rerank_on),
                "reranker_provider": str(runtime.data.rerank_provider or ""),
                "reranker_tier": runtime.module.describe_reranker_provider(
                    str(runtime.data.rerank_provider or ""),
                    provider_name=str(getattr(settings, "COLBERT_RERANK_PROVIDER", "deterministic") or "deterministic"),
                ).get("tier"),
                "reranker_top_n": int(runtime.data.rerank_top_n),
                "visible_evidence_only": bool(runtime.data.visible_evidence_only),
                "retrieval_contract_mode": runtime.data.retrieval_contract_mode_effective or None,
                "must_recall_requested": bool(runtime.data.must_recall),
                "must_recall_expected_source_keys": list(runtime.data.must_recall_expected_source_keys or []),
                "must_recall_required_anchor_fields": list(runtime.data.must_recall_required_anchor_fields or []),
                "vector_backend": str(getattr(settings, "VECTOR_BACKEND", "") or ""),
                "bm25_enabled": bool(getattr(settings, "BM25_INDEX_ENABLED", False)),
                "lexical_enabled": bool(getattr(settings, "LEXICAL_DB_TRGM_ENABLED", False)),
                "sparse_enabled": bool(getattr(settings, "SPARSE_RETRIEVAL_ENABLED", False)),
                "sparse_provider": str(getattr(settings, "SPARSE_RETRIEVAL_PROVIDER", "") or ""),
                "sparse_index_persist_enabled": bool(
                    getattr(settings, "SPARSE_RETRIEVAL_INDEX_PERSIST_ENABLED", False)
                ),
                "colbert_enabled": bool(getattr(settings, "COLBERT_RETRIEVAL_ENABLED", False)),
                "colbert_provider": str(getattr(settings, "COLBERT_RETRIEVAL_PROVIDER", "") or ""),
                "colbert_index_persist_enabled": bool(
                    getattr(settings, "COLBERT_RETRIEVAL_INDEX_PERSIST_ENABLED", False)
                ),
                "colbert_max_docs": int(getattr(settings, "COLBERT_RETRIEVAL_MAX_DOCS", 0) or 0),
                "parent_child_auto_merge_enabled": bool(
                    getattr(settings, "RAG_PARENT_CHILD_AUTO_MERGE_ENABLED", False)
                ),
                "parent_child_auto_merge_mode": str(getattr(settings, "RAG_PARENT_CHILD_AUTO_MERGE_MODE", "") or ""),
                "kg_query_expansion_enabled": bool(runtime.data.kg_query_expansion_enabled),
                "kg_chunk_injection_enabled": bool(runtime.data.kg_chunk_injection_enabled),
                "kg_chunk_injection_max_chunks": int(runtime.data.kg_chunk_injection_max_chunks_i or 0),
                "kg_chunk_boost_enabled": bool(runtime.data.kg_chunk_boost_meta.get("enabled")),
                "kg_chunk_boost_weight": runtime.data.kg_chunk_boost_meta.get("weight"),
                "kg_chunk_boost_max_promoted": runtime.data.kg_chunk_boost_meta.get("max_promoted"),
                "kg_chunk_boost_promoted": int(runtime.data.kg_chunk_boost_meta.get("promoted", 0) or 0),
                "kg_chunk_boost_top_changed": bool(runtime.data.kg_chunk_boost_meta.get("top_changed")),
                "evidence_post_rerank_enabled": bool(getattr(settings, "EVIDENCE_POST_RERANK_ENABLED", False)),
                "evidence_post_rerank_provider": str(getattr(settings, "EVIDENCE_POST_RERANK_PROVIDER", "") or ""),
                "evidence_post_rerank_top_n": int(getattr(settings, "EVIDENCE_POST_RERANK_TOP_N", 0) or 0),
                "evidence_post_rerank_pipeline_enabled": bool(
                    getattr(settings, "EVIDENCE_POST_RERANK_PIPELINE_ENABLED", False)
                ),
                "evidence_post_rerank_pipeline": runtime.data.pipe_summary,
                "multi_query": {
                    "enabled": bool(runtime.data.mq_enabled),
                    "count": int(runtime.data.mq_n or 0),
                    "temperature": float(runtime.data.mq_temp or 0.0),
                    "max_chars": int(runtime.data.mq_max_chars or 0),
                    "diversify": {
                        "enabled": bool(runtime.data.mq_diversify_enabled),
                        "budget": int(runtime.data.mq_diversify_budget or 0)
                        if runtime.data.mq_diversify_enabled
                        else 0,
                    },
                },
                "step_back": {
                    "enabled": bool(runtime.data.step_back_enabled),
                    "temperature": float(runtime.data.step_back_temp or 0.0),
                    "max_chars": int(runtime.data.step_back_max_chars or 0),
                    "output_max_chars": int(runtime.data.step_back_output_max or 0),
                },
                "query_rewrite": {
                    "enabled": bool(runtime.data.rewrite_enabled),
                    "strategy_id": runtime.data.rewrite_strategy_id if runtime.data.rewrite_enabled else None,
                    "strategy_hash": runtime.data.rewrite_strategy_hash if runtime.data.rewrite_enabled else None,
                    "temperature": runtime.data.rewrite_temperature if runtime.data.rewrite_enabled else None,
                    "max_chars": int(runtime.data.rewrite_max_chars or 0) if runtime.data.rewrite_enabled else None,
                },
            }
        )
        runtime.data.retrieval_config_hash = str(runtime.data.fp.get("hash") or "").strip() or None
    except Exception:
        runtime.data.retrieval_config_hash = None


async def build_rag_trace_payload(runtime: StandardStreamState) -> None:

    runtime.data.rag_trace_payload: dict[str, Any] = {
        "event": "rag_trace",
        "conversation_id": str(runtime.data.conversation_id) if runtime.data.conversation_id else None,
        "tenant_id": str(runtime.data.tenant_id) if runtime.data.tenant_id else None,
        "request_id": runtime.data.request_id,
        "question": runtime.data.question,
        "query_for_retrieval": runtime.data.query_for_retrieval,
        "history_chars": len(runtime.data.history_text or ""),
        "history_tokens": runtime.module.num_tokens_from_string(runtime.data.history_text or ""),
        "context_chars": len(runtime.data.context or ""),
        "context_tokens": runtime.module.num_tokens_from_string(runtime.data.context or ""),
        **runtime.module.compute_context_cliff_metrics(
            context_tokens=runtime.module.num_tokens_from_string(runtime.data.context or ""),
            threshold_tokens=int(getattr(settings, "RAG_CONTEXT_CLIFF_THRESHOLD_TOKENS", 2500) or 2500),
        ),
        "citations_count": len(runtime.data.citations),
        "context_evidence": {
            "enabled": bool(settings.RAG_CONTEXT_EVIDENCE_ENABLED),
            "max_sentences_per_chunk": int(settings.RAG_CONTEXT_EVIDENCE_MAX_SENTENCES_PER_CHUNK or 0),
            "min_sentence_chars": int(settings.RAG_CONTEXT_EVIDENCE_MIN_SENTENCE_CHARS or 0),
        },
        "query_expansion": {
            "alias_enabled": bool(runtime.data.alias_enabled),
            "alias_used": bool(runtime.data.alias_used),
            "alias_count": len(runtime.data.alias_queries),
            "alias_elapsed_sec": round(runtime.data.alias_elapsed, 3),
            "alias_meta": runtime.data.alias_meta,
            "dict_enabled": bool(runtime.data.dict_meta.get("enabled")),
            "dict_used": bool(runtime.data.dict_used),
            "dict_count": len(runtime.data.dict_expansions),
            "dict_elapsed_sec": round(runtime.data.dict_elapsed, 3),
            "dict_meta": runtime.data.dict_meta,
            "multi_query_enabled": bool(runtime.data.mq_enabled),
            "multi_query_used": bool(runtime.data.multi_query_used),
            "multi_query_count": len(runtime.data.multi_queries),
            "multi_query_count_requested": int(runtime.data.mq_n or 0),
            "multi_query_elapsed_sec": round(runtime.data.multi_query_elapsed, 3),
            "multi_query_model_used": runtime.data.multi_query_model_used,
            "multi_query_temperature": float(runtime.data.mq_temp or 0.0),
            "multi_query_max_chars": int(runtime.data.mq_max_chars or 0),
            "multi_query_parse_ok": bool(runtime.data.multi_query_parse_meta.get("ok")),
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
            "decompose_parse_error": runtime.data.decompose_parse_meta.get("error"),
        },
        "retrieval": {
            "mode": runtime.data.mode_used,
            "requested_mode": runtime.data.mode_req,
            "auto_routed": bool(runtime.data.mode_auto),
            "profile": runtime.data.profile_norm or None,
            "profile_requested": (
                str(runtime.data.profile_req).strip().lower() if runtime.data.profile_req is not None else None
            ),
            "contract_mode": runtime.data.retrieval_contract_mode_effective or None,
            "contract_policy": dict(runtime.data.retrieval_contract_policy or {}),
            "intent_router": runtime.data.intent_router_meta,
            "industry_rules": dict(runtime.data.industry_rules_meta),
            "retrieval_config_hash": runtime.data.retrieval_config_hash,
            "recall_bucket": runtime.data.recall_bucket,
            "top_k": int(runtime.data.top_k) if runtime.data.top_k is not None else None,
            "elapsed_sec": round(runtime.data.retrieval_elapsed, 3),
            "alpha": runtime.data.alpha_val,
            "enable_weight_rerank": runtime.data.weight_rerank,
            "vector_weight": runtime.data.vec_w,
            "keyword_weight": runtime.data.kw_w,
            "mmr_lambda": runtime.data.mmr_lambda_val,
            "enable_reranker": runtime.data.rerank_on,
            "reranker_provider": runtime.data.rerank_provider,
            "reranker_top_n": runtime.data.rerank_top_n,
            "enable_hierarchy_recall": bool(runtime.data.enable_hierarchy_recall),
            "hierarchy_family_collapse": bool(runtime.data.hierarchy_family_collapse),
            "hierarchy_family_aggregation": (
                str(runtime.data.hierarchy_family_aggregation).strip().lower()
                if runtime.data.hierarchy_family_aggregation is not None
                else None
            ),
            "hierarchy_tree_dedup": (
                bool(runtime.data.hierarchy_tree_dedup) if runtime.data.hierarchy_tree_dedup is not None else None
            ),
            "hierarchy_parent_depth": (
                int(runtime.data.hierarchy_parent_depth) if runtime.data.hierarchy_parent_depth is not None else None
            ),
            "hierarchy_sibling_window": (
                int(runtime.data.hierarchy_sibling_window)
                if runtime.data.hierarchy_sibling_window is not None
                else None
            ),
            "hierarchy_overfetch_factor": int(runtime.data.hierarchy_overfetch_factor or 1),
            "query_parallelism": runtime.data.retrieval_parallelism,
            "query_count": len(runtime.data.retrieval_plan),
            "per_query": runtime.data.retrieval_per_query[:8],
            "errors": runtime.data.retrieval_errors[:5],
        },
        "kg": {
            "chunk_injection_enabled": bool(runtime.data.kg_chunk_injection_enabled),
            "chunk_injection_max_chunks": int(runtime.data.kg_chunk_injection_max_chunks_i or 0),
            "chunks_injected": int(runtime.data.kg_chunks_injected or 0),
            "chunk_boost": dict(runtime.data.kg_chunk_boost_meta)
            if isinstance(runtime.data.kg_chunk_boost_meta, dict)
            else None,
            "used_cached_result": bool(runtime.data.kg_result_cached),
        },
        "multimodal": {
            "modality": str(runtime.data.multimodal_modality or "text"),
            "reasons": list(runtime.data.multimodal_reasons or []),
            "image": dict(runtime.data.image_meta) if isinstance(runtime.data.image_meta, dict) else None,
            "vision_reader": dict(runtime.data.vision_reader_meta)
            if isinstance(runtime.data.vision_reader_meta, dict)
            else None,
            "vision_generation": (
                dict(runtime.data.vision_generation_meta)
                if isinstance(runtime.data.vision_generation_meta, dict)
                else None
            ),
        },
        "tag": runtime.data.tag_meta,
        "citations": runtime.data.citations[: min(len(runtime.data.citations), int(runtime.data.top_k or 5))],
        "rag_config_template": runtime.data.rag_config_template
        if isinstance(runtime.data.rag_config_template, dict)
        else None,
        "prompt": {
            "prompt_template_id": str(runtime.data.selected_prompt_template_id)
            if runtime.data.selected_prompt_template_id
            else None,
            "prompt_template_key": runtime.data.selected_prompt_template_key,
            "prompt_ab_experiment_key": runtime.data.selected_prompt_ab_experiment_key,
            "prompt_ab_variant": runtime.data.selected_prompt_ab_variant,
        },
        "route": {
            "model_route": runtime.data.model_route,
            "model_used": getattr(runtime.data.llm, "model_name", None) or getattr(runtime.data.llm, "model", None),
            "reason": runtime.data.routing_reason,
            "structured_temperature": runtime.data.request_llm_meta.get("structured_temperature"),
            "structured_temperature_override_applied": bool(
                runtime.data.request_llm_meta.get("structured_temperature_override_applied")
            ),
        },
    }


EVIDENCE_OPERATIONS = (
    StreamOperation(apply_temporal_rerank, streams=False),
    StreamOperation(apply_rail_and_build_citations, streams=True),
    StreamOperation(evaluate_abstention, streams=True),
    StreamOperation(stream_corrective_retrieval, streams=True),
    StreamOperation(emit_abstention_result, streams=True),
    StreamOperation(recall_kg_context, streams=False),
    StreamOperation(build_chunk_context, streams=False),
    StreamOperation(join_context_sections, streams=False),
    StreamOperation(build_retrieval_config_trace, streams=False),
    StreamOperation(build_rag_trace_payload, streams=False),
)

__all__ = ["EVIDENCE_OPERATIONS"]
