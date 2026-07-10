
from pathlib import Path
from typing import Any

from app.models.connector import ConnectorRun
from app.services.connector_sync_state import get_resume_cursor, normalize_source_manifest, slice_items_from_cursor


def _github_repo_path_is_included(path: str, include_set: set[str]) -> bool:
    ext = Path(path).suffix.lower()
    if ext:
        return ext in include_set
    return "" in include_set


def _github_repo_listed_files_and_observed_paths(
    *,
    tree_items: list[dict[str, Any]],
    tracked_paths: set[str],
    include_set: set[str],
    max_files: int,
) -> tuple[list[tuple[str, str]], set[str]]:
    files: list[tuple[str, str]] = []
    observed_tracked_paths: set[str] = set()
    max_files_bound = max(1, min(max_files, 200))

    for item in tree_items:
        if not isinstance(item, dict):
            continue
        if str(item.get("type") or "") != "blob":
            continue

        path = str(item.get("path") or "").strip()
        if not path:
            continue
        if path in tracked_paths:
            observed_tracked_paths.add(path)
        if not _github_repo_path_is_included(path, include_set):
            continue

        blob_sha = str(item.get("sha") or "").strip()
        if len(files) < max_files_bound:
            files.append((path, blob_sha))

    return files, observed_tracked_paths


def _github_repo_delta_files(
    *,
    files: list[tuple[str, str]],
    existing_manifest: dict[str, str],
    mode: str,
    enable_source_acl: bool,
) -> tuple[list[tuple[str, str]], int]:
    delta_files: list[tuple[str, str]] = []
    skipped_unchanged = 0

    for path, blob_sha in files:
        if (not enable_source_acl) and mode == "incremental" and existing_manifest.get(path) == blob_sha:
            skipped_unchanged += 1
            continue
        delta_files.append((path, blob_sha))

    return delta_files, skipped_unchanged


def _build_github_repo_execution_plan(
    *,
    run_stats: dict[str, Any],
    state: dict[str, Any],
    tree_items: list[dict[str, Any]],
    include_set: set[str],
    max_files: int,
    enable_source_acl: bool,
) -> dict[str, Any]:
    existing_manifest = normalize_source_manifest(state.get("source_manifest"))
    tracked_paths = set(existing_manifest)
    resume_cursor_raw = get_resume_cursor(state)
    files, observed_tracked_paths = _github_repo_listed_files_and_observed_paths(
        tree_items=tree_items,
        tracked_paths=tracked_paths,
        include_set=include_set,
        max_files=max_files,
    )

    is_resume_run = bool((run_stats or {}).get("resume_of")) or bool((not existing_manifest) and resume_cursor_raw > 0)
    mode = "incremental" if existing_manifest else "full"
    delta_files, skipped_unchanged = _github_repo_delta_files(
        files=files,
        existing_manifest=existing_manifest,
        mode=mode,
        enable_source_acl=enable_source_acl,
    )

    removed_paths = sorted(tracked_paths - observed_tracked_paths) if mode == "incremental" else []
    resume_cursor = resume_cursor_raw if (is_resume_run and mode == "full") else 0
    files_to_process, cursor_in = slice_items_from_cursor(delta_files, cursor=resume_cursor)
    source_manifest_state = {path: sha for path, sha in existing_manifest.items() if path not in removed_paths}
    processed_visible = skipped_unchanged + cursor_in

    return {
        "mode": mode,
        "files": files,
        "delta_files": delta_files,
        "removed_paths": removed_paths,
        "files_to_process": files_to_process,
        "cursor_in": int(cursor_in),
        "skipped_unchanged": int(skipped_unchanged),
        "processed_visible": int(processed_visible),
        "source_manifest_state": source_manifest_state,
        "resumed_from_state": bool(is_resume_run and ((mode == "incremental") or cursor_in > 0)),
    }


def _initialize_github_repo_run_stats(*, run: ConnectorRun, plan: dict[str, Any]) -> dict[str, Any]:
    stats = dict(run.stats or {})
    stats.update(
        {
            "mode": plan.get("mode"),
            "total_files": int(len(plan.get("files") or [])),
            "delta_files": int(len(plan.get("delta_files") or [])),
            "skipped_unchanged": int(plan.get("skipped_unchanged") or 0),
            "processed_files": int(plan.get("processed_visible") or 0),
            "cursor": int(plan.get("cursor_in") or 0),
            "created": 0,
            "failed": 0,
            "failed_paths": [],
            "cursor_in": int(plan.get("cursor_in") or 0),
            "resumed_from_state": bool(plan.get("resumed_from_state")),
            "removed_paths": int(len(plan.get("removed_paths") or [])),
            "removed_paths_reconciled": 0,
            "removed_documents_disabled": 0,
            "source_manifest": dict(plan.get("source_manifest_state") or {}),
        }
    )
    return stats
