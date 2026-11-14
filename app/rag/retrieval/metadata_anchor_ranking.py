"""Rank constructed metadata anchors shared by candidate and document ordering."""

from typing import Any, TypedDict


class MetadataAnchor(TypedDict):
    field: str
    value: str
    score: float
    norm: str


def rank_metadata_anchor_matches(matches: list[MetadataAnchor]) -> dict[str, Any]:
    if not matches:
        return {}

    # Keep the longest alias per field before combining independent anchors.
    filtered: list[MetadataAnchor] = []
    seen_norms: set[str] = set()
    for item in sorted(matches, key=lambda x: (-len(x["norm"]), -x["score"])):
        field = item["field"]
        norm = item["norm"]
        if any(kept["field"] == field and norm in kept["norm"] for kept in filtered):
            continue
        if norm in seen_norms:
            continue
        seen_norms.add(norm)
        filtered.append(item)

    ranked = sorted(
        filtered,
        key=lambda x: (-x["score"], -len(x["norm"]), x["field"]),
    )
    primary = ranked[0]
    aggregate = primary["score"]
    aggregate += 0.5 * sum(item["score"] for item in ranked[1:])
    aggregate = min(1.0, aggregate)

    fields = list(dict.fromkeys(item["field"] for item in ranked if item["field"]))
    values = [item["value"] for item in ranked if item["value"]]
    return {
        "field": primary["field"],
        "value": primary["value"],
        "score": round(aggregate, 6),
        "primary_score": round(primary["score"], 6),
        "fields": fields[:8],
        "values": values[:8],
    }
