import asyncio
import contextlib
from typing import Any
from uuid import UUID

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.api.schemas.connector import (
    ConfluenceSpaceConnectorConfig,
    ConnectorRunCreateRequest,
    ConnectorRunOut,
    DriveFilesConnectorConfig,
    GitHubRepoConnectorConfig,
    JiraProjectConnectorConfig,
    MinioBucketConnectorConfig,
    MySQLCatalogConnectorConfig,
    SQLServerCatalogConnectorConfig,
    UrlBatchConnectorConfig,
    WebCrawlConnectorConfig,
)
from app.core.config import settings
from app.core.secrets import encrypt_connector_config_secrets, redact_secrets
from app.models.connector import ConnectorRun, ConnectorRunDocument
from app.models.dataset import Dataset, DatasetPermission, DatasetPermissionEnum
from app.models.document import Document as DBDocument
from app.models.document import DocumentPermission
from app.models.group_permissions import DatasetGroupPermission, DocumentGroupPermission
from app.models.tenant_group import TenantGroup, TenantGroupMember
from app.services import dataset_service
from app.services.connector_egress_policy import validate_db_connector_config
from app.services.connector_execution.shared.runtime import _now
from app.services.connector_registry import get_connector_definition
from app.services.connector_run_executor import _resolve_connector_executor
from app.services.connector_sync_state import build_persisted_state, get_resume_cursor, normalize_source_manifest
from app.services.dataset_service import EDIT_ROLES
from app.services.rbac_service import TenantPermissions, ensure_tenant_permission
from app.services.security_redaction import redact_connection_info
from app.tasks.queue import enqueue_connector_run, get_queue

_URL_INGEST_CONNECTOR_IDS = frozenset(
    {
        "url_batch",
        "web_crawl",
        "github_repo",
        "drive_files",
        "minio_bucket",
        "confluence_space",
        "jira_project",
    }
)
_DB_CATALOG_CONNECTOR_IDS = frozenset({"mysql_catalog", "sqlserver_catalog"})
_DB_CONNECTOR_IDS = _DB_CATALOG_CONNECTOR_IDS
CONNECTOR_RUN_NOT_FOUND_DETAIL = "Connector run not found"
UNSUPPORTED_CONNECTOR_ID_DETAIL = "Unsupported connector_id"
URL_INGEST_DISABLED_DETAIL = "URL ingestion is disabled"
CONNECTOR_QUEUE_UNAVAILABLE_DETAIL = "Connector processing queue unavailable"
CONNECTOR_QUEUE_HANDOFF_FAILED_ERROR = "connector_queue_handoff_failed"
_CONNECTOR_CONFIG_MODELS: dict[str, Any] = {
    "url_batch": UrlBatchConnectorConfig,
    "web_crawl": WebCrawlConnectorConfig,
    "github_repo": GitHubRepoConnectorConfig,
    "drive_files": DriveFilesConnectorConfig,
    "minio_bucket": MinioBucketConnectorConfig,
    "confluence_space": ConfluenceSpaceConnectorConfig,
    "jira_project": JiraProjectConnectorConfig,
    "mysql_catalog": MySQLCatalogConnectorConfig,
    "sqlserver_catalog": SQLServerCatalogConnectorConfig,
}
_DB_CONNECTOR_PERMISSION_DETAIL = "No permission to run DB connectors"


def _writable_dataset_ids_subquery(*, tenant_id: UUID, account_id: str):
    member_group_ids_subq = select(TenantGroupMember.group_id).where(
        TenantGroupMember.tenant_id == tenant_id,
        TenantGroupMember.user_id == account_id,
    )

    partial_member_exists = exists().where(
        DatasetPermission.tenant_id == tenant_id,
        DatasetPermission.dataset_id == Dataset.id,
        DatasetPermission.account_id == account_id,
    )
    partial_group_exists = exists().where(
        DatasetGroupPermission.tenant_id == tenant_id,
        DatasetGroupPermission.dataset_id == Dataset.id,
        DatasetGroupPermission.group_id.in_(member_group_ids_subq),
    )

    return select(Dataset.id).where(
        Dataset.tenant_id == tenant_id,
        or_(
            Dataset.owner_id == account_id,
            Dataset.permission == DatasetPermissionEnum.ALL_TEAM_MEMBERS,
            and_(
                Dataset.permission == DatasetPermissionEnum.PARTIAL_MEMBERS,
                or_(partial_member_exists, partial_group_exists),
            ),
        ),
    )


def _extract_failed_urls(stats: dict) -> list[str]:
    urls: list[str] = []
    raw_failed = stats.get("failed_urls")
    if isinstance(raw_failed, list):
        urls = [str(url or "").strip() for url in raw_failed if str(url or "").strip()]
    if not urls:
        raw_errors = stats.get("errors")
        if isinstance(raw_errors, list):
            urls = [str((error or {}).get("url") or "").strip() for error in raw_errors if isinstance(error, dict)]
            urls = [url for url in urls if url]
    seen: set[str] = set()
    out: list[str] = []
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        out.append(url)
    return out


def _get_connector_run_or_404(db: Session, *, run_id: UUID, tenant_id: UUID) -> ConnectorRun:
    run = db.query(ConnectorRun).filter(ConnectorRun.id == run_id, ConnectorRun.tenant_id == tenant_id).first()
    if not run:
        raise HTTPException(status_code=404, detail=CONNECTOR_RUN_NOT_FOUND_DETAIL)
    return run


def _assert_connector_run_dataset_writable(db: Session, *, run: ConnectorRun, tenant_id: UUID, account_id: str) -> None:
    if not run.dataset_id:
        return
    dataset = dataset_service.get_dataset(db, tenant_id, run.dataset_id)
    dataset_service.assert_dataset_writable(db, dataset, account_id)


def _connector_run_dispatcher(connector_id: str) -> Any:
    dispatcher = _resolve_connector_executor(connector_id)
    if dispatcher is None:
        raise HTTPException(status_code=400, detail=UNSUPPORTED_CONNECTOR_ID_DETAIL)
    return dispatcher


def _validate_connector_run_enabled(connector_id: str) -> None:
    if connector_id not in _CONNECTOR_CONFIG_MODELS:
        raise HTTPException(status_code=400, detail=UNSUPPORTED_CONNECTOR_ID_DETAIL)
    if connector_id in _URL_INGEST_CONNECTOR_IDS and not settings.URL_INGEST_ENABLED:
        raise HTTPException(status_code=400, detail=URL_INGEST_DISABLED_DETAIL)
    if connector_id in _DB_CATALOG_CONNECTOR_IDS and not settings.DB_CATALOG_ENABLED:
        raise HTTPException(status_code=400, detail="DB catalog ingestion is disabled")


def _validate_and_encrypt_run_config(
    connector_id: str, raw_config: dict[str, Any] | None
) -> tuple[Any, dict[str, Any]]:
    config_model = _CONNECTOR_CONFIG_MODELS.get(connector_id)
    if config_model is None:
        raise HTTPException(status_code=400, detail=UNSUPPORTED_CONNECTOR_ID_DETAIL)
    cfg = config_model.model_validate(raw_config or {})
    cfg_dict = cfg.model_dump(mode="json", exclude_none=True)
    return cfg, encrypt_connector_config_secrets(cfg_dict)


def _connector_run_group_ids_to_check(cfg: Any) -> list[UUID]:
    group_ids: list[UUID] = []
    access = getattr(cfg, "access", None)
    group_ids.extend(list(getattr(access, "partial_group_list", None) or []))
    source_acl = getattr(cfg, "source_acl", None)
    for rule in getattr(source_acl, "group_mappings", None) or []:
        group_id = getattr(rule, "group_id", None)
        if group_id:
            group_ids.append(group_id)
    return group_ids


def _assert_connector_run_groups_exist(db: Session, *, tenant_id: UUID, cfg: Any) -> None:
    group_ids = _connector_run_group_ids_to_check(cfg)
    if not group_ids:
        return
    missing = _unknown_tenant_groups(db, tenant_id=tenant_id, group_ids=group_ids)
    if missing:
        raise HTTPException(status_code=400, detail=f"Unknown tenant groups: {', '.join(missing[:20])}")


def _create_pending_connector_run(
    db: Session,
    *,
    values: dict[str, Any],
) -> ConnectorRun:
    run_values = dict(values)
    run_values.setdefault("status", "pending")
    run_values.setdefault("stats", {})
    run = ConnectorRun(**run_values)
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _build_retry_failed_run_config(
    *,
    connector_id: str,
    base_cfg: dict[str, Any],
    failed_urls: list[str],
) -> tuple[str, dict[str, Any]]:
    if connector_id == "url_batch":
        new_cfg = dict(base_cfg)
        new_cfg["urls"] = failed_urls
        return "url_batch", new_cfg

    if connector_id == "web_crawl":
        new_cfg: dict[str, Any] = {"urls": failed_urls}
        for key in ("filename", "user_agent", "auth", "parser_backend", "chunk_strategy", "pipeline", "access"):
            if key in base_cfg:
                new_cfg[key] = base_cfg.get(key)
        return "url_batch", new_cfg

    raise HTTPException(status_code=400, detail=UNSUPPORTED_CONNECTOR_ID_DETAIL)


async def _enqueue_connector_run_if_enabled(
    *,
    tenant_id: UUID,
    run_id: UUID,
    requested_by: str,
) -> str | None:
    if not settings.TASK_QUEUE_ENABLED:
        return None

    job_id = f"connector:{tenant_id}:{run_id}"
    return await enqueue_connector_run(
        tenant_id=tenant_id,
        run_id=run_id,
        requested_by=requested_by,
        job_id=job_id,
    )


def _persist_connector_run_task_id(db: Session, *, run: ConnectorRun, task_id: str) -> None:
    run.task_id = task_id
    db.commit()
    db.refresh(run)


def _mark_connector_run_failed(db: Session, *, run: ConnectorRun, error: str) -> None:
    run.task_id = None
    run.status = "failed"
    run.error_message = error
    run.finished_at = _now()
    db.commit()
    db.refresh(run)


async def enqueue_or_schedule_run(
    db: Session,
    *,
    background_tasks: BackgroundTasks,
    run: ConnectorRun,
    tenant_id: UUID,
    requested_by: str,
) -> ConnectorRunOut:
    connector_id = str(run.connector_id or "").strip()
    try:
        dispatcher = _connector_run_dispatcher(connector_id)
    except HTTPException:
        _mark_connector_run_failed(db, run=run, error="unsupported_connector_id")
        raise

    queue_required = settings.TASK_QUEUE_ENABLED
    if queue_required:
        try:
            task_id = await _enqueue_connector_run_if_enabled(
                tenant_id=tenant_id,
                run_id=run.id,
                requested_by=requested_by,
            )
        except Exception as exc:
            _mark_connector_run_failed(db, run=run, error=CONNECTOR_QUEUE_HANDOFF_FAILED_ERROR)
            raise HTTPException(status_code=503, detail=CONNECTOR_QUEUE_UNAVAILABLE_DETAIL) from exc
        if not task_id:
            _mark_connector_run_failed(db, run=run, error=CONNECTOR_QUEUE_HANDOFF_FAILED_ERROR)
            raise HTTPException(status_code=503, detail=CONNECTOR_QUEUE_UNAVAILABLE_DETAIL)
        _persist_connector_run_task_id(db, run=run, task_id=task_id)
    else:
        _schedule_connector_run_dispatch(
            background_tasks=background_tasks,
            dispatcher=dispatcher,
            run_id=run.id,
            tenant_id=tenant_id,
            requested_by=requested_by,
        )
    return _run_out(run)


def _schedule_connector_run_dispatch(
    *,
    background_tasks: BackgroundTasks,
    dispatcher: Any,
    run_id: UUID,
    tenant_id: UUID,
    requested_by: str,
) -> None:
    background_tasks.add_task(
        dispatcher,
        run_id=run_id,
        tenant_id=tenant_id,
        requested_by=requested_by,
    )


def _connector_run_has_abortable_task(*, task_queue_enabled: bool, task_id: object) -> bool:
    return bool(task_queue_enabled and isinstance(task_id, str) and task_id)


def _load_arq_job_class():
    from arq.jobs import Job

    return Job


async def _get_queue_or_none():
    try:
        return await get_queue()
    except Exception:
        return None


async def _abort_connector_run_task_if_possible(run: ConnectorRun) -> None:
    task_id = run.task_id
    if not _connector_run_has_abortable_task(
        task_queue_enabled=settings.TASK_QUEUE_ENABLED,
        task_id=task_id,
    ):
        return

    job_cls = _load_arq_job_class()
    queue = await _get_queue_or_none()
    if queue is None:
        return

    queue_name = settings.TASK_QUEUE_NAME
    job = job_cls(str(task_id), queue, _queue_name=queue_name)
    with contextlib.suppress(TimeoutError, asyncio.TimeoutError):
        await job.abort(timeout=0.2)


def _non_negative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _compact_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item or "").strip() for item in value if str(item or "").strip()]


def _get_resumable_connector_definition(connector_id: str) -> Any:
    connector_definition = get_connector_definition(connector_id)
    if connector_definition is None or not getattr(connector_definition, "supports_resume", False):
        raise HTTPException(status_code=400, detail=f"Resume is not supported for {connector_id or 'this connector'}")
    return connector_definition


def _build_url_batch_resume_run_config(
    *,
    run_id: UUID,
    base_cfg: dict[str, Any],
    stats: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    cursor = _non_negative_int(stats.get("cursor", stats.get("processed_urls", 0)))
    urls = _compact_string_list(base_cfg.get("urls"))
    remaining = urls[cursor:] if cursor < len(urls) else []
    if not remaining:
        raise HTTPException(status_code=400, detail="No remaining URLs to resume")

    new_cfg = dict(base_cfg)
    new_cfg["urls"] = remaining
    return new_cfg, {"resume_of": str(run_id), "resume_cursor": int(cursor)}


def _stateful_resume_total_key(connector_definition: Any) -> str | None:
    return next((key for key in getattr(connector_definition, "state_keys", []) if key != "cursor"), None)


def _stateful_resume_has_no_remaining_items(
    *,
    connector_definition: Any,
    stats: dict[str, Any],
    resume_state: dict[str, Any],
    cursor: int,
) -> bool:
    total_key = _stateful_resume_total_key(connector_definition)
    has_incremental_manifest = bool(normalize_source_manifest(resume_state.get("source_manifest")))
    if not total_key or has_incremental_manifest:
        return False
    total_items = _non_negative_int(stats.get(total_key))
    return total_items > 0 and cursor >= total_items


def _build_stateful_resume_run_config(
    *,
    run_id: UUID,
    connector_id: str,
    connector_definition: Any,
    base_cfg: dict[str, Any],
    stats: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    existing_state = base_cfg.get("_state") if isinstance(base_cfg.get("_state"), dict) else {}
    resume_state = build_persisted_state(
        connector_id=connector_id,
        existing_state=dict(existing_state or {}),
        stats=stats,
        run_id=run_id,
    )
    cursor = get_resume_cursor(resume_state)
    if _stateful_resume_has_no_remaining_items(
        connector_definition=connector_definition,
        stats=stats,
        resume_state=resume_state,
        cursor=cursor,
    ):
        raise HTTPException(status_code=400, detail="No remaining items to resume")
    if not resume_state:
        raise HTTPException(status_code=400, detail="No saved resume state found")

    new_cfg = dict(base_cfg)
    new_cfg["_state"] = resume_state
    return new_cfg, {"resume_of": str(run_id), "resume_cursor": int(cursor)}


def _build_resume_run_config(
    *,
    run: ConnectorRun,
    connector_id: str,
    connector_definition: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    base_cfg = dict(run.config or {})
    stats = dict(run.stats or {})
    if connector_id == "url_batch":
        return _build_url_batch_resume_run_config(run_id=run.id, base_cfg=base_cfg, stats=stats)
    return _build_stateful_resume_run_config(
        run_id=run.id,
        connector_id=connector_id,
        connector_definition=connector_definition,
        base_cfg=base_cfg,
        stats=stats,
    )


def _unknown_tenant_groups(db: Session, *, tenant_id: UUID, group_ids: list[UUID]) -> list[str]:
    ids = list(dict.fromkeys(group_ids))[:200]
    if not ids:
        return []
    rows = db.query(TenantGroup.id).filter(TenantGroup.tenant_id == tenant_id, TenantGroup.id.in_(ids)).all()
    found = {row[0] for row in rows if row and row[0]}
    return [str(group_id) for group_id in ids if group_id not in found]


def _normalize_doc_access_mode(value: object) -> str:
    mode = str(value or "").strip().lower()
    if not mode or mode == "inherit":
        return "inherit"
    return mode


def _fetch_connector_run_acl_summaries(
    db: Session,
    *,
    tenant_id: UUID,
    run_ids: list[UUID],
) -> dict[UUID, dict[str, Any]]:
    if not run_ids:
        return {}

    normalized_run_ids = list(dict.fromkeys(run_ids))
    mode_counts: dict[UUID, dict[str, int]] = {}
    rows = (
        db.query(ConnectorRunDocument.run_id, DBDocument.access_mode, func.count(DBDocument.id))
        .join(DBDocument, DBDocument.id == ConnectorRunDocument.document_id)
        .filter(
            ConnectorRunDocument.tenant_id == tenant_id,
            ConnectorRunDocument.run_id.in_(normalized_run_ids),
        )
        .group_by(ConnectorRunDocument.run_id, DBDocument.access_mode)
        .all()
    )
    for run_id, access_mode, count in rows:
        mode = _normalize_doc_access_mode(access_mode)
        mode_counts.setdefault(run_id, {})[mode] = int(count or 0)

    def _partial_doc_counts(permission_model):  # noqa: ANN001
        per_doc = (
            db.query(
                ConnectorRunDocument.run_id.label("run_id"),
                ConnectorRunDocument.document_id.label("document_id"),
                func.count(permission_model.id).label("allowlist_count"),
            )
            .join(DBDocument, DBDocument.id == ConnectorRunDocument.document_id)
            .outerjoin(
                permission_model,
                and_(
                    permission_model.tenant_id == tenant_id,
                    permission_model.document_id == ConnectorRunDocument.document_id,
                ),
            )
            .filter(
                ConnectorRunDocument.tenant_id == tenant_id,
                ConnectorRunDocument.run_id.in_(normalized_run_ids),
                func.lower(DBDocument.access_mode) == "partial_members",
            )
            .group_by(ConnectorRunDocument.run_id, ConnectorRunDocument.document_id)
            .subquery()
        )
        if permission_model is DocumentPermission:
            rows = (
                db.query(
                    per_doc.c.run_id,
                    func.count(per_doc.c.document_id),
                    func.min(per_doc.c.allowlist_count),
                    func.max(per_doc.c.allowlist_count),
                )
                .group_by(per_doc.c.run_id)
                .all()
            )
            return {
                run_id: {
                    "partial_members_doc_count": int(doc_count or 0),
                    "partial_member_count_min": int(min_count or 0),
                    "partial_member_count_max": int(max_count or 0),
                }
                for run_id, doc_count, min_count, max_count in rows
            }
        rows = (
            db.query(per_doc.c.run_id, func.min(per_doc.c.allowlist_count), func.max(per_doc.c.allowlist_count))
            .group_by(per_doc.c.run_id)
            .all()
        )
        return {
            run_id: {
                "partial_group_count_min": int(min_count or 0),
                "partial_group_count_max": int(max_count or 0),
            }
            for run_id, min_count, max_count in rows
        }

    member_stats_by_run = _partial_doc_counts(DocumentPermission)
    group_stats_by_run = _partial_doc_counts(DocumentGroupPermission)
    summaries: dict[UUID, dict[str, Any]] = {}
    for run_id in normalized_run_ids:
        counts = mode_counts.get(run_id, {})
        documents_total = sum(counts.values())
        if documents_total == 0:
            continue
        modes = [mode for mode, count in counts.items() if count > 0]
        summary: dict[str, Any] = {
            "mode": modes[0] if len(modes) == 1 else "mixed",
            "documents_total": documents_total,
            "access_mode_counts": counts,
        }
        partial_docs = counts.get("partial_members", 0)
        if partial_docs:
            summary["partial_members_doc_count"] = partial_docs
        summary.update(member_stats_by_run.get(run_id, {}))
        summary.update(group_stats_by_run.get(run_id, {}))
        summaries[run_id] = summary
    return summaries


def _run_out(run: ConnectorRun, *, acl_summary: dict[str, Any] | None = None) -> ConnectorRunOut:
    documents = run.documents or []
    connector_id = str(run.connector_id or "").strip()
    config = redact_connection_info(
        redact_secrets(dict(run.config or {})),
        enabled=connector_id in _DB_CONNECTOR_IDS,
    )
    return ConnectorRunOut(
        id=run.id,
        tenant_id=run.tenant_id,
        dataset_id=run.dataset_id,
        connector_id=connector_id,
        requested_by=run.requested_by or None,
        status=str(run.status or "pending"),
        config=config,
        stats=dict(run.stats or {}),
        error_message=run.error_message or None,
        task_id=run.task_id or None,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        acl_summary=acl_summary or None,
        documents=[
            {
                "document_id": document.document_id,
                "source_ref": document.source_ref or None,
                "status": str(document.status or "created"),
            }
            for document in documents
        ],
    )


async def create_run(
    *,
    payload: ConnectorRunCreateRequest,
    background_tasks: BackgroundTasks,
    db: Session,
    tenant_id: UUID,
    account_id: str,
) -> ConnectorRunOut:
    """
    Create a connector run.

    Requires dataset write permission.
    """
    connector_id = str(payload.connector_id or "").strip()
    _validate_connector_run_enabled(connector_id)

    if connector_id in _DB_CATALOG_CONNECTOR_IDS:
        ensure_tenant_permission(
            db,
            tenant_id,
            account_id,
            TenantPermissions.SETTINGS_WRITE,
            detail=_DB_CONNECTOR_PERMISSION_DETAIL,
        )
    else:
        dataset_service.ensure_member(db, tenant_id, account_id)
    dataset = dataset_service.resolve_writable_dataset(db, tenant_id, account_id, payload.dataset_id)
    cfg, cfg_dict = _validate_and_encrypt_run_config(connector_id, payload.config)
    if connector_id in _DB_CATALOG_CONNECTOR_IDS:
        try:
            validate_db_connector_config(cfg)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    _assert_connector_run_groups_exist(db, tenant_id=tenant_id, cfg=cfg)

    run = _create_pending_connector_run(
        db,
        values={
            "tenant_id": tenant_id,
            "dataset_id": dataset.id,
            "connector_id": connector_id,
            "requested_by": account_id,
            "config": cfg_dict,
        },
    )
    return await enqueue_or_schedule_run(
        db,
        background_tasks=background_tasks,
        run=run,
        tenant_id=tenant_id,
        requested_by=account_id,
    )


def list_runs(
    *,
    skip: int,
    limit: int,
    dataset_id: UUID | None,
    tenant_id: UUID,
    account_id: str,
    db: Session,
) -> dict[str, Any]:
    """List connector runs (requires dataset write permission for each returned run's dataset)."""
    member = dataset_service.ensure_member(db, tenant_id, account_id)

    query = db.query(ConnectorRun).filter(ConnectorRun.tenant_id == tenant_id)
    if dataset_id:
        dataset = dataset_service.get_dataset(db, tenant_id, dataset_id)
        dataset_service.assert_dataset_writable(db, dataset, account_id)
        query = query.filter(ConnectorRun.dataset_id == dataset_id)
    elif str(getattr(member, "role", "") or "").lower() not in EDIT_ROLES:
        return {"total": 0, "items": []}
    else:
        query = query.filter(
            ConnectorRun.dataset_id.in_(_writable_dataset_ids_subquery(tenant_id=tenant_id, account_id=account_id))
        )

    total = int(query.count())
    runs = (
        query.options(selectinload(ConnectorRun.documents))
        .order_by(ConnectorRun.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    summaries = _fetch_connector_run_acl_summaries(
        db,
        tenant_id=tenant_id,
        run_ids=[run.id for run in runs],
    )

    return {
        "total": total,
        "items": [_run_out(run, acl_summary=summaries.get(run.id)) for run in runs],
    }


def get_run(
    run_id: UUID,
    *,
    tenant_id: UUID,
    account_id: str,
    db: Session,
) -> ConnectorRunOut:
    """Get connector run detail (requires dataset write permission)."""
    dataset_service.ensure_member(db, tenant_id, account_id)

    run = (
        db.query(ConnectorRun)
        .options(selectinload(ConnectorRun.documents))
        .filter(ConnectorRun.id == run_id, ConnectorRun.tenant_id == tenant_id)
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail=CONNECTOR_RUN_NOT_FOUND_DETAIL)

    if run.dataset_id:
        dataset = dataset_service.get_dataset(db, tenant_id, run.dataset_id)
        dataset_service.assert_dataset_writable(db, dataset, account_id)

    summary = _fetch_connector_run_acl_summaries(
        db,
        tenant_id=tenant_id,
        run_ids=[run.id],
    ).get(run.id)

    return _run_out(run, acl_summary=summary)


async def retry_failed_run(
    run_id: UUID,
    background_tasks: BackgroundTasks,
    *,
    tenant_id: UUID,
    account_id: str,
    db: Session,
) -> ConnectorRunOut:
    """Create a new connector run that retries only the failed URLs (best-effort)."""
    if not settings.URL_INGEST_ENABLED:
        raise HTTPException(status_code=400, detail=URL_INGEST_DISABLED_DETAIL)

    dataset_service.ensure_member(db, tenant_id, account_id)

    run = _get_connector_run_or_404(db, run_id=run_id, tenant_id=tenant_id)

    status = str(run.status or "").lower()
    if status in {"pending", "running"}:
        raise HTTPException(status_code=400, detail="Connector run is still active")

    _assert_connector_run_dataset_writable(db, run=run, tenant_id=tenant_id, account_id=account_id)

    stats = dict(run.stats or {})
    failed_urls = _extract_failed_urls(stats)[:500]
    if not failed_urls:
        raise HTTPException(status_code=400, detail="No failed URLs to retry")

    base_cfg = dict(run.config or {})
    connector_id = str(run.connector_id or "").strip()
    new_connector_id, new_cfg = _build_retry_failed_run_config(
        connector_id=connector_id,
        base_cfg=base_cfg,
        failed_urls=failed_urls,
    )

    new_run = _create_pending_connector_run(
        db,
        values={
            "tenant_id": tenant_id,
            "dataset_id": run.dataset_id,
            "connector_id": new_connector_id,
            "requested_by": account_id,
            "config": new_cfg,
            "stats": {"retry_of": str(run.id), "retry_kind": "failed_only"},
        },
    )
    return await enqueue_or_schedule_run(
        db,
        background_tasks=background_tasks,
        run=new_run,
        tenant_id=tenant_id,
        requested_by=account_id,
    )


async def resume_run(
    run_id: UUID,
    background_tasks: BackgroundTasks,
    *,
    tenant_id: UUID,
    account_id: str,
    db: Session,
) -> ConnectorRunOut:
    """Create a new connector run that resumes from where the previous run stopped (best-effort)."""
    if not settings.URL_INGEST_ENABLED:
        raise HTTPException(status_code=400, detail=URL_INGEST_DISABLED_DETAIL)

    dataset_service.ensure_member(db, tenant_id, account_id)

    run = _get_connector_run_or_404(db, run_id=run_id, tenant_id=tenant_id)

    status = str(run.status or "").lower()
    if status not in {"cancelled", "failed"}:
        raise HTTPException(status_code=400, detail="Connector run is not resumable")

    _assert_connector_run_dataset_writable(db, run=run, tenant_id=tenant_id, account_id=account_id)

    connector_id = str(run.connector_id or "").strip()
    connector_definition = _get_resumable_connector_definition(connector_id)
    new_cfg, resume_stats = _build_resume_run_config(
        run=run,
        connector_id=connector_id,
        connector_definition=connector_definition,
    )

    new_run = _create_pending_connector_run(
        db,
        values={
            "tenant_id": tenant_id,
            "dataset_id": run.dataset_id,
            "connector_id": connector_id,
            "requested_by": account_id,
            "config": new_cfg,
            "stats": resume_stats,
        },
    )
    return await enqueue_or_schedule_run(
        db,
        background_tasks=background_tasks,
        run=new_run,
        tenant_id=tenant_id,
        requested_by=account_id,
    )


async def cancel_run(
    run_id: UUID,
    *,
    tenant_id: UUID,
    account_id: str,
    db: Session,
) -> ConnectorRunOut:
    """Cancel a running connector run (best-effort)."""
    dataset_service.ensure_member(db, tenant_id, account_id)

    run = _get_connector_run_or_404(db, run_id=run_id, tenant_id=tenant_id)
    _assert_connector_run_dataset_writable(db, run=run, tenant_id=tenant_id, account_id=account_id)

    status = str(run.status or "").lower()
    if status in {"completed", "failed"}:
        return _run_out(run)

    run.status = "cancelled"
    run.finished_at = _now()
    db.commit()
    db.refresh(run)

    await _abort_connector_run_task_if_possible(run)
    return _run_out(run)
