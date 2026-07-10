
import importlib
from collections.abc import Awaitable, Callable
from uuid import UUID

ConnectorExecutor = Callable[..., Awaitable[None]]

_CONNECTOR_EXECUTOR_NAMES = {
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


def is_supported_connector_run(connector_id: str) -> bool:
    return str(connector_id or "").strip() in _CONNECTOR_EXECUTOR_NAMES


def _resolve_connector_executor(connector_id: str) -> ConnectorExecutor | None:
    executor_name = _CONNECTOR_EXECUTOR_NAMES.get(str(connector_id or "").strip())
    if not executor_name:
        return None

    # Connector executors still live behind the API module compatibility surface.
    # Keep that dependency lazy and centralized so queue workers do not import API
    # routers during module initialization or through scattered local imports.
    connectors_module = importlib.import_module("app.api.v1.connectors")
    executor = getattr(connectors_module, executor_name, None)
    return executor if callable(executor) else None


async def execute_connector_run(
    *,
    connector_id: str,
    run_id: UUID,
    tenant_id: UUID,
    requested_by: str,
) -> bool:
    executor = _resolve_connector_executor(connector_id)
    if executor is None:
        return False
    await executor(run_id=run_id, tenant_id=tenant_id, requested_by=requested_by)
    return True
