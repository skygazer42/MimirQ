"""Channel budget policy resolution for retrieval fusion."""

import json
from collections.abc import Mapping
from typing import Annotated, Any, Literal

from pydantic import ConfigDict, Field, TypeAdapter

from app.infrastructure.hashing import stable_hash
from app.infrastructure.model_policy import reject_retired_retrieval_options
from app.types.document_metadata import metadata_text

_CHANNEL_BUDGET_POLICY_SCHEMA_V1 = "mimirq.channel_budget_policy.v1"
_ChannelName = Literal["vector", "bm25", "lexical"]
_CHANNEL_BUDGETS = TypeAdapter(
    dict[_ChannelName, Annotated[int, Field(ge=0)]], config=ConfigDict(hide_input_in_errors=True)
)
_CHANNEL_MIN_SCORES = TypeAdapter(
    dict[_ChannelName, Annotated[float, Field(ge=0, le=1)]], config=ConfigDict(hide_input_in_errors=True)
)


def _normalize_channel_names(raw: object) -> object:
    if not isinstance(raw, Mapping):
        return raw
    return {key.strip().lower() if isinstance(key, str) else key: value for key, value in raw.items()}


def _coerce_channel_budgets(raw: Any) -> dict[str, int]:
    if raw is None:
        return {}
    return _CHANNEL_BUDGETS.validate_python(_normalize_channel_names(raw))


def _coerce_channel_min_scores(raw: Any) -> dict[str, float]:
    if raw is None:
        return {}
    return _CHANNEL_MIN_SCORES.validate_python(_normalize_channel_names(raw))


def resolve_channel_budget_policy_overrides(
    *,
    policy: dict[str, Any] | None,
    retrieval_mode: str,
    retrieval_profile: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    meta: dict[str, Any] = {"enabled": isinstance(policy, dict), "used": False}
    if not isinstance(policy, dict):
        meta["reason"] = "policy_missing"
        return {}, meta

    schema = metadata_text(policy, "schema")
    if schema and schema != _CHANNEL_BUDGET_POLICY_SCHEMA_V1:
        meta.update(reason="schema_mismatch", schema=schema)
        return {}, meta
    profiles = policy.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        meta["reason"] = "profiles_missing"
        return {}, meta

    mode_norm = retrieval_mode.strip().lower() or "hybrid"
    profile_norm = retrieval_profile.strip().lower() if retrieval_profile is not None else None
    selected_key = ""
    for key in (profile_norm, mode_norm, "default"):
        if key and isinstance(profiles.get(key), dict):
            selected_key = key
            break
    if not selected_key:
        meta.update(reason="profile_not_found", retrieval_mode=mode_norm, retrieval_profile=profile_norm)
        return {}, meta

    selected = profiles[selected_key]
    reject_retired_retrieval_options(selected)
    budgets = _coerce_channel_budgets(selected.get("fusion_budgets"))
    if not budgets:
        meta["reason"] = "budgets_missing"
        meta["selected_profile"] = selected_key
        return {}, meta

    fusion_strategy = (
        str(selected.get("fusion_strategy") or policy.get("fusion_strategy") or "budgeted_rrf").strip().lower()
        or "budgeted_rrf"
    )
    overrides: dict[str, Any] = {
        "fusion_strategy": fusion_strategy,
        "fusion_budgets": budgets,
    }
    min_scores = _coerce_channel_min_scores(selected.get("fusion_min_scores"))
    if min_scores:
        overrides["fusion_min_scores"] = min_scores
    meta.update(
        used=True,
        reason="applied",
        selected_profile=selected_key,
        retrieval_mode=mode_norm,
        retrieval_profile=profile_norm,
        budget_channels=sorted(budgets.keys()),
        policy_hash=stable_hash(json.dumps(policy, ensure_ascii=False, sort_keys=True), length=16),
    )
    return overrides, meta
