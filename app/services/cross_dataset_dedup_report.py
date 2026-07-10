
from typing import Any

from app.services.dataset_precheck_near_dup_summary import summarize_near_dup_payload


def _normalize_dataset_row(row: dict[str, Any]) -> dict[str, Any]:
    raw_summary = row.get("near_dup_summary")
    if isinstance(raw_summary, dict) and raw_summary:
        summary = dict(raw_summary)
    else:
        summary = summarize_near_dup_payload(row.get("near_dup_payload"))

    return {
        "dataset_id": str(row.get("dataset_id") or "").strip(),
        "dataset_name": str(row.get("dataset_name") or "").strip() or None,
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
            -int(item["affected_files"]),
            -int(item["clusters"]),
            str(item["dataset_name"] or ""),
            str(item["dataset_id"] or ""),
        )
    )

    enabled = [item for item in datasets if bool(item.get("enabled"))]
    summary = {
        "dataset_count": len(datasets),
        "enabled_dataset_count": len(enabled),
        "pairs": sum(int(item.get("pairs") or 0) for item in enabled),
        "clusters": sum(int(item.get("clusters") or 0) for item in enabled),
        "affected_files": sum(int(item.get("affected_files") or 0) for item in enabled),
        "largest_cluster_size": max([int(item.get("largest_cluster_size") or 0) for item in enabled] or [0]),
    }

    return {
        "schema": "mimirq.cross_dataset_dedup_report.v1",
        "summary": summary,
        "datasets": datasets,
    }


__all__ = ["build_cross_dataset_dedup_report"]
