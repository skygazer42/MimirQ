
from collections import defaultdict
from typing import Any

from app.rag.preprocessing.simhash import hamming_distance64, simhash64


def build_simhash_review_candidates(
    rows: list[dict[str, Any]],
    *,
    hamming_threshold: int = 5,
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        path = str(row.get("path") or "").strip()
        text = str(row.get("text") or "").strip()
        if not path or not text:
            continue
        items.append(
            {
                "path": path,
                "text": text,
                "size_bytes": int(row.get("size_bytes") or 0),
                "mtime": int(row.get("mtime") or 0),
                "simhash64": simhash64(text),
            }
        )

    parent = list(range(len(items)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra = find(a)
        rb = find(b)
        if ra != rb:
            parent[rb] = ra

    pairs: list[dict[str, Any]] = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            distance = hamming_distance64(items[i]["simhash64"], items[j]["simhash64"])
            if distance <= int(hamming_threshold):
                pairs.append({"a": items[i]["path"], "b": items[j]["path"], "distance": int(distance)})
                union(i, j)

    groups: dict[int, list[int]] = defaultdict(list)
    for idx in range(len(items)):
        groups[find(idx)].append(idx)

    clusters: list[dict[str, Any]] = []
    affected_files = 0
    for member_indexes in groups.values():
        if len(member_indexes) < 2:
            continue
        members_sorted = sorted(
            member_indexes,
            key=lambda idx: (
                -len(str(items[idx]["text"] or "")),
                -int(items[idx]["size_bytes"] or 0),
                -int(items[idx]["mtime"] or 0),
                str(items[idx]["path"] or ""),
            ),
        )
        keep = items[members_sorted[0]]
        members = [str(items[idx]["path"] or "") for idx in members_sorted]
        affected_files += len(members)
        clusters.append(
            {
                "members": members,
                "keep_candidate": str(keep["path"]),
                "review_candidates": members[1:],
                "member_stats": [
                    {
                        "path": str(items[idx]["path"]),
                        "text_characters": len(str(items[idx]["text"] or "")),
                        "size_bytes": int(items[idx]["size_bytes"] or 0),
                        "mtime": int(items[idx]["mtime"] or 0),
                    }
                    for idx in members_sorted
                ],
            }
        )

    clusters.sort(key=lambda row: (-len(row.get("members") or []), str(row.get("keep_candidate") or "")))
    return {
        "schema": "mimirq.pre_poc.simhash_review.v1",
        "summary": {
            "clusters": int(len(clusters)),
            "affected_files": int(affected_files),
            "pairs": int(len(pairs)),
            "threshold": int(hamming_threshold),
        },
        "clusters": clusters,
        "pairs": pairs,
    }


__all__ = ["build_simhash_review_candidates"]
