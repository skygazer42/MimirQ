
from collections import defaultdict
from typing import Any


def find_exact_md5_duplicates(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        digest = str(row.get("md5") or "").strip().lower()
        path = str(row.get("path") or "").strip()
        if not digest or not path:
            continue
        grouped[digest].append(dict(row))

    groups_out: list[dict[str, Any]] = []
    duplicate_files = 0
    for digest, members in sorted(grouped.items(), key=lambda kv: kv[0]):
        if len(members) < 2:
            continue
        members_sorted = sorted(
            members,
            key=lambda row: (
                -int(row.get("size_bytes") or 0),
                -int(row.get("mtime") or 0),
                str(row.get("path") or ""),
            ),
        )
        keep = members_sorted[0]
        duplicates = sorted(str(row.get("path") or "") for row in members_sorted[1:] if str(row.get("path") or ""))
        duplicate_files += 1 + len(duplicates)
        groups_out.append(
            {
                "md5": digest,
                "keep_path": str(keep.get("path") or ""),
                "duplicate_paths": duplicates,
                "count": int(len(members_sorted)),
            }
        )

    return {
        "schema": "mimirq.pre_poc.md5_dedup.v1",
        "summary": {
            "duplicate_groups": int(len(groups_out)),
            "duplicate_files": int(duplicate_files),
        },
        "groups": groups_out,
    }


__all__ = ["find_exact_md5_duplicates"]
