"""Provider metadata and capabilities without importing reranker implementations."""

from dataclasses import dataclass
from typing import Any, NotRequired, TypedDict


@dataclass(frozen=True)
class RerankerProviderFamily:
    canonical_name: str
    aliases: tuple[str, ...]
    tier: str
    category: str
    lazy_modules: tuple[str, ...]


_FAMILIES: tuple[RerankerProviderFamily, ...] = (
    RerankerProviderFamily(
        canonical_name="none",
        aliases=("none", "off", "false", "0"),
        tier="disabled",
        category="disabled",
        lazy_modules=(),
    ),
    RerankerProviderFamily(
        canonical_name="long_context",
        aliases=("long_context",),
        tier="prod",
        category="local",
        lazy_modules=("app.rag.retrieval.reranking.long_context",),
    ),
    RerankerProviderFamily(
        canonical_name="mmr",
        aliases=("mmr",),
        tier="prod",
        category="local",
        lazy_modules=("app.rag.retrieval.reranking.mmr",),
    ),
    RerankerProviderFamily(
        canonical_name="weighted",
        aliases=("weighted",),
        tier="prod",
        category="document",
        lazy_modules=("app.rag.retrieval.reranking.weighted",),
    ),
    RerankerProviderFamily(
        canonical_name="parent_child",
        aliases=("parent_child", "pc"),
        tier="prod",
        category="document",
        lazy_modules=("app.rag.retrieval.reranking.parent_child",),
    ),
    RerankerProviderFamily(
        canonical_name="kg_pagerank",
        aliases=("kg_pagerank",),
        tier="prod",
        category="graph",
        lazy_modules=("app.rag.retrieval.reranking.kg", "app.rag.kg.search.config"),
    ),
    RerankerProviderFamily(
        canonical_name="kg_rrf",
        aliases=("kg_rrf",),
        tier="prod",
        category="graph",
        lazy_modules=("app.rag.retrieval.reranking.kg", "app.rag.kg.search.config"),
    ),
    RerankerProviderFamily(
        canonical_name="llm",
        aliases=("llm",),
        tier="experimental",
        category="document",
        lazy_modules=("app.rag.retrieval.reranking.llm",),
    ),
    RerankerProviderFamily(
        canonical_name="openai",
        aliases=("openai",),
        tier="experimental",
        category="api",
        lazy_modules=("app.rag.retrieval.reranking.api",),
    ),
    RerankerProviderFamily(
        canonical_name="dashscope",
        aliases=("dashscope", "aliyun"),
        tier="experimental",
        category="api",
        lazy_modules=("app.rag.retrieval.reranking.api",),
    ),
)

_FAMILY_BY_ALIAS = {alias: family for family in _FAMILIES for alias in family.aliases}


def get_reranker_provider_family(provider: str | None) -> RerankerProviderFamily | None:
    normalized = provider.strip().lower() if provider is not None else ""
    if not normalized:
        return None
    return _FAMILY_BY_ALIAS.get(normalized)


def iter_reranker_provider_families() -> tuple[RerankerProviderFamily, ...]:
    return _FAMILIES


def list_registered_reranker_providers() -> list[str]:
    return [family.canonical_name for family in _FAMILIES]


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
    normalized = (provider.strip().lower() if provider is not None else "") or "openai"
    if normalized in {"colbert", "late_interaction"}:
        return {"provider": "colbert", "tier": "retired"}
    family = get_reranker_provider_family(normalized)

    if family is None:
        return {"provider": normalized, "tier": "experimental"}

    if family.canonical_name == "none":
        return {"provider": "none", "tier": "disabled"}

    if family.canonical_name in {"long_context", "mmr"}:
        return {"provider": family.canonical_name, "tier": family.tier}
    return {"provider": normalized, "tier": family.tier}


def get_reranker_capabilities(provider: str | None, **kwargs: Any) -> RerankerCapabilities:
    normalized = (provider.strip().lower() if provider is not None else "") or "openai"
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
