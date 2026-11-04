"""Capability discovery for reranker providers."""

from typing import Any, NotRequired, TypedDict

from app.core.config import settings
from app.rag.reranker.registry import (
    get_reranker_provider_family,
    iter_reranker_provider_families,
)


class RerankerDescription(TypedDict):
    provider: str
    tier: str
    mode: NotRequired[str]


class RerankerCapabilities(TypedDict):
    requested_provider: NotRequired[str]
    resolved_provider: str | None
    aliases: list[str]
    tier: str
    category: str
    lazy_modules: list[str]
    mode: NotRequired[str]


def describe_reranker_provider(provider: str | None, **kwargs: Any) -> RerankerDescription:
    normalized = str(provider or "").strip().lower() or "openai"
    provider_name = str(kwargs.get("provider_name") or "").strip().lower() or None
    family = get_reranker_provider_family(normalized)

    if family is None:
        return {"provider": normalized, "tier": "experimental"}

    if family.canonical_name == "none":
        return {"provider": "none", "tier": "disabled"}

    if family.canonical_name in {"cross_encoder", "ltr", "local_bge_v2_m3", "long_context", "mmr"}:
        return {"provider": family.canonical_name, "tier": family.tier}
    if family.canonical_name == "colbert":
        mode = provider_name or (settings.COLBERT_RERANK_PROVIDER or "deterministic").strip().lower()
        if mode == "deterministic":
            return {"provider": "colbert", "tier": "offline_only", "mode": "deterministic"}
        return {"provider": "colbert", "tier": family.tier, "mode": mode}

    return {"provider": normalized, "tier": family.tier}


def get_reranker_capabilities(provider: str | None, **kwargs: Any) -> RerankerCapabilities:
    normalized = str(provider or "").strip().lower() or "openai"
    family = get_reranker_provider_family(normalized)
    summary = describe_reranker_provider(normalized, **kwargs)
    if family is None:
        return {
            "requested_provider": normalized,
            "resolved_provider": None,
            "aliases": [],
            "tier": summary["tier"],
            "category": "unknown",
            "lazy_modules": [],
        }
    return {
        "requested_provider": normalized,
        "resolved_provider": family.canonical_name,
        "aliases": list(family.aliases),
        "tier": summary["tier"],
        "category": family.category,
        "lazy_modules": list(family.lazy_modules),
        **({"mode": summary["mode"]} if "mode" in summary else {}),
    }


def list_reranker_capabilities() -> list[RerankerCapabilities]:
    return [
        {
            "resolved_provider": family.canonical_name,
            "aliases": list(family.aliases),
            "tier": family.tier,
            "category": family.category,
            "lazy_modules": list(family.lazy_modules),
        }
        for family in iter_reranker_provider_families()
    ]
