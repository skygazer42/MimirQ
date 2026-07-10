
from dataclasses import dataclass


@dataclass(frozen=True)
class ConnectorDefinition:
    connector_id: str
    name: str
    description: str = ""
    supports_incremental: bool = False
    supports_resume: bool = False
    supports_full_reconcile: bool = False
    sync_cursor_kind: str = "none"
    state_keys: tuple[str, ...] = ()


CONNECTOR_REGISTRY: dict[str, ConnectorDefinition] = {
    "url_batch": ConnectorDefinition(
        connector_id="url_batch",
        name="URL 批量导入",
        description="从多个 http(s) URL 拉取内容并入库（支持 URL_INGEST_* 安全开关）",
        supports_incremental=True,
        supports_resume=True,
        sync_cursor_kind="offset",
        state_keys=("cursor", "total_urls"),
    ),
    "web_crawl": ConnectorDefinition(
        connector_id="web_crawl",
        name="网站抓取（站点级）",
        description="从站点种子 URL 开始抓取链接并批量入库（支持 Cookie/Bearer/Basic 登录态；配置中的密钥会被加密存储并在响应中脱敏）",
        supports_incremental=True,
        supports_resume=True,
        supports_full_reconcile=True,
        sync_cursor_kind="offset",
        state_keys=("cursor", "total_urls", "source_manifest"),
    ),
    "github_repo": ConnectorDefinition(
        connector_id="github_repo",
        name="GitHub Repo 导入",
        description="从 GitHub 仓库列出文件并通过 raw.githubusercontent.com 拉取入库（可选 Bearer token；用于私有仓库/更高 API 限额）",
        supports_incremental=True,
        supports_resume=True,
        supports_full_reconcile=True,
        sync_cursor_kind="offset",
        state_keys=("cursor", "total_files", "source_manifest"),
    ),
    "drive_files": ConnectorDefinition(
        connector_id="drive_files",
        name="Google Drive 文件导入（链接）",
        description="从 Google Drive 文件分享链接解析 file_id 并构造直链下载入库（仅文件；不支持文件夹）",
        supports_incremental=True,
        supports_resume=True,
        supports_full_reconcile=True,
        sync_cursor_kind="offset",
        state_keys=("cursor", "total_urls", "source_manifest"),
    ),
    "minio_bucket": ConnectorDefinition(
        connector_id="minio_bucket",
        name="MinIO/S3 Bucket 导入",
        description="列出 MinIO bucket 对象并用 presigned URL 拉取入库（需要 MINIO_ENABLED=true；URL_INGEST 需允许访问 MinIO 端点）",
        supports_incremental=True,
        supports_resume=True,
        supports_full_reconcile=True,
        sync_cursor_kind="offset",
        state_keys=("cursor", "total_objects", "source_manifest", "source_scope_hash"),
    ),
    "confluence_space": ConnectorDefinition(
        connector_id="confluence_space",
        name="Confluence Space 导入",
        description="从 Confluence Space 列出页面并入库（支持增量 cursor；配置中的 Cookie/Token/Password 会被加密存储并在响应中脱敏）",
        supports_incremental=True,
        supports_full_reconcile=True,
        sync_cursor_kind="timestamp",
        state_keys=("last_modified", "last_modified_ids"),
    ),
    "jira_project": ConnectorDefinition(
        connector_id="jira_project",
        name="Jira Project 导入",
        description="从 Jira Cloud 项目拉取 issue 并入库（支持增量 updated cursor；配置中的 Token/Password 会被加密存储并在响应中脱敏）",
        supports_incremental=True,
        supports_full_reconcile=True,
        sync_cursor_kind="timestamp",
        state_keys=("last_modified", "last_modified_ids"),
    ),
    "sqlserver_catalog": ConnectorDefinition(
        connector_id="sqlserver_catalog",
        name="SQLServer Catalog 导入",
        description="从 SQLServer 同步 schema/table/column 目录与安全画像（仅聚合统计；不外发原始行）",
        supports_incremental=True,
        supports_resume=True,
        supports_full_reconcile=True,
        state_keys=("total_tables", "source_manifest"),
    ),
    "mysql_catalog": ConnectorDefinition(
        connector_id="mysql_catalog",
        name="MySQL Catalog 导入",
        description="从 MySQL 同步 schema/table/column 目录与安全画像（仅聚合统计；不外发原始行）",
        supports_incremental=True,
        supports_resume=True,
        supports_full_reconcile=True,
        state_keys=("total_tables", "source_manifest"),
    ),
}


def get_connector_definition(connector_id: str) -> ConnectorDefinition | None:
    return CONNECTOR_REGISTRY.get(str(connector_id or "").strip())


def list_connector_definitions() -> list[ConnectorDefinition]:
    return list(CONNECTOR_REGISTRY.values())


__all__ = [
    "CONNECTOR_REGISTRY",
    "ConnectorDefinition",
    "get_connector_definition",
    "list_connector_definitions",
]
