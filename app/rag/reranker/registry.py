"""Static reranker provider registry.

The registry is data-only: it describes provider families, aliases, and lazy
import targets without importing provider implementations.
"""


from dataclasses import dataclass


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
        canonical_name="cross_encoder",
        aliases=("cross_encoder", "cross-encoder", "sentence_transformers", "sentence-transformers"),
        tier="prod",
        category="local",
        lazy_modules=("app.rag.reranker.cross_encoder",),
    ),
    RerankerProviderFamily(
        canonical_name="long_context",
        aliases=("long_context",),
        tier="prod",
        category="local",
        lazy_modules=("app.rag.reranker.long_context_rerank",),
    ),
    RerankerProviderFamily(
        canonical_name="mmr",
        aliases=("mmr",),
        tier="prod",
        category="local",
        lazy_modules=("app.rag.reranker.mmr",),
    ),
    RerankerProviderFamily(
        canonical_name="local_bge_v2_m3",
        aliases=("local_bge_v2_m3", "bge_v2_m3"),
        tier="prod",
        category="local",
        lazy_modules=("app.rag.reranker.local_bge_v2_m3",),
    ),
    RerankerProviderFamily(
        canonical_name="ltr",
        aliases=("ltr", "xgboost_ltr"),
        tier="prod",
        category="local",
        lazy_modules=("app.rag.reranker.ltr",),
    ),
    RerankerProviderFamily(
        canonical_name="weighted",
        aliases=("weighted",),
        tier="prod",
        category="document",
        lazy_modules=("app.rag.reranker.hybrid",),
    ),
    RerankerProviderFamily(
        canonical_name="parent_child",
        aliases=("parent_child", "pc"),
        tier="prod",
        category="document",
        lazy_modules=("app.rag.reranker.parent_child",),
    ),
    RerankerProviderFamily(
        canonical_name="kg_pagerank",
        aliases=("kg_pagerank",),
        tier="prod",
        category="graph",
        lazy_modules=("app.rag.reranker.kg", "app.rag.kg.search.config"),
    ),
    RerankerProviderFamily(
        canonical_name="kg_rrf",
        aliases=("kg_rrf",),
        tier="prod",
        category="graph",
        lazy_modules=("app.rag.reranker.kg", "app.rag.kg.search.config"),
    ),
    RerankerProviderFamily(
        canonical_name="llm",
        aliases=("llm",),
        tier="experimental",
        category="document",
        lazy_modules=("app.rag.reranker.llm_based",),
    ),
    RerankerProviderFamily(
        canonical_name="openai",
        aliases=("openai",),
        tier="experimental",
        category="api",
        lazy_modules=("app.rag.reranker.openai",),
    ),
    RerankerProviderFamily(
        canonical_name="dashscope",
        aliases=("dashscope", "aliyun"),
        tier="experimental",
        category="api",
        lazy_modules=("app.rag.reranker.dashscope",),
    ),
    RerankerProviderFamily(
        canonical_name="colbert",
        aliases=("colbert", "late_interaction"),
        tier="experimental",
        category="late_interaction",
        lazy_modules=("app.rag.reranker.colbert",),
    ),
)

_FAMILY_BY_ALIAS = {
    alias: family
    for family in _FAMILIES
    for alias in family.aliases
}


def get_reranker_provider_family(provider: str | None) -> RerankerProviderFamily | None:
    normalized = str(provider or "").strip().lower()
    if not normalized:
        return None
    return _FAMILY_BY_ALIAS.get(normalized)


def iter_reranker_provider_families() -> tuple[RerankerProviderFamily, ...]:
    return _FAMILIES


def list_registered_reranker_providers() -> list[str]:
    return [family.canonical_name for family in _FAMILIES]
