from typing import Any


def _stable_unique(values: list[str]) -> list[str]:
    return sorted({v.strip() for v in (values or []) if v.strip()})


def build_lazy_index_plan(
    *,
    hit_community_ids: list[str],
    indexed_community_ids: list[str],
    max_new_communities: int = 3,
) -> dict[str, Any]:
    hit = _stable_unique(list(hit_community_ids or []))
    indexed = set(_stable_unique(list(indexed_community_ids or [])))
    limit = max(0, int(max_new_communities or 0))

    deferred = [community_id for community_id in hit if community_id not in indexed]
    if limit > 0:
        deferred = deferred[:limit]

    reason_codes = ["build_missing_hit_communities"] if deferred else ["all_hit_communities_indexed"]
    return {
        "schema": "mimirq.kg_lazy_index_plan.v1",
        "hit_communities": hit,
        "indexed_communities": sorted(indexed),
        "deferred_communities": deferred,
        "reason_codes": reason_codes,
    }


__all__ = ["build_lazy_index_plan"]
