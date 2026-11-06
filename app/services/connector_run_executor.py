from collections.abc import Awaitable, Callable
from uuid import UUID

from app.services.connector_execution.confluence import execute as _execute_confluence_space
from app.services.connector_execution.db_catalog import execute as _execute_db_catalog
from app.services.connector_execution.drive_files import execute as _execute_drive_files
from app.services.connector_execution.github_repo import execute as _execute_github_repo
from app.services.connector_execution.jira import execute as _execute_jira_project
from app.services.connector_execution.minio_bucket import execute as _execute_minio_bucket
from app.services.connector_execution.url_batch import execute as _execute_url_batch
from app.services.connector_execution.web_crawl import execute as _execute_web_crawl

ConnectorExecutor = Callable[..., Awaitable[None]]

_CONNECTOR_EXECUTORS: dict[str, ConnectorExecutor] = {
    "url_batch": _execute_url_batch,
    "web_crawl": _execute_web_crawl,
    "github_repo": _execute_github_repo,
    "drive_files": _execute_drive_files,
    "minio_bucket": _execute_minio_bucket,
    "confluence_space": _execute_confluence_space,
    "jira_project": _execute_jira_project,
    "mysql_catalog": _execute_db_catalog,
    "sqlserver_catalog": _execute_db_catalog,
}


def is_supported_connector_run(connector_id: str) -> bool:
    return connector_id.strip() in _CONNECTOR_EXECUTORS


def _resolve_connector_executor(connector_id: str) -> ConnectorExecutor | None:
    return _CONNECTOR_EXECUTORS.get(connector_id.strip())


get_connector_run_executor = _resolve_connector_executor


async def execute_connector_run(
    *,
    connector_id: str,
    run_id: UUID,
    tenant_id: UUID,
    requested_by: str,
) -> bool:
    executor = get_connector_run_executor(connector_id)
    if executor is None:
        return False
    await executor(run_id=run_id, tenant_id=tenant_id, requested_by=requested_by)
    return True
