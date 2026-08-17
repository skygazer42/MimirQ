"""Channel budget policy resolution and post-rerank pipeline config summaries.

Split out of ``app.rag.retrieval.orchestrator`` (see
``app.rag.retrieval.orchestration``).
"""

import json
from typing import Any

from app.rag.core.hashing import stable_hash
from app.rag.retrieval.orchestration.common import _safe_int

_CHANNEL_BUDGET_POLICY_SCHEMA_V1 = "mimirq.channel_budget_policy.v1"


def _safe_post_rerank_pipeline_summary(raw: Any) -> list[dict[str, Any]]:
    """
    Parse/normalize the Evidence post-rerank pipeline config into a low-cardinality summary.

    Notes:
    - We intentionally keep only {provider, top_n} so this can be embedded into retrieval_config_hash
      without leaking secrets or environment-specific paths.
    - Expected input is JSON from settings.EVIDENCE_POST_RERANK_PIPELINE.
    """
    text = str(raw or "").strip()
    if not text:
        return []
    try:
        obj = json.loads(text)
    except (TypeError, ValueError, AttributeError):
        return []
    if not isinstance(obj, list):
        return []

    out: list[dict[str, Any]] = []
    for item in obj:
        row = _safe_post_rerank_pipeline_item(item)
        if row is None:
            continue
        out.append(row)
        if len(out) >= 4:
            break
    return out


def _safe_post_rerank_pipeline_item(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    provider = str(item.get("provider") or "").strip().lower()
    if not provider or provider in {"none", "off", "false", "0"}:
        return None
    top_n = _safe_int(item.get("top_n"), minimum=0)
    return {"provider": provider, "top_n": top_n or None}


def _coerce_channel_budgets(raw: Any) -> dict[str, int]:
    if not isinstance(raw, dict):
        return {}
    allowed = {"vector", "bm25", "lexical", "sparse"}
    out: dict[str, int] = {}
    for k, v in raw.items():
        key = str(k or "").strip().lower()
        if not key or key not in allowed:
            continue
        try:
            iv = int(v) if v is not None else 0
        except (TypeError, ValueError, AttributeError):
            continue
        out[key] = max(0, int(iv))
    return out


def _coerce_channel_min_scores(raw: Any) -> dict[str, float]:
    if not isinstance(raw, dict):
        return {}
    allowed = {"vector", "bm25", "lexical", "sparse"}
    out: dict[str, float] = {}
    for k, v in raw.items():
        key = str(k or "").strip().lower()
        if not key or key not in allowed:
            continue
        try:
            fv = float(v) if v is not None else 0.0
        except (TypeError, ValueError, AttributeError):
            continue
        out[key] = max(0.0, min(1.0, float(fv)))
    return out


def resolve_channel_budget_policy_overrides(
    *,
    policy: dict[str, Any] | None,
    retrieval_mode: str,
    retrieval_profile: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    meta: dict[str, Any] = {"enabled": bool(isinstance(policy, dict)), "used": False}
    if not isinstance(policy, dict):
        meta["reason"] = "policy_missing"
        return {}, meta

    profiles, disabled_meta = _channel_budget_policy_profiles(policy)
    if disabled_meta is not None:
        meta.update(disabled_meta)
        return {}, meta

    mode_norm = str(retrieval_mode or "").strip().lower() or "hybrid"
    profile_norm = str(retrieval_profile or "").strip().lower()
    selected_key, selected, disabled_meta = _channel_budget_policy_selected(
        profiles,
        mode_norm=mode_norm,
        profile_norm=profile_norm,
    )
    if disabled_meta is not None:
        meta.update(disabled_meta)
        return {}, meta

    budgets = _coerce_channel_budgets((selected or {}).get("fusion_budgets"))
    if not budgets:
        meta["reason"] = "budgets_missing"
        meta["selected_profile"] = selected_key
        return {}, meta

    overrides = _channel_budget_policy_overrides(policy, selected=selected, budgets=budgets)
    meta.update(
        _channel_budget_policy_applied_meta(
            policy, selected_key=selected_key, mode_norm=mode_norm, profile_norm=profile_norm, budgets=budgets
        )
    )
    return overrides, meta


def _channel_budget_policy_profiles(policy: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    schema_meta = _channel_budget_policy_schema_meta(policy)
    if schema_meta is not None:
        return {}, schema_meta
    profiles = policy.get("profiles") if isinstance(policy.get("profiles"), dict) else {}
    if not profiles:
        return {}, {"reason": "profiles_missing"}
    return profiles, None


def _channel_budget_policy_schema_meta(policy: dict[str, Any]) -> dict[str, Any] | None:
    schema = str(policy.get("schema") or "").strip()
    if schema and schema != _CHANNEL_BUDGET_POLICY_SCHEMA_V1:
        return {"reason": "schema_mismatch", "schema": schema}
    return None


def _select_channel_budget_profile(profiles: dict[str, Any], *, profile_norm: str, mode_norm: str) -> str:
    for key in (profile_norm, mode_norm, "default"):
        if key and isinstance(profiles.get(key), dict):
            return key
    return ""


def _channel_budget_policy_selected(
    profiles: dict[str, Any],
    *,
    mode_norm: str,
    profile_norm: str,
) -> tuple[str, dict[str, Any], dict[str, Any] | None]:
    selected_key = _select_channel_budget_profile(profiles, profile_norm=profile_norm, mode_norm=mode_norm)
    if not selected_key:
        return (
            "",
            {},
            {
                "reason": "profile_not_found",
                "retrieval_mode": mode_norm,
                "retrieval_profile": profile_norm or None,
            },
        )
    selected = profiles.get(selected_key) if isinstance(profiles.get(selected_key), dict) else {}
    return selected_key, selected, None


def _channel_budget_policy_overrides(
    policy: dict[str, Any],
    *,
    selected: dict[str, Any],
    budgets: dict[str, int],
) -> dict[str, Any]:
    fusion_strategy = (
        str((selected or {}).get("fusion_strategy") or policy.get("fusion_strategy") or "budgeted_rrf").strip().lower()
        or "budgeted_rrf"
    )
    overrides: dict[str, Any] = {
        "fusion_strategy": fusion_strategy,
        "fusion_budgets": budgets,
    }
    min_scores = _coerce_channel_min_scores((selected or {}).get("fusion_min_scores"))
    if min_scores:
        overrides["fusion_min_scores"] = min_scores
    return overrides


def _channel_budget_policy_applied_meta(
    policy: dict[str, Any],
    *,
    selected_key: str,
    mode_norm: str,
    profile_norm: str,
    budgets: dict[str, int],
) -> dict[str, Any]:
    return {
        "used": True,
        "reason": "applied",
        "selected_profile": selected_key,
        "retrieval_mode": mode_norm,
        "retrieval_profile": profile_norm or None,
        "budget_channels": sorted(budgets.keys()),
        "policy_hash": stable_hash(json.dumps(policy, ensure_ascii=False, sort_keys=True), length=16),
    }
