import contextlib
import sys
from typing import Any
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


def _get_drive_files_run(db: Session, *, run_id: UUID, tenant_id: UUID) -> ConnectorRun | None:
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


def _mark_drive_files_run_running(db: Session, *, run: ConnectorRun) -> None:
    run.status = "running"
    run.started_at = _resolve_connectors_helper("_now")()
    run.error_message = None
    run.stats = dict(run.stats or {})
    db.commit()
    db.refresh(run)


def _build_drive_files_run_settings(cfg: dict[str, Any]) -> dict[str, Any]:
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
    return {
        "urls": _resolve_connectors_helper("_normalize_connector_string_list")(cfg.get("urls")),
        "filename": cfg.get("filename") if isinstance(cfg.get("filename"), str) else None,
        "user_agent": cfg.get("user_agent") if isinstance(cfg.get("user_agent"), str) else None,
        "parser_backend": cfg.get("parser_backend") if isinstance(cfg.get("parser_backend"), str) else "auto",
        "chunk_strategy": (
            cfg.get("chunk_strategy") if isinstance(cfg.get("chunk_strategy"), str) else "langchain_recursive"
        ),
        "pipeline": cfg.get("pipeline") if isinstance(cfg.get("pipeline"), dict) else None,
        "access": access,
        "source_acl": source_acl,
        "auth_headers": _resolve_connectors_helper("_build_auth_headers")(cfg),
        "source_acl_mode": source_acl_mode,
        "source_acl_fallback_mode": source_acl_fallback_mode,
        "allow_anyone": bool(source_acl.get("allow_anyone", False)) if isinstance(source_acl, dict) else False,
        "access_mode": access_mode,
        "has_manual_access_override": has_manual_access_override,
        "enable_source_acl": bool(source_acl_mode == "inherit" and not has_manual_access_override),
    }


async def _discover_drive_sources(
    client,
    *,
    settings_map: dict[str, Any],
) -> list[tuple[str, str, str, str]]:
    discovered_sources: list[tuple[str, str, str, str]] = []
    for source_url in settings_map.get("urls") or []:
        file_id_raw = _resolve_connectors_helper("_extract_drive_file_id")(str(source_url or ""))
        file_id = str(file_id_raw or "").strip()
        source_ref = _resolve_connectors_helper("_drive_source_ref")(
            file_id=file_id_raw,
            source_url=str(source_url or ""),
        )
        source_token = await _resolve_connectors_helper("_drive_fetch_file_sync_token")(
            client=client,
            file_id=file_id,
            source_url=str(source_url or ""),
            headers=dict(settings_map.get("auth_headers") or {}),
        )
        discovered_sources.append((str(source_url or ""), source_ref, file_id, source_token))
    return discovered_sources


def _build_drive_files_execution_plan(
    *,
    run_stats: dict[str, Any],
    state: dict[str, Any],
    discovered_sources: list[tuple[str, str, str, str]],
    enable_source_acl: bool,
) -> dict[str, Any]:
    existing_manifest = _resolve_connectors_helper("normalize_source_manifest")(state.get("source_manifest"))
    tracked_source_refs = set(existing_manifest)
    resume_cursor_raw = _resolve_connectors_helper("get_resume_cursor")(state)
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
    sources_to_process, cursor_in = _resolve_connectors_helper("slice_items_from_cursor")(
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
    return str(run.status or "").lower() == "cancelled"


async def _resolve_drive_source_acl(
    client,
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
        ext_ids, has_anyone = _resolve_connectors_helper("_drive_permission_external_ids_and_anyone")(
            await _resolve_connectors_helper("_drive_fetch_file_permissions")(
                client=client,
                file_id=file_id,
                headers=dict(settings_map.get("auth_headers") or {}),
            )
        )

        if has_anyone and bool(settings_map.get("allow_anyone")):
            effective_access = {"mode": "all_team_members"}
            fallback_used = False
        else:
            mapped_gids = _resolve_connectors_helper("_resolve_tenant_group_ids_by_external_id")(
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
    client,
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

    dl_url = _resolve_connectors_helper("_drive_direct_download_url")(file_id)
    updated_existing = 0
    connector_config_id = _resolve_connectors_helper("_connector_config_id_from_run")(run)
    if settings_map.get("enable_source_acl"):
        updated_existing = int(
            _resolve_connectors_helper("_delta_sync_connector_documents_acl_by_source_url")(
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

    body = _resolve_connectors_helper("UrlUploadRequest")(
        url=dl_url,
        dataset_id=run.dataset_id,
        filename=settings_map.get("filename"),
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
        connector_id="drive_files",
    )
    if isinstance(acl_provenance, dict):
        with contextlib.suppress(Exception):
            from app.services.document_acl_provenance_service import apply_document_acl_provenance

            apply_document_acl_provenance(doc, provenance=acl_provenance)
    _resolve_connectors_helper("_apply_connector_identity_metadata")(
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
    run.stats = _resolve_connectors_helper("_finalize_connector_stats")(stats)
    db.commit()


async def _process_drive_files_sources(
    client,
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
        if _resolve_connectors_helper("_drive_files_run_cancelled")(db, run=run):
            break

        try:
            result = await _resolve_connectors_helper("_ingest_drive_file_source")(
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
            run.stats = _resolve_connectors_helper("_append_connector_error")(
                dict(run.stats or {}),
                url=source_url or source_ref,
                exc=exc,
            )
        finally:
            if succeeded:
                source_manifest_state[source_ref] = source_token
            _resolve_connectors_helper("_persist_drive_files_progress")(
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


def _finalize_cancelled_drive_files_run(db: Session, *, run: ConnectorRun) -> None:
    if run.finished_at is None:
        run.finished_at = _resolve_connectors_helper("_now")()
    run.stats = _resolve_connectors_helper("_finalize_connector_stats")(dict(run.stats or {}))
    db.commit()
    with contextlib.suppress(Exception):
        _resolve_connectors_helper("_sync_connector_config_from_run")(db, run=run)


def _reconcile_removed_drive_sources(
    db: Session,
    *,
    run: ConnectorRun,
    tenant_id: UUID,
    removed_source_refs: list[str],
) -> tuple[int, int]:
    removed_paths_reconciled = 0
    removed_documents_disabled = 0
    connector_config_id = _resolve_connectors_helper("_connector_config_id_from_run")(run)
    for source_ref in removed_source_refs:
        try:
            if str(source_ref).startswith("url:"):
                disabled = _resolve_connectors_helper("_soft_disable_connector_documents_by_source_ref")(
                    db,
                    tenant_id=tenant_id,
                    dataset_id=run.dataset_id,
                    connector_id="drive_files",
                    source_ref=source_ref,
                    connector_config_id=connector_config_id,
                )
            else:
                disabled = _resolve_connectors_helper("_soft_disable_connector_documents_by_source_url")(
                    db,
                    tenant_id=tenant_id,
                    dataset_id=run.dataset_id,
                    connector_id="drive_files",
                    source_url=_resolve_connectors_helper("_drive_direct_download_url")(source_ref),
                    connector_config_id=connector_config_id,
                )
        except Exception as exc:  # noqa: BLE001
            stats = _resolve_connectors_helper("_append_connector_error")(
                dict(run.stats or {}), url=source_ref, exc=exc
            )
            run.stats = _resolve_connectors_helper("_finalize_connector_stats")(stats)
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
    run.stats = _resolve_connectors_helper("_finalize_connector_stats")(stats)
    run.finished_at = _resolve_connectors_helper("_now")()
    run.status = _resolve_connectors_helper("_connector_run_completion_status")(
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
        _resolve_connectors_helper("_sync_connector_config_from_run")(db, run=run)


def _mark_drive_files_run_failed(db: Session, *, run_id: UUID, tenant_id: UUID, exc: Exception) -> None:
    with contextlib.suppress(Exception):
        run = db.query(ConnectorRun).filter(ConnectorRun.id == run_id, ConnectorRun.tenant_id == tenant_id).first()
        if run is not None:
            run.status = "failed"
            run.finished_at = _resolve_connectors_helper("_now")()
            run.error_message = str(exc)[:200]
            db.commit()
            with contextlib.suppress(Exception):
                _resolve_connectors_helper("_sync_connector_config_from_run")(db, run=run)


async def _execute_drive_files_run(*, run_id: UUID, tenant_id: UUID, requested_by: str) -> None:
    """
    Background execution for drive_files connector.
    """
    db = _resolve_connectors_attr("SessionLocal")()
    run: ConnectorRun | None = None
    drive_client = None
    try:
        run = _get_drive_files_run(db, run_id=run_id, tenant_id=tenant_id)
        if run is None:
            return

        _mark_drive_files_run_running(db, run=run)
        cfg = _resolve_connectors_helper("decrypt_connector_config_secrets")(dict(run.config or {}))
        settings_map = _build_drive_files_run_settings(cfg)
        state = cfg.get("_state") if isinstance(cfg.get("_state"), dict) else {}

        httpx_mod = _resolve_connectors_attr("httpx")
        drive_client = httpx_mod.AsyncClient(timeout=httpx_mod.Timeout(30.0))
        discovered_sources = await _discover_drive_sources(drive_client, settings_map=settings_map)
        plan = _build_drive_files_execution_plan(
            run_stats=dict(run.stats or {}),
            state=state,
            discovered_sources=discovered_sources,
            enable_source_acl=bool(settings_map.get("enable_source_acl")),
        )
        run.stats = _resolve_connectors_helper("_finalize_connector_stats")(
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
