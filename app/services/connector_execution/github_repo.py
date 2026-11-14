import contextlib
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx
from sqlalchemy.orm import Session

from app.api.schemas.documents import UrlUploadRequest
from app.core.database import SessionLocal
from app.core.secrets import decrypt_connector_config_secrets
from app.models.connector import ConnectorRun, ConnectorRunDocument
from app.services import document_ingestion as ingestion_service
from app.services.connector_document_access import (
    _apply_document_access_from_config,
    _delta_sync_connector_documents_acl_by_source_url,
    _soft_disable_connector_documents_by_source_url,
    build_source_access_settings,
    resolve_configured_source_access,
)
from app.services.connector_execution.plans.github_repo import (
    GitHubRepoExecutionPlan,
    _build_github_repo_execution_plan,
    _initialize_github_repo_run_stats,
)
from app.services.connector_execution.shared.artifacts import (
    _apply_connector_identity_metadata,
    _normalize_connector_string_list,
)
from app.services.connector_execution.shared.common import (
    _append_connector_error,
    _connector_config_id_from_run,
    _connector_run_completion_status,
    _finalize_connector_stats,
    build_ingestion_options,
)
from app.services.connector_execution.shared.external import (
    _build_auth_headers,
    _github_fetch_repo_team_principal_keys,
    _github_raw_url,
    _resolve_tenant_group_ids_by_external_id,
)
from app.services.connector_execution.shared.runtime import (
    _now,
    _sync_connector_config_from_run,
)
from app.services.connector_execution.shared.runtime import (
    connector_run_cancelled as _github_repo_run_cancelled,
)
from app.services.connector_execution.shared.runtime import (
    finalize_cancelled_connector_run as _finalize_cancelled_github_repo_run,
)
from app.services.connector_execution.shared.runtime import (
    get_active_connector_run as _get_github_repo_run,
)
from app.services.connector_execution.shared.runtime import (
    mark_connector_run_failed as _mark_github_repo_run_failed,
)
from app.services.connector_execution.shared.runtime import (
    mark_connector_run_running as _mark_github_repo_run_running,
)


def _normalize_github_include_set(values: object) -> set[str]:
    include_exts = _normalize_connector_string_list(values)
    normalized = [("." + ext if not ext.startswith(".") else ext).lower() for ext in include_exts]
    return set(normalized) if normalized else {".md", ".txt"}


def _build_github_repo_run_settings(cfg: dict[str, Any]) -> dict[str, Any]:
    repo = cfg["repo"].strip()
    if "/" not in repo:
        raise ValueError("invalid repo")
    owner, repo_name = repo.split("/", 1)
    owner = owner.strip()
    repo_name = repo_name.strip()
    if not owner or not repo_name:
        raise ValueError("invalid repo")

    branch = str(cfg.get("branch") or "main").strip() or "main"
    access_settings = build_source_access_settings(cfg)

    user_agent = cfg.get("user_agent") if isinstance(cfg.get("user_agent"), str) else None
    auth_headers = _build_auth_headers(cfg)
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": (user_agent or "Ragvia/1.0 (+github_repo)"),
    }
    headers.update(auth_headers)

    return {
        "repo": repo,
        "owner": owner,
        "repo_name": repo_name,
        "branch": branch,
        "max_files": int(cfg.get("max_files") or 50),
        "include_set": _normalize_github_include_set(cfg.get("include_extensions")),
        **build_ingestion_options(cfg),
        "access": access_settings["access"],
        "source_acl": access_settings["source_acl"],
        "access_mode": access_settings["access_mode"],
        "has_manual_access_override": access_settings["has_manual_access_override"],
        "user_agent": user_agent,
        "auth_headers": auth_headers,
        "headers": headers,
        "api_url": f"https://api.github.com/repos/{owner}/{repo_name}/git/trees/{quote(branch, safe='')}?recursive=1",
        "source_acl_mode": access_settings["source_acl_mode"],
        "source_acl_fallback_mode": access_settings["source_acl_fallback_mode"],
        "enable_source_acl": access_settings["enable_source_acl"],
    }


async def _fetch_github_repo_listing_and_acl_keys(settings_map: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    team_principal_keys: list[str] = []
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        resp = await client.get(settings_map["api_url"], headers=dict(settings_map.get("headers") or {}))
        if resp.status_code >= 400:
            raise RuntimeError(f"github api failed (status={resp.status_code})")
        data = resp.json()

        if settings_map.get("enable_source_acl"):
            with contextlib.suppress(Exception):
                team_principal_keys = await _github_fetch_repo_team_principal_keys(
                    client=client,
                    owner=settings_map["owner"],
                    repo=settings_map["repo_name"],
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

    source_acl_config = settings_map.get("source_acl")
    if source_acl_config and source_acl_config.get("group_mappings"):
        source_acl_access, mapped_group_ids = resolve_configured_source_access(
            source_system="github",
            source_acl_config=source_acl_config,
            principal_keys=team_principal_keys,
        )
    else:
        with contextlib.suppress(Exception):
            mapped_group_ids = _resolve_tenant_group_ids_by_external_id(
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
                "repo": settings_map["repo"],
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
        connector_config_id = _connector_config_id_from_run(run)
        return int(
            _delta_sync_connector_documents_acl_by_source_url(
                db,
                tenant_id=tenant_id,
                dataset_id=run.dataset_id,
                connector_id="github_repo",
                source_url=raw_url,
                requested_by=requested_by,
                access=effective_access,
                acl_provenance=source_acl_provenance,
                connector_config_id=connector_config_id,
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
    raw_url = _github_raw_url(
        owner=settings_map["owner"],
        repo=settings_map["repo_name"],
        branch=settings_map["branch"],
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

    body = UrlUploadRequest(
        url=raw_url,
        dataset_id=run.dataset_id,
        filename=Path(path).name,
        fetch_headers=settings_map.get("auth_headers"),
        user_agent=settings_map.get("user_agent"),
        parser_backend=str(settings_map.get("parser_backend") or "auto"),
        chunk_strategy=str(settings_map.get("chunk_strategy") or "langchain_recursive"),
        pipeline=settings_map.get("pipeline"),
    )
    doc = await ingestion_service.ingest_url(
        background_tasks=None,
        body=body,
        tenant_id=tenant_id,
        account_id=requested_by,
        db=db,
    )

    _apply_document_access_from_config(
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

    _apply_connector_identity_metadata(
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
    plan: GitHubRepoExecutionPlan,
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
    processed_visible = plan["skipped_unchanged"] + processed
    stats = dict(run.stats or {})
    stats.update(
        {
            "mode": plan["mode"],
            "total_files": len(plan["files"]),
            "delta_files": len(plan["delta_files"]),
            "skipped_unchanged": plan["skipped_unchanged"],
            "processed_files": int(processed_visible),
            "cursor": int(processed),
            "created": int(created),
            "failed": int(failed),
            "document_ids": [str(doc_id) for doc_id in created_doc_ids],
            "acl_delta_sync_updated_documents": int(delta_acl_docs_updated),
            "acl_delta_sync_updated_sources": int(delta_acl_sources_updated),
            "removed_paths": len(plan["removed_paths"]),
            "removed_paths_reconciled": int(removed_paths_reconciled),
            "removed_documents_disabled": int(removed_documents_disabled),
            "source_manifest": dict(source_manifest_state),
        }
    )
    run.stats = _finalize_connector_stats(stats)
    db.commit()


async def _process_github_repo_files(
    db: Session,
    *,
    run: ConnectorRun,
    tenant_id: UUID,
    requested_by: str,
    settings_map: dict[str, Any],
    plan: GitHubRepoExecutionPlan,
    source_acl_context: dict[str, Any],
) -> dict[str, Any]:
    created = 0
    failed = 0
    created_doc_ids: list[UUID] = []
    delta_acl_docs_updated = 0
    delta_acl_sources_updated = 0
    removed_paths_reconciled = 0
    removed_documents_disabled = 0
    source_manifest_state = dict(plan["source_manifest_state"])
    cursor_in = plan["cursor_in"]

    for idx, item in enumerate(plan["files_to_process"]):
        path, blob_sha = item
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
            created += 1
            created_doc_ids = [*created_doc_ids, result["doc_id"]]
            updated_existing = int(result.get("updated_existing") or 0)
            delta_acl_docs_updated += updated_existing
            if updated_existing:
                delta_acl_sources_updated += 1
            source_manifest_state = dict(source_manifest_state)
            if path and blob_sha:
                source_manifest_state[path] = blob_sha
        except Exception as exc:  # noqa: BLE001
            failed += 1
            run.stats = _append_connector_error(dict(run.stats or {}), url=path, exc=exc)
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
    connector_config_id = _connector_config_id_from_run(run)
    for path in removed_paths:
        raw_url = _github_raw_url(
            owner=settings_map["owner"],
            repo=settings_map["repo_name"],
            branch=settings_map["branch"],
            path=path,
        )
        try:
            disabled = _soft_disable_connector_documents_by_source_url(
                db,
                tenant_id=tenant_id,
                dataset_id=run.dataset_id,
                connector_id="github_repo",
                source_url=raw_url,
                connector_config_id=connector_config_id,
            )
        except Exception as exc:  # noqa: BLE001
            stats = _append_connector_error(dict(run.stats or {}), url=path, exc=exc)
            run.stats = _finalize_connector_stats(stats)
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
                "repo": settings_map["repo"],
                "branch": settings_map["branch"],
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
    plan: GitHubRepoExecutionPlan,
    source_acl_context: dict[str, Any],
    progress: dict[str, Any],
) -> None:
    stats = dict(run.stats or {})
    stats.update(
        {
            "mode": plan["mode"],
            "delta_files": len(plan["delta_files"]),
            "skipped_unchanged": plan["skipped_unchanged"],
            "document_ids": [str(doc_id) for doc_id in (progress.get("created_doc_ids") or [])],
            "acl_delta_sync_updated_documents": int(progress.get("delta_acl_docs_updated") or 0),
            "acl_delta_sync_updated_sources": int(progress.get("delta_acl_sources_updated") or 0),
            "removed_paths": len(plan["removed_paths"]),
            "removed_paths_reconciled": int(progress.get("removed_paths_reconciled") or 0),
            "removed_documents_disabled": int(progress.get("removed_documents_disabled") or 0),
            "source_manifest": dict(progress.get("source_manifest_state") or {}),
        }
    )
    run.stats = _finalize_connector_stats(stats)
    run.finished_at = _now()
    run.status = _connector_run_completion_status(
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
        _sync_connector_config_from_run(db, run=run)


async def execute(*, run_id: UUID, tenant_id: UUID, requested_by: str) -> None:
    """
    Background execution for github_repo connector.

    Flow:
    - List repository files via GitHub API (tree)
    - Ingest selected files via raw.githubusercontent.com URLs
    """
    db = SessionLocal()
    run: ConnectorRun | None = None
    try:
        run = _get_github_repo_run(db, run_id=run_id, tenant_id=tenant_id)
        if run is None:
            return

        _mark_github_repo_run_running(db, run=run)
        cfg = decrypt_connector_config_secrets(dict(run.config or {}))
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
        plan = _build_github_repo_execution_plan(
            run_stats=dict(run.stats or {}),
            state=state,
            tree_items=(tree if isinstance(tree, list) else []),
            include_set=set(settings_map.get("include_set") or set()),
            max_files=int(settings_map.get("max_files") or 50),
            enable_source_acl=bool(source_acl_context.get("enable_source_acl")),
        )
        run.stats = _initialize_github_repo_run_stats(run=run, plan=plan)
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

        removed_paths = list(plan["removed_paths"])
        if plan["mode"] == "incremental" and removed_paths:
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
