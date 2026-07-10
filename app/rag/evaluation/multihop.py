"""
Deterministic multi-hop citation chain evaluation helpers.
"""


from typing import Any


def _coerce_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return dict(value)
    return {}


def _extract_chain_ids(evidence_chain: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in (evidence_chain or []):
        row = _coerce_dict(item)
        cid = str(row.get("chunk_id") or "").strip()
        if not cid:
            continue
        if cid in seen:
            continue
        seen.add(cid)
        out.append(cid)
    return out


def _extract_citation_rank_map(citations: Any, *, top_k: int = 20) -> dict[str, int]:
    rows: dict[str, int] = {}
    k = max(1, int(top_k or 1))
    rank = 0
    for item in (citations or []):
        row = _coerce_dict(item)
        cid = str(row.get("chunk_id") or "").strip()
        if not cid:
            continue
        if cid in rows:
            continue
        rank += 1
        rows[cid] = rank
        if rank >= k:
            break
    return rows


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
    expected_chain = _extract_chain_ids(evidence_chain)
    rank_map = _extract_citation_rank_map(citations, top_k=top_k)
    hop_count = len([str(x) for x in (reasoning_hops or []) if str(x or "").strip()])

    if not expected_chain:
        return {
            "schema": "mimirq.multihop_chain_score.v1",
            "enabled": False,
            "reasoning_hops_count": int(hop_count),
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
    matched_positions: list[tuple[int, int]] = []
    for expected_idx, cid in enumerate(expected_chain):
        rank = rank_map.get(cid)
        if rank is None:
            missing_chain_ids.append(cid)
            continue
        matched_chain_ids.append(cid)
        matched_positions.append((expected_idx, rank))

    expected_steps = int(len(expected_chain))
    matched_steps = int(len(matched_chain_ids))
    completeness = round(float(matched_steps) / float(max(1, expected_steps)), 4)

    # Pairwise order consistency on matched chain steps.
    total_pairs = 0
    consistent_pairs = 0
    for i in range(len(matched_positions)):
        for j in range(i + 1, len(matched_positions)):
            total_pairs += 1
            _exp_i, rank_i = matched_positions[i]
            _exp_j, rank_j = matched_positions[j]
            if rank_i < rank_j:
                consistent_pairs += 1

    if matched_steps <= 1:
        order_consistency = 1.0 if matched_steps == expected_steps else 0.0
    else:
        order_consistency = float(consistent_pairs) / float(max(1, total_pairs))
    order_consistency = round(float(order_consistency), 4)

    return {
        "schema": "mimirq.multihop_chain_score.v1",
        "enabled": True,
        "reasoning_hops_count": int(hop_count),
        "expected_chain_steps": expected_steps,
        "matched_chain_steps": matched_steps,
        "path_completeness": completeness,
        "order_consistency": order_consistency,
        "chain_hit": bool(matched_steps == expected_steps and expected_steps > 0),
        "missing_chain_ids": missing_chain_ids[:20],
        "matched_chain_ids": matched_chain_ids[:20],
    }


__all__ = ["score_multihop_citation_chain"]
