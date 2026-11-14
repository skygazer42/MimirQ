"""
Retrieval profile introspection endpoint.

Goal:
- expose stable, reproducible profile definitions for operators/contributors
- avoid leaking scope/query/internal request fields
"""

import json
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies import get_current_account_id
from app.api.utils import DEFAULT_HTTP_EXCEPTION_RESPONSES as _DEFAULT_HTTP_EXCEPTION_RESPONSES
from app.core.config import settings
from app.rag.core.hashing import stable_hash
from app.rag.core.retrieval_profiles import (
    PRODUCTION_RETRIEVAL_PROFILE,
    RECALL_FIRST_RETRIEVAL_PROFILES,
    SUPPORTED_RETRIEVAL_PROFILES,
    apply_retrieval_profile_overrides,
    normalize_retrieval_profile,
)

router = APIRouter(
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
    dependencies=[Depends(get_current_account_id)],
)

_SCHEMA = "mimirq.retrieval_profiles.v1"


class RetrievalProfileDefinition(BaseModel):
    name: str
    is_recall_first: bool
    retrieval_mode: str | None
    top_k: int
    score_threshold: float
    enable_reranker: bool
    reranker_provider: str | None
    reranker_top_n: int
    enable_weight_rerank: bool
    sparse_retrieval_enabled: bool
    sparse_retrieval_provider: str
    retrieval_contract_mode: str | None
    visible_evidence_only: bool


class RetrievalProfileDefaults(BaseModel):
    production_profile: str
    chat_default_profile: str | None
    request_defaults: dict[str, Any]
    chat_default_effective: dict[str, Any]
    production_effective: dict[str, Any]
    runtime_defaults: dict[str, Any]


class RetrievalProfilesResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_: str = Field(alias="schema", serialization_alias="schema")
    effective_defaults: RetrievalProfileDefaults
    profiles: list[RetrievalProfileDefinition]
    version_hash: str


def _runtime_baseline() -> dict[str, Any]:
    return {
        "top_k": settings.RETRIEVAL_TOP_K,
        "score_threshold": settings.SIMILARITY_THRESHOLD,
        "retrieval_mode": settings.RETRIEVAL_MODE,
        "enable_reranker": settings.ENABLE_RERANKER,
        "reranker_provider": settings.RERANKER_PROVIDER,
        "reranker_top_n": settings.RERANKER_TOP_N,
        "enable_weight_rerank": True,
        "sparse_retrieval_enabled": settings.SPARSE_RETRIEVAL_ENABLED,
        "sparse_retrieval_provider": settings.SPARSE_RETRIEVAL_PROVIDER,
        "retrieval_contract_mode": None,
        "visible_evidence_only": False,
    }


def _effective_profile(profile: str | None, *, baseline: dict[str, Any]) -> dict[str, Any]:
    return apply_retrieval_profile_overrides(
        profile=profile,
        top_k=baseline["top_k"],
        score_threshold=baseline["score_threshold"],
        retrieval_mode=baseline["retrieval_mode"],
        enable_reranker=baseline["enable_reranker"],
        reranker_provider=baseline["reranker_provider"],
        reranker_top_n=baseline["reranker_top_n"],
        enable_weight_rerank=baseline["enable_weight_rerank"],
        retrieval_contract_mode=baseline["retrieval_contract_mode"],
        visible_evidence_only=baseline["visible_evidence_only"],
    )


def _public_profile_definition(name: str, *, baseline: dict[str, Any]) -> dict[str, Any]:
    applied = _effective_profile(name, baseline=baseline)
    return {
        "name": applied["retrieval_profile"],
        "is_recall_first": name in RECALL_FIRST_RETRIEVAL_PROFILES,
        "retrieval_mode": applied["retrieval_mode"],
        "top_k": applied["top_k"],
        "score_threshold": applied["score_threshold"],
        "enable_reranker": applied["enable_reranker"],
        "reranker_provider": applied["reranker_provider"] if applied["enable_reranker"] else None,
        "reranker_top_n": applied["reranker_top_n"] if applied["enable_reranker"] else 0,
        "enable_weight_rerank": applied["enable_weight_rerank"],
        "sparse_retrieval_enabled": applied.get("sparse_retrieval_enabled", baseline["sparse_retrieval_enabled"]),
        "sparse_retrieval_provider": applied.get("sparse_retrieval_provider", baseline["sparse_retrieval_provider"]),
        "retrieval_contract_mode": applied["retrieval_contract_mode"],
        "visible_evidence_only": applied["visible_evidence_only"],
    }


@router.get("/profiles")
def get_retrieval_profiles() -> RetrievalProfilesResponse:
    baseline = _runtime_baseline()
    chat_default_profile = normalize_retrieval_profile(settings.CHAT_DEFAULT_RETRIEVAL_PROFILE)
    request_defaults = _effective_profile(None, baseline=baseline)
    chat_default_effective = _effective_profile(chat_default_profile, baseline=baseline)
    production_effective = _effective_profile(PRODUCTION_RETRIEVAL_PROFILE, baseline=baseline)

    ordered_profiles = sorted(SUPPORTED_RETRIEVAL_PROFILES)
    profiles = [_public_profile_definition(name, baseline=baseline) for name in ordered_profiles]

    payload: dict[str, Any] = {
        "schema": _SCHEMA,
        "effective_defaults": {
            "production_profile": PRODUCTION_RETRIEVAL_PROFILE,
            "chat_default_profile": chat_default_profile,
            "request_defaults": request_defaults,
            "chat_default_effective": chat_default_effective,
            "production_effective": production_effective,
            "runtime_defaults": baseline,
        },
        "profiles": profiles,
    }
    payload_for_hash = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return RetrievalProfilesResponse.model_validate(
        {**payload, "version_hash": stable_hash(payload_for_hash, length=24)}
    )


__all__ = ["router", "get_retrieval_profiles"]
