"""Deterministic metadata-anchor ordering shared by candidate and evidence stages."""

from collections.abc import Callable
from typing import Any

from app.core.config import settings
from app.rag.retrieval.hybrid.common import _apply_metadata_exact_anchor_to_result, _float_or_default
from app.rag.retrieval.hybrid.result_values import result_key


def order_metadata_anchors(
    query: str, results: list[dict[str, Any]], *, stats: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    if not query or not results:
        if stats is not None:
            stats["applied"] = False
            stats["reason"] = "empty"
        return results
    phrase_boost_weight = max(0.0, float(settings.RETRIEVAL_EXACT_PHRASE_RERANK_BOOST or 0.0))
    annotated, annotated_count, promoted_count = _annotated_metadata_anchor_results(
        query=query, results=results, phrase_boost_weight=phrase_boost_weight
    )
    if annotated_count <= 0:
        if stats is not None:
            stats["applied"] = False
            stats["annotated"] = 0
        return results
    before_top = result_key(annotated[0][0]) if annotated else ""
    annotated.sort(key=_metadata_anchor_sort_key_factory(annotated, result_count=len(results)))
    ordered = [item for item, _pos in annotated]
    after_top = result_key(ordered[0]) if ordered else ""
    if stats is not None:
        stats["applied"] = True
        stats["annotated"] = annotated_count
        stats["score_promoted"] = promoted_count
        stats["top_changed"] = bool(before_top and after_top and (before_top != after_top))
    return ordered


def _annotated_metadata_anchor_results(
    *, query: str, results: list[dict[str, Any]], phrase_boost_weight: float
) -> tuple[list[tuple[dict[str, Any], int]], int, int]:
    annotated: list[tuple[dict[str, Any], int]] = []
    annotated_count = 0
    promoted_count = 0
    for pos, result in enumerate(results):
        item = dict(result)
        changed = _apply_metadata_exact_anchor_to_result(
            query=query, result=item, phrase_boost_weight=phrase_boost_weight, promote_score=True
        )
        if changed:
            annotated_count += 1
            if item.get("metadata_exact_match_promoted_score") is not None:
                promoted_count += 1
        else:
            item = result
        annotated.append((item, pos))
    return (annotated, annotated_count, promoted_count)


def _metadata_anchor_sort_key_factory(
    annotated: list[tuple[dict[str, Any], int]], *, result_count: int
) -> Callable[[tuple[dict[str, Any], int]], tuple[float, float, int]]:
    has_budgeted_prefix = any((result.get("fusion_budgeted_prefix_rank") is not None for result, _pos in annotated))
    best_anchor_score = max(
        (_float_or_default(item.get("metadata_exact_match_score"), 0.0) for item, _pos in annotated)
    )

    def sort_key(pair: tuple[dict[str, Any], int]) -> tuple[float, float, int]:
        item, pos = pair
        if has_budgeted_prefix:
            try:
                prefix_rank = int(item.get("fusion_budgeted_prefix_rank"))
            except (TypeError, ValueError):
                prefix_rank = result_count + pos + 1
            return (float(prefix_rank), -_float_or_default(item.get("metadata_exact_match_score"), 0.0), pos)
        if best_anchor_score >= 0.65:
            return (
                -_float_or_default(item.get("metadata_exact_match_score"), 0.0),
                -_float_or_default(item.get("score"), 0.0),
                pos,
            )
        return (
            -_float_or_default(item.get("score"), 0.0),
            -_float_or_default(item.get("metadata_exact_match_score"), 0.0),
            pos,
        )

    return sort_key
