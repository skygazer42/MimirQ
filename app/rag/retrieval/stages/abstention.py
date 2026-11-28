"""Apply abstention policies and enqueue eligible hard cases."""

import json
import time
from typing import Any

from app.infrastructure.config import settings
from app.infrastructure.env import parse_csv
from app.infrastructure.hashing import stable_hash
from app.rag.llm.response_parsing import build_retrieval_abstain_followup as build_abstain_followup
from app.rag.policy.out_of_scope_retrieval import (
    run_default_out_of_scope_live_guard,
)
from app.rag.policy.out_of_scope_verifier import maybe_apply_out_of_scope_live_guard
from app.rag.retrieval.evidence.validity import NO_CURRENT_EVIDENCE, requests_current_evidence
from app.rag.retrieval.stages.state import RetrievalRuntimeState
from app.services.evaluation.hardcase_discovery import (
    build_parse_risk_hardcase_candidate,
    evaluate_parse_risk_auto_enqueue_policy,
)
from app.types.document_metadata import metadata_text


def _top_relevance_score(citations: list[dict[str, Any]]) -> float:
    if not citations:
        return 0.0
    try:
        return max(
            float(
                (
                    citation.get("relevance_score")
                    if citation.get("relevance_score") is not None
                    else citation.get("retrieval_score")
                )
                or 0.0
            )
            for citation in citations
        )
    except (TypeError, ValueError):
        return 0.0


def _apply_abstain_thresholds(ctx: RetrievalRuntimeState) -> None:
    if not ctx.citations and requests_current_evidence(ctx.question):
        ctx.abstain_enabled = True
        ctx.abstain_triggered = True
        ctx.abstain_reason = NO_CURRENT_EVIDENCE
        return
    if ctx.abstain_enabled:
        min_citations = max(0, int(settings.RAG_ABSTAIN_MIN_CITATIONS))
        min_top_rel = float(settings.RAG_ABSTAIN_MIN_TOP_RELEVANCE_SCORE)
        if min_citations > 0 and len(ctx.citations) < min_citations:
            ctx.abstain_triggered = True
            ctx.abstain_reason = "citations_lt_min"
        elif min_top_rel > 0 and ctx.top_rel < min_top_rel:
            ctx.abstain_triggered = True
            ctx.abstain_reason = "top_relevance_lt_min"
    if ctx.parse_quality_gate_blocked:
        ctx.abstain_enabled = True
        if not ctx.abstain_triggered:
            ctx.abstain_triggered = True
            ctx.abstain_reason = "parse_quality_gate_strict"
    if ctx.must_recall_enabled and not ctx.must_recall_passed:
        ctx.abstain_enabled = True
        if not ctx.abstain_triggered:
            ctx.abstain_triggered = True
            ctx.abstain_reason = "must_recall_failed"


def _apply_out_of_scope_guard(ctx: RetrievalRuntimeState) -> dict[str, Any]:
    tenant_id = metadata_text(ctx.state, "tenant_id")
    dataset_id = metadata_text(ctx.state, "dataset_id")
    ruleset_name = settings.RAG_OUT_OF_SCOPE_RULESET.strip()
    result = maybe_apply_out_of_scope_live_guard(
        query=ctx.query_for_retrieval,
        enabled=bool(settings.RAG_OUT_OF_SCOPE_LIVE_GUARD_ENABLED),
        candidate=bool(ctx.abstain_triggered or not ctx.citations),
        current_triggered=bool(ctx.abstain_triggered),
        current_reason=ctx.abstain_reason,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        verifier=lambda: run_default_out_of_scope_live_guard(
            query=ctx.query_for_retrieval,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            ruleset_name=ruleset_name,
            hyde_query=ctx.hyde_text if bool(ctx.hyde_used and ctx.hyde_text) else None,
            vector_similarity_threshold=float(settings.RAG_OUT_OF_SCOPE_VECTOR_THRESHOLD),
            hyde_similarity_threshold=float(settings.RAG_OUT_OF_SCOPE_HYDE_THRESHOLD),
        ),
    )
    ctx.abstain_triggered = bool(result.get("abstain_triggered"))
    ctx.abstain_reason = result.get("abstain_reason")
    return result


def _record_abstain_metrics(ctx: RetrievalRuntimeState, out_of_scope_guard: dict[str, Any]) -> None:
    ctx.metrics["abstain_enabled"] = bool(ctx.abstain_enabled)
    ctx.metrics["abstain_triggered"] = bool(ctx.abstain_triggered)
    ctx.metrics["abstain_reason"] = ctx.abstain_reason
    ctx.metrics["out_of_scope_guard_enabled"] = bool(settings.RAG_OUT_OF_SCOPE_LIVE_GUARD_ENABLED)
    if isinstance(out_of_scope_guard.get("verdict"), dict):
        ctx.metrics["out_of_scope_guard"] = dict(out_of_scope_guard.get("verdict") or {})
    ctx.metrics["abstain_min_citations"] = int(settings.RAG_ABSTAIN_MIN_CITATIONS)
    ctx.metrics["abstain_min_top_relevance_score"] = float(settings.RAG_ABSTAIN_MIN_TOP_RELEVANCE_SCORE)
    ctx.metrics["visible_evidence_only_enabled"] = bool(ctx.strict_visible)
    ctx.metrics["visible_evidence_only_requested"] = bool(ctx.state.get("visible_evidence_only"))
    ctx.metrics["top_relevance_score"] = round(float(ctx.top_rel or 0.0), 3)
    if ctx.abstain_triggered:
        ctx.metrics["abstain_followup"] = build_abstain_followup(
            reason=ctx.abstain_reason,
            citations=ctx.citations,
        )


def _emit_retrieval_hardcase(ctx: RetrievalRuntimeState) -> None:
    enabled = bool(settings.RETRIEVAL_HARDCASE_EMIT_ENABLED)
    if not enabled or (not ctx.abstain_triggered and ctx.citations):
        return
    reason = "abstain" if ctx.abstain_triggered else "no_citations"
    dedupe_payload = {
        "reason": reason,
        "query_hash": stable_hash(ctx.query_for_retrieval),
        "mode": ctx.request_retrieval_mode,
        "profile": ctx.profile_norm,
        "cfg_hash": ctx.metrics.get("retrieval_config_hash"),
    }
    ctx.metrics["hardcase_candidate"] = {
        "schema": "mimirq.hardcase_candidate.v1",
        "reason": reason,
        "query_hash": stable_hash(ctx.query_for_retrieval),
        "retrieval_mode": ctx.request_retrieval_mode,
        "retrieval_profile": ctx.profile_norm,
        "dedupe_key": stable_hash(
            json.dumps(dedupe_payload, ensure_ascii=False, sort_keys=True),
            length=32,
        ),
        "ts_ms": int(time.time() * 1000),
    }


def _parse_risk_enqueue_policy(ctx: RetrievalRuntimeState) -> dict[str, Any]:
    levels = {
        str(value).strip().lower()
        for value in parse_csv(str(settings.RETRIEVAL_PARSE_RISK_AUTO_ENQUEUE_LEVELS))
        if str(value).strip()
    }
    if not levels:
        levels = {"high", "medium"}
    min_score = settings.RETRIEVAL_PARSE_RISK_AUTO_ENQUEUE_MIN_SCORE
    return evaluate_parse_risk_auto_enqueue_policy(
        parse_risk=ctx.parse_risk,
        enabled=bool(settings.RETRIEVAL_PARSE_RISK_HARDCASE_EMIT_ENABLED),
        allowed_levels=levels,
        min_score=min(1.0, max(0.0, min_score)),
    )


def _emit_parse_risk_hardcase(ctx: RetrievalRuntimeState, policy: dict[str, Any]) -> None:
    if isinstance(ctx.metrics.get("hardcase_candidate"), dict) or not bool(policy.get("enqueue")):
        return
    candidate = build_parse_risk_hardcase_candidate(
        query_hash=stable_hash(ctx.query_for_retrieval),
        retrieval_mode=ctx.request_retrieval_mode,
        retrieval_profile=ctx.profile_norm,
        retrieval_config_hash=ctx.metrics.get("retrieval_config_hash"),
        parse_risk=ctx.parse_risk,
        ts_ms=int(time.time() * 1000),
    )
    if isinstance(candidate, dict):
        ctx.metrics["hardcase_candidate"] = candidate


def _run_retrieval_abstain_hardcase_phase(ctx: RetrievalRuntimeState) -> dict[str, Any] | None:
    ctx.strict_visible = bool(
        bool(ctx.state.get("visible_evidence_only"))
        or bool(ctx.retrieval_contract_policy["force_visible_evidence_only"])
    )
    ctx.abstain_enabled = (
        bool(settings.RAG_ABSTAIN_ENABLED) or ctx.strict_visible or bool(ctx.evidence_span_strict_enabled)
    )
    ctx.abstain_triggered = False
    ctx.abstain_reason: str | None = None
    ctx.top_rel = _top_relevance_score(ctx.citations)
    _apply_abstain_thresholds(ctx)
    out_of_scope_guard = _apply_out_of_scope_guard(ctx)
    _record_abstain_metrics(ctx, out_of_scope_guard)
    _emit_retrieval_hardcase(ctx)
    parse_risk_auto_enqueue_policy = _parse_risk_enqueue_policy(ctx)
    ctx.metrics["parse_risk_auto_enqueue_policy"] = dict(parse_risk_auto_enqueue_policy)
    _emit_parse_risk_hardcase(ctx, parse_risk_auto_enqueue_policy)
    return None
