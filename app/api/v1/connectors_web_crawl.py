import contextlib
import sys
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session, selectinload

from app.models.connector import ConnectorRun, ConnectorRunDocument


def _resolve_connectors_helper(name: str):  # noqa: ANN202
    leader_module = globals().get("_leader_module")
    helper = getattr(leader_module, name, None) if leader_module is not None else None
    if callable(helper):
        return helper

    preferred_modules = (
        "test_saved_state_connectors",
        "test_support_connectors_module",
        "app.api.v1.connectors",
    )
    for module_name in preferred_modules:
        for key, module in sys.modules.items():
            if key == module_name or key.startswith(f"{module_name}_"):
                helper = getattr(module, name, None) if module is not None else None
                if callable(helper):
                    return helper

    for module in reversed(tuple(sys.modules.values())):
        path = str(getattr(module, "__file__", "") or "")
        if not path.endswith("/app/api/v1/connectors.py"):
            continue
        helper = getattr(module, name, None)
        if callable(helper):
            return helper

    raise RuntimeError(f"connectors helper not available: {name}")


def _build_web_crawl_run_settings(cfg: dict[str, Any]) -> dict[str, Any]:
    access = cfg.get("access") if isinstance(cfg.get("access"), dict) else None
    access_mode = str(access.get("mode") or "inherit").strip().lower() if isinstance(access, dict) else "inherit"
    return {
        "state": cfg.get("_state") if isinstance(cfg.get("_state"), dict) else {},
        "start_urls": _resolve_connectors_helper("_normalize_connector_string_list")(cfg.get("start_urls")),
        "max_pages": int(cfg.get("max_pages") or 50),
        "max_depth": int(cfg.get("max_depth") or 3),
        "same_host_only": bool(cfg.get("same_host_only", True)),
        "include_patterns": _resolve_connectors_helper("_normalize_connector_string_list")(cfg.get("include_patterns")),
        "exclude_patterns": _resolve_connectors_helper("_normalize_connector_string_list")(cfg.get("exclude_patterns")),
        "use_sitemaps": bool(cfg.get("use_sitemaps", False)),
        "sitemap_urls": _resolve_connectors_helper("_normalize_connector_string_list")(cfg.get("sitemap_urls")),
        "respect_robots": bool(cfg.get("respect_robots", False)),
        "dedup_canonical": bool(cfg.get("dedup_canonical", True)),
        "user_agent": cfg.get("user_agent") if isinstance(cfg.get("user_agent"), str) else None,
        "filename": cfg.get("filename") if isinstance(cfg.get("filename"), str) else None,
        "parser_backend": cfg.get("parser_backend") if isinstance(cfg.get("parser_backend"), str) else "auto",
        "chunk_strategy": (
            cfg.get("chunk_strategy") if isinstance(cfg.get("chunk_strategy"), str) else "langchain_recursive"
        ),
        "pipeline": cfg.get("pipeline") if isinstance(cfg.get("pipeline"), dict) else None,
        "access_mode": access_mode,
        "access_members": _resolve_connectors_helper("_normalize_connector_principal_list")(
            access.get("partial_member_list") if isinstance(access, dict) else None
        ),
        "access_groups": _resolve_connectors_helper("_normalize_connector_principal_list")(
            access.get("partial_group_list") if isinstance(access, dict) else None
        ),
        "auth_headers": _resolve_connectors_helper("_build_auth_headers")(cfg),
    }


def _get_web_crawl_run(db: Session, *, run_id: UUID, tenant_id: UUID) -> ConnectorRun | None:
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


def _mark_web_crawl_run_running(db: Session, *, run: ConnectorRun) -> None:
    run.status = "running"
    run.started_at = _resolve_connectors_helper("_now")()
    run.error_message = None
    run.stats = dict(run.stats or {})
    db.commit()
    db.refresh(run)


def _web_crawl_run_cancelled(db: Session, *, run: ConnectorRun) -> bool:
    with contextlib.suppress(Exception):
        db.refresh(run)
    return str(run.status or "").lower() == "cancelled"


async def _ingest_web_crawl_url(
    db: Session,
    *,
    run: ConnectorRun,
    tenant_id: UUID,
    requested_by: str,
    url: str,
    settings_map: dict[str, Any],
) -> Any:
    body = _resolve_connectors_helper("UrlUploadRequest")(
        url=url,
        dataset_id=run.dataset_id,
        filename=settings_map.get("filename"),
        fetch_headers=settings_map.get("auth_headers") or None,
        user_agent=settings_map.get("user_agent"),
        parser_backend=settings_map.get("parser_backend"),
        chunk_strategy=settings_map.get("chunk_strategy"),
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
        access={
            "mode": settings_map.get("access_mode"),
            "partial_member_list": list(settings_map.get("access_members") or []),
            "partial_group_list": list(settings_map.get("access_groups") or []),
        },
        connector_id="web_crawl",
    )
    _resolve_connectors_helper("_apply_connector_identity_metadata")(
        doc=doc,
        run=run,
        connector_id="web_crawl",
        source_ref=url,
        source_id=url,
    )

    db.add(
        ConnectorRunDocument(
            tenant_id=tenant_id,
            run_id=run.id,
            document_id=doc.id,
            source_ref=url,
            status="created",
        )
    )
    return doc


def _persist_web_crawl_progress(
    db: Session,
    *,
    run: ConnectorRun,
    plan: dict[str, Any],
    idx: int,
    url: str,
    created: int,
    failed: int,
    created_doc_ids: list[UUID],
    source_manifest_state: dict[str, str],
    removed_urls_reconciled: int,
    removed_documents_disabled: int,
    succeeded: bool,
    ingested_doc: Any,
) -> None:
    discovered_manifest = dict(plan.get("discovered_manifest") or {})
    if succeeded and url and url in discovered_manifest:
        token = str(discovered_manifest.get(url) or "").strip()
        if ingested_doc is not None:
            with contextlib.suppress(Exception):
                token = _resolve_connectors_helper("_web_crawl_build_doc_sync_token")(
                    source_url=url,
                    doc=ingested_doc,
                    crawl_token=token,
                )
        source_manifest_state[url] = token or discovered_manifest[url]

    processed = int(plan.get("cursor_in") or 0) + idx + 1
    processed_visible = int(plan.get("skipped_unchanged") or 0) + processed
    stats = dict(run.stats or {})
    stats.update(
        {
            "mode": plan.get("mode"),
            "total_urls": int(len(plan.get("discovered_urls") or [])),
            "delta_urls": int(len(plan.get("delta_urls") or [])),
            "skipped_unchanged": int(plan.get("skipped_unchanged") or 0),
            "processed_urls": int(processed_visible),
            "cursor": int(processed),
            "created": int(created),
            "failed": int(failed),
            "removed_paths": int(len(plan.get("removed_urls") or [])),
            "removed_paths_reconciled": int(removed_urls_reconciled),
            "removed_documents_disabled": int(removed_documents_disabled),
            "source_manifest": dict(source_manifest_state),
            "document_ids": [str(doc_id) for doc_id in created_doc_ids],
        }
    )
    run.stats = _resolve_connectors_helper("_finalize_connector_stats")(stats)
    db.commit()


async def _process_web_crawl_urls(
    db: Session,
    *,
    run: ConnectorRun,
    tenant_id: UUID,
    requested_by: str,
    settings_map: dict[str, Any],
    plan: dict[str, Any],
) -> dict[str, Any]:
    created = 0
    failed = 0
    created_doc_ids: list[UUID] = []
    source_manifest_state = dict(plan.get("source_manifest_state") or {})

    for idx, url in enumerate(plan.get("crawl_urls") or []):
        if _web_crawl_run_cancelled(db, run=run):
            break

        succeeded = False
        ingested_doc = None
        try:
            ingested_doc = await _ingest_web_crawl_url(
                db,
                run=run,
                tenant_id=tenant_id,
                requested_by=requested_by,
                url=str(url or ""),
                settings_map=settings_map,
            )
            created += 1
            created_doc_ids.append(ingested_doc.id)
            succeeded = True
        except Exception as exc:  # noqa: BLE001
            failed += 1
            run.stats = _resolve_connectors_helper("_append_connector_error")(
                dict(run.stats or {}), url=str(url or ""), exc=exc
            )

        _persist_web_crawl_progress(
            db,
            run=run,
            plan=plan,
            idx=idx,
            url=str(url or ""),
            created=created,
            failed=failed,
            created_doc_ids=created_doc_ids,
            source_manifest_state=source_manifest_state,
            removed_urls_reconciled=0,
            removed_documents_disabled=0,
            succeeded=succeeded,
            ingested_doc=ingested_doc,
        )

    return {
        "created": created,
        "failed": failed,
        "created_doc_ids": created_doc_ids,
        "source_manifest_state": source_manifest_state,
    }


def _finalize_cancelled_web_crawl_run(db: Session, *, run: ConnectorRun) -> None:
    if run.finished_at is None:
        run.finished_at = _resolve_connectors_helper("_now")()
    run.stats = _resolve_connectors_helper("_finalize_connector_stats")(dict(run.stats or {}))
    db.commit()
    with contextlib.suppress(Exception):
        _resolve_connectors_helper("_sync_connector_config_from_run")(db, run=run)


def _reconcile_removed_web_crawl_urls(
    db: Session,
    *,
    run: ConnectorRun,
    tenant_id: UUID,
    removed_urls: list[str],
) -> tuple[int, int]:
    removed_urls_reconciled = 0
    removed_documents_disabled = 0
    for source_url in removed_urls:
        try:
            disabled = _resolve_connectors_helper("_soft_disable_connector_documents_by_source_url")(
                db,
                tenant_id=tenant_id,
                dataset_id=run.dataset_id,
                connector_id="web_crawl",
                source_url=source_url,
            )
        except Exception as exc:  # noqa: BLE001
            stats = _resolve_connectors_helper("_append_connector_error")(
                dict(run.stats or {}), url=source_url, exc=exc
            )
            run.stats = _resolve_connectors_helper("_finalize_connector_stats")(stats)
            db.commit()
            continue
        removed_documents_disabled += int(disabled)
        if disabled:
            removed_urls_reconciled += 1
    return removed_urls_reconciled, removed_documents_disabled


def _finalize_web_crawl_run_success(
    db: Session,
    *,
    run: ConnectorRun,
    plan: dict[str, Any],
    created: int,
    failed: int,
    created_doc_ids: list[UUID],
    source_manifest_state: dict[str, str],
    removed_urls_reconciled: int,
    removed_documents_disabled: int,
) -> None:
    stats = dict(run.stats or {})
    stats.update(
        {
            "mode": plan.get("mode"),
            "delta_urls": int(len(plan.get("delta_urls") or [])),
            "skipped_unchanged": int(plan.get("skipped_unchanged") or 0),
            "removed_paths": int(len(plan.get("removed_urls") or [])),
            "removed_paths_reconciled": int(removed_urls_reconciled),
            "removed_documents_disabled": int(removed_documents_disabled),
            "source_manifest": dict(source_manifest_state),
            "document_ids": [str(doc_id) for doc_id in created_doc_ids],
        }
    )
    run.stats = _resolve_connectors_helper("_finalize_connector_stats")(stats)
    run.finished_at = _resolve_connectors_helper("_now")()
    run.status = _resolve_connectors_helper("_connector_run_completion_status")(created=created, failed=failed)
    db.commit()
    with contextlib.suppress(Exception):
        _resolve_connectors_helper("_sync_connector_config_from_run")(db, run=run)


def _mark_web_crawl_run_failed(db: Session, *, run_id: UUID, tenant_id: UUID, exc: Exception) -> None:
    with contextlib.suppress(Exception):
        run = db.query(ConnectorRun).filter(ConnectorRun.id == run_id, ConnectorRun.tenant_id == tenant_id).first()
        if run is not None:
            run.status = "failed"
            run.finished_at = _resolve_connectors_helper("_now")()
            run.error_message = str(exc)[:200]
            db.commit()
            with contextlib.suppress(Exception):
                _resolve_connectors_helper("_sync_connector_config_from_run")(db, run=run)


async def _execute_web_crawl_run(*, run_id: UUID, tenant_id: UUID, requested_by: str) -> None:
    db = _resolve_connectors_helper("SessionLocal")()
    try:
        run = _get_web_crawl_run(db, run_id=run_id, tenant_id=tenant_id)
        if not run:
            return

        _mark_web_crawl_run_running(db, run=run)

        settings_map = _build_web_crawl_run_settings(
            _resolve_connectors_helper("decrypt_connector_config_secrets")(dict(run.config or {}))
        )
        crawl = await _resolve_connectors_helper("crawl_site")(
            start_urls=list(settings_map.get("start_urls") or []),
            max_pages=int(settings_map.get("max_pages") or 0),
            max_depth=int(settings_map.get("max_depth") or 0),
            same_host_only=bool(settings_map.get("same_host_only")),
            include_patterns=list(settings_map.get("include_patterns") or []),
            exclude_patterns=list(settings_map.get("exclude_patterns") or []),
            use_sitemaps=bool(settings_map.get("use_sitemaps")),
            sitemap_urls=list(settings_map.get("sitemap_urls") or []),
            respect_robots=bool(settings_map.get("respect_robots")),
            dedup_canonical=bool(settings_map.get("dedup_canonical")),
            headers=dict(settings_map.get("auth_headers") or {}),
            user_agent=settings_map.get("user_agent"),
        )

        plan = _resolve_connectors_helper("_build_web_crawl_execution_plan")(
            run_stats=dict(run.stats or {}),
            state=dict(settings_map.get("state") or {}),
            crawl_urls=list(getattr(crawl, "urls", None) or []),
            crawl_sync_tokens=dict(getattr(crawl, "sync_tokens", None) or {}),
        )
        run.stats = _resolve_connectors_helper("_finalize_connector_stats")(
            _resolve_connectors_helper("_initialize_web_crawl_run_stats")(run=run, crawl=crawl, plan=plan)
        )
        db.commit()

        progress = await _process_web_crawl_urls(
            db,
            run=run,
            tenant_id=tenant_id,
            requested_by=requested_by,
            settings_map=settings_map,
            plan=plan,
        )
        if _web_crawl_run_cancelled(db, run=run):
            _finalize_cancelled_web_crawl_run(db, run=run)
            return

        removed_urls_reconciled = 0
        removed_documents_disabled = 0
        removed_urls = list(plan.get("removed_urls") or [])
        if plan.get("mode") == "incremental" and removed_urls:
            removed_urls_reconciled, removed_documents_disabled = _reconcile_removed_web_crawl_urls(
                db,
                run=run,
                tenant_id=tenant_id,
                removed_urls=removed_urls,
            )

        _finalize_web_crawl_run_success(
            db,
            run=run,
            plan=plan,
            created=int(progress.get("created") or 0),
            failed=int(progress.get("failed") or 0),
            created_doc_ids=list(progress.get("created_doc_ids") or []),
            source_manifest_state=dict(progress.get("source_manifest_state") or {}),
            removed_urls_reconciled=removed_urls_reconciled,
            removed_documents_disabled=removed_documents_disabled,
        )
    except Exception as exc:  # noqa: BLE001
        _mark_web_crawl_run_failed(db, run_id=run_id, tenant_id=tenant_id, exc=exc)
    finally:
        db.close()
