import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.rag.core.evidence_expectations import DEFAULT_EVIDENCE_ANCHOR_FIELDS, normalize_anchor_fields
from app.rag.policy.must_recall import normalize_source_keys
from app.rag.retrieval.orchestration.channel_budget import resolve_channel_budget_policy_overrides
from app.rag.retrieval.orchestration.common import _log_orchestrator_fallback
from app.rag.retrieval.orchestration.query_contract import (
    HierarchyContractSettings,
    QueryContractDefaults,
    QueryContractNormalizationInput,
    normalize_query_contract,
)
from app.rag.retrieval.sparse import normalize_sparse_provider_name


def _resolve_must_recall_enabled(
    *,
    state: dict[str, Any],
    retrieval_contract_policy: dict[str, Any],
) -> tuple[Any, bool]:
    must_recall_requested = state.get("must_recall")
    if must_recall_requested is None:
        must_recall_enabled = bool(getattr(settings, "RETRIEVAL_MUST_RECALL_DEFAULT_ENABLED", False))
    else:
        must_recall_enabled = bool(must_recall_requested)
    if bool(retrieval_contract_policy.get("must_recall_strict")):
        must_recall_enabled = True
    return must_recall_requested, must_recall_enabled


def _resolve_expected_source_keys(
    *,
    state: dict[str, Any],
    query_for_retrieval: str,
    must_recall_enabled: bool,
    infer_expected_source_keys_fn: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    explicit_expected_source_keys = state.get("must_recall_expected_source_keys") is not None
    raw_expected_source_keys = (
        state.get("must_recall_expected_source_keys")
        if explicit_expected_source_keys
        else getattr(settings, "RETRIEVAL_MUST_RECALL_REQUIRED_SOURCE_KEYS", "")
    )
    expected_source_keys = normalize_source_keys(raw_expected_source_keys)
    auto_enabled = bool(
        state.get("must_recall_auto_expected_source_keys_enabled")
        if state.get("must_recall_auto_expected_source_keys_enabled") is not None
        else getattr(settings, "RETRIEVAL_MUST_RECALL_AUTO_EXPECTED_SOURCE_KEYS_ENABLED", True)
    )
    auto_source_keys: list[str] = []
    auto_reason_codes: list[str] = []
    auto_confidence = "none"
    auto_applied = False
    if (
        bool(must_recall_enabled)
        and bool(auto_enabled)
        and not expected_source_keys
        and not explicit_expected_source_keys
    ):
        auto_max_keys = max(
            1,
            int(getattr(settings, "RETRIEVAL_MUST_RECALL_AUTO_EXPECTED_SOURCE_KEYS_MAX", 12) or 12),
        )
        allow_filter = bool(getattr(settings, "RETRIEVAL_MUST_RECALL_AUTO_INFER_FROM_METADATA_FILTER", True))
        meta_filter = state.get("metadata_filter") if allow_filter else None
        scope_payload = _build_must_recall_scope_payload(state)
        inferred = infer_expected_source_keys_fn(
            query=query_for_retrieval,
            metadata_filter=(meta_filter if isinstance(meta_filter, dict) else None),
            scope=(scope_payload if scope_payload else None),
            max_keys=auto_max_keys,
        )
        auto_source_keys = normalize_source_keys(list(inferred.get("expected_source_keys") or []))
        auto_reason_codes = [str(value) for value in (inferred.get("reason_codes") or []) if str(value).strip()][:8]
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
    *,
    state: dict[str, Any],
    query_for_retrieval: str,
    must_recall_enabled: bool,
    infer_required_anchor_fields_fn: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    explicit_required_anchor_fields = state.get("must_recall_required_anchor_fields") is not None
    raw_required_anchor_fields = (
        state.get("must_recall_required_anchor_fields")
        if explicit_required_anchor_fields
        else getattr(settings, "RETRIEVAL_MUST_RECALL_REQUIRED_ANCHOR_FIELDS", "")
    )
    required_anchor_fields = normalize_anchor_fields(raw_required_anchor_fields)
    auto_enabled = bool(
        state.get("must_recall_auto_required_anchor_fields_enabled")
        if state.get("must_recall_auto_required_anchor_fields_enabled") is not None
        else getattr(settings, "RETRIEVAL_MUST_RECALL_AUTO_REQUIRED_ANCHOR_FIELDS_ENABLED", True)
    )
    auto_fields: list[str] = []
    auto_reason_codes: list[str] = []
    auto_applied = False
    if bool(must_recall_enabled) and bool(auto_enabled):
        inferred_anchor = infer_required_anchor_fields_fn(
            query=query_for_retrieval,
            default_fields=(required_anchor_fields if required_anchor_fields else list(DEFAULT_EVIDENCE_ANCHOR_FIELDS)),
        )
        auto_fields = normalize_anchor_fields(list(inferred_anchor.get("required_anchor_fields") or []))
        auto_reason_codes = [str(value) for value in (inferred_anchor.get("reason_codes") or []) if str(value).strip()][
            :8
        ]
        if auto_fields and (
            bool(inferred_anchor.get("applied")) or not required_anchor_fields or not explicit_required_anchor_fields
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
        else bool(getattr(settings, "RETRIEVAL_CONTEXTUAL_FOLLOWUP_ENABLED", False))
    )
    contextual_followup_mode = (
        str(
            state.get("contextual_followup_mode")
            if state.get("contextual_followup_mode") is not None
            else (getattr(settings, "RETRIEVAL_CONTEXTUAL_FOLLOWUP_MODE", "keyword") or "keyword")
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
                else (getattr(settings, "RETRIEVAL_CONTEXTUAL_FOLLOWUP_TOP_K", 40) or 40)
            ),
        ),
        "contextual_followup_max_docs": max(
            1,
            int(
                state.get("contextual_followup_max_docs")
                if state.get("contextual_followup_max_docs") is not None
                else (getattr(settings, "RETRIEVAL_CONTEXTUAL_FOLLOWUP_MAX_DOCS", 4) or 4)
            ),
        ),
        "contextual_followup_max_terms": max(
            0,
            int(
                state.get("contextual_followup_max_terms")
                if state.get("contextual_followup_max_terms") is not None
                else (getattr(settings, "RETRIEVAL_CONTEXTUAL_FOLLOWUP_MAX_TERMS", 4) or 4)
            ),
        ),
        "contextual_followup_min_term_chars": max(
            2,
            int(
                state.get("contextual_followup_min_term_chars")
                if state.get("contextual_followup_min_term_chars") is not None
                else (getattr(settings, "RETRIEVAL_CONTEXTUAL_FOLLOWUP_MIN_TERM_CHARS", 4) or 4)
            ),
        ),
        "contextual_followup_max_query_chars": max(
            32,
            int(
                state.get("contextual_followup_max_query_chars")
                if state.get("contextual_followup_max_query_chars") is not None
                else (getattr(settings, "RETRIEVAL_CONTEXTUAL_FOLLOWUP_MAX_QUERY_CHARS", 500) or 500)
            ),
        ),
        "contextual_followup_max_hops": max(
            1,
            int(
                state.get("contextual_followup_max_hops")
                if state.get("contextual_followup_max_hops") is not None
                else (getattr(settings, "RETRIEVAL_CONTEXTUAL_FOLLOWUP_MAX_HOPS", 1) or 1)
            ),
        ),
        "contextual_followup_latency_budget_ms": max(
            0.0,
            float(
                state.get("contextual_followup_latency_budget_ms")
                if state.get("contextual_followup_latency_budget_ms") is not None
                else (getattr(settings, "RETRIEVAL_CONTEXTUAL_FOLLOWUP_LATENCY_BUDGET_MS", 500.0) or 500.0)
            ),
        ),
    }


def _resolve_hierarchy_settings(state: dict[str, Any]) -> dict[str, Any]:
    hierarchy_recall_req = state.get("enable_hierarchy_recall")
    hierarchy_recall_enabled = (
        bool(hierarchy_recall_req)
        if hierarchy_recall_req is not None
        else bool(getattr(settings, "HIERARCHY_RECALL_ENABLED", False))
    )
    hierarchy_family_collapse_req = state.get("hierarchy_family_collapse")
    hierarchy_family_collapse = (
        bool(hierarchy_family_collapse_req)
        if hierarchy_family_collapse_req is not None
        else bool(getattr(settings, "HIERARCHY_RECALL_FAMILY_COLLAPSE", False))
    )
    hierarchy_family_aggregation = (
        str(
            state.get("hierarchy_family_aggregation")
            if state.get("hierarchy_family_aggregation") is not None
            else (getattr(settings, "HIERARCHY_RECALL_FAMILY_AGGREGATION", "combined") or "combined")
        )
        .strip()
        .lower()
        or "combined"
    )
    if hierarchy_family_aggregation not in {"frequency", "score", "combined"}:
        hierarchy_family_aggregation = "combined"
    hierarchy_tree_dedup_req = state.get("hierarchy_tree_dedup")
    hierarchy_tree_dedup = (
        bool(hierarchy_tree_dedup_req)
        if hierarchy_tree_dedup_req is not None
        else bool(getattr(settings, "HIERARCHY_RECALL_TREE_DEDUP", False))
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
                else (getattr(settings, "HIERARCHY_RECALL_PARENT_DEPTH", 0) or 0)
            ),
        ),
        "hierarchy_sibling_window": max(
            0,
            int(
                state.get("hierarchy_sibling_window")
                if state.get("hierarchy_sibling_window") is not None
                else (getattr(settings, "HIERARCHY_RECALL_SIBLING_WINDOW", 0) or 0)
            ),
        ),
        "hierarchy_overfetch_factor": max(
            1,
            int(
                state.get("hierarchy_overfetch_factor")
                if state.get("hierarchy_overfetch_factor") is not None
                else (getattr(settings, "HIERARCHY_RECALL_OVERFETCH_FACTOR", 4) or 4)
            ),
        ),
    }


def resolve_contract_phase(
    state: dict[str, Any],
    *,
    query_for_retrieval: str,
    resolve_retrieval_contract_policy_fn: Callable[..., dict[str, Any]],
    infer_expected_source_keys_fn: Callable[..., dict[str, Any]],
    infer_required_anchor_fields_fn: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    requested_retrieval_mode = state.get("retrieval_mode", "hybrid") or "hybrid"
    requested_retrieval_profile = state.get("retrieval_profile")
    retrieval_contract_policy = resolve_retrieval_contract_policy_fn(
        mode=(
            state.get("retrieval_contract_mode")
            if state.get("retrieval_contract_mode") is not None
            else getattr(settings, "RETRIEVAL_CONTRACT_MODE", "")
        ),
        requested_top_k=int(state.get("top_k", settings.RETRIEVAL_TOP_K) or settings.RETRIEVAL_TOP_K or 5),
        hard_fallback_enabled_setting=bool(getattr(settings, "RETRIEVAL_HARD_FALLBACK_ENABLED", False)),
        hard_fallback_mode_setting=str(getattr(settings, "RETRIEVAL_HARD_FALLBACK_MODE", "keyword") or "keyword"),
        hard_fallback_top_k_setting=int(getattr(settings, "RETRIEVAL_HARD_FALLBACK_TOP_K", 30) or 30),
        visible_evidence_only_setting=bool(getattr(settings, "RAG_VISIBLE_EVIDENCE_ONLY_ENABLED", False)),
        evidence_span_strict_setting=bool(getattr(settings, "RAG_EVIDENCE_REQUIRE_SPANS_ENABLED", False)),
    )
    retrieval_contract_mode = str(retrieval_contract_policy.get("mode") or "").strip().lower()
    contract_deterministic_recall = bool(retrieval_contract_policy.get("deterministic_recall"))
    contract_must_recall_strict = bool(retrieval_contract_policy.get("must_recall_strict"))

    must_recall_requested, must_recall_enabled = _resolve_must_recall_enabled(
        state=state,
        retrieval_contract_policy=retrieval_contract_policy,
    )
    expected_source_keys = _resolve_expected_source_keys(
        state=state,
        query_for_retrieval=query_for_retrieval,
        must_recall_enabled=must_recall_enabled,
        infer_expected_source_keys_fn=infer_expected_source_keys_fn,
    )
    required_anchor_fields = _resolve_required_anchor_fields(
        state=state,
        query_for_retrieval=query_for_retrieval,
        must_recall_enabled=must_recall_enabled,
        infer_required_anchor_fields_fn=infer_required_anchor_fields_fn,
    )
    contextual_followup_settings = _resolve_contextual_followup_settings(state)
    hierarchy_settings = _resolve_hierarchy_settings(state)

    must_recall_second_pass_enabled = bool(
        bool(retrieval_contract_policy.get("enable_partial_miss_second_pass"))
        and bool(getattr(settings, "RETRIEVAL_MUST_RECALL_SECOND_PASS_ENABLED", True))
    )
    must_recall_second_pass_mode = (
        str(getattr(settings, "RETRIEVAL_MUST_RECALL_SECOND_PASS_MODE", "keyword") or "keyword").strip().lower()
        or "keyword"
    )
    must_recall_second_pass_top_k = max(
        int(state.get("top_k", settings.RETRIEVAL_TOP_K) or settings.RETRIEVAL_TOP_K or 1),
        int(getattr(settings, "RETRIEVAL_MUST_RECALL_SECOND_PASS_TOP_K", 80) or 80),
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
    route_retrieval_preset_fn: Callable[..., tuple[dict[str, Any], dict[str, Any]]],
) -> dict[str, Any]:
    intent_router_req = state.get("intent_router")
    intent_router_enabled = (
        bool(intent_router_req)
        if intent_router_req is not None
        else bool(getattr(settings, "RAG_INTENT_ROUTER_ENABLED", False))
    )
    intent_router_meta: dict[str, Any] = {"enabled": bool(intent_router_enabled), "used": False}
    if not bool(intent_router_enabled):
        return intent_router_meta
    try:
        overrides, intent_router_meta = route_retrieval_preset_fn(
            query=query_for_retrieval,
            retrieval_mode=str(requested_retrieval_mode or ""),
            retrieval_profile=(
                str(requested_retrieval_profile).strip() if requested_retrieval_profile is not None else None
            ),
            top_k=int(state.get("top_k", settings.RETRIEVAL_TOP_K) or settings.RETRIEVAL_TOP_K or 5),
            score_threshold=float(
                state.get("score_threshold", settings.SIMILARITY_THRESHOLD)
                if state.get("score_threshold", settings.SIMILARITY_THRESHOLD) is not None
                else (settings.SIMILARITY_THRESHOLD or 0.0)
            ),
            enable_reranker=bool(state.get("enable_reranker", settings.ENABLE_RERANKER)),
            enable_weight_rerank=bool(state.get("enable_weight_rerank", True)),
            enable_multi_query=(state.get("enable_multi_query") if "enable_multi_query" in state else None),
            enable_query_alias_expansion=(
                state.get("enable_query_alias_expansion") if "enable_query_alias_expansion" in state else None
            ),
            intent_router_policy=(state.get("intent_router_policy") if "intent_router_policy" in state else None),
            learned_router_model=(
                state.get("intent_router_model") if isinstance(state.get("intent_router_model"), dict) else None
            ),
            learned_router_model_path=(
                str(state.get("intent_router_model_path") or "").strip()
                if state.get("intent_router_model_path") is not None
                else str(getattr(settings, "RAG_INTENT_ROUTER_MODEL_PATH", "") or "").strip()
            ),
            learned_router_confidence_min=float(
                state.get("intent_router_model_confidence_min")
                if state.get("intent_router_model_confidence_min") is not None
                else (getattr(settings, "RAG_INTENT_ROUTER_MODEL_CONFIDENCE_MIN", 0.7) or 0.7)
            ),
        )
        for key, value in (overrides or {}).items():
            state[key] = value
    except Exception as exc:  # noqa: BLE001
        _log_orchestrator_fallback("_apply_routing_phase", exc)
        intent_router_meta = {
            "enabled": True,
            "used": False,
            "error": f"intent_router_exception:{str(exc)[:160]}",
        }
    return intent_router_meta


def _load_policy_from_path(*, policy_path: str) -> dict[str, Any] | None:
    policy_file = Path(policy_path)
    if not policy_file.exists():
        return None
    return json.loads(policy_file.read_text(encoding="utf-8"))


def _apply_adaptive_router(
    *,
    state: dict[str, Any],
    query_for_retrieval: str,
    intent_router_meta: dict[str, Any],
    route_adaptive_retrieval_overrides_fn: Callable[..., tuple[dict[str, Any], dict[str, Any]]],
) -> dict[str, Any]:
    adaptive_router_req = state.get("adaptive_router")
    adaptive_router_enabled = (
        bool(adaptive_router_req)
        if adaptive_router_req is not None
        else bool(getattr(settings, "RAG_ADAPTIVE_ROUTER_ENABLED", False))
    )
    adaptive_router_meta: dict[str, Any] = {"enabled": bool(adaptive_router_enabled), "used": False}
    if not bool(adaptive_router_enabled):
        return adaptive_router_meta

    adaptive_policy = state.get("adaptive_router_policy")
    if not isinstance(adaptive_policy, dict):
        policy_path = str(getattr(settings, "RAG_ADAPTIVE_ROUTER_POLICY_PATH", "") or "").strip()
        if policy_path:
            try:
                adaptive_policy = _load_policy_from_path(policy_path=policy_path)
            except Exception as exc:  # noqa: BLE001
                _log_orchestrator_fallback("_apply_routing_phase", exc)
                adaptive_policy = None
    try:
        adaptive_overrides, adaptive_router_meta = route_adaptive_retrieval_overrides_fn(
            query=query_for_retrieval,
            retrieval_mode=str(state.get("retrieval_mode", "hybrid") or "hybrid"),
            intent_meta=(intent_router_meta if isinstance(intent_router_meta, dict) else None),
            adaptive_router_policy=(adaptive_policy if isinstance(adaptive_policy, dict) else None),
        )
        for key, value in (adaptive_overrides or {}).items():
            state[key] = value
    except Exception as exc:  # noqa: BLE001
        _log_orchestrator_fallback("_apply_routing_phase", exc)
        adaptive_router_meta = {
            "enabled": True,
            "used": False,
            "error": f"adaptive_router_exception:{str(exc)[:160]}",
        }
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
) -> Any:
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
            defaults=QueryContractDefaults(
                retrieval_top_k=int(settings.RETRIEVAL_TOP_K or 5),
                similarity_threshold=float(settings.SIMILARITY_THRESHOLD or 0.0),
                enable_reranker=bool(settings.ENABLE_RERANKER),
                reranker_provider=str(settings.RERANKER_PROVIDER or ""),
                reranker_top_n=int(settings.RERANKER_TOP_N or 20),
                retrieval_contract_mode=str(getattr(settings, "RETRIEVAL_CONTRACT_MODE", "") or ""),
                hard_fallback_enabled_setting=bool(getattr(settings, "RETRIEVAL_HARD_FALLBACK_ENABLED", False)),
                hard_fallback_mode_setting=str(
                    getattr(settings, "RETRIEVAL_HARD_FALLBACK_MODE", "keyword") or "keyword"
                ),
                hard_fallback_top_k_setting=int(getattr(settings, "RETRIEVAL_HARD_FALLBACK_TOP_K", 30) or 30),
                visible_evidence_only_setting=bool(getattr(settings, "RAG_VISIBLE_EVIDENCE_ONLY_ENABLED", False)),
                evidence_span_strict_setting=bool(getattr(settings, "RAG_EVIDENCE_REQUIRE_SPANS_ENABLED", False)),
                retrieval_fusion_strategy=str(settings.RETRIEVAL_FUSION_STRATEGY or ""),
                retrieval_mmr_lambda=float(settings.RETRIEVAL_MMR_LAMBDA or 0.0),
            ),
        )
    )


def _resolve_channel_budget_meta(
    *,
    state: dict[str, Any],
    request_retrieval_mode: str,
    profile_applied: dict[str, Any],
    profile_norm: str,
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
            state.get("channel_budget_policy_path") or getattr(settings, "RAG_CHANNEL_BUDGET_POLICY_PATH", "") or ""
        ).strip()
        if policy_path:
            channel_budget_policy_meta = {"enabled": True, "used": False, "policy_path": policy_path}
            try:
                loaded_policy = _load_policy_from_path(policy_path=policy_path)
                if loaded_policy is None:
                    channel_budget_policy_meta["reason"] = "policy_file_missing"
                else:
                    channel_budget_policy = loaded_policy
            except Exception as exc:  # noqa: BLE001
                _log_orchestrator_fallback("_apply_routing_phase", exc)
                channel_budget_policy = None
                channel_budget_policy_meta["reason"] = f"policy_file_error:{exc.__class__.__name__}"
    if not isinstance(channel_budget_policy, dict):
        return channel_budget_policy_meta

    overrides, channel_budget_policy_meta = resolve_channel_budget_policy_overrides(
        policy=channel_budget_policy,
        retrieval_mode=str(profile_applied.get("retrieval_mode") or request_retrieval_mode),
        retrieval_profile=(profile_norm or None),
    )
    if overrides:
        for key, value in overrides.items():
            state[key] = value
    return channel_budget_policy_meta


def apply_routing_phase(  # noqa: PLR0913
    state: dict[str, Any],
    *,
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
    hybrid_retriever_obj: Any,
    route_retrieval_preset_fn: Callable[..., tuple[dict[str, Any], dict[str, Any]]],
    route_adaptive_retrieval_overrides_fn: Callable[..., tuple[dict[str, Any], dict[str, Any]]],
) -> dict[str, Any]:
    intent_router_meta = _apply_intent_router(
        state=state,
        query_for_retrieval=query_for_retrieval,
        requested_retrieval_mode=requested_retrieval_mode,
        requested_retrieval_profile=requested_retrieval_profile,
        route_retrieval_preset_fn=route_retrieval_preset_fn,
    )
    adaptive_router_meta = _apply_adaptive_router(
        state=state,
        query_for_retrieval=query_for_retrieval,
        intent_router_meta=intent_router_meta,
        route_adaptive_retrieval_overrides_fn=route_adaptive_retrieval_overrides_fn,
    )
    query_contract = _build_query_contract(
        state=state,
        query_for_retrieval=query_for_retrieval,
        requested_retrieval_mode=requested_retrieval_mode,
        requested_retrieval_profile=requested_retrieval_profile,
        sparse_enabled=sparse_enabled,
        sparse_provider=sparse_provider,
        hierarchy_recall_enabled=hierarchy_recall_enabled,
        hierarchy_family_collapse=hierarchy_family_collapse,
        hierarchy_family_aggregation=hierarchy_family_aggregation,
        hierarchy_tree_dedup=hierarchy_tree_dedup,
        hierarchy_parent_depth=hierarchy_parent_depth,
        hierarchy_sibling_window=hierarchy_sibling_window,
        hierarchy_overfetch_factor=hierarchy_overfetch_factor,
    )

    request_retrieval_mode = query_contract.request_retrieval_mode
    retrieval_mode_routed = bool(query_contract.retrieval_mode_routed)
    profile_applied = dict(query_contract.profile_applied)
    profile_norm = query_contract.profile_norm or ""
    sparse_enabled = bool(query_contract.sparse_enabled)
    sparse_provider = normalize_sparse_provider_name(str(query_contract.sparse_provider or ""))
    hierarchy_recall_enabled = bool(query_contract.hierarchy.enabled)
    hierarchy_family_collapse = bool(query_contract.hierarchy.family_collapse)
    hierarchy_family_aggregation = str(query_contract.hierarchy.family_aggregation or "combined")
    hierarchy_tree_dedup = bool(query_contract.hierarchy.tree_dedup)
    hierarchy_parent_depth = int(query_contract.hierarchy.parent_depth)
    hierarchy_sibling_window = int(query_contract.hierarchy.sibling_window)
    hierarchy_overfetch_factor = int(query_contract.hierarchy.overfetch_factor)

    channel_budget_policy_meta = _resolve_channel_budget_meta(
        state=state,
        request_retrieval_mode=request_retrieval_mode,
        profile_applied=profile_applied,
        profile_norm=profile_norm,
    )
    retriever_update: dict[str, Any] = dict(query_contract.retriever_update)
    for key, value in query_contract.state_updates.items():
        state[key] = value
    retriever = hybrid_retriever_obj.model_copy(update=retriever_update)
    return {
        "intent_router_meta": intent_router_meta,
        "adaptive_router_meta": adaptive_router_meta,
        "channel_budget_policy_meta": channel_budget_policy_meta,
        "request_retrieval_mode": request_retrieval_mode,
        "retrieval_mode_routed": retrieval_mode_routed,
        "profile_applied": profile_applied,
        "profile_norm": profile_norm,
        "retrieval_contract_policy": dict(query_contract.retrieval_contract_policy or {}),
        "retrieval_contract_mode": str(query_contract.retrieval_contract_mode or "").strip().lower(),
        "contract_deterministic_recall": bool(query_contract.contract_deterministic_recall),
        "sparse_enabled": sparse_enabled,
        "sparse_provider": sparse_provider,
        "hierarchy_recall_enabled": hierarchy_recall_enabled,
        "hierarchy_family_collapse": hierarchy_family_collapse,
        "hierarchy_family_aggregation": hierarchy_family_aggregation,
        "hierarchy_tree_dedup": hierarchy_tree_dedup,
        "hierarchy_parent_depth": hierarchy_parent_depth,
        "hierarchy_sibling_window": hierarchy_sibling_window,
        "hierarchy_overfetch_factor": hierarchy_overfetch_factor,
        "retriever_update": retriever_update,
        "retriever": retriever,
    }
