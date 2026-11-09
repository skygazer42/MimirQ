from collections import defaultdict
from typing import Any, TypedDict

from app.rag.preprocessing.simhash import hamming_distance64, simhash64


class _SimhashItem(TypedDict):
    path: str
    text: str
    size_bytes: int
    mtime: int
    simhash64: int


class _SimhashPair(TypedDict):
    a: str
    b: str
    distance: int


class _SimhashMemberStats(TypedDict):
    path: str
    text_characters: int
    size_bytes: int
    mtime: int


class _SimhashCluster(TypedDict):
    members: list[str]
    keep_candidate: str
    review_candidates: list[str]
    member_stats: list[_SimhashMemberStats]


def build_simhash_review_candidates(
    rows: list[dict[str, Any]],
    *,
    hamming_threshold: int = 5,
) -> dict[str, Any]:
    items = _normalize_simhash_items(rows)
    pairs, groups = _group_simhash_items(items, hamming_threshold=int(hamming_threshold))
    clusters = _build_simhash_clusters(items, groups)
    affected_files = sum(len(cluster["members"]) for cluster in clusters)
    clusters.sort(key=lambda row: (-len(row["members"]), row["keep_candidate"]))
    return {
        "schema": "mimirq.pre_poc.simhash_review.v1",
        "summary": {
            "clusters": len(clusters),
            "affected_files": affected_files,
            "pairs": len(pairs),
            "threshold": int(hamming_threshold),
        },
        "clusters": clusters,
        "pairs": pairs,
    }


def _normalize_simhash_items(rows: list[dict[str, Any]]) -> list[_SimhashItem]:
    items: list[_SimhashItem] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        raw_path, raw_text = row.get("path"), row.get("text")
        path = str(raw_path).strip() if raw_path is not None else None
        text = str(raw_text).strip() if raw_text is not None else None
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
    items: list[_SimhashItem],
    *,
    hamming_threshold: int,
) -> tuple[list[_SimhashPair], dict[int, list[int]]]:
    parent = list(range(len(items)))
    pairs: list[_SimhashPair] = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            distance = hamming_distance64(items[i]["simhash64"], items[j]["simhash64"])
            if distance <= hamming_threshold:
                pairs.append({"a": items[i]["path"], "b": items[j]["path"], "distance": distance})
                _union_parents(parent, i, j)

    groups: dict[int, list[int]] = defaultdict(list)
    for idx in range(len(items)):
        groups[_find_parent(parent, idx)].append(idx)
    return pairs, groups


def _build_simhash_clusters(
    items: list[_SimhashItem],
    groups: dict[int, list[int]],
) -> list[_SimhashCluster]:
    clusters: list[_SimhashCluster] = []
    for member_indexes in groups.values():
        if len(member_indexes) < 2:
            continue
        members_sorted = sorted(
            member_indexes,
            key=lambda idx: (
                -len(items[idx]["text"]),
                -items[idx]["size_bytes"],
                -items[idx]["mtime"],
                items[idx]["path"],
            ),
        )
        keep = items[members_sorted[0]]
        members = [items[idx]["path"] for idx in members_sorted]
        clusters.append(
            {
                "members": members,
                "keep_candidate": keep["path"],
                "review_candidates": members[1:],
                "member_stats": [
                    {
                        "path": items[idx]["path"],
                        "text_characters": len(items[idx]["text"]),
                        "size_bytes": items[idx]["size_bytes"],
                        "mtime": items[idx]["mtime"],
                    }
                    for idx in members_sorted
                ],
            }
        )
    return clusters


__all__ = ["build_simhash_review_candidates"]
