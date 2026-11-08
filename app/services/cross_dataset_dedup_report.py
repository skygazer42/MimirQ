from typing import Any, TypedDict

from app.services.dataset_precheck_near_dup_summary import summarize_near_dup_payload


class _DatasetDedupRow(TypedDict):
    dataset_id: str
    dataset_name: str | None
    enabled: bool
    pairs: int
    clusters: int
    affected_files: int
    largest_cluster_size: int
    keep_candidates_sample: list[Any]


def _normalize_dataset_row(row: dict[str, Any]) -> _DatasetDedupRow:
    raw_summary = row.get("near_dup_summary")
    if isinstance(raw_summary, dict) and raw_summary:
        summary = dict(raw_summary)
    else:
        summary = summarize_near_dup_payload(row.get("near_dup_payload"))

    return {
        "dataset_id": str(row.get("dataset_id") or "").strip(),
        "dataset_name": row.get("dataset_name"),
        "enabled": bool(summary.get("enabled", False)),
        "pairs": int(summary.get("pairs") or 0),
        "clusters": int(summary.get("clusters") or 0),
        "affected_files": int(summary.get("affected_files") or 0),
        "largest_cluster_size": int(summary.get("largest_cluster_size") or 0),
        "keep_candidates_sample": list(summary.get("keep_candidates_sample") or [])[:20],
    }


def build_cross_dataset_dedup_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    datasets = [_normalize_dataset_row(row) for row in (rows or []) if isinstance(row, dict)]
    datasets.sort(
        key=lambda item: (
            -item["affected_files"],
            -item["clusters"],
            item["dataset_name"] or "",
            item["dataset_id"],
        )
    )

    enabled = [item for item in datasets if item["enabled"]]
    summary = {
        "dataset_count": len(datasets),
        "enabled_dataset_count": len(enabled),
        "pairs": sum(item["pairs"] for item in enabled),
        "clusters": sum(item["clusters"] for item in enabled),
        "affected_files": sum(item["affected_files"] for item in enabled),
        "largest_cluster_size": max([item["largest_cluster_size"] for item in enabled] or [0]),
    }

    return {
        "schema": "mimirq.cross_dataset_dedup_report.v1",
        "summary": summary,
        "datasets": datasets,
    }


__all__ = ["build_cross_dataset_dedup_report"]
