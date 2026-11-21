"""
Deterministic multi-hop citation chain evaluation helpers.
"""

from collections.abc import Iterator
from itertools import combinations
from typing import Any


def _coerce_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return dict(value)
    return {}


def _iter_chunk_ids(items: Any) -> Iterator[str]:
    seen: set[str] = set()
    for item in items or []:
        row = _coerce_dict(item)
        raw_id = row.get("chunk_id")
        if raw_id is None:
            continue
        cid = str(raw_id).strip()
        if not cid or cid in seen:
            continue
        seen.add(cid)
        yield cid


def _extract_citation_rank_map(citations: Any, *, top_k: int = 20) -> dict[str, int]:
    k = max(1, int(top_k or 1))
    ranks: dict[str, int] = {}
    for rank, cid in enumerate(_iter_chunk_ids(citations), 1):
        ranks[cid] = rank
        if rank >= k:
            break
    return ranks


def score_multihop_citation_chain(
    *,
    evidence_chain: list[dict[str, Any]] | None,
    citations: list[dict[str, Any]] | None,
    reasoning_hops: list[str] | None = None,
    top_k: int = 20,
) -> dict[str, Any]:
    """
    Score multi-hop citation quality against an expected evidence chain.

    Metrics:
    - path_completeness: expected chain steps found in top-k citations.
    - order_consistency: pairwise ordering correctness for matched chain steps.
    """
    expected_chain = list(_iter_chunk_ids(evidence_chain))
    rank_map = _extract_citation_rank_map(citations, top_k=top_k)
    hop_count = len([x for x in (reasoning_hops or []) if x.strip()])

    if not expected_chain:
        return {
            "schema": "mimirq.multihop_chain_score.v1",
            "enabled": False,
            "reasoning_hops_count": hop_count,
            "expected_chain_steps": 0,
            "matched_chain_steps": 0,
            "path_completeness": None,
            "order_consistency": None,
            "chain_hit": None,
            "missing_chain_ids": [],
            "matched_chain_ids": [],
        }

    matched_chain_ids: list[str] = []
    missing_chain_ids: list[str] = []
    matched_ranks: list[int] = []
    for cid in expected_chain:
        rank = rank_map.get(cid)
        if rank is None:
            missing_chain_ids.append(cid)
            continue
        matched_chain_ids.append(cid)
        matched_ranks.append(rank)

    expected_steps = len(expected_chain)
    matched_steps = len(matched_chain_ids)
    completeness = round(float(matched_steps) / float(max(1, expected_steps)), 4)

    if matched_steps <= 1:
        order_consistency = 1.0 if matched_steps == expected_steps else 0.0
    else:
        total_pairs = matched_steps * (matched_steps - 1) // 2
        consistent_pairs = sum(first < second for first, second in combinations(matched_ranks, 2))
        order_consistency = float(consistent_pairs) / float(total_pairs)
    order_consistency = round(order_consistency, 4)

    return {
        "schema": "mimirq.multihop_chain_score.v1",
        "enabled": True,
        "reasoning_hops_count": hop_count,
        "expected_chain_steps": expected_steps,
        "matched_chain_steps": matched_steps,
        "path_completeness": completeness,
        "order_consistency": order_consistency,
        "chain_hit": matched_steps == expected_steps,
        "missing_chain_ids": missing_chain_ids[:20],
        "matched_chain_ids": matched_chain_ids[:20],
    }


__all__ = ["score_multihop_citation_chain"]
