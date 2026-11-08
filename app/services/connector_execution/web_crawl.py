from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.api.schemas.document_ingestion import UrlUploadRequest
from app.core.database import SessionLocal
from app.core.secrets import decrypt_connector_config_secrets
from app.models.connector import ConnectorRun, ConnectorRunDocument
from app.models.document import Document
from app.services import document_ingestion as ingestion_service
from app.services.connector_document_access import (
    _apply_document_access_from_config,
    _soft_disable_connector_documents_by_source_url,
)
from app.services.connector_execution.plans.web_crawl import (
    WebCrawlExecutionPlan,
    _build_web_crawl_execution_plan,
    _initialize_web_crawl_run_stats,
    _web_crawl_build_doc_sync_token,
)
from app.services.connector_execution.shared.artifacts import (
    _apply_connector_identity_metadata,
    _normalize_connector_principal_list,
    _normalize_connector_string_list,
)
from app.services.connector_execution.shared.common import (
    _append_connector_error,
    _connector_run_completion_status,
    _finalize_connector_stats,
    build_ingestion_options,
)
from app.services.connector_execution.shared.external import _build_auth_headers
from app.services.connector_execution.shared.runtime import (
    _now,
    _sync_connector_config_from_run,
)
from app.services.connector_execution.shared.runtime import (
    finalize_cancelled_connector_run as _finalize_cancelled_web_crawl_run,
)
from app.services.connector_execution.shared.runtime import (
    get_active_connector_run as _get_web_crawl_run,
)
from app.services.connector_execution.shared.runtime import (
    mark_connector_run_failed as _mark_web_crawl_run_failed,
)
from app.services.connector_execution.shared.runtime import (
    mark_connector_run_running as _mark_web_crawl_run_running,
)

if TYPE_CHECKING:
    from app.services.web_crawler import WebCrawlResult


async def crawl_site(**kwargs: Any) -> WebCrawlResult:
    from app.services.web_crawler import crawl_site as crawl

    return await crawl(**kwargs)


def _build_web_crawl_run_settings(cfg: dict[str, Any]) -> dict[str, Any]:
    access = cfg.get("access") if isinstance(cfg.get("access"), dict) else None
    access_mode = str(access.get("mode") or "inherit").strip().lower() if isinstance(access, dict) else "inherit"
    return {
        "state": cfg.get("_state") if isinstance(cfg.get("_state"), dict) else {},
        "start_urls": _normalize_connector_string_list(cfg.get("start_urls")),
        "max_pages": int(cfg.get("max_pages") or 50),
        "max_depth": int(cfg.get("max_depth") or 3),
        "same_host_only": bool(cfg.get("same_host_only", True)),
        "include_patterns": _normalize_connector_string_list(cfg.get("include_patterns")),
        "exclude_patterns": _normalize_connector_string_list(cfg.get("exclude_patterns")),
        "use_sitemaps": bool(cfg.get("use_sitemaps", False)),
        "sitemap_urls": _normalize_connector_string_list(cfg.get("sitemap_urls")),
        "respect_robots": bool(cfg.get("respect_robots", False)),
        "dedup_canonical": bool(cfg.get("dedup_canonical", True)),
        "user_agent": cfg.get("user_agent") if isinstance(cfg.get("user_agent"), str) else None,
        "filename": cfg.get("filename") if isinstance(cfg.get("filename"), str) else None,
        **build_ingestion_options(cfg),
        "access_mode": access_mode,
        "access_members": _normalize_connector_principal_list(
            access.get("partial_member_list") if isinstance(access, dict) else None
        ),
        "access_groups": _normalize_connector_principal_list(
            access.get("partial_group_list") if isinstance(access, dict) else None
        ),
        "auth_headers": _build_auth_headers(cfg),
    }


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
) -> Document:
    body = UrlUploadRequest(
        url=url,
        dataset_id=run.dataset_id,
        filename=settings_map.get("filename"),
        fetch_headers=settings_map.get("auth_headers"),
        user_agent=settings_map.get("user_agent"),
        parser_backend=settings_map.get("parser_backend"),
        chunk_strategy=settings_map.get("chunk_strategy"),
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
        access={
            "mode": settings_map.get("access_mode"),
            "partial_member_list": list(settings_map.get("access_members") or []),
            "partial_group_list": list(settings_map.get("access_groups") or []),
        },
        connector_id="web_crawl",
    )
    _apply_connector_identity_metadata(
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
    plan: WebCrawlExecutionPlan,
    idx: int,
    url: str,
    created: int,
    failed: int,
    created_doc_ids: list[UUID],
    source_manifest_state: dict[str, str],
    removed_urls_reconciled: int,
    removed_documents_disabled: int,
    succeeded: bool,
    ingested_doc: Document | None,
) -> None:
    discovered_manifest = dict(plan.get("discovered_manifest") or {})
    if succeeded and url and url in discovered_manifest:
        token = str(discovered_manifest.get(url) or "").strip()
        if ingested_doc is not None:
            with contextlib.suppress(Exception):
                token = _web_crawl_build_doc_sync_token(
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
    run.stats = _finalize_connector_stats(stats)
    db.commit()


async def _process_web_crawl_urls(
    db: Session,
    *,
    run: ConnectorRun,
    tenant_id: UUID,
    requested_by: str,
    settings_map: dict[str, Any],
    plan: WebCrawlExecutionPlan,
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
            run.stats = _append_connector_error(dict(run.stats or {}), url=str(url or ""), exc=exc)

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
            disabled = _soft_disable_connector_documents_by_source_url(
                db,
                tenant_id=tenant_id,
                dataset_id=run.dataset_id,
                connector_id="web_crawl",
                source_url=source_url,
            )
        except Exception as exc:  # noqa: BLE001
            stats = _append_connector_error(dict(run.stats or {}), url=source_url, exc=exc)
            run.stats = _finalize_connector_stats(stats)
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
    plan: WebCrawlExecutionPlan,
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
    run.stats = _finalize_connector_stats(stats)
    run.finished_at = _now()
    run.status = _connector_run_completion_status(created=created, failed=failed)
    db.commit()
    with contextlib.suppress(Exception):
        _sync_connector_config_from_run(db, run=run)


async def execute(*, run_id: UUID, tenant_id: UUID, requested_by: str) -> None:
    db = SessionLocal()
    try:
        run = _get_web_crawl_run(db, run_id=run_id, tenant_id=tenant_id)
        if not run:
            return

        _mark_web_crawl_run_running(db, run=run)

        settings_map = _build_web_crawl_run_settings(decrypt_connector_config_secrets(dict(run.config or {})))
        crawl = await crawl_site(
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

        plan = _build_web_crawl_execution_plan(
            run_stats=dict(run.stats or {}),
            state=dict(settings_map.get("state") or {}),
            crawl_urls=list(crawl.urls),
            crawl_sync_tokens=dict(crawl.sync_tokens),
        )
        run.stats = _finalize_connector_stats(_initialize_web_crawl_run_stats(run=run, crawl=crawl, plan=plan))
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
