import contextlib
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy.orm import Session

from app.api.schemas.document_ingestion import UrlUploadRequest
from app.core.database import SessionLocal
from app.core.secrets import decrypt_connector_config_secrets
from app.models.connector import ConnectorRun, ConnectorRunDocument
from app.services import document_ingestion as ingestion_service
from app.services.connector_document_access import (
    _apply_document_access_from_config,
    _delta_sync_connector_documents_acl_by_source_url,
    _soft_disable_connector_documents_by_source_ref,
    _soft_disable_connector_documents_by_source_url,
    build_source_access_settings,
    resolve_configured_source_access,
)
from app.services.connector_execution.shared.artifacts import (
    _apply_connector_identity_metadata,
    _normalize_connector_string_list,
)
from app.services.connector_execution.shared.common import (
    _optional_source_text,
    _append_connector_error,
    _connector_config_id_from_run,
    _connector_run_completion_status,
    _finalize_connector_stats,
    build_ingestion_options,
)
from app.services.connector_execution.shared.external import (
    _build_auth_headers,
    _drive_direct_download_url,
    _drive_fetch_file_permissions,
    _drive_fetch_file_sync_token,
    _drive_permission_external_ids_and_anyone,
    _drive_source_ref,
    _extract_drive_file_id,
    _resolve_tenant_group_ids_by_external_id,
)
from app.services.connector_execution.shared.runtime import (
    _now,
    _sync_connector_config_from_run,
)
from app.services.connector_execution.shared.runtime import (
    finalize_cancelled_connector_run as _finalize_cancelled_drive_files_run,
)
from app.services.connector_execution.shared.runtime import (
    get_active_connector_run as _get_drive_files_run,
)
from app.services.connector_execution.shared.runtime import (
    mark_connector_run_failed as _mark_drive_files_run_failed,
)
from app.services.connector_execution.shared.runtime import (
    mark_connector_run_running as _mark_drive_files_run_running,
)
from app.services.connector_sync_state import get_resume_cursor, normalize_source_manifest, slice_items_from_cursor


def _build_drive_files_run_settings(cfg: dict[str, Any]) -> dict[str, Any]:
    access_settings = build_source_access_settings(cfg)
    source_acl = access_settings["source_acl"]
    return {
        "urls": _normalize_connector_string_list(cfg.get("urls")),
        "filename": cfg.get("filename") if isinstance(cfg.get("filename"), str) else None,
        "user_agent": cfg.get("user_agent") if isinstance(cfg.get("user_agent"), str) else None,
        **build_ingestion_options(cfg),
        "access": access_settings["access"],
        "source_acl": source_acl,
        "auth_headers": _build_auth_headers(cfg),
        "source_acl_mode": access_settings["source_acl_mode"],
        "source_acl_fallback_mode": access_settings["source_acl_fallback_mode"],
        "allow_anyone": bool(source_acl.get("allow_anyone", False)) if isinstance(source_acl, dict) else False,
        "access_mode": access_settings["access_mode"],
        "has_manual_access_override": access_settings["has_manual_access_override"],
        "enable_source_acl": access_settings["enable_source_acl"],
    }


async def _discover_drive_sources(
    client: httpx.AsyncClient,
    *,
    settings_map: dict[str, Any],
) -> list[tuple[str, str, str | None, str]]:
    discovered_sources: list[tuple[str, str, str | None, str]] = []
    for source_url in settings_map.get("urls") or []:
        file_id_raw = _extract_drive_file_id(source_url)
        file_id = _optional_source_text(file_id_raw)
        source_ref = _drive_source_ref(
            file_id=file_id_raw,
            source_url=source_url,
        )
        source_token = await _drive_fetch_file_sync_token(
            client=client,
            file_id=file_id,
            source_url=source_url,
            headers=dict(settings_map.get("auth_headers") or {}),
        )
        discovered_sources.append((source_url, source_ref, file_id, source_token))
    return discovered_sources


def _build_drive_files_execution_plan(
    *,
    run_stats: dict[str, Any],
    state: dict[str, Any],
    discovered_sources: list[tuple[str, str, str, str]],
    enable_source_acl: bool,
) -> dict[str, Any]:
    existing_manifest = normalize_source_manifest(state.get("source_manifest"))
    tracked_source_refs = set(existing_manifest)
    resume_cursor_raw = get_resume_cursor(state)
    is_resume_run = bool((run_stats or {}).get("resume_of")) or bool((not existing_manifest) and resume_cursor_raw > 0)
    mode = "incremental" if existing_manifest else "full"

    observed_tracked_refs: set[str] = set()
    delta_sources: list[tuple[str, str, str, str]] = []
    skipped_unchanged = 0
    for source_url, source_ref, file_id, source_token in discovered_sources:
        if source_ref in tracked_source_refs:
            observed_tracked_refs.add(source_ref)
        if (not enable_source_acl) and mode == "incremental" and existing_manifest.get(source_ref) == source_token:
            skipped_unchanged += 1
            continue
        delta_sources.append((source_url, source_ref, file_id, source_token))

    removed_source_refs = sorted(tracked_source_refs - observed_tracked_refs) if mode == "incremental" else []
    resume_cursor = resume_cursor_raw if (is_resume_run and mode == "full") else 0
    sources_to_process, cursor_in = slice_items_from_cursor(
        delta_sources,
        cursor=resume_cursor,
    )
    source_manifest_state = {
        source_ref: token for source_ref, token in existing_manifest.items() if source_ref not in removed_source_refs
    }
    processed_visible = skipped_unchanged + cursor_in

    return {
        "mode": mode,
        "delta_sources": delta_sources,
        "removed_source_refs": removed_source_refs,
        "sources_to_process": sources_to_process,
        "cursor_in": int(cursor_in),
        "skipped_unchanged": int(skipped_unchanged),
        "processed_visible": int(processed_visible),
        "source_manifest_state": source_manifest_state,
        "resumed_from_state": bool(is_resume_run and ((mode == "incremental") or cursor_in > 0)),
    }


def _initialize_drive_files_run_stats(
    *,
    run: ConnectorRun,
    plan: dict[str, Any],
    discovered_sources: list[tuple[str, str, str, str]],
) -> dict[str, Any]:
    stats = dict(run.stats or {})
    stats.update(
        {
            "mode": plan.get("mode"),
            "total_urls": int(len(discovered_sources)),
            "delta_urls": int(len(plan.get("delta_sources") or [])),
            "skipped_unchanged": int(plan.get("skipped_unchanged") or 0),
            "processed_urls": int(plan.get("processed_visible") or 0),
            "cursor": int(plan.get("cursor_in") or 0),
            "created": 0,
            "failed": 0,
            "failed_urls": [],
            "cursor_in": int(plan.get("cursor_in") or 0),
            "resumed_from_state": bool(plan.get("resumed_from_state")),
            "removed_paths": int(len(plan.get("removed_source_refs") or [])),
            "removed_paths_reconciled": 0,
            "removed_documents_disabled": 0,
            "source_manifest": dict(plan.get("source_manifest_state") or {}),
        }
    )
    return stats


def _drive_files_run_cancelled(db: Session, *, run: ConnectorRun) -> bool:
    with contextlib.suppress(Exception):
        db.refresh(run)
    return run.status.lower() == "cancelled"


async def _resolve_drive_source_acl(
    client: httpx.AsyncClient,
    db: Session,
    *,
    tenant_id: UUID,
    run_id: UUID,
    settings_map: dict[str, Any],
    file_id: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    effective_access = settings_map.get("access")
    acl_provenance: dict[str, Any] | None = None

    if not settings_map.get("enable_source_acl"):
        return (effective_access if isinstance(effective_access, dict) else None), None

    ext_ids: list[str] = []
    mapped_gids: set[UUID] = set()
    has_anyone = False
    fallback_used = False
    try:
        ext_ids, has_anyone = _drive_permission_external_ids_and_anyone(
            await _drive_fetch_file_permissions(
                client=client,
                file_id=file_id,
                headers=dict(settings_map.get("auth_headers") or {}),
            )
        )

        if has_anyone and bool(settings_map.get("allow_anyone")):
            effective_access, mapped_gids = resolve_configured_source_access(
                source_system="drive",
                source_acl_config=settings_map["source_acl"],
                principal_keys=ext_ids,
                has_anyone=True,
            )
            fallback_used = effective_access.get("mode") != "all_team_members"
        elif (source_acl_config := settings_map.get("source_acl")) and source_acl_config.get("group_mappings"):
            effective_access, mapped_gids = resolve_configured_source_access(
                source_system="drive",
                source_acl_config=source_acl_config,
                principal_keys=ext_ids,
                has_anyone=has_anyone,
            )
            fallback_used = effective_access.get("mode") != "partial_members" or not mapped_gids
        else:
            mapped_gids = _resolve_tenant_group_ids_by_external_id(
                db,
                tenant_id=tenant_id,
                external_ids=ext_ids,
            )
            if mapped_gids:
                ordered = sorted(mapped_gids, key=lambda value: str(value))
                effective_access = {
                    "mode": "partial_members",
                    "partial_group_list": [str(group_id) for group_id in ordered],
                }
                fallback_used = False
            else:
                effective_access = {"mode": str(settings_map.get("source_acl_fallback_mode") or "partial_members")}
                fallback_used = True
    except Exception:
        effective_access = {"mode": str(settings_map.get("source_acl_fallback_mode") or "partial_members")}
        fallback_used = True

    with contextlib.suppress(Exception):
        from app.services.document_acl_provenance_service import build_document_acl_provenance

        acl_provenance = build_document_acl_provenance(
            connector_id="drive_files",
            connector_run_id=str(run_id),
            effective_access=effective_access,
            source_acl_mode=str(settings_map.get("source_acl_mode") or "disabled"),
            source_acl_fallback_mode=str(settings_map.get("source_acl_fallback_mode") or "partial_members"),
            source_principal_external_ids=ext_ids,
            mapped_group_ids=mapped_gids,
            fallback_used=fallback_used,
            allow_anyone=bool(settings_map.get("allow_anyone")),
            anyone_detected=has_anyone,
        )

    return (effective_access if isinstance(effective_access, dict) else None), acl_provenance


async def _ingest_drive_file_source(
    client: httpx.AsyncClient,
    db: Session,
    *,
    run: ConnectorRun,
    run_id: UUID,
    tenant_id: UUID,
    requested_by: str,
    source_ref: str,
    file_id: str,
    settings_map: dict[str, Any],
) -> dict[str, Any]:
    if not file_id:
        raise ValueError("unsupported_drive_url")

    effective_access, acl_provenance = await _resolve_drive_source_acl(
        client,
        db,
        tenant_id=tenant_id,
        run_id=run_id,
        settings_map=settings_map,
        file_id=file_id,
    )

    dl_url = _drive_direct_download_url(file_id)
    updated_existing = 0
    connector_config_id = _connector_config_id_from_run(run)
    if settings_map.get("enable_source_acl"):
        updated_existing = int(
            _delta_sync_connector_documents_acl_by_source_url(
                db,
                tenant_id=tenant_id,
                dataset_id=run.dataset_id,
                connector_id="drive_files",
                source_url=dl_url,
                requested_by=requested_by,
                access=effective_access,
                acl_provenance=acl_provenance,
                connector_config_id=connector_config_id,
            )
        )

    body = UrlUploadRequest(
        url=dl_url,
        dataset_id=run.dataset_id,
        filename=settings_map.get("filename"),
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
        connector_id="drive_files",
    )
    if isinstance(acl_provenance, dict):
        with contextlib.suppress(Exception):
            from app.services.document_acl_provenance_service import apply_document_acl_provenance

            apply_document_acl_provenance(doc, provenance=acl_provenance)
    _apply_connector_identity_metadata(
        doc=doc,
        run=run,
        connector_id="drive_files",
        source_ref=source_ref,
        source_id=file_id,
    )
    db.add(
        ConnectorRunDocument(
            tenant_id=tenant_id,
            run_id=run.id,
            document_id=doc.id,
            source_ref=source_ref,
            status="created",
        )
    )
    return {
        "doc_id": doc.id,
        "updated_existing": int(updated_existing),
    }


def _persist_drive_files_progress(
    db: Session,
    *,
    run: ConnectorRun,
    plan: dict[str, Any],
    discovered_sources: list[tuple[str, str, str, str]],
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
            "total_urls": int(len(discovered_sources)),
            "delta_urls": int(len(plan.get("delta_sources") or [])),
            "skipped_unchanged": int(plan.get("skipped_unchanged") or 0),
            "processed_urls": int(processed_visible),
            "cursor": int(processed),
            "created": int(created),
            "failed": int(failed),
            "removed_paths": int(len(plan.get("removed_source_refs") or [])),
            "removed_paths_reconciled": int(removed_paths_reconciled),
            "removed_documents_disabled": int(removed_documents_disabled),
            "source_manifest": dict(source_manifest_state),
            "document_ids": [str(doc_id) for doc_id in created_doc_ids],
            "acl_delta_sync_updated_documents": int(delta_acl_docs_updated),
            "acl_delta_sync_updated_sources": int(delta_acl_sources_updated),
        }
    )
    run.stats = _finalize_connector_stats(stats)
    db.commit()


async def _process_drive_files_sources(
    client: httpx.AsyncClient,
    db: Session,
    *,
    run: ConnectorRun,
    run_id: UUID,
    tenant_id: UUID,
    requested_by: str,
    settings_map: dict[str, Any],
    discovered_sources: list[tuple[str, str, str, str]],
    plan: dict[str, Any],
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

    for idx, item in enumerate(plan.get("sources_to_process") or []):
        source_url, source_ref, file_id, source_token = item if isinstance(item, tuple) else ("", "", "", "")
        succeeded = False
        if _drive_files_run_cancelled(db, run=run):
            break

        try:
            result = await _ingest_drive_file_source(
                client,
                db,
                run=run,
                run_id=run_id,
                tenant_id=tenant_id,
                requested_by=requested_by,
                source_ref=source_ref,
                file_id=file_id,
                settings_map=settings_map,
            )
            created += 1
            created_doc_ids.append(result["doc_id"])
            delta_acl_docs_updated += int(result.get("updated_existing") or 0)
            if int(result.get("updated_existing") or 0):
                delta_acl_sources_updated += 1
            succeeded = True
        except Exception as exc:  # noqa: BLE001
            failed += 1
            run.stats = _append_connector_error(
                dict(run.stats or {}),
                url=source_url or source_ref,
                exc=exc,
            )
        finally:
            if succeeded:
                source_manifest_state[source_ref] = source_token
            _persist_drive_files_progress(
                db,
                run=run,
                plan=plan,
                discovered_sources=discovered_sources,
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


def _reconcile_removed_drive_sources(
    db: Session,
    *,
    run: ConnectorRun,
    tenant_id: UUID,
    removed_source_refs: list[str],
) -> tuple[int, int]:
    removed_paths_reconciled = 0
    removed_documents_disabled = 0
    connector_config_id = _connector_config_id_from_run(run)
    for source_ref in removed_source_refs:
        try:
            if str(source_ref).startswith("url:"):
                disabled = _soft_disable_connector_documents_by_source_ref(
                    db,
                    tenant_id=tenant_id,
                    dataset_id=run.dataset_id,
                    connector_id="drive_files",
                    source_ref=source_ref,
                    connector_config_id=connector_config_id,
                )
            else:
                disabled = _soft_disable_connector_documents_by_source_url(
                    db,
                    tenant_id=tenant_id,
                    dataset_id=run.dataset_id,
                    connector_id="drive_files",
                    source_url=_drive_direct_download_url(source_ref),
                    connector_config_id=connector_config_id,
                )
        except Exception as exc:  # noqa: BLE001
            stats = _append_connector_error(dict(run.stats or {}), url=source_ref, exc=exc)
            run.stats = _finalize_connector_stats(stats)
            db.commit()
            continue
        removed_documents_disabled += int(disabled)
        if disabled:
            removed_paths_reconciled += 1
    return removed_paths_reconciled, removed_documents_disabled


def _emit_drive_files_source_acl_delta_sync_audit(
    db: Session,
    *,
    tenant_id: UUID,
    requested_by: str,
    run: ConnectorRun,
    run_id: UUID,
    settings_map: dict[str, Any],
    progress: dict[str, Any],
) -> None:
    if not settings_map.get("enable_source_acl"):
        return
    with contextlib.suppress(Exception):
        from app.services.audit_log_service import audit_log_event

        audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=requested_by,
            action="drive_files.source_acl.delta_sync",
            resource_type="connector_run",
            resource_id=str(run_id),
            details={
                "dataset_id": str(run.dataset_id),
                "connector_id": "drive_files",
                "updated_documents": int(progress.get("delta_acl_docs_updated") or 0),
                "updated_sources": int(progress.get("delta_acl_sources_updated") or 0),
                "allow_anyone": bool(settings_map.get("allow_anyone")),
                "fallback_mode": str(settings_map.get("source_acl_fallback_mode") or "partial_members"),
            },
        )


def _finalize_drive_files_run_success(
    db: Session,
    *,
    run: ConnectorRun,
    tenant_id: UUID,
    requested_by: str,
    run_id: UUID,
    settings_map: dict[str, Any],
    plan: dict[str, Any],
    progress: dict[str, Any],
) -> None:
    stats = dict(run.stats or {})
    stats.update(
        {
            "mode": plan.get("mode"),
            "delta_urls": int(len(plan.get("delta_sources") or [])),
            "skipped_unchanged": int(plan.get("skipped_unchanged") or 0),
            "document_ids": [str(doc_id) for doc_id in (progress.get("created_doc_ids") or [])],
            "acl_delta_sync_updated_documents": int(progress.get("delta_acl_docs_updated") or 0),
            "acl_delta_sync_updated_sources": int(progress.get("delta_acl_sources_updated") or 0),
            "removed_paths": int(len(plan.get("removed_source_refs") or [])),
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
    _emit_drive_files_source_acl_delta_sync_audit(
        db,
        tenant_id=tenant_id,
        requested_by=requested_by,
        run=run,
        run_id=run_id,
        settings_map=settings_map,
        progress=progress,
    )
    db.commit()
    with contextlib.suppress(Exception):
        _sync_connector_config_from_run(db, run=run)


async def execute(*, run_id: UUID, tenant_id: UUID, requested_by: str) -> None:
    """
    Background execution for drive_files connector.
    """
    db = SessionLocal()
    run: ConnectorRun | None = None
    drive_client = None
    try:
        run = _get_drive_files_run(db, run_id=run_id, tenant_id=tenant_id)
        if run is None:
            return

        _mark_drive_files_run_running(db, run=run)
        cfg = decrypt_connector_config_secrets(dict(run.config or {}))
        settings_map = _build_drive_files_run_settings(cfg)
        state = cfg.get("_state") if isinstance(cfg.get("_state"), dict) else {}

        httpx_mod = httpx
        drive_client = httpx_mod.AsyncClient(timeout=httpx_mod.Timeout(30.0))
        discovered_sources = await _discover_drive_sources(drive_client, settings_map=settings_map)
        plan = _build_drive_files_execution_plan(
            run_stats=dict(run.stats or {}),
            state=state,
            discovered_sources=discovered_sources,
            enable_source_acl=bool(settings_map.get("enable_source_acl")),
        )
        run.stats = _finalize_connector_stats(
            _initialize_drive_files_run_stats(
                run=run,
                plan=plan,
                discovered_sources=discovered_sources,
            )
        )
        db.commit()

        progress = await _process_drive_files_sources(
            drive_client,
            db,
            run=run,
            run_id=run_id,
            tenant_id=tenant_id,
            requested_by=requested_by,
            settings_map=settings_map,
            discovered_sources=discovered_sources,
            plan=plan,
        )

        if _drive_files_run_cancelled(db, run=run):
            _finalize_cancelled_drive_files_run(db, run=run)
            return

        removed_source_refs = list(plan.get("removed_source_refs") or [])
        if plan.get("mode") == "incremental" and removed_source_refs:
            removed_paths_reconciled, removed_documents_disabled = _reconcile_removed_drive_sources(
                db,
                run=run,
                tenant_id=tenant_id,
                removed_source_refs=removed_source_refs,
            )
            progress["removed_paths_reconciled"] = int(removed_paths_reconciled)
            progress["removed_documents_disabled"] = int(removed_documents_disabled)

        _finalize_drive_files_run_success(
            db,
            run=run,
            tenant_id=tenant_id,
            requested_by=requested_by,
            run_id=run_id,
            settings_map=settings_map,
            plan=plan,
            progress=progress,
        )
    except Exception as exc:  # noqa: BLE001
        _mark_drive_files_run_failed(db, run_id=run_id, tenant_id=tenant_id, exc=exc)
    finally:
        if drive_client is not None:
            with contextlib.suppress(Exception):
                await drive_client.aclose()
        db.close()
