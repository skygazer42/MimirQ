"""
Retrieval profile introspection endpoint.

Goal:
- expose stable, reproducible profile definitions for operators/contributors
- avoid leaking scope/query/internal request fields
"""


import json
from typing import Any

from fastapi import APIRouter, Depends

from app.api.dependencies.auth import get_current_account_id
from app.core.config import settings
from app.rag.core.hashing import stable_hash
from app.rag.core.retrieval_profiles import (
    PRODUCTION_RETRIEVAL_PROFILE,
    RECALL_FIRST_RETRIEVAL_PROFILES,
    SUPPORTED_RETRIEVAL_PROFILES,
    apply_retrieval_profile_overrides,
)

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
    dependencies=[Depends(get_current_account_id)],
)

_SCHEMA = "mimirq.retrieval_profiles.v1"


def _runtime_baseline() -> dict[str, Any]:
    return {
        "top_k": int(getattr(settings, "RETRIEVAL_TOP_K", 5) or 5),
        "score_threshold": float(getattr(settings, "SIMILARITY_THRESHOLD", 0.0) or 0.0),
        "retrieval_mode": settings.RETRIEVAL_MODE,
        "enable_reranker": bool(getattr(settings, "ENABLE_RERANKER", False)),
        "reranker_provider": str(getattr(settings, "RERANKER_PROVIDER", "llm") or "llm"),
        "reranker_top_n": int(getattr(settings, "RERANKER_TOP_N", 20) or 20),
        "enable_weight_rerank": True,
        "sparse_retrieval_enabled": bool(getattr(settings, "SPARSE_RETRIEVAL_ENABLED", False)),
        "sparse_retrieval_provider": str(getattr(settings, "SPARSE_RETRIEVAL_PROVIDER", "") or "").strip() or None,
        "retrieval_contract_mode": None,
        "visible_evidence_only": False,
    }


def _public_profile_definition(name: str, *, baseline: dict[str, Any]) -> dict[str, Any]:
    applied = apply_retrieval_profile_overrides(
        profile=name,
        top_k=int(baseline.get("top_k") or 0),
        score_threshold=float(baseline.get("score_threshold") or 0.0),
        retrieval_mode=str(baseline.get("retrieval_mode") or "hybrid"),
        enable_reranker=bool(baseline.get("enable_reranker")),
        reranker_provider=str(baseline.get("reranker_provider") or ""),
        reranker_top_n=int(baseline.get("reranker_top_n") or 0),
        enable_weight_rerank=bool(baseline.get("enable_weight_rerank", True)),
        retrieval_contract_mode=(
            str(baseline.get("retrieval_contract_mode") or "").strip().lower() or None
        ),
        visible_evidence_only=bool(baseline.get("visible_evidence_only", False)),
    )
    return {
        "name": str(applied.get("retrieval_profile") or name),
        "is_recall_first": bool(name in RECALL_FIRST_RETRIEVAL_PROFILES),
        "retrieval_mode": str(applied.get("retrieval_mode") or baseline.get("retrieval_mode") or "hybrid"),
        "top_k": int(applied.get("top_k") or 0),
        "score_threshold": float(applied.get("score_threshold") or 0.0),
        "enable_reranker": bool(applied.get("enable_reranker") if applied.get("enable_reranker") is not None else False),
        "reranker_provider": (
            str(applied.get("reranker_provider") or "")
            if bool(applied.get("enable_reranker"))
            else None
        ),
        "reranker_top_n": (
            int(applied.get("reranker_top_n") or 0)
            if bool(applied.get("enable_reranker"))
            else 0
        ),
        "enable_weight_rerank": bool(applied.get("enable_weight_rerank", True)),
        "sparse_retrieval_enabled": bool(applied.get("sparse_retrieval_enabled", baseline.get("sparse_retrieval_enabled", False))),
        "sparse_retrieval_provider": (
            str(applied.get("sparse_retrieval_provider") or baseline.get("sparse_retrieval_provider") or "").strip()
            or None
        ),
        "retrieval_contract_mode": (
            str(applied.get("retrieval_contract_mode") or "").strip().lower() or None
        ),
        "visible_evidence_only": bool(applied.get("visible_evidence_only", False)),
    }


@router.get("/profiles", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_retrieval_profiles() -> dict[str, Any]:
    baseline = _runtime_baseline()
    chat_default_profile = str(getattr(settings, "CHAT_DEFAULT_RETRIEVAL_PROFILE", "") or "").strip().lower() or None
    request_defaults = apply_retrieval_profile_overrides(
        profile=None,
        top_k=int(baseline.get("top_k") or 0),
        score_threshold=float(baseline.get("score_threshold") or 0.0),
        retrieval_mode=str(baseline.get("retrieval_mode") or "hybrid"),
        enable_reranker=bool(baseline.get("enable_reranker")),
        reranker_provider=str(baseline.get("reranker_provider") or ""),
        reranker_top_n=int(baseline.get("reranker_top_n") or 0),
        enable_weight_rerank=bool(baseline.get("enable_weight_rerank", True)),
        retrieval_contract_mode=(
            str(baseline.get("retrieval_contract_mode") or "").strip().lower() or None
        ),
        visible_evidence_only=bool(baseline.get("visible_evidence_only", False)),
    )
    chat_default_effective = apply_retrieval_profile_overrides(
        profile=chat_default_profile,
        top_k=int(baseline.get("top_k") or 0),
        score_threshold=float(baseline.get("score_threshold") or 0.0),
        retrieval_mode=str(baseline.get("retrieval_mode") or "hybrid"),
        enable_reranker=bool(baseline.get("enable_reranker")),
        reranker_provider=str(baseline.get("reranker_provider") or ""),
        reranker_top_n=int(baseline.get("reranker_top_n") or 0),
        enable_weight_rerank=bool(baseline.get("enable_weight_rerank", True)),
        retrieval_contract_mode=(
            str(baseline.get("retrieval_contract_mode") or "").strip().lower() or None
        ),
        visible_evidence_only=bool(baseline.get("visible_evidence_only", False)),
    )
    production_effective = apply_retrieval_profile_overrides(
        profile=PRODUCTION_RETRIEVAL_PROFILE,
        top_k=int(baseline.get("top_k") or 0),
        score_threshold=float(baseline.get("score_threshold") or 0.0),
        retrieval_mode=str(baseline.get("retrieval_mode") or "hybrid"),
        enable_reranker=bool(baseline.get("enable_reranker")),
        reranker_provider=str(baseline.get("reranker_provider") or ""),
        reranker_top_n=int(baseline.get("reranker_top_n") or 0),
        enable_weight_rerank=bool(baseline.get("enable_weight_rerank", True)),
        retrieval_contract_mode=(
            str(baseline.get("retrieval_contract_mode") or "").strip().lower() or None
        ),
        visible_evidence_only=bool(baseline.get("visible_evidence_only", False)),
    )

    ordered_profiles = sorted({str(p) for p in SUPPORTED_RETRIEVAL_PROFILES})
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
    payload["version_hash"] = stable_hash(payload_for_hash, length=24)
    return payload


__all__ = ["router", "get_retrieval_profiles"]
