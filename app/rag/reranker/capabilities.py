"""Capability discovery for reranker providers."""


from typing import Any

from app.core.config import settings
from app.rag.reranker.registry import (
    get_reranker_provider_family,
    iter_reranker_provider_families,
)


def describe_reranker_provider(provider: str | None, **kwargs: Any) -> dict[str, Any]:
    normalized = str(provider or "").strip().lower() or "openai"
    provider_name = str(kwargs.get("provider_name") or "").strip().lower() or None
    family = get_reranker_provider_family(normalized)

    if family is None:
        return {"provider": normalized, "tier": "experimental"}

    if family.canonical_name == "none":
        return {"provider": "none", "tier": "disabled"}

    if family.canonical_name == "cross_encoder":
        return {"provider": "cross_encoder", "tier": family.tier}
    if family.canonical_name == "ltr":
        return {"provider": "ltr", "tier": family.tier}
    if family.canonical_name == "local_bge_v2_m3":
        return {"provider": "local_bge_v2_m3", "tier": family.tier}
    if family.canonical_name == "colbert":
        mode = provider_name or str(getattr(settings, "COLBERT_RERANK_PROVIDER", "deterministic") or "deterministic").strip().lower()
        if mode == "deterministic":
            return {"provider": "colbert", "tier": "offline_only", "mode": "deterministic"}
        return {"provider": "colbert", "tier": family.tier, "mode": mode}

    if family.canonical_name in {"long_context", "mmr"}:
        return {"provider": family.canonical_name, "tier": family.tier}

    if family.canonical_name in {"weighted", "parent_child", "kg_pagerank", "kg_rrf", "llm", "openai", "dashscope"}:
        return {"provider": normalized, "tier": family.tier}

    return {"provider": normalized, "tier": family.tier}


def get_reranker_capabilities(provider: str | None, **kwargs: Any) -> dict[str, Any]:
    normalized = str(provider or "").strip().lower() or "openai"
    family = get_reranker_provider_family(normalized)
    summary = describe_reranker_provider(normalized, **kwargs)
    if family is None:
        return {
            "requested_provider": normalized,
            "resolved_provider": None,
            "aliases": [],
            "tier": str(summary.get("tier") or "experimental"),
            "category": "unknown",
            "lazy_modules": [],
        }
    return {
        "requested_provider": normalized,
        "resolved_provider": family.canonical_name,
        "aliases": list(family.aliases),
        "tier": str(summary.get("tier") or family.tier),
        "category": family.category,
        "lazy_modules": list(family.lazy_modules),
        **({"mode": summary["mode"]} if "mode" in summary else {}),
    }


def list_reranker_capabilities() -> list[dict[str, Any]]:
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
