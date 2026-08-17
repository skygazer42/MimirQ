"""Focused support types and helpers for ``app.rag.retriever``."""

from dataclasses import asdict, dataclass, replace
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from app.core.config import settings
from app.rag.core.hashing import stable_json_hash

if TYPE_CHECKING:
    from app.rag.retriever import HybridRetriever


def _dataset_scoped_runtime_lookup_error(
    *,
    tenant_id: UUID | None,
    dataset_ids: tuple[UUID, ...] = (),
    document_ids: list[UUID] | None = None,
    reason: str = "unavailable",
) -> LookupError:
    detail = reason.strip() or "unavailable"
    return LookupError(
        "dataset-scoped embedding runtime "
        f"{detail} (tenant_id={tenant_id}, dataset_ids={len(dataset_ids)}, document_ids={len(document_ids or [])})"
    )


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
    return cast(HybridSearchOptions, replace(options, **legacy_overrides))


def _build_retrieval_cache_behavior_hash(
    *,
    retriever: "HybridRetriever",
    options: HybridSearchOptions,
) -> str:
    option_values = asdict(options)
    if options.document_ids:
        option_values["document_ids"] = sorted({str(document_id) for document_id in options.document_ids})
    prefixes = ("BM25_", "COLBERT_", "COLPALI_", "LEXICAL_", "RERANK", "RETRIEVAL_", "SPARSE_")
    runtime = {
        key: value
        for key, value in settings.model_dump(mode="json").items()
        if key.startswith(prefixes) or key == "VECTOR_BACKEND"
    }
    return stable_json_hash(
        {"options": option_values, "retriever": retriever.model_dump(mode="json"), "runtime": runtime},
        length=24,
    )


def _is_dataset_scope_condition(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, dict):
        if "$eq" in value:
            return bool(str(value.get("$eq") or "").strip())
        if "$in" in value:
            items = value.get("$in")
            return isinstance(items, list | tuple | set) and any(str(item or "").strip() for item in items)
        return False
    if isinstance(value, list | tuple | set):
        return any(str(item or "").strip() for item in value)
    return bool(str(value or "").strip())


def _metadata_filter_has_dataset_scope(metadata_filter: dict[str, Any] | None) -> bool:
    if not isinstance(metadata_filter, dict) or not metadata_filter:
        return False
    if _is_dataset_scope_condition(metadata_filter.get("dataset_id")):
        return True

    and_parts = metadata_filter.get("$and")
    if isinstance(and_parts, list):
        return any(_metadata_filter_has_dataset_scope(part) for part in and_parts if isinstance(part, dict))

    or_parts = metadata_filter.get("$or")
    if isinstance(or_parts, list) and or_parts:
        scoped_parts = [_metadata_filter_has_dataset_scope(part) for part in or_parts if isinstance(part, dict)]
        return bool(scoped_parts) and all(scoped_parts)

    return False


__all__ = [
    "HybridSearchOptions",
    "_build_retrieval_cache_behavior_hash",
    "_dataset_scoped_runtime_lookup_error",
    "_metadata_filter_has_dataset_scope",
    "_resolve_hybrid_search_options",
]
