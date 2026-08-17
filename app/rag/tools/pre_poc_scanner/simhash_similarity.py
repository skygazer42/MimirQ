
from collections import defaultdict
from typing import Any

from app.rag.preprocessing.simhash import hamming_distance64, simhash64


def build_simhash_review_candidates(
    rows: list[dict[str, Any]],
    *,
    hamming_threshold: int = 5,
) -> dict[str, Any]:
    items = _normalize_simhash_items(rows)
    pairs, groups = _group_simhash_items(items, hamming_threshold=int(hamming_threshold))
    clusters = _build_simhash_clusters(items, groups)
    affected_files = sum(len(cluster["members"]) for cluster in clusters)
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


def _normalize_simhash_items(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
    return items


def _find_parent(parent: list[int], index: int) -> int:
    while parent[index] != index:
        parent[index] = parent[parent[index]]
        index = parent[index]
    return index


def _union_parents(parent: list[int], left: int, right: int) -> None:
    left_root = _find_parent(parent, left)
    right_root = _find_parent(parent, right)
    if left_root != right_root:
        parent[right_root] = left_root


def _group_simhash_items(
    items: list[dict[str, Any]],
    *,
    hamming_threshold: int,
) -> tuple[list[dict[str, Any]], dict[int, list[int]]]:
    parent = list(range(len(items)))
    pairs: list[dict[str, Any]] = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            distance = hamming_distance64(items[i]["simhash64"], items[j]["simhash64"])
            if distance <= hamming_threshold:
                pairs.append({"a": items[i]["path"], "b": items[j]["path"], "distance": int(distance)})
                _union_parents(parent, i, j)

    groups: dict[int, list[int]] = defaultdict(list)
    for idx in range(len(items)):
        groups[_find_parent(parent, idx)].append(idx)
    return pairs, groups


def _build_simhash_clusters(
    items: list[dict[str, Any]],
    groups: dict[int, list[int]],
) -> list[dict[str, Any]]:
    clusters: list[dict[str, Any]] = []
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
    return clusters


__all__ = ["build_simhash_review_candidates"]
