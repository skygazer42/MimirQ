from collections import defaultdict
from typing import Any


def find_exact_md5_duplicates(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        raw_digest, raw_path = row.get("md5"), row.get("path")
        digest = str(raw_digest).strip().lower() if raw_digest is not None else None
        path = str(raw_path).strip() if raw_path is not None else None
        if not digest or not path:
            continue
        grouped[digest].append({**row, "path": path})

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
                row["path"],
            ),
        )
        keep = members_sorted[0]
        duplicates = sorted(row["path"] for row in members_sorted[1:])
        duplicate_files += 1 + len(duplicates)
        groups_out.append(
            {
                "md5": digest,
                "keep_path": keep["path"],
                "duplicate_paths": duplicates,
                "count": len(members_sorted),
            }
        )

    return {
        "schema": "mimirq.pre_poc.md5_dedup.v1",
        "summary": {
            "duplicate_groups": len(groups_out),
            "duplicate_files": duplicate_files,
        },
        "groups": groups_out,
    }


__all__ = ["find_exact_md5_duplicates"]
