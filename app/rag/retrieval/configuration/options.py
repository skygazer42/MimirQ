"""Per-call hybrid search parameters and rerank search limits."""

from dataclasses import dataclass, replace
from typing import Any
from uuid import UUID

from app.infrastructure.config import settings


def normalize_rerank_profile(name: str | None) -> str | None:
    if name is None:
        return None
    return name.strip().lower() or None


def resolve_rerank_search_k(*, requested_k: int, profile: str | None) -> int:
    minimum = 20 if normalize_rerank_profile(profile) == "sweet_spot" else 1
    return max(minimum, requested_k)


@dataclass(frozen=True)
class HybridSearchOptions:
    top_k: int = 5
    score_threshold: float = 0.7
    document_ids: list[UUID] | None = None
    tenant_id: UUID | None = None
    alpha: float = settings.RETRIEVAL_DEFAULT_ALPHA
    enable_weight_rerank: bool = True
    vector_weight: float = 0.6
    keyword_weight: float = 0.4
    retrieval_mode: str = "hybrid"
    mmr_lambda: float = 0.7
    mmr_fetch_k_multiplier: int = 4
    metadata_filter: dict[str, Any] | None = None
    entity_key: str | None = None
    partition_keys: list[str] | None = None
    entity_candidates: list[str] | None = None
    requested_k: int | None = None


def _resolve_hybrid_search_options(
    *,
    options: HybridSearchOptions | None,
    legacy_overrides: dict[str, Any],
) -> HybridSearchOptions:
    if options is None:
        return HybridSearchOptions(**legacy_overrides)
    if not legacy_overrides:
        return options
    return replace(options, **legacy_overrides)


__all__ = [
    "HybridSearchOptions",
    "_resolve_hybrid_search_options",
]
