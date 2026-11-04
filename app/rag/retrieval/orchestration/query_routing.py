"""Owned query contract, routing and policy decisions without retriever/context dependencies."""

import json
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.rag.core.evidence_expectations import DEFAULT_EVIDENCE_ANCHOR_FIELDS, normalize_anchor_fields
from app.rag.core.retrieval_profiles import is_recall_first_profile
from app.rag.core.text import guess_recall_bucket
from app.rag.policy.intent_router import route_adaptive_retrieval_overrides, route_retrieval_preset
from app.rag.policy.must_recall import normalize_source_keys
from app.rag.policy.must_recall_auto import infer_expected_source_keys, infer_required_anchor_fields
from app.rag.retrieval.contract import resolve_retrieval_contract_policy
from app.rag.retrieval.orchestration.channel_budget import resolve_channel_budget_policy_overrides
from app.rag.retrieval.orchestration.common import _log_orchestrator_fallback
from app.rag.retrieval.orchestration.query_contract import (
    HierarchyContractSettings,
    QueryContractNormalizationInput,
    QueryContractNormalizationOutput,
    normalize_query_contract,
)
from app.rag.retrieval.orchestration.query_contracts import (
    QueryRoutingDecision,
    SparseQuerySettings,
    StreamQueryRoutingDecision,
)
from app.rag.retrieval.orchestration.query_options import query_contract_defaults
from app.rag.retrieval.orchestration.text_helpers import normalize_retrieval_mode


def _resolve_must_recall_enabled(
    *, state: dict[str, Any], retrieval_contract_policy: dict[str, Any]
) -> tuple[Any, bool]:
    must_recall_requested = state.get("must_recall")
    if must_recall_requested is None:
        must_recall_enabled = settings.RETRIEVAL_MUST_RECALL_DEFAULT_ENABLED
    else:
        must_recall_enabled = bool(must_recall_requested)
    if bool(retrieval_contract_policy.get("must_recall_strict")):
        must_recall_enabled = True
    return (must_recall_requested, must_recall_enabled)


def _resolve_expected_source_keys(
    *, state: dict[str, Any], query_for_retrieval: str, must_recall_enabled: bool
) -> dict[str, Any]:
    explicit_expected_source_keys = state.get("must_recall_expected_source_keys") is not None
    raw_expected_source_keys = (
        state.get("must_recall_expected_source_keys")
        if explicit_expected_source_keys
        else settings.RETRIEVAL_MUST_RECALL_REQUIRED_SOURCE_KEYS
    )
    expected_source_keys = normalize_source_keys(raw_expected_source_keys)
    auto_enabled = bool(
        state.get("must_recall_auto_expected_source_keys_enabled")
        if state.get("must_recall_auto_expected_source_keys_enabled") is not None
        else settings.RETRIEVAL_MUST_RECALL_AUTO_EXPECTED_SOURCE_KEYS_ENABLED
    )
    auto_source_keys: list[str] = []
    auto_reason_codes: list[str] = []
    auto_confidence = "none"
    auto_applied = False
    if (
        bool(must_recall_enabled)
        and bool(auto_enabled)
        and (not expected_source_keys)
        and (not explicit_expected_source_keys)
    ):
        auto_max_keys = max(1, settings.RETRIEVAL_MUST_RECALL_AUTO_EXPECTED_SOURCE_KEYS_MAX or 12)
        allow_filter = settings.RETRIEVAL_MUST_RECALL_AUTO_INFER_FROM_METADATA_FILTER
        meta_filter = state.get("metadata_filter") if allow_filter else None
        scope_payload = _build_must_recall_scope_payload(state)
        inferred = infer_expected_source_keys(
            query=query_for_retrieval,
            metadata_filter=meta_filter if isinstance(meta_filter, dict) else None,
            scope=scope_payload if scope_payload else None,
            max_keys=auto_max_keys,
        )
        auto_source_keys = normalize_source_keys(list(inferred.get("expected_source_keys") or []))
        auto_reason_codes = [str(value) for value in inferred.get("reason_codes") or [] if str(value).strip()][:8]
        auto_confidence = str(inferred.get("confidence") or "none")
        if auto_source_keys:
            expected_source_keys = auto_source_keys
            auto_applied = True
    return {
        "explicit_expected_source_keys": explicit_expected_source_keys,
        "must_recall_expected_source_keys": expected_source_keys,
        "must_recall_auto_expected_source_keys_enabled": auto_enabled,
        "must_recall_auto_expected_source_keys": auto_source_keys,
        "must_recall_auto_expected_source_keys_reason_codes": auto_reason_codes,
        "must_recall_auto_expected_source_keys_confidence": auto_confidence,
        "must_recall_auto_expected_source_keys_applied": auto_applied,
    }


def _build_must_recall_scope_payload(state: dict[str, Any]) -> dict[str, Any]:
    scope_payload: dict[str, Any] = {}
    dataset_scope = str(state.get("dataset_id") or "").strip()
    if dataset_scope:
        scope_payload["dataset_id"] = dataset_scope
    raw_doc_scope = state.get("document_ids")
    if isinstance(raw_doc_scope, list):
        scope_payload["document_ids"] = [str(value) for value in raw_doc_scope if str(value or "").strip()][:200]
    raw_table_scope = state.get("table_ids")
    if isinstance(raw_table_scope, list):
        scope_payload["table_ids"] = [str(value) for value in raw_table_scope if str(value or "").strip()][:200]
    return scope_payload


def _resolve_required_anchor_fields(
    *, state: dict[str, Any], query_for_retrieval: str, must_recall_enabled: bool
) -> dict[str, Any]:
    explicit_required_anchor_fields = state.get("must_recall_required_anchor_fields") is not None
    raw_required_anchor_fields = (
        state.get("must_recall_required_anchor_fields")
        if explicit_required_anchor_fields
        else settings.RETRIEVAL_MUST_RECALL_REQUIRED_ANCHOR_FIELDS
    )
    required_anchor_fields = normalize_anchor_fields(raw_required_anchor_fields)
    auto_enabled = bool(
        state.get("must_recall_auto_required_anchor_fields_enabled")
        if state.get("must_recall_auto_required_anchor_fields_enabled") is not None
        else settings.RETRIEVAL_MUST_RECALL_AUTO_REQUIRED_ANCHOR_FIELDS_ENABLED
    )
    auto_fields: list[str] = []
    auto_reason_codes: list[str] = []
    auto_applied = False
    if bool(must_recall_enabled) and bool(auto_enabled):
        inferred_anchor = infer_required_anchor_fields(
            query=query_for_retrieval,
            default_fields=required_anchor_fields if required_anchor_fields else list(DEFAULT_EVIDENCE_ANCHOR_FIELDS),
        )
        auto_fields = normalize_anchor_fields(list(inferred_anchor.get("required_anchor_fields") or []))
        auto_reason_codes = [str(value) for value in inferred_anchor.get("reason_codes") or [] if str(value).strip()][
            :8
        ]
        if auto_fields and (
            bool(inferred_anchor.get("applied")) or not required_anchor_fields or (not explicit_required_anchor_fields)
        ):
            required_anchor_fields = auto_fields
            auto_applied = True
    if not required_anchor_fields and must_recall_enabled:
        required_anchor_fields = list(DEFAULT_EVIDENCE_ANCHOR_FIELDS)
    return {
        "must_recall_required_anchor_fields": required_anchor_fields,
        "must_recall_auto_required_anchor_fields_enabled": auto_enabled,
        "must_recall_auto_required_anchor_fields": auto_fields,
        "must_recall_auto_required_anchor_fields_reason_codes": auto_reason_codes,
        "must_recall_auto_required_anchor_fields_applied": auto_applied,
    }


def _resolve_contextual_followup_settings(state: dict[str, Any]) -> dict[str, Any]:
    valid_retrieval_modes = {"hybrid", "vector", "keyword", "mmr"}
    contextual_followup_req = state.get("contextual_followup_enabled")
    contextual_followup_enabled = (
        bool(contextual_followup_req)
        if contextual_followup_req is not None
        else settings.RETRIEVAL_CONTEXTUAL_FOLLOWUP_ENABLED
    )
    contextual_followup_mode = (
        str(
            state.get("contextual_followup_mode")
            if state.get("contextual_followup_mode") is not None
            else settings.RETRIEVAL_CONTEXTUAL_FOLLOWUP_MODE or "keyword"
        )
        .strip()
        .lower()
        or "keyword"
    )
    if contextual_followup_mode not in valid_retrieval_modes:
        contextual_followup_mode = "keyword"
    return {
        "contextual_followup_enabled": contextual_followup_enabled,
        "contextual_followup_mode": contextual_followup_mode,
        "contextual_followup_top_k": max(
            int(state.get("top_k", settings.RETRIEVAL_TOP_K) or settings.RETRIEVAL_TOP_K or 1),
            int(
                state.get("contextual_followup_top_k")
                if state.get("contextual_followup_top_k") is not None
                else settings.RETRIEVAL_CONTEXTUAL_FOLLOWUP_TOP_K or 40
            ),
        ),
        "contextual_followup_max_docs": max(
            1,
            int(
                state.get("contextual_followup_max_docs")
                if state.get("contextual_followup_max_docs") is not None
                else settings.RETRIEVAL_CONTEXTUAL_FOLLOWUP_MAX_DOCS or 4
            ),
        ),
        "contextual_followup_max_terms": max(
            0,
            int(
                state.get("contextual_followup_max_terms")
                if state.get("contextual_followup_max_terms") is not None
                else settings.RETRIEVAL_CONTEXTUAL_FOLLOWUP_MAX_TERMS or 4
            ),
        ),
        "contextual_followup_min_term_chars": max(
            2,
            int(
                state.get("contextual_followup_min_term_chars")
                if state.get("contextual_followup_min_term_chars") is not None
                else settings.RETRIEVAL_CONTEXTUAL_FOLLOWUP_MIN_TERM_CHARS or 4
            ),
        ),
        "contextual_followup_max_query_chars": max(
            32,
            int(
                state.get("contextual_followup_max_query_chars")
                if state.get("contextual_followup_max_query_chars") is not None
                else settings.RETRIEVAL_CONTEXTUAL_FOLLOWUP_MAX_QUERY_CHARS or 500
            ),
        ),
        "contextual_followup_max_hops": max(
            1,
            int(
                state.get("contextual_followup_max_hops")
                if state.get("contextual_followup_max_hops") is not None
                else settings.RETRIEVAL_CONTEXTUAL_FOLLOWUP_MAX_HOPS or 1
            ),
        ),
        "contextual_followup_latency_budget_ms": max(
            0.0,
            float(
                state.get("contextual_followup_latency_budget_ms")
                if state.get("contextual_followup_latency_budget_ms") is not None
                else settings.RETRIEVAL_CONTEXTUAL_FOLLOWUP_LATENCY_BUDGET_MS or 500.0
            ),
        ),
    }


def _resolve_hierarchy_settings(state: dict[str, Any]) -> dict[str, Any]:
    hierarchy_recall_req = state.get("enable_hierarchy_recall")
    hierarchy_recall_enabled = (
        bool(hierarchy_recall_req) if hierarchy_recall_req is not None else settings.HIERARCHY_RECALL_ENABLED
    )
    hierarchy_family_collapse_req = state.get("hierarchy_family_collapse")
    hierarchy_family_collapse = (
        bool(hierarchy_family_collapse_req)
        if hierarchy_family_collapse_req is not None
        else settings.HIERARCHY_RECALL_FAMILY_COLLAPSE
    )
    hierarchy_family_aggregation = (
        str(
            state.get("hierarchy_family_aggregation")
            if state.get("hierarchy_family_aggregation") is not None
            else settings.HIERARCHY_RECALL_FAMILY_AGGREGATION or "combined"
        )
        .strip()
        .lower()
        or "combined"
    )
    if hierarchy_family_aggregation not in {"frequency", "score", "combined"}:
        hierarchy_family_aggregation = "combined"
    hierarchy_tree_dedup_req = state.get("hierarchy_tree_dedup")
    hierarchy_tree_dedup = (
        bool(hierarchy_tree_dedup_req) if hierarchy_tree_dedup_req is not None else settings.HIERARCHY_RECALL_TREE_DEDUP
    )
    return {
        "hierarchy_recall_enabled": hierarchy_recall_enabled,
        "hierarchy_family_collapse": hierarchy_family_collapse,
        "hierarchy_family_aggregation": hierarchy_family_aggregation,
        "hierarchy_tree_dedup": hierarchy_tree_dedup,
        "hierarchy_parent_depth": max(
            0,
            int(
                state.get("hierarchy_parent_depth")
                if state.get("hierarchy_parent_depth") is not None
                else settings.HIERARCHY_RECALL_PARENT_DEPTH
            ),
        ),
        "hierarchy_sibling_window": max(
            0,
            int(
                state.get("hierarchy_sibling_window")
                if state.get("hierarchy_sibling_window") is not None
                else settings.HIERARCHY_RECALL_SIBLING_WINDOW
            ),
        ),
        "hierarchy_overfetch_factor": max(
            1,
            int(
                state.get("hierarchy_overfetch_factor")
                if state.get("hierarchy_overfetch_factor") is not None
                else settings.HIERARCHY_RECALL_OVERFETCH_FACTOR or 4
            ),
        ),
    }


def resolve_evidence_contract(options: dict[str, Any], *, query: str) -> dict[str, Any]:
    state = dict(options)
    requested_retrieval_mode = state.get("retrieval_mode", "hybrid") or "hybrid"
    requested_retrieval_profile = state.get("retrieval_profile")
    retrieval_contract_policy = resolve_retrieval_contract_policy(
        mode=state.get("retrieval_contract_mode")
        if state.get("retrieval_contract_mode") is not None
        else settings.RETRIEVAL_CONTRACT_MODE,
        requested_top_k=int(state.get("top_k", settings.RETRIEVAL_TOP_K) or settings.RETRIEVAL_TOP_K or 5),
        hard_fallback_enabled_setting=settings.RETRIEVAL_HARD_FALLBACK_ENABLED,
        hard_fallback_mode_setting=settings.RETRIEVAL_HARD_FALLBACK_MODE or "keyword",
        hard_fallback_top_k_setting=settings.RETRIEVAL_HARD_FALLBACK_TOP_K or 30,
        visible_evidence_only_setting=settings.RAG_VISIBLE_EVIDENCE_ONLY_ENABLED,
        evidence_span_strict_setting=settings.RAG_EVIDENCE_REQUIRE_SPANS_ENABLED,
    )
    retrieval_contract_mode = str(retrieval_contract_policy.get("mode") or "").strip().lower()
    contract_deterministic_recall = bool(retrieval_contract_policy.get("deterministic_recall"))
    contract_must_recall_strict = bool(retrieval_contract_policy.get("must_recall_strict"))
    must_recall_requested, must_recall_enabled = _resolve_must_recall_enabled(
        state=state, retrieval_contract_policy=retrieval_contract_policy
    )
    expected_source_keys = _resolve_expected_source_keys(
        state=state, query_for_retrieval=query, must_recall_enabled=must_recall_enabled
    )
    required_anchor_fields = _resolve_required_anchor_fields(
        state=state, query_for_retrieval=query, must_recall_enabled=must_recall_enabled
    )
    contextual_followup_settings = _resolve_contextual_followup_settings(state)
    hierarchy_settings = _resolve_hierarchy_settings(state)
    must_recall_second_pass_enabled = bool(
        bool(retrieval_contract_policy.get("enable_partial_miss_second_pass"))
        and settings.RETRIEVAL_MUST_RECALL_SECOND_PASS_ENABLED
    )
    must_recall_second_pass_mode = (
        settings.RETRIEVAL_MUST_RECALL_SECOND_PASS_MODE or "keyword"
    ).strip().lower() or "keyword"
    must_recall_second_pass_top_k = max(
        int(state.get("top_k", settings.RETRIEVAL_TOP_K) or settings.RETRIEVAL_TOP_K or 1),
        settings.RETRIEVAL_MUST_RECALL_SECOND_PASS_TOP_K or 80,
    )
    return {
        "requested_retrieval_mode": requested_retrieval_mode,
        "requested_retrieval_profile": requested_retrieval_profile,
        "retrieval_contract_policy": retrieval_contract_policy,
        "retrieval_contract_mode": retrieval_contract_mode,
        "contract_deterministic_recall": contract_deterministic_recall,
        "contract_must_recall_strict": contract_must_recall_strict,
        "must_recall_requested": must_recall_requested,
        "must_recall_enabled": must_recall_enabled,
        "must_recall_expected_source_keys": expected_source_keys["must_recall_expected_source_keys"],
        "must_recall_auto_expected_source_keys_enabled": expected_source_keys[
            "must_recall_auto_expected_source_keys_enabled"
        ],
        "must_recall_auto_expected_source_keys": expected_source_keys["must_recall_auto_expected_source_keys"],
        "must_recall_auto_expected_source_keys_reason_codes": expected_source_keys[
            "must_recall_auto_expected_source_keys_reason_codes"
        ],
        "must_recall_auto_expected_source_keys_confidence": expected_source_keys[
            "must_recall_auto_expected_source_keys_confidence"
        ],
        "must_recall_auto_expected_source_keys_applied": expected_source_keys[
            "must_recall_auto_expected_source_keys_applied"
        ],
        "must_recall_required_anchor_fields": required_anchor_fields["must_recall_required_anchor_fields"],
        "must_recall_auto_required_anchor_fields_enabled": required_anchor_fields[
            "must_recall_auto_required_anchor_fields_enabled"
        ],
        "must_recall_auto_required_anchor_fields": required_anchor_fields["must_recall_auto_required_anchor_fields"],
        "must_recall_auto_required_anchor_fields_reason_codes": required_anchor_fields[
            "must_recall_auto_required_anchor_fields_reason_codes"
        ],
        "must_recall_auto_required_anchor_fields_applied": required_anchor_fields[
            "must_recall_auto_required_anchor_fields_applied"
        ],
        "must_recall_second_pass_enabled": must_recall_second_pass_enabled,
        "must_recall_second_pass_mode": must_recall_second_pass_mode,
        "must_recall_second_pass_top_k": must_recall_second_pass_top_k,
        **contextual_followup_settings,
        **hierarchy_settings,
    }


def _apply_intent_router(
    *,
    state: dict[str, Any],
    query_for_retrieval: str,
    requested_retrieval_mode: Any,
    requested_retrieval_profile: Any,
    learned_router_enabled: bool = True,
) -> dict[str, Any]:
    intent_router_req = state.get("intent_router")
    intent_router_enabled = (
        bool(intent_router_req) if intent_router_req is not None else settings.RAG_INTENT_ROUTER_ENABLED
    )
    intent_router_meta: dict[str, Any] = {"enabled": bool(intent_router_enabled), "used": False}
    if not bool(intent_router_enabled):
        return intent_router_meta
    learned_options = {}
    if learned_router_enabled:
        learned_options = {
            "learned_router_model": state.get("intent_router_model")
            if isinstance(state.get("intent_router_model"), dict)
            else None,
            "learned_router_model_path": str(state.get("intent_router_model_path") or "").strip()
            if state.get("intent_router_model_path") is not None
            else settings.RAG_INTENT_ROUTER_MODEL_PATH.strip(),
            "learned_router_confidence_min": float(
                state.get("intent_router_model_confidence_min")
                if state.get("intent_router_model_confidence_min") is not None
                else settings.RAG_INTENT_ROUTER_MODEL_CONFIDENCE_MIN or 0.7
            ),
        }
    try:
        overrides, intent_router_meta = route_retrieval_preset(
            query=query_for_retrieval,
            retrieval_mode=str(requested_retrieval_mode or ""),
            retrieval_profile=str(requested_retrieval_profile).strip()
            if requested_retrieval_profile is not None
            else None,
            top_k=int(state.get("top_k", settings.RETRIEVAL_TOP_K) or settings.RETRIEVAL_TOP_K or 5),
            score_threshold=float(
                state.get("score_threshold", settings.SIMILARITY_THRESHOLD)
                if state.get("score_threshold", settings.SIMILARITY_THRESHOLD) is not None
                else settings.SIMILARITY_THRESHOLD or 0.0
            ),
            enable_reranker=bool(state.get("enable_reranker", settings.ENABLE_RERANKER)),
            enable_weight_rerank=bool(state.get("enable_weight_rerank", True)),
            enable_multi_query=state.get("enable_multi_query") if "enable_multi_query" in state else None,
            enable_query_alias_expansion=state.get("enable_query_alias_expansion")
            if "enable_query_alias_expansion" in state
            else None,
            intent_router_policy=state.get("intent_router_policy") if "intent_router_policy" in state else None,
            **learned_options,
        )
        for key, value in (overrides or {}).items():
            state[key] = value
    except Exception as exc:
        _log_orchestrator_fallback("_apply_routing_phase", exc)
        intent_router_meta = {"enabled": True, "used": False, "error": f"intent_router_exception:{str(exc)[:160]}"}
    return intent_router_meta


def _load_policy_from_path(*, policy_path: str) -> dict[str, Any] | None:
    policy_file = Path(policy_path)
    if not policy_file.exists():
        return None
    return json.loads(policy_file.read_text(encoding="utf-8"))


def _apply_adaptive_router(
    *, state: dict[str, Any], query_for_retrieval: str, intent_router_meta: dict[str, Any]
) -> dict[str, Any]:
    adaptive_router_req = state.get("adaptive_router")
    adaptive_router_enabled = (
        bool(adaptive_router_req) if adaptive_router_req is not None else settings.RAG_ADAPTIVE_ROUTER_ENABLED
    )
    adaptive_router_meta: dict[str, Any] = {"enabled": bool(adaptive_router_enabled), "used": False}
    if not bool(adaptive_router_enabled):
        return adaptive_router_meta
    adaptive_policy = state.get("adaptive_router_policy")
    if not isinstance(adaptive_policy, dict):
        policy_path = settings.RAG_ADAPTIVE_ROUTER_POLICY_PATH.strip()
        if policy_path:
            try:
                adaptive_policy = _load_policy_from_path(policy_path=policy_path)
            except Exception as exc:
                _log_orchestrator_fallback("_apply_routing_phase", exc)
                adaptive_policy = None
    try:
        adaptive_overrides, adaptive_router_meta = route_adaptive_retrieval_overrides(
            query=query_for_retrieval,
            retrieval_mode=str(state.get("retrieval_mode", "hybrid") or "hybrid"),
            intent_meta=intent_router_meta if isinstance(intent_router_meta, dict) else None,
            adaptive_router_policy=adaptive_policy if isinstance(adaptive_policy, dict) else None,
        )
        for key, value in (adaptive_overrides or {}).items():
            state[key] = value
    except Exception as exc:
        _log_orchestrator_fallback("_apply_routing_phase", exc)
        adaptive_router_meta = {"enabled": True, "used": False, "error": f"adaptive_router_exception:{str(exc)[:160]}"}
    return adaptive_router_meta


def _build_query_contract(
    *,
    state: dict[str, Any],
    query_for_retrieval: str,
    requested_retrieval_mode: Any,
    requested_retrieval_profile: Any,
    sparse_enabled: bool,
    sparse_provider: str,
    hierarchy_recall_enabled: bool,
    hierarchy_family_collapse: bool,
    hierarchy_family_aggregation: str,
    hierarchy_tree_dedup: bool,
    hierarchy_parent_depth: int,
    hierarchy_sibling_window: int,
    hierarchy_overfetch_factor: int,
) -> QueryContractNormalizationOutput:
    return normalize_query_contract(
        QueryContractNormalizationInput(
            state=state,
            query_for_retrieval=query_for_retrieval,
            requested_retrieval_mode=requested_retrieval_mode,
            requested_retrieval_profile=requested_retrieval_profile,
            sparse_enabled=bool(sparse_enabled),
            sparse_provider=str(sparse_provider or ""),
            hierarchy=HierarchyContractSettings(
                enabled=bool(hierarchy_recall_enabled),
                family_collapse=bool(hierarchy_family_collapse),
                family_aggregation=str(hierarchy_family_aggregation),
                tree_dedup=bool(hierarchy_tree_dedup),
                parent_depth=int(hierarchy_parent_depth),
                sibling_window=int(hierarchy_sibling_window),
                overfetch_factor=int(hierarchy_overfetch_factor),
            ),
            defaults=query_contract_defaults(),
        )
    )


def _resolve_channel_budget_meta(
    *, state: dict[str, Any], request_retrieval_mode: str, profile_applied: dict[str, Any], profile_norm: str
) -> dict[str, Any]:
    explicit_fusion_budgets = state.get("fusion_budgets") if isinstance(state.get("fusion_budgets"), dict) else None
    explicit_fusion_weights = state.get("fusion_weights") if isinstance(state.get("fusion_weights"), dict) else None
    if explicit_fusion_budgets:
        return {"enabled": False, "used": False, "reason": "request_fusion_budgets_override"}
    if explicit_fusion_weights:
        return {"enabled": False, "used": False, "reason": "request_fusion_weights_override"}
    channel_budget_policy = state.get("channel_budget_policy")
    channel_budget_policy_meta: dict[str, Any] = {"enabled": False, "used": False}
    if not isinstance(channel_budget_policy, dict):
        policy_path = str(
            state.get("channel_budget_policy_path") or settings.RAG_CHANNEL_BUDGET_POLICY_PATH or ""
        ).strip()
        if policy_path:
            channel_budget_policy_meta = {"enabled": True, "used": False, "policy_path": policy_path}
            try:
                loaded_policy = _load_policy_from_path(policy_path=policy_path)
                if loaded_policy is None:
                    channel_budget_policy_meta["reason"] = "policy_file_missing"
                else:
                    channel_budget_policy = loaded_policy
            except Exception as exc:
                _log_orchestrator_fallback("_apply_routing_phase", exc)
                channel_budget_policy = None
                channel_budget_policy_meta["reason"] = f"policy_file_error:{exc.__class__.__name__}"
    if not isinstance(channel_budget_policy, dict):
        return channel_budget_policy_meta
    overrides, channel_budget_policy_meta = resolve_channel_budget_policy_overrides(
        policy=channel_budget_policy,
        retrieval_mode=str(profile_applied.get("retrieval_mode") or request_retrieval_mode),
        retrieval_profile=profile_norm or None,
    )
    if overrides:
        for key, value in overrides.items():
            state[key] = value
    return channel_budget_policy_meta


def resolve_query_routing(
    query: str, *, options: Mapping[str, Any], sparse: SparseQuerySettings
) -> QueryRoutingDecision:
    effective = dict(options)
    evidence = resolve_evidence_contract(effective, query=query)
    contract_mode = str(evidence.get("retrieval_contract_mode") or "").strip()
    if contract_mode and not str(effective.get("retrieval_contract_mode") or "").strip():
        effective["retrieval_contract_mode"] = contract_mode
    intent = _apply_intent_router(
        state=effective,
        query_for_retrieval=query,
        requested_retrieval_mode=evidence["requested_retrieval_mode"],
        requested_retrieval_profile=evidence["requested_retrieval_profile"],
    )
    adaptive = _apply_adaptive_router(state=effective, query_for_retrieval=query, intent_router_meta=intent)
    normalization = _build_query_contract(
        state=effective,
        query_for_retrieval=query,
        requested_retrieval_mode=evidence["requested_retrieval_mode"],
        requested_retrieval_profile=evidence["requested_retrieval_profile"],
        sparse_enabled=sparse.enabled,
        sparse_provider=sparse.provider,
        hierarchy_recall_enabled=evidence["hierarchy_recall_enabled"],
        hierarchy_family_collapse=evidence["hierarchy_family_collapse"],
        hierarchy_family_aggregation=evidence["hierarchy_family_aggregation"],
        hierarchy_tree_dedup=evidence["hierarchy_tree_dedup"],
        hierarchy_parent_depth=evidence["hierarchy_parent_depth"],
        hierarchy_sibling_window=evidence["hierarchy_sibling_window"],
        hierarchy_overfetch_factor=evidence["hierarchy_overfetch_factor"],
    )
    channel = _resolve_channel_budget_meta(
        state=effective,
        request_retrieval_mode=normalization.request_retrieval_mode,
        profile_applied=normalization.profile_applied,
        profile_norm=normalization.profile_norm or "",
    )
    if channel["used"]:
        applied = {
            key: effective[key]
            for key in ("fusion_strategy", "fusion_budgets", "fusion_min_scores")
            if key in effective
        }
        normalization = replace(normalization, retriever_update={**normalization.retriever_update, **applied})
    effective.update(normalization.state_updates)
    updates = {key: value for key, value in effective.items() if key not in options or value != options[key]}
    return QueryRoutingDecision(normalization, evidence, intent, adaptive, channel, effective, updates)


def resolve_stream_query_routing(
    query: str, *, options: Mapping[str, Any], sparse: SparseQuerySettings, complexity_overrides: Mapping[str, Any]
) -> StreamQueryRoutingDecision:
    """Apply the stream's recall buckets/profile, then its existing complexity route."""
    effective = dict(options)
    evidence = resolve_evidence_contract(effective, query=query)
    contract_mode = str(evidence.get("retrieval_contract_mode") or "").strip()
    if contract_mode and not str(effective.get("retrieval_contract_mode") or "").strip():
        effective["retrieval_contract_mode"] = contract_mode
    intent = _apply_intent_router(
        state=effective,
        query_for_retrieval=query,
        requested_retrieval_mode=evidence["requested_retrieval_mode"],
        requested_retrieval_profile=evidence["requested_retrieval_profile"],
        learned_router_enabled=False,
    )
    for key, default in (
        ("alpha", 0.6),
        ("vector_weight", 0.6),
        ("keyword_weight", 0.4),
        ("mmr_lambda", settings.RETRIEVAL_MMR_LAMBDA),
    ):
        if effective.get(key) is None:
            effective[key] = default
    effective["reranker_provider"] = effective.get("reranker_provider") or settings.RERANKER_PROVIDER or "llm"
    effective["reranker_top_n"] = effective.get("reranker_top_n") or settings.RERANKER_TOP_N or 20
    mode_auto = normalize_retrieval_mode(effective.get("retrieval_mode") or "hybrid") == "auto"
    recall_bucket = None
    if mode_auto and settings.RAG_RECALL_BUCKETS_ENABLED:
        recall_bucket = guess_recall_bucket(query)
        if recall_bucket in {"schema", "policy", "definition"}:
            effective.update(retrieval_mode="keyword", score_threshold=0.0, vector_weight=0.2, keyword_weight=0.8)
        elif recall_bucket == "procedure":
            effective.update(vector_weight=0.7, keyword_weight=0.3)
        elif recall_bucket == "numeric":
            effective.update(vector_weight=0.5, keyword_weight=0.5)
    normal = normalize_query_contract(
        QueryContractNormalizationInput(
            state=effective,
            query_for_retrieval=query,
            requested_retrieval_mode=evidence["requested_retrieval_mode"],
            requested_retrieval_profile=evidence["requested_retrieval_profile"],
            sparse_enabled=sparse.enabled,
            sparse_provider=sparse.provider,
            hierarchy=HierarchyContractSettings(
                enabled=bool(effective.get("enable_hierarchy_recall")),
                family_collapse=bool(effective.get("hierarchy_family_collapse")),
                family_aggregation=effective.get("hierarchy_family_aggregation") or "combined",
                tree_dedup=bool(effective.get("hierarchy_tree_dedup")),
                parent_depth=effective.get("hierarchy_parent_depth") or 0,
                sibling_window=effective.get("hierarchy_sibling_window") or 0,
                overfetch_factor=effective.get("hierarchy_overfetch_factor") or 1,
            ),
            defaults=query_contract_defaults(),
        )
    )
    if mode_auto and recall_bucket is not None:
        normal = replace(normal, retrieval_mode_routed=True)
    effective.update(normal.state_updates)
    for key in (
        "enable_weight_rerank",
        "enable_hierarchy_recall",
        "hierarchy_family_collapse",
        "hierarchy_family_aggregation",
        "hierarchy_tree_dedup",
        "hierarchy_parent_depth",
        "hierarchy_sibling_window",
        "hierarchy_overfetch_factor",
    ):
        if normal.profile_applied.get(key) is not None:
            effective[key] = normal.profile_applied[key]
    update = dict(normal.retriever_update)
    profile = normal.profile_norm
    if complexity_overrides.get("top_k") is not None:
        update["k"] = max(1, int(complexity_overrides["top_k"] or update["k"] or 1))
    if complexity_overrides.get("enable_multi_query") is not None:
        effective["enable_multi_query"] = bool(complexity_overrides["enable_multi_query"])
    if complexity_overrides.get("multi_query_count") is not None:
        effective["multi_query_count"] = max(0, int(complexity_overrides["multi_query_count"]))
    if complexity_overrides.get("retrieval_profile") is not None:
        profile = str(complexity_overrides["retrieval_profile"]).strip() or profile
        profile = profile.lower() if profile is not None else None
        update["retrieval_profile"] = profile
        if is_recall_first_profile(profile):
            update["score_threshold"] = 0.0
    effective.update(
        top_k=update["k"],
        retrieval_profile=profile,
        retrieval_mode=update["retrieval_mode"],
        sparse_retrieval_enabled=normal.sparse_enabled,
        sparse_retrieval_provider=normal.sparse_provider,
    )
    normal = replace(normal, profile_norm=profile, retriever_update=update)
    updates = {key: value for key, value in effective.items() if key not in options or value != options[key]}
    return StreamQueryRoutingDecision(
        QueryRoutingDecision(
            normal,
            evidence,
            intent,
            {"enabled": bool(complexity_overrides), "used": bool(complexity_overrides)},
            {"enabled": False, "used": False},
            effective,
            updates,
        ),
        dict(complexity_overrides),
        recall_bucket,
    )
