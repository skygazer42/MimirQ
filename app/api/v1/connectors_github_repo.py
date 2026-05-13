from __future__ import annotations

import contextlib
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import UUID

from sqlalchemy.orm import Session, selectinload

from app.models.connector import ConnectorRun, ConnectorRunDocument


def _resolve_connectors_attr(name: str):  # noqa: ANN202
    leader_module = globals().get("_leader_module")
    if leader_module is not None and hasattr(leader_module, name):
        return getattr(leader_module, name)

    preferred_modules = (
        "test_saved_state_connectors",
        "test_support_connectors_module",
        "app.api.v1.connectors",
    )
    for module_name in preferred_modules:
        for key, module in sys.modules.items():
            if key == module_name or key.startswith(f"{module_name}_"):
                if module is not None and hasattr(module, name):
                    return getattr(module, name)

    for module in reversed(tuple(sys.modules.values())):
        path = str(getattr(module, "__file__", "") or "")
        if not path.endswith("/app/api/v1/connectors.py"):
            continue
        if hasattr(module, name):
            return getattr(module, name)

    raise RuntimeError(f"connectors attribute not available: {name}")


def _resolve_connectors_helper(name: str):  # noqa: ANN202
    helper = _resolve_connectors_attr(name)
    if callable(helper):
        return helper
    raise RuntimeError(f"connectors helper not callable: {name}")


def _get_github_repo_run(db: Session, *, run_id: UUID, tenant_id: UUID) -> ConnectorRun | None:
    run = (
        db.query(ConnectorRun)
        .options(selectinload(ConnectorRun.documents))
        .filter(ConnectorRun.id == run_id, ConnectorRun.tenant_id == tenant_id)
        .first()
    )
    if not run:
        return None
    if str(run.status or "").lower() in {"cancelled", "completed", "failed"}:
        return None
    return run


def _mark_github_repo_run_running(db: Session, *, run: ConnectorRun) -> None:
    run.status = "running"
    run.started_at = _resolve_connectors_helper("_now")()
    run.error_message = None
    run.stats = dict(run.stats or {})
    db.commit()
    db.refresh(run)


def _normalize_github_include_set(values: object) -> set[str]:
    include_exts = _resolve_connectors_helper("_normalize_connector_string_list")(values)
    normalized = [("." + ext if not ext.startswith(".") else ext).lower() for ext in include_exts]
    return set(normalized) if normalized else {".md", ".txt"}


def _build_github_repo_run_settings(cfg: dict[str, Any]) -> dict[str, Any]:
    repo = str(cfg.get("repo") or "").strip()
    if "/" not in repo:
        raise ValueError("invalid repo")
    owner, repo_name = repo.split("/", 1)
    owner = owner.strip()
    repo_name = repo_name.strip()
    if not owner or not repo_name:
        raise ValueError("invalid repo")

    branch = str(cfg.get("branch") or "main").strip() or "main"
    access = cfg.get("access") if isinstance(cfg.get("access"), dict) else None
    source_acl = cfg.get("source_acl") if isinstance(cfg.get("source_acl"), dict) else None
    access_mode = str(access.get("mode") or "inherit").strip().lower() if isinstance(access, dict) else "inherit"
    has_manual_access_override = bool(isinstance(access, dict) and access_mode != "inherit")
    source_acl_mode = (
        str(source_acl.get("mode") or "disabled").strip().lower() if isinstance(source_acl, dict) else "disabled"
    )
    source_acl_fallback_mode = (
        str(source_acl.get("fallback_mode") or "partial_members").strip().lower()
        if isinstance(source_acl, dict)
        else "partial_members"
    )

    user_agent = cfg.get("user_agent") if isinstance(cfg.get("user_agent"), str) else None
    auth_headers = _resolve_connectors_helper("_build_auth_headers")(cfg)
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": (user_agent or "MimirQ/1.0 (+github_repo)"),
    }
    headers.update(auth_headers)

    return {
        "repo": repo,
        "owner": owner,
        "repo_name": repo_name,
        "branch": branch,
        "max_files": int(cfg.get("max_files") or 50),
        "include_set": _normalize_github_include_set(cfg.get("include_extensions")),
        "parser_backend": cfg.get("parser_backend") if isinstance(cfg.get("parser_backend"), str) else "auto",
        "chunk_strategy": (
            cfg.get("chunk_strategy") if isinstance(cfg.get("chunk_strategy"), str) else "langchain_recursive"
        ),
        "pipeline": cfg.get("pipeline") if isinstance(cfg.get("pipeline"), dict) else None,
        "access": access,
        "source_acl": source_acl,
        "access_mode": access_mode,
        "has_manual_access_override": has_manual_access_override,
        "user_agent": user_agent,
        "auth_headers": auth_headers,
        "headers": headers,
        "api_url": f"https://api.github.com/repos/{owner}/{repo_name}/git/trees/{quote(branch, safe='')}?recursive=1",
        "source_acl_mode": source_acl_mode,
        "source_acl_fallback_mode": source_acl_fallback_mode,
        "enable_source_acl": bool(source_acl_mode == "inherit" and not has_manual_access_override),
    }


async def _fetch_github_repo_listing_and_acl_keys(settings_map: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    team_principal_keys: list[str] = []
    async with _resolve_connectors_attr("httpx").AsyncClient(
        timeout=_resolve_connectors_attr("httpx").Timeout(30.0)
    ) as client:
        resp = await client.get(str(settings_map.get("api_url") or ""), headers=dict(settings_map.get("headers") or {}))
        if resp.status_code >= 400:
            raise RuntimeError(f"github api failed (status={resp.status_code})")
        data = resp.json()

        if settings_map.get("enable_source_acl"):
            with contextlib.suppress(Exception):
                team_principal_keys = await _resolve_connectors_helper("_github_fetch_repo_team_principal_keys")(
                    client=client,
                    owner=str(settings_map.get("owner") or ""),
                    repo=str(settings_map.get("repo_name") or ""),
                    headers=dict(settings_map.get("headers") or {}),
                )

    return dict(data or {}), team_principal_keys


def _build_github_repo_source_acl_context(
    db: Session,
    *,
    tenant_id: UUID,
    requested_by: str,
    run: ConnectorRun,
    run_id: UUID,
    settings_map: dict[str, Any],
    team_principal_keys: list[str],
) -> dict[str, Any]:
    source_acl_access: dict[str, Any] | None = None
    mapped_group_ids: set[UUID] = set()
    source_acl_provenance: dict[str, Any] | None = None

    if not settings_map.get("enable_source_acl"):
        return {
            "enable_source_acl": False,
            "source_acl_access": None,
            "team_principal_keys": [],
            "mapped_group_ids": set(),
            "source_acl_provenance": None,
        }

    with contextlib.suppress(Exception):
        mapped_group_ids = _resolve_connectors_helper("_resolve_tenant_group_ids_by_external_id")(
            db,
            tenant_id=tenant_id,
            external_ids=team_principal_keys,
        )

    if mapped_group_ids:
        ordered = sorted(mapped_group_ids, key=lambda value: str(value))
        source_acl_access = {
            "mode": "partial_members",
            "partial_group_list": [str(group_id) for group_id in ordered],
        }
    else:
        source_acl_access = {"mode": str(settings_map.get("source_acl_fallback_mode") or "partial_members")}

    with contextlib.suppress(Exception):
        from app.services.audit_log_service import audit_log_event

        audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=requested_by,
            action="github_repo.source_acl.applied",
            resource_type="connector_run",
            resource_id=str(run_id),
            details={
                "dataset_id": str(run.dataset_id),
                "connector_id": "github_repo",
                "repo": str(settings_map.get("repo") or ""),
                "team_principal_count": int(len(team_principal_keys)),
                "mapped_group_count": int(len(mapped_group_ids)),
                "fallback_mode": str(settings_map.get("source_acl_fallback_mode") or "partial_members"),
            },
        )

    with contextlib.suppress(Exception):
        from app.services.document_acl_provenance_service import build_document_acl_provenance

        source_acl_provenance = build_document_acl_provenance(
            connector_id="github_repo",
            connector_run_id=str(run_id),
            effective_access=source_acl_access,
            source_acl_mode=str(settings_map.get("source_acl_mode") or "disabled"),
            source_acl_fallback_mode=str(settings_map.get("source_acl_fallback_mode") or "partial_members"),
            source_principal_external_ids=team_principal_keys,
            mapped_group_ids=mapped_group_ids,
            fallback_used=not bool(mapped_group_ids),
        )

    return {
        "enable_source_acl": True,
        "source_acl_access": source_acl_access,
        "team_principal_keys": list(team_principal_keys),
        "mapped_group_ids": set(mapped_group_ids),
        "source_acl_provenance": source_acl_provenance,
    }


def _github_repo_run_cancelled(db: Session, *, run: ConnectorRun) -> bool:
    with contextlib.suppress(Exception):
        db.refresh(run)
    return str(run.status or "").lower() == "cancelled"


def _github_repo_effective_access(
    *,
    settings_map: dict[str, Any],
    source_acl_context: dict[str, Any],
) -> dict[str, Any] | None:
    effective_access = settings_map.get("access")
    source_acl_access = source_acl_context.get("source_acl_access")
    if not settings_map.get("has_manual_access_override") and isinstance(source_acl_access, dict):
        effective_access = source_acl_access
    return effective_access if isinstance(effective_access, dict) else None


def _apply_github_repo_source_acl_delta_sync(
    db: Session,
    *,
    run: ConnectorRun,
    tenant_id: UUID,
    requested_by: str,
    raw_url: str,
    effective_access: dict[str, Any] | None,
    source_acl_context: dict[str, Any],
) -> int:
    source_acl_access = source_acl_context.get("source_acl_access")
    source_acl_provenance = source_acl_context.get("source_acl_provenance")
    if effective_access is source_acl_access and isinstance(source_acl_access, dict):
        return int(
            _resolve_connectors_helper("_delta_sync_connector_documents_acl_by_source_url")(
                db,
                tenant_id=tenant_id,
                dataset_id=run.dataset_id,
                connector_id="github_repo",
                source_url=raw_url,
                requested_by=requested_by,
                access=effective_access,
                acl_provenance=source_acl_provenance,
            )
        )
    return 0


async def _ingest_github_repo_file(
    db: Session,
    *,
    run: ConnectorRun,
    tenant_id: UUID,
    requested_by: str,
    path: str,
    settings_map: dict[str, Any],
    source_acl_context: dict[str, Any],
) -> dict[str, Any]:
    raw_url = _resolve_connectors_helper("_github_raw_url")(
        owner=str(settings_map.get("owner") or ""),
        repo=str(settings_map.get("repo_name") or ""),
        branch=str(settings_map.get("branch") or ""),
        path=path,
    )
    effective_access = _github_repo_effective_access(
        settings_map=settings_map,
        source_acl_context=source_acl_context,
    )
    updated_existing = _apply_github_repo_source_acl_delta_sync(
        db,
        run=run,
        tenant_id=tenant_id,
        requested_by=requested_by,
        raw_url=raw_url,
        effective_access=effective_access,
        source_acl_context=source_acl_context,
    )

    body = _resolve_connectors_helper("UrlUploadRequest")(
        url=raw_url,
        dataset_id=run.dataset_id,
        filename=Path(path).name,
        fetch_headers=settings_map.get("auth_headers") or None,
        user_agent=settings_map.get("user_agent"),
        parser_backend=str(settings_map.get("parser_backend") or "auto"),
        chunk_strategy=str(settings_map.get("chunk_strategy") or "langchain_recursive"),
        pipeline=settings_map.get("pipeline"),
    )
    doc = await _resolve_connectors_helper("_ingest_url_upload_request")(
        background_tasks=None,
        body=body,
        tenant_id=tenant_id,
        account_id=requested_by,
        db=db,
    )

    _resolve_connectors_helper("_apply_document_access_from_config")(
        db,
        tenant_id=tenant_id,
        requested_by=requested_by,
        doc=doc,
        access=effective_access,
        connector_id="github_repo",
    )

    if effective_access is source_acl_context.get("source_acl_access") and isinstance(
        source_acl_context.get("source_acl_provenance"), dict
    ):
        with contextlib.suppress(Exception):
            from app.services.document_acl_provenance_service import apply_document_acl_provenance

            apply_document_acl_provenance(doc, provenance=source_acl_context.get("source_acl_provenance"))

    _resolve_connectors_helper("_apply_connector_identity_metadata")(
        doc=doc,
        run=run,
        connector_id="github_repo",
        source_ref=path,
        source_id=path,
    )

    db.add(
        ConnectorRunDocument(
            tenant_id=tenant_id,
            run_id=run.id,
            document_id=doc.id,
            source_ref=path,
            status="created",
        )
    )

    return {
        "doc_id": doc.id,
        "updated_existing": int(updated_existing),
    }


def _persist_github_repo_progress(
    db: Session,
    *,
    run: ConnectorRun,
    plan: dict[str, Any],
    processed: int,
    created: int,
    failed: int,
    created_doc_ids: list[UUID],
    delta_acl_docs_updated: int,
    delta_acl_sources_updated: int,
    removed_paths_reconciled: int,
    removed_documents_disabled: int,
    source_manifest_state: dict[str, str],
) -> None:
    processed_visible = int(plan.get("skipped_unchanged") or 0) + processed
    stats = dict(run.stats or {})
    stats.update(
        {
            "mode": plan.get("mode"),
            "total_files": int(len(plan.get("files") or [])),
            "delta_files": int(len(plan.get("delta_files") or [])),
            "skipped_unchanged": int(plan.get("skipped_unchanged") or 0),
            "processed_files": int(processed_visible),
            "cursor": int(processed),
            "created": int(created),
            "failed": int(failed),
            "document_ids": [str(doc_id) for doc_id in created_doc_ids],
            "acl_delta_sync_updated_documents": int(delta_acl_docs_updated),
            "acl_delta_sync_updated_sources": int(delta_acl_sources_updated),
            "removed_paths": int(len(plan.get("removed_paths") or [])),
            "removed_paths_reconciled": int(removed_paths_reconciled),
            "removed_documents_disabled": int(removed_documents_disabled),
            "source_manifest": dict(source_manifest_state),
        }
    )
    run.stats = _resolve_connectors_helper("_finalize_connector_stats")(stats)
    db.commit()


def _github_repo_apply_processed_file_success(
    *,
    path: str,
    blob_sha: str,
    result: dict[str, Any],
    created: int,
    created_doc_ids: list[UUID],
    delta_acl_docs_updated: int,
    delta_acl_sources_updated: int,
    source_manifest_state: dict[str, str],
) -> dict[str, Any]:
    created += 1
    created_doc_ids = [*created_doc_ids, result["doc_id"]]

    updated_existing = int(result.get("updated_existing") or 0)
    delta_acl_docs_updated += updated_existing
    if updated_existing:
        delta_acl_sources_updated += 1
    if path and blob_sha:
        source_manifest_state = {
            **source_manifest_state,
            path: blob_sha,
        }

    return {
        "created": created,
        "created_doc_ids": created_doc_ids,
        "delta_acl_docs_updated": delta_acl_docs_updated,
        "delta_acl_sources_updated": delta_acl_sources_updated,
        "source_manifest_state": source_manifest_state,
    }


async def _process_github_repo_files(
    db: Session,
    *,
    run: ConnectorRun,
    tenant_id: UUID,
    requested_by: str,
    settings_map: dict[str, Any],
    plan: dict[str, Any],
    source_acl_context: dict[str, Any],
) -> dict[str, Any]:
    created = 0
    failed = 0
    created_doc_ids: list[UUID] = []
    delta_acl_docs_updated = 0
    delta_acl_sources_updated = 0
    removed_paths_reconciled = 0
    removed_documents_disabled = 0
    source_manifest_state = dict(plan.get("source_manifest_state") or {})
    cursor_in = int(plan.get("cursor_in") or 0)

    for idx, item in enumerate(plan.get("files_to_process") or []):
        path, blob_sha = item if isinstance(item, tuple) else (str(item or ""), "")
        if _github_repo_run_cancelled(db, run=run):
            break

        try:
            result = await _ingest_github_repo_file(
                db,
                run=run,
                tenant_id=tenant_id,
                requested_by=requested_by,
                path=path,
                settings_map=settings_map,
                source_acl_context=source_acl_context,
            )
            success_state = _github_repo_apply_processed_file_success(
                path=path,
                blob_sha=blob_sha,
                result=result,
                created=created,
                created_doc_ids=created_doc_ids,
                delta_acl_docs_updated=delta_acl_docs_updated,
                delta_acl_sources_updated=delta_acl_sources_updated,
                source_manifest_state=source_manifest_state,
            )
            created = int(success_state["created"])
            created_doc_ids = list(success_state["created_doc_ids"])
            delta_acl_docs_updated = int(success_state["delta_acl_docs_updated"])
            delta_acl_sources_updated = int(success_state["delta_acl_sources_updated"])
            source_manifest_state = dict(success_state["source_manifest_state"])
        except Exception as exc:  # noqa: BLE001
            failed += 1
            run.stats = _resolve_connectors_helper("_append_connector_error")(dict(run.stats or {}), url=path, exc=exc)
        finally:
            _persist_github_repo_progress(
                db,
                run=run,
                plan=plan,
                processed=cursor_in + idx + 1,
                created=created,
                failed=failed,
                created_doc_ids=created_doc_ids,
                delta_acl_docs_updated=delta_acl_docs_updated,
                delta_acl_sources_updated=delta_acl_sources_updated,
                removed_paths_reconciled=removed_paths_reconciled,
                removed_documents_disabled=removed_documents_disabled,
                source_manifest_state=source_manifest_state,
            )

    return {
        "created": created,
        "failed": failed,
        "created_doc_ids": created_doc_ids,
        "delta_acl_docs_updated": delta_acl_docs_updated,
        "delta_acl_sources_updated": delta_acl_sources_updated,
        "removed_paths_reconciled": removed_paths_reconciled,
        "removed_documents_disabled": removed_documents_disabled,
        "source_manifest_state": source_manifest_state,
    }


def _finalize_cancelled_github_repo_run(db: Session, *, run: ConnectorRun) -> None:
    if run.finished_at is None:
        run.finished_at = _resolve_connectors_helper("_now")()
    run.stats = _resolve_connectors_helper("_finalize_connector_stats")(dict(run.stats or {}))
    db.commit()
    with contextlib.suppress(Exception):
        _resolve_connectors_helper("_sync_connector_config_from_run")(db, run=run)


def _reconcile_removed_github_repo_paths(
    db: Session,
    *,
    run: ConnectorRun,
    tenant_id: UUID,
    settings_map: dict[str, Any],
    removed_paths: list[str],
) -> tuple[int, int]:
    removed_paths_reconciled = 0
    removed_documents_disabled = 0
    for path in removed_paths:
        raw_url = _resolve_connectors_helper("_github_raw_url")(
            owner=str(settings_map.get("owner") or ""),
            repo=str(settings_map.get("repo_name") or ""),
            branch=str(settings_map.get("branch") or ""),
            path=path,
        )
        try:
            disabled = _resolve_connectors_helper("_soft_disable_connector_documents_by_source_url")(
                db,
                tenant_id=tenant_id,
                dataset_id=run.dataset_id,
                connector_id="github_repo",
                source_url=raw_url,
            )
        except Exception as exc:  # noqa: BLE001
            stats = _resolve_connectors_helper("_append_connector_error")(dict(run.stats or {}), url=path, exc=exc)
            run.stats = _resolve_connectors_helper("_finalize_connector_stats")(stats)
            db.commit()
            continue
        removed_documents_disabled += int(disabled)
        if disabled:
            removed_paths_reconciled += 1
    return removed_paths_reconciled, removed_documents_disabled


def _emit_github_repo_source_acl_delta_sync_audit(
    db: Session,
    *,
    tenant_id: UUID,
    requested_by: str,
    run: ConnectorRun,
    run_id: UUID,
    settings_map: dict[str, Any],
    source_acl_context: dict[str, Any],
    delta_acl_docs_updated: int,
    delta_acl_sources_updated: int,
) -> None:
    if not source_acl_context.get("enable_source_acl"):
        return
    with contextlib.suppress(Exception):
        from app.services.audit_log_service import audit_log_event

        audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=requested_by,
            action="github_repo.source_acl.delta_sync",
            resource_type="connector_run",
            resource_id=str(run_id),
            details={
                "dataset_id": str(run.dataset_id),
                "connector_id": "github_repo",
                "repo": str(settings_map.get("repo") or ""),
                "branch": str(settings_map.get("branch") or ""),
                "updated_documents": int(delta_acl_docs_updated),
                "updated_sources": int(delta_acl_sources_updated),
            },
        )


def _finalize_github_repo_run_success(
    db: Session,
    *,
    run: ConnectorRun,
    tenant_id: UUID,
    requested_by: str,
    run_id: UUID,
    settings_map: dict[str, Any],
    plan: dict[str, Any],
    source_acl_context: dict[str, Any],
    progress: dict[str, Any],
) -> None:
    stats = dict(run.stats or {})
    stats.update(
        {
            "mode": plan.get("mode"),
            "delta_files": int(len(plan.get("delta_files") or [])),
            "skipped_unchanged": int(plan.get("skipped_unchanged") or 0),
            "document_ids": [str(doc_id) for doc_id in (progress.get("created_doc_ids") or [])],
            "acl_delta_sync_updated_documents": int(progress.get("delta_acl_docs_updated") or 0),
            "acl_delta_sync_updated_sources": int(progress.get("delta_acl_sources_updated") or 0),
            "removed_paths": int(len(plan.get("removed_paths") or [])),
            "removed_paths_reconciled": int(progress.get("removed_paths_reconciled") or 0),
            "removed_documents_disabled": int(progress.get("removed_documents_disabled") or 0),
            "source_manifest": dict(progress.get("source_manifest_state") or {}),
        }
    )
    run.stats = _resolve_connectors_helper("_finalize_connector_stats")(stats)
    run.finished_at = _resolve_connectors_helper("_now")()
    run.status = _resolve_connectors_helper("_connector_run_completion_status")(
        created=int(progress.get("created") or 0),
        failed=int(progress.get("failed") or 0),
    )
    _emit_github_repo_source_acl_delta_sync_audit(
        db,
        tenant_id=tenant_id,
        requested_by=requested_by,
        run=run,
        run_id=run_id,
        settings_map=settings_map,
        source_acl_context=source_acl_context,
        delta_acl_docs_updated=int(progress.get("delta_acl_docs_updated") or 0),
        delta_acl_sources_updated=int(progress.get("delta_acl_sources_updated") or 0),
    )
    db.commit()
    with contextlib.suppress(Exception):
        _resolve_connectors_helper("_sync_connector_config_from_run")(db, run=run)


def _mark_github_repo_run_failed(db: Session, *, run_id: UUID, tenant_id: UUID, exc: Exception) -> None:
    with contextlib.suppress(Exception):
        run = (
            db.query(ConnectorRun)
            .filter(ConnectorRun.id == run_id, ConnectorRun.tenant_id == tenant_id)
            .first()
        )
        if run is not None:
            run.status = "failed"
            run.finished_at = _resolve_connectors_helper("_now")()
            run.error_message = str(exc)[:200]
            db.commit()
            with contextlib.suppress(Exception):
                _resolve_connectors_helper("_sync_connector_config_from_run")(db, run=run)


async def _execute_github_repo_run(*, run_id: UUID, tenant_id: UUID, requested_by: str) -> None:
    """
    Background execution for github_repo connector.

    Flow:
    - List repository files via GitHub API (tree)
    - Ingest selected files via raw.githubusercontent.com URLs
    """
    db = _resolve_connectors_attr("SessionLocal")()
    run: ConnectorRun | None = None
    try:
        run = _get_github_repo_run(db, run_id=run_id, tenant_id=tenant_id)
        if run is None:
            return

        _mark_github_repo_run_running(db, run=run)
        cfg = _resolve_connectors_helper("decrypt_connector_config_secrets")(dict(run.config or {}))
        settings_map = _build_github_repo_run_settings(cfg)
        data, team_principal_keys = await _fetch_github_repo_listing_and_acl_keys(settings_map)
        source_acl_context = _build_github_repo_source_acl_context(
            db,
            tenant_id=tenant_id,
            requested_by=requested_by,
            run=run,
            run_id=run_id,
            settings_map=settings_map,
            team_principal_keys=team_principal_keys,
        )

        state = cfg.get("_state") if isinstance(cfg.get("_state"), dict) else {}
        tree = data.get("tree")
        plan = _resolve_connectors_helper("_build_github_repo_execution_plan")(
            run_stats=dict(run.stats or {}),
            state=state,
            tree_items=(tree if isinstance(tree, list) else []),
            include_set=set(settings_map.get("include_set") or set()),
            max_files=int(settings_map.get("max_files") or 50),
            enable_source_acl=bool(source_acl_context.get("enable_source_acl")),
        )
        run.stats = _resolve_connectors_helper("_initialize_github_repo_run_stats")(run=run, plan=plan)
        db.commit()

        progress = await _process_github_repo_files(
            db,
            run=run,
            tenant_id=tenant_id,
            requested_by=requested_by,
            settings_map=settings_map,
            plan=plan,
            source_acl_context=source_acl_context,
        )

        if _github_repo_run_cancelled(db, run=run):
            _finalize_cancelled_github_repo_run(db, run=run)
            return

        removed_paths = list(plan.get("removed_paths") or [])
        if plan.get("mode") == "incremental" and removed_paths:
            removed_paths_reconciled, removed_documents_disabled = _reconcile_removed_github_repo_paths(
                db,
                run=run,
                tenant_id=tenant_id,
                settings_map=settings_map,
                removed_paths=removed_paths,
            )
            progress["removed_paths_reconciled"] = int(removed_paths_reconciled)
            progress["removed_documents_disabled"] = int(removed_documents_disabled)

        _finalize_github_repo_run_success(
            db,
            run=run,
            tenant_id=tenant_id,
            requested_by=requested_by,
            run_id=run_id,
            settings_map=settings_map,
            plan=plan,
            source_acl_context=source_acl_context,
            progress=progress,
        )
    except Exception as exc:  # noqa: BLE001
        _mark_github_repo_run_failed(db, run_id=run_id, tenant_id=tenant_id, exc=exc)
    finally:
        db.close()
