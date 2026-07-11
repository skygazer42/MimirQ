import asyncio
import contextlib
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import Session, selectinload

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.connector import (
    ConfluenceSpaceConnectorConfig,
    ConnectorRunCreateRequest,
    ConnectorRunListResponse,
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
from app.api.v1 import connectors as connectors_module
from app.core.database import get_db
from app.models.connector import ConnectorRun
from app.models.dataset import Dataset, DatasetPermission, DatasetPermissionEnum
from app.models.group_permissions import DatasetGroupPermission
from app.models.tenant_group import TenantGroupMember
from app.services.connector_egress_policy import validate_db_connector_config
from app.services.dataset_service import EDIT_ROLES
from app.services.rbac_service import TenantPermissions, ensure_tenant_permission

router = APIRouter(responses=connectors_module._DEFAULT_HTTP_EXCEPTION_RESPONSES)

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
_CONNECTOR_RUN_DISPATCHER_NAMES = {
    "url_batch": "_execute_url_batch_run",
    "web_crawl": "_execute_web_crawl_run",
    "github_repo": "_execute_github_repo_run",
    "drive_files": "_execute_drive_files_run",
    "minio_bucket": "_execute_minio_bucket_run",
    "confluence_space": "_execute_confluence_space_run",
    "jira_project": "_execute_jira_project_run",
    "mysql_catalog": "_execute_db_catalog_run",
    "sqlserver_catalog": "_execute_db_catalog_run",
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


class ConnectorRunListParams:
    def __init__(
        self,
        skip: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=200)] = 20,
        dataset_id: UUID | None = None,
    ) -> None:
        self.skip = skip
        self.limit = limit
        self.dataset_id = dataset_id


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
        raise HTTPException(status_code=404, detail=connectors_module.CONNECTOR_RUN_NOT_FOUND_DETAIL)
    return run


def _assert_connector_run_dataset_writable(db: Session, *, run: ConnectorRun, tenant_id: UUID, account_id: str) -> None:
    if not run.dataset_id:
        return
    dataset = connectors_module.DatasetService.get_dataset(db, tenant_id, run.dataset_id)
    connectors_module.DatasetService.assert_dataset_writable(db, dataset, account_id)


def _connector_run_dispatcher(connector_id: str) -> Any:
    dispatcher_name = _CONNECTOR_RUN_DISPATCHER_NAMES.get(connector_id)
    if not dispatcher_name:
        raise HTTPException(status_code=400, detail=connectors_module.UNSUPPORTED_CONNECTOR_ID_DETAIL)
    return getattr(connectors_module, dispatcher_name)


def _validate_connector_run_enabled(connector_id: str) -> None:
    if connector_id not in _CONNECTOR_CONFIG_MODELS:
        raise HTTPException(status_code=400, detail=connectors_module.UNSUPPORTED_CONNECTOR_ID_DETAIL)
    if connector_id in _URL_INGEST_CONNECTOR_IDS and not bool(getattr(connectors_module.settings, "URL_INGEST_ENABLED", False)):
        raise HTTPException(status_code=400, detail=connectors_module.URL_INGEST_DISABLED_DETAIL)
    if connector_id in _DB_CATALOG_CONNECTOR_IDS and not bool(getattr(connectors_module.settings, "DB_CATALOG_ENABLED", False)):
        raise HTTPException(status_code=400, detail="DB catalog ingestion is disabled")


def _validate_and_encrypt_run_config(connector_id: str, raw_config: dict[str, Any] | None) -> tuple[Any, dict[str, Any]]:
    config_model = _CONNECTOR_CONFIG_MODELS.get(connector_id)
    if config_model is None:
        raise HTTPException(status_code=400, detail=connectors_module.UNSUPPORTED_CONNECTOR_ID_DETAIL)
    cfg = config_model.model_validate(raw_config or {})
    cfg_dict = cfg.model_dump(mode="json", exclude_none=True)
    return cfg, connectors_module.encrypt_connector_config_secrets(cfg_dict)


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
    missing = connectors_module._unknown_tenant_groups(db, tenant_id=tenant_id, group_ids=group_ids)
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

    raise HTTPException(status_code=400, detail=connectors_module.UNSUPPORTED_CONNECTOR_ID_DETAIL)


async def _enqueue_connector_run_if_enabled(
    *,
    tenant_id: UUID,
    run_id: UUID,
    requested_by: str,
) -> str | None:
    if not bool(getattr(connectors_module.settings, "TASK_QUEUE_ENABLED", False)):
        return None

    job_id = f"connector:{tenant_id}:{run_id}"
    try:
        return await connectors_module.enqueue_connector_run(
            tenant_id=tenant_id,
            run_id=run_id,
            requested_by=requested_by,
            job_id=job_id,
        )
    except Exception:
        return None


def _persist_connector_run_task_id(db: Session, *, run: ConnectorRun, task_id: str) -> None:
    run.task_id = task_id
    db.commit()
    db.refresh(run)


async def _enqueue_or_schedule_connector_run(
    db: Session,
    *,
    background_tasks: BackgroundTasks,
    run: ConnectorRun,
    tenant_id: UUID,
    requested_by: str,
) -> ConnectorRunOut:
    task_id = await _enqueue_connector_run_if_enabled(
        tenant_id=tenant_id,
        run_id=run.id,
        requested_by=requested_by,
    )
    if task_id:
        _persist_connector_run_task_id(db, run=run, task_id=task_id)
    else:
        _schedule_connector_run_dispatch(
            background_tasks=background_tasks,
            connector_id=str(run.connector_id or "").strip(),
            run_id=run.id,
            tenant_id=tenant_id,
            requested_by=requested_by,
        )
    return connectors_module._run_out(run)


def _schedule_connector_run_dispatch(
    *,
    background_tasks: BackgroundTasks,
    connector_id: str,
    run_id: UUID,
    tenant_id: UUID,
    requested_by: str,
) -> None:
    background_tasks.add_task(
        _connector_run_dispatcher(connector_id),
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
        return await connectors_module.get_queue()
    except Exception:
        return None


async def _abort_connector_run_task_if_possible(run: ConnectorRun) -> None:
    task_id = getattr(run, "task_id", None)
    if not _connector_run_has_abortable_task(
        task_queue_enabled=bool(getattr(connectors_module.settings, "TASK_QUEUE_ENABLED", False)),
        task_id=task_id,
    ):
        return

    job_cls = connectors_module._load_arq_job_class()
    queue = await connectors_module._get_queue_or_none()
    if queue is None:
        return

    queue_name = getattr(connectors_module.settings, "TASK_QUEUE_NAME", "mimirq")
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
    connector_definition = connectors_module.get_connector_definition(connector_id)
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
    has_incremental_manifest = bool(connectors_module.normalize_source_manifest(resume_state.get("source_manifest")))
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
    resume_state = connectors_module.build_persisted_state(
        connector_id=connector_id,
        existing_state=dict(existing_state or {}),
        stats=stats,
        run_id=run_id,
    )
    cursor = connectors_module.get_resume_cursor(resume_state)
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


@router.post("/runs", response_model=ConnectorRunOut, status_code=201, responses=connectors_module._DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def create_connector_run(
    payload: ConnectorRunCreateRequest,
    background_tasks: BackgroundTasks,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
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
        connectors_module.DatasetService.ensure_member(db, tenant_id, account_id)
    dataset = connectors_module._resolve_writable_dataset(db, tenant_id, account_id, payload.dataset_id)
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
    return await _enqueue_or_schedule_connector_run(
        db,
        background_tasks=background_tasks,
        run=run,
        tenant_id=tenant_id,
        requested_by=account_id,
    )


@router.get("/runs", response_model=ConnectorRunListResponse, responses=connectors_module._DEFAULT_HTTP_EXCEPTION_RESPONSES)
def list_connector_runs(
    params: Annotated[ConnectorRunListParams, Depends()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """List connector runs (requires dataset write permission for each returned run's dataset)."""
    member = connectors_module.DatasetService.ensure_member(db, tenant_id, account_id)

    query = db.query(ConnectorRun).filter(ConnectorRun.tenant_id == tenant_id)
    if params.dataset_id:
        dataset = connectors_module.DatasetService.get_dataset(db, tenant_id, params.dataset_id)
        connectors_module.DatasetService.assert_dataset_writable(db, dataset, account_id)
        query = query.filter(ConnectorRun.dataset_id == params.dataset_id)
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
        .offset(params.skip)
        .limit(params.limit)
        .all()
    )

    summaries = connectors_module._fetch_connector_run_acl_summaries(
        db,
        tenant_id=tenant_id,
        run_ids=[run.id for run in runs],
    )

    return {"total": total, "items": [connectors_module._run_out(run, acl_summary=summaries.get(run.id)) for run in runs]}


@router.get("/runs/{run_id}", response_model=ConnectorRunOut, responses=connectors_module._DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_connector_run(
    run_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Get connector run detail (requires dataset write permission)."""
    connectors_module.DatasetService.ensure_member(db, tenant_id, account_id)

    run = (
        db.query(ConnectorRun)
        .options(selectinload(ConnectorRun.documents))
        .filter(ConnectorRun.id == run_id, ConnectorRun.tenant_id == tenant_id)
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail=connectors_module.CONNECTOR_RUN_NOT_FOUND_DETAIL)

    if run.dataset_id:
        dataset = connectors_module.DatasetService.get_dataset(db, tenant_id, run.dataset_id)
        connectors_module.DatasetService.assert_dataset_writable(db, dataset, account_id)

    summary = connectors_module._fetch_connector_run_acl_summaries(
        db,
        tenant_id=tenant_id,
        run_ids=[run.id],
    ).get(run.id)

    return connectors_module._run_out(run, acl_summary=summary)


@router.post("/runs/{run_id}/retry-failed", response_model=ConnectorRunOut, status_code=201, responses=connectors_module._DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def retry_failed_connector_run(
    run_id: UUID,
    background_tasks: BackgroundTasks,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Create a new connector run that retries only the failed URLs (best-effort)."""
    if not bool(getattr(connectors_module.settings, "URL_INGEST_ENABLED", False)):
        raise HTTPException(status_code=400, detail=connectors_module.URL_INGEST_DISABLED_DETAIL)

    connectors_module.DatasetService.ensure_member(db, tenant_id, account_id)

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
    return await _enqueue_or_schedule_connector_run(
        db,
        background_tasks=background_tasks,
        run=new_run,
        tenant_id=tenant_id,
        requested_by=account_id,
    )


@router.post("/runs/{run_id}/resume", response_model=ConnectorRunOut, status_code=201, responses=connectors_module._DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def resume_connector_run(
    run_id: UUID,
    background_tasks: BackgroundTasks,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Create a new connector run that resumes from where the previous run stopped (best-effort)."""
    if not bool(getattr(connectors_module.settings, "URL_INGEST_ENABLED", False)):
        raise HTTPException(status_code=400, detail=connectors_module.URL_INGEST_DISABLED_DETAIL)

    connectors_module.DatasetService.ensure_member(db, tenant_id, account_id)

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
    return await _enqueue_or_schedule_connector_run(
        db,
        background_tasks=background_tasks,
        run=new_run,
        tenant_id=tenant_id,
        requested_by=account_id,
    )


@router.post("/runs/{run_id}/cancel", response_model=ConnectorRunOut, responses=connectors_module._DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def cancel_connector_run(
    run_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Cancel a running connector run (best-effort)."""
    connectors_module.DatasetService.ensure_member(db, tenant_id, account_id)

    run = _get_connector_run_or_404(db, run_id=run_id, tenant_id=tenant_id)
    _assert_connector_run_dataset_writable(db, run=run, tenant_id=tenant_id, account_id=account_id)

    status = str(run.status or "").lower()
    if status in {"completed", "failed"}:
        return connectors_module._run_out(run)

    run.status = "cancelled"
    run.finished_at = connectors_module._now()
    db.commit()
    db.refresh(run)

    await _abort_connector_run_task_if_possible(run)
    return connectors_module._run_out(run)
