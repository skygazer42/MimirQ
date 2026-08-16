
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from app.rag.retrieval.hybrid.common import _apply_metadata_exact_anchor_to_result, _float_or_default
from app.rag.retrieval.hybrid.vector_normalizer import normalize_vector_channel_results


@dataclass(frozen=True)
class HybridChannelResults:
    vector_results: list[dict[str, Any]]
    bm25_results: list[dict[str, Any]]
    lexical_results: list[dict[str, Any]]
    sparse_results: list[dict[str, Any]]
    metadata_exact_pre_fusion_stats: dict[str, Any]


def prepare_hybrid_channel_results(
    *,
    query: str,
    vector_results: list[dict[str, Any]],
    bm25_results: list[dict[str, Any]],
    lexical_results: list[dict[str, Any]],
    sparse_results: list[dict[str, Any]],
    document_ids: list[Any] | None,
    vector_filter: dict[str, Any] | None,
    runtime_shards_present: bool,
    chunk_id_lookup: Mapping[str, str] | None,
    match_metadata_filter: Callable[[dict[str, Any], dict[str, Any]], bool],
    metadata_exact_pre_fusion_enabled: bool,
    phrase_boost_weight: float,
) -> HybridChannelResults:
    normalized_vector_results = normalize_vector_channel_results(
        vector_results,
        document_ids=document_ids,
        vector_filter=vector_filter,
        runtime_shards_present=runtime_shards_present,
        chunk_id_lookup=chunk_id_lookup,
        match_metadata_filter=match_metadata_filter,
    )

    metadata_exact_pre_fusion_stats: dict[str, Any] = {
        "enabled": bool(metadata_exact_pre_fusion_enabled),
        "annotated": 0,
        "promoted": 0,
    }
    if metadata_exact_pre_fusion_enabled and query:
        for channel_name, channel_items in (
            ("vector", normalized_vector_results),
            ("bm25", bm25_results),
            ("lexical", lexical_results),
            ("sparse", sparse_results),
        ):
            channel_annotated = 0
            channel_promoted = 0
            for item in channel_items or []:
                if not isinstance(item, dict):
                    continue
                before = _float_or_default(item.get("score"), 0.0)
                if _apply_metadata_exact_anchor_to_result(
                    query=query,
                    result=item,
                    phrase_boost_weight=phrase_boost_weight,
                    promote_score=True,
                ):
                    channel_annotated += 1
                    after = _float_or_default(item.get("score"), 0.0)
                    if after > before:
                        channel_promoted += 1
            if channel_annotated:
                metadata_exact_pre_fusion_stats[channel_name] = {
                    "annotated": int(channel_annotated),
                    "promoted": int(channel_promoted),
                }
                metadata_exact_pre_fusion_stats["annotated"] = int(
                    metadata_exact_pre_fusion_stats.get("annotated", 0) or 0
                ) + int(channel_annotated)
                metadata_exact_pre_fusion_stats["promoted"] = int(
                    metadata_exact_pre_fusion_stats.get("promoted", 0) or 0
                ) + int(channel_promoted)

    return HybridChannelResults(
        vector_results=normalized_vector_results,
        bm25_results=bm25_results,
        lexical_results=lexical_results,
        sparse_results=sparse_results,
        metadata_exact_pre_fusion_stats=metadata_exact_pre_fusion_stats,
    )
