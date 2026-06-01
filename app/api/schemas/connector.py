"""
Connector-related Pydantic schemas.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.api.schemas.connector_acl import ConnectorSourceAclConfig
from app.api.schemas.document import DocumentAccessUpdateRequest, DocumentPipelineOptions

# NOTE: keep connector identifiers forward-compatible.
# The API layer still validates supported connector ids at runtime.
ConnectorId = str
ConnectorRunStatus = Literal["pending", "running", "completed", "failed", "cancelled"]


class ConnectorInfo(BaseModel):
    id: ConnectorId
    name: str
    description: str = ""
    supports_incremental: bool = False
    supports_resume: bool = False
    supports_full_reconcile: bool = False
    sync_cursor_kind: str = "none"


class WebCrawlAuthConfig(BaseModel):
    """
    Authentication config for website crawling.

    Security notes:
    - Secrets (cookie/token/password) are stored encrypted in connector_runs.config by the API layer.
    - The API redacts secrets when returning run.config.
    """

    type: Literal["none", "cookie", "bearer", "basic"] = "none"
    cookie: str | None = Field(default=None, max_length=20_000, description="Cookie header value (login session)")
    token: str | None = Field(default=None, max_length=10_000, description="Bearer token")
    username: str | None = Field(default=None, max_length=500)
    password: str | None = Field(default=None, max_length=10_000)

    @model_validator(mode="after")
    def _validate(self) -> "WebCrawlAuthConfig":
        t = str(self.type or "none").strip().lower()
        self.type = t  # type: ignore[assignment]
        if t == "none":
            self.cookie = None
            self.token = None
            self.username = None
            self.password = None
            return self
        if t == "cookie":
            if not (self.cookie or "").strip():
                raise ValueError("auth.cookie is required for type=cookie")
            self.token = None
            self.username = None
            self.password = None
            return self
        if t == "bearer":
            if not (self.token or "").strip():
                raise ValueError("auth.token is required for type=bearer")
            self.cookie = None
            self.username = None
            self.password = None
            return self
        if t == "basic":
            if not (self.username or "").strip() or not (self.password or "").strip():
                raise ValueError("auth.username/password are required for type=basic")
            self.cookie = None
            self.token = None
            return self
        raise ValueError("invalid auth.type")


class UrlBatchConnectorConfig(BaseModel):
    """Config for `url_batch` connector."""

    urls: list[str] = Field(..., min_length=1, max_length=50, description="One URL per entry")
    filename: str | None = Field(
        default=None,
        max_length=500,
        description="Optional: override filename for display/extension inference (applies to all urls).",
    )
    # Optional: authenticated fetch (cookie/bearer/basic) for private pages.
    user_agent: str | None = Field(default=None, max_length=200)
    auth: WebCrawlAuthConfig | None = None

    parser_backend: str = Field(default="auto")
    chunk_strategy: str = Field(default="langchain_recursive")
    pipeline: DocumentPipelineOptions | None = None
    access: DocumentAccessUpdateRequest | None = None
    source_acl: ConnectorSourceAclConfig | None = None

    @model_validator(mode="after")
    def _normalize(self) -> "UrlBatchConnectorConfig":
        # Trim and dedupe URLs.
        seen: set[str] = set()
        normalized: list[str] = []
        for raw in self.urls or []:
            url = str(raw or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            normalized.append(url)
            if len(normalized) >= 50:
                break
        self.urls = normalized
        return self


class WebCrawlConnectorConfig(BaseModel):
    """Config for `web_crawl` connector (site-level crawling)."""

    start_urls: list[str] = Field(..., min_length=1, max_length=5, description="One or more seed URLs")
    max_pages: int = Field(default=50, ge=1, le=500)
    max_depth: int = Field(default=3, ge=0, le=10)
    same_host_only: bool = Field(default=True, description="Only follow links under the same host as start_urls")
    include_patterns: list[str] = Field(default_factory=list, description="Regex patterns; if set, only matched URLs are crawled")
    exclude_patterns: list[str] = Field(default_factory=list, description="Regex patterns to exclude URLs")
    use_sitemaps: bool = Field(
        default=False,
        description="If true, try sitemap.xml (and robots.txt Sitemap hints) before link crawling (best-effort).",
    )
    sitemap_urls: list[str] = Field(
        default_factory=list,
        description="Optional explicit sitemap URLs (one or more sitemap.xml / sitemapindex.xml).",
    )
    respect_robots: bool = Field(default=False, description="If true, respect robots.txt allow/deny rules (best-effort).")
    dedup_canonical: bool = Field(
        default=True,
        description="If true, deduplicate pages by <link rel='canonical'> when crawling HTML (best-effort).",
    )
    user_agent: str | None = Field(default=None, max_length=200)
    auth: WebCrawlAuthConfig | None = None

    # Ingest options for each discovered URL.
    filename: str | None = Field(default=None, max_length=500, description="Optional: override filename for display/extension inference")
    parser_backend: str = Field(default="auto")
    chunk_strategy: str = Field(default="langchain_recursive")
    pipeline: DocumentPipelineOptions | None = None
    access: DocumentAccessUpdateRequest | None = None
    source_acl: ConnectorSourceAclConfig | None = None

    @model_validator(mode="after")
    def _normalize(self) -> "WebCrawlConnectorConfig":
        # Trim and dedupe start_urls.
        seen: set[str] = set()
        normalized: list[str] = []
        for raw in self.start_urls or []:
            url = str(raw or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            normalized.append(url)
            if len(normalized) >= 5:
                break
        self.start_urls = normalized

        # Deduplicate sitemap URLs (keep it bounded; sitemap discovery is optional).
        sitemap_seen: set[str] = set()
        sitemap_norm: list[str] = []
        for raw in self.sitemap_urls or []:
            url = str(raw or "").strip()
            if not url or url in sitemap_seen:
                continue
            sitemap_seen.add(url)
            sitemap_norm.append(url)
            if len(sitemap_norm) >= 10:
                break
        self.sitemap_urls = sitemap_norm

        # Cap regex patterns to reduce ReDoS risk (compiled server-side).
        self.include_patterns = [str(p or "").strip()[:500] for p in (self.include_patterns or []) if str(p or "").strip()][:30]
        self.exclude_patterns = [str(p or "").strip()[:500] for p in (self.exclude_patterns or []) if str(p or "").strip()][:60]
        return self


class GitHubRepoConnectorConfig(BaseModel):
    """Config for `github_repo` connector (repository file ingestion via raw.githubusercontent.com)."""

    repo: str = Field(..., max_length=200, description="GitHub repo in owner/repo format")
    branch: str = Field(default="main", max_length=200, description="Branch or tag name (default: main)")
    include_extensions: list[str] = Field(
        default_factory=lambda: [".md", ".txt", ".pdf"],
        description="File extensions to ingest (case-insensitive).",
    )
    max_files: int = Field(default=50, ge=1, le=200)
    user_agent: str | None = Field(default=None, max_length=200)
    auth: WebCrawlAuthConfig | None = None  # bearer token for GitHub API (optional)

    # Ingest options for each discovered file URL.
    parser_backend: str = Field(default="auto")
    chunk_strategy: str = Field(default="langchain_recursive")
    pipeline: DocumentPipelineOptions | None = None
    access: DocumentAccessUpdateRequest | None = None
    source_acl: ConnectorSourceAclConfig | None = None

    @model_validator(mode="after")
    def _normalize(self) -> "GitHubRepoConnectorConfig":
        repo = str(self.repo or "").strip()
        if "/" not in repo:
            raise ValueError("repo must be in owner/repo format")
        owner, name = repo.split("/", 1)
        owner = owner.strip()
        name = name.strip()
        if not owner or not name:
            raise ValueError("repo must be in owner/repo format")
        self.repo = f"{owner}/{name}"

        branch = str(self.branch or "").strip() or "main"
        self.branch = branch

        exts: list[str] = []
        seen: set[str] = set()
        for raw in self.include_extensions or []:
            ext = str(raw or "").strip().lower()
            if not ext:
                continue
            if not ext.startswith("."):
                ext = "." + ext
            if len(ext) > 12:
                continue
            if ext in seen:
                continue
            seen.add(ext)
            exts.append(ext)
            if len(exts) >= 20:
                break
        if not exts:
            exts = [".md", ".txt"]
        self.include_extensions = exts
        return self


class DriveFilesConnectorConfig(BaseModel):
    """Config for `drive_files` connector (Google Drive share links -> direct download)."""

    urls: list[str] = Field(..., min_length=1, max_length=50, description="Google Drive file share links")
    filename: str | None = Field(
        default=None,
        max_length=500,
        description="Optional override filename for display/extension inference (applies to all urls).",
    )
    user_agent: str | None = Field(default=None, max_length=200)
    auth: WebCrawlAuthConfig | None = None

    parser_backend: str = Field(default="auto")
    chunk_strategy: str = Field(default="langchain_recursive")
    pipeline: DocumentPipelineOptions | None = None
    access: DocumentAccessUpdateRequest | None = None
    source_acl: ConnectorSourceAclConfig | None = None

    @model_validator(mode="after")
    def _normalize(self) -> "DriveFilesConnectorConfig":
        seen: set[str] = set()
        normalized: list[str] = []
        for raw in self.urls or []:
            url = str(raw or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            normalized.append(url)
            if len(normalized) >= 50:
                break
        self.urls = normalized
        return self


class MinioBucketConnectorConfig(BaseModel):
    """Config for `minio_bucket` connector (list objects -> presigned URLs -> ingest)."""

    bucket: str | None = Field(default=None, max_length=63, description="MinIO bucket name (default: settings.MINIO_BUCKET_NAME)")
    prefix: str | None = Field(default=None, max_length=512)
    include_extensions: list[str] = Field(default_factory=lambda: [".pdf", ".md", ".txt"])
    max_objects: int = Field(default=50, ge=1, le=200)
    presign_expiry_sec: int = Field(default=3600, ge=60, le=7 * 24 * 3600)

    parser_backend: str = Field(default="auto")
    chunk_strategy: str = Field(default="langchain_recursive")
    pipeline: DocumentPipelineOptions | None = None
    access: DocumentAccessUpdateRequest | None = None
    source_acl: ConnectorSourceAclConfig | None = None

    @model_validator(mode="after")
    def _normalize(self) -> "MinioBucketConnectorConfig":
        exts: list[str] = []
        seen: set[str] = set()
        for raw in self.include_extensions or []:
            ext = str(raw or "").strip().lower()
            if not ext:
                continue
            if not ext.startswith("."):
                ext = "." + ext
            if ext in seen:
                continue
            seen.add(ext)
            exts.append(ext)
            if len(exts) >= 20:
                break
        if not exts:
            exts = [".pdf", ".md", ".txt"]
        self.include_extensions = exts
        return self

class ConfluenceSpaceConnectorConfig(BaseModel):
    """Config for `confluence_space` connector (list pages in a space -> ingest page HTML)."""

    base_url: str = Field(..., max_length=2000, description="Confluence base URL (cloud or on-prem). Example: https://<site>.atlassian.net/wiki")
    space_key: str = Field(..., max_length=255, description="Confluence space key")

    # Confluence auth typically supports basic (email + API token) / bearer / cookie session.
    auth: WebCrawlAuthConfig | None = None

    # How to ingest each page after listing:
    # - api_view: fetch HTML via Confluence REST API (body.view)
    # - webui: ingest the Confluence web UI URL via the existing URL ingestion pipeline
    ingest_method: Literal["api_view", "webui"] = Field(
        default="api_view",
        description="api_view: REST body.view; webui: ingest _links.webui URL",
    )

    sync_mode: Literal["auto", "full", "incremental"] = Field(
        default="auto",
        description="auto: incremental if state.last_modified exists else full",
    )
    max_pages: int = Field(default=50, ge=1, le=500)
    page_size: int = Field(default=25, ge=1, le=100)
    soft_delete: bool = Field(default=False, description="If true, disable connector-managed docs missing from a full sync (best-effort).")

    include_attachments: bool = Field(default=False, description="If true, list and ingest page attachments (bounded).")
    max_attachments_per_page: int = Field(default=10, ge=1, le=50, description="Max attachments ingested per page (bounded).")
    max_total_attachments: int = Field(default=200, ge=1, le=2000, description="Max attachments ingested per run (bounded).")

    user_agent: str | None = Field(default=None, max_length=200)

    # Ingest options per page.
    parser_backend: str = Field(default="auto")
    chunk_strategy: str = Field(default="langchain_recursive")
    pipeline: DocumentPipelineOptions | None = None
    access: DocumentAccessUpdateRequest | None = None
    source_acl: ConnectorSourceAclConfig | None = None

    @model_validator(mode="after")
    def _normalize(self) -> "ConfluenceSpaceConnectorConfig":
        self.base_url = str(self.base_url or "").strip().rstrip("/")
        self.space_key = str(self.space_key or "").strip()

        if not self.base_url:
            raise ValueError("base_url is required")
        parsed = urlparse(self.base_url)
        scheme = (parsed.scheme or "").lower().strip()
        if scheme not in {"http", "https"} or not (parsed.netloc or "").strip():
            raise ValueError("base_url must be an absolute URL with scheme http or https")
        if not self.space_key:
            raise ValueError("space_key is required")
        return self


def _normalized_jira_custom_field(raw: object) -> str | None:
    if raw is None:
        return None
    key = str(raw or "").strip().lower()
    if not key or len(key) > 80:
        return None
    if not re.fullmatch(r"customfield_\d+", key):
        return None
    return key


def _normalize_jira_custom_fields(raw_fields: list[str] | None) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for raw in raw_fields or []:
        key = _normalized_jira_custom_field(raw)
        if key is None or key in seen:
            continue
        seen.add(key)
        normalized.append(key)
        if len(normalized) >= 30:
            break
    return normalized


class JiraProjectConnectorConfig(BaseModel):
    """Config for `jira_project` connector (list issues in a Jira project -> ingest rendered issue HTML)."""

    base_url: str = Field(..., max_length=2000, description="Jira base URL. Example: https://<site>.atlassian.net")
    project_key: str = Field(..., max_length=255, description="Jira project key")
    jql: str | None = Field(default=None, max_length=2000, description="Optional extra JQL filter appended to the project query.")

    auth: WebCrawlAuthConfig | None = None

    sync_mode: Literal["auto", "full", "incremental"] = Field(
        default="auto",
        description="auto: incremental if state.last_modified exists else full",
    )
    max_issues: int = Field(default=50, ge=1, le=500)
    page_size: int = Field(default=25, ge=1, le=100)
    include_comments: bool = Field(default=True, description="If true, include issue comments in the rendered HTML document.")
    max_comments_per_issue: int = Field(default=20, ge=0, le=200)
    custom_fields: list[str] = Field(
        default_factory=list,
        description="Optional: allowlist additional Jira custom fields to fetch and include in the rendered issue document. Example: customfield_10016",
    )
    include_linked_artifacts: bool = Field(
        default=False,
        description="If true, extract and ingest linked URL artifacts referenced by the issue (best-effort, bounded).",
    )
    max_linked_artifacts_per_issue: int = Field(default=10, ge=1, le=50, description="Max linked artifacts ingested per issue (bounded).")
    max_total_linked_artifacts: int = Field(default=200, ge=1, le=2000, description="Max linked artifacts ingested per run (bounded).")
    include_attachments: bool = Field(default=False, description="If true, list and ingest issue attachments (bounded).")
    max_attachments_per_issue: int = Field(default=10, ge=1, le=50, description="Max attachments ingested per issue (bounded).")
    max_total_attachments: int = Field(default=200, ge=1, le=2000, description="Max attachments ingested per run (bounded).")

    user_agent: str | None = Field(default=None, max_length=200)

    parser_backend: str = Field(default="auto")
    chunk_strategy: str = Field(default="jira_ticket")
    pipeline: DocumentPipelineOptions | None = None
    access: DocumentAccessUpdateRequest | None = None
    source_acl: ConnectorSourceAclConfig | None = None

    @model_validator(mode="after")
    def _normalize(self) -> "JiraProjectConnectorConfig":
        self.base_url = str(self.base_url or "").strip().rstrip("/")
        self.project_key = str(self.project_key or "").strip().upper()
        if self.jql is not None:
            jql = str(self.jql or "").strip()
            self.jql = jql or None
        self.custom_fields = _normalize_jira_custom_fields(self.custom_fields)

        if not self.base_url:
            raise ValueError("base_url is required")
        parsed = urlparse(self.base_url)
        scheme = (parsed.scheme or "").lower().strip()
        if scheme not in {"http", "https"} or not (parsed.netloc or "").strip():
            raise ValueError("base_url must be an absolute URL with scheme http or https")
        if not self.project_key:
            raise ValueError("project_key is required")
        return self


class MySQLCatalogConnectorConfig(BaseModel):
    """Config for `mysql_catalog` connector (ingest schema/table/column catalog + safe profiling)."""

    host: str = Field(..., max_length=255)
    port: int = Field(default=3306, ge=1, le=65535)
    database: str = Field(..., max_length=255, description="Database name")
    username: str = Field(..., max_length=255)
    password: str = Field(..., max_length=10_000)
    # Optional: allowlist which schemas/tables to ingest (best-effort; connector runner may ignore).
    include_schemas: list[str] = Field(default_factory=list, description="Optional: ingest only these schemas")
    include_tables: list[str] = Field(default_factory=list, description="Optional: ingest only these tables (names, not patterns)")
    max_tables: int = Field(default=200, ge=1, le=2000)
    profile_enabled: bool = Field(default=True, description="If true, compute safe aggregate profiles (no raw rows)")
    row_sync_enabled: bool = Field(
        default=False,
        description="If true, ingest bounded row snapshots into a TAG sidecar document for deterministic row recall.",
    )
    row_sync_max_tables: int = Field(default=0, ge=0, le=500, description="Per-run cap for row-snapshot tables; 0 means use global default.")
    row_sync_max_rows_per_table: int = Field(default=0, ge=0, le=1000, description="Per-table row cap for row snapshots; 0 means use global default.")
    row_sync_max_cols: int = Field(default=0, ge=0, le=500, description="Per-table column cap for row snapshots; 0 means use global default.")

    @model_validator(mode="after")
    def _normalize(self) -> "MySQLCatalogConnectorConfig":
        self.host = str(self.host or "").strip()
        self.database = str(self.database or "").strip()
        self.username = str(self.username or "").strip()
        self.password = str(self.password or "")
        if not self.host:
            raise ValueError("host is required")
        if not self.database:
            raise ValueError("database is required")
        if not self.username:
            raise ValueError("username is required")
        return self


class SQLServerCatalogConnectorConfig(BaseModel):
    """Config for `sqlserver_catalog` connector (ingest schema/table/column catalog + safe profiling)."""

    host: str = Field(..., max_length=255)
    port: int = Field(default=1433, ge=1, le=65535)
    database: str = Field(..., max_length=255, description="Database name")
    username: str = Field(..., max_length=255)
    password: str = Field(..., max_length=10_000)
    # Optional: allowlist which schemas/tables to ingest (best-effort; connector runner may ignore).
    include_schemas: list[str] = Field(default_factory=list, description="Optional: ingest only these schemas")
    include_tables: list[str] = Field(default_factory=list, description="Optional: ingest only these tables (names, not patterns)")
    max_tables: int = Field(default=200, ge=1, le=2000)
    profile_enabled: bool = Field(default=True, description="If true, compute safe aggregate profiles (no raw rows)")
    row_sync_enabled: bool = Field(
        default=False,
        description="If true, ingest bounded row snapshots into a TAG sidecar document for deterministic row recall.",
    )
    row_sync_max_tables: int = Field(default=0, ge=0, le=500, description="Per-run cap for row-snapshot tables; 0 means use global default.")
    row_sync_max_rows_per_table: int = Field(default=0, ge=0, le=1000, description="Per-table row cap for row snapshots; 0 means use global default.")
    row_sync_max_cols: int = Field(default=0, ge=0, le=500, description="Per-table column cap for row snapshots; 0 means use global default.")

    @model_validator(mode="after")
    def _normalize(self) -> "SQLServerCatalogConnectorConfig":
        self.host = str(self.host or "").strip()
        self.database = str(self.database or "").strip()
        self.username = str(self.username or "").strip()
        self.password = str(self.password or "")
        if not self.host:
            raise ValueError("host is required")
        if not self.database:
            raise ValueError("database is required")
        if not self.username:
            raise ValueError("username is required")
        return self


class ConnectorRunCreateRequest(BaseModel):
    connector_id: ConnectorId = "url_batch"
    dataset_id: UUID | None = None
    # Connector-specific config payload (validated in the API layer).
    config: dict[str, Any] = Field(default_factory=dict)


class ConnectorValidateRequest(BaseModel):
    """
    Best-effort connector config validation.

    Notes:
    - This endpoint is intended for operator UX (pre-flight checks).
    - Connectivity checks are optional and best-effort; failures are surfaced as warnings.
    """

    connector_id: ConnectorId = "url_batch"
    config: dict[str, Any] = Field(default_factory=dict)
    check_connectivity: bool = True


class ConnectorValidateResponse(BaseModel):
    ok: bool
    connector_id: str
    config: dict[str, Any] = Field(default_factory=dict)
    errors: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    checks: dict[str, Any] = Field(default_factory=dict)


class ConnectorRunDocumentOut(BaseModel):
    document_id: UUID
    source_ref: str | None = None
    status: str = "created"


class ConnectorRunAclSummaryOut(BaseModel):
    """
    Run-level summary of document ACL applied to connector-created documents.

    Privacy:
    - contains counts only (no member ids)
    """

    mode: str = Field(default="inherit", description="Normalized access_mode; 'mixed' when docs have multiple modes.")
    documents_total: int = 0
    access_mode_counts: dict[str, int] = Field(default_factory=dict)

    partial_members_doc_count: int = 0
    partial_member_count_min: int | None = None
    partial_member_count_max: int | None = None
    partial_group_count_min: int | None = None
    partial_group_count_max: int | None = None


class ConnectorRunOut(BaseModel):
    id: UUID
    tenant_id: UUID
    dataset_id: UUID | None = None
    connector_id: str
    requested_by: str | None = None
    status: ConnectorRunStatus
    config: dict[str, Any] = Field(default_factory=dict)
    stats: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    task_id: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    acl_summary: ConnectorRunAclSummaryOut | None = None
    documents: list[ConnectorRunDocumentOut] = Field(default_factory=list)


class ConnectorRunListResponse(BaseModel):
    total: int
    items: list[ConnectorRunOut]


class ConnectorConfigCreateRequest(BaseModel):
    connector_id: str
    dataset_id: UUID
    name: str = Field(..., max_length=255)
    enabled: bool = True
    schedule_cron: str | None = Field(default=None, max_length=64)
    config: dict[str, Any] = Field(default_factory=dict)


class ConnectorConfigUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    enabled: bool | None = None
    schedule_cron: str | None = Field(default=None, max_length=64)
    config: dict[str, Any] | None = None
    state: dict[str, Any] | None = None


class ConnectorConfigOut(BaseModel):
    id: UUID
    tenant_id: UUID
    dataset_id: UUID
    connector_id: str
    name: str
    enabled: bool
    schedule_cron: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    state: dict[str, Any] = Field(default_factory=dict)
    last_run_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime
    updated_at: datetime


class ConnectorConfigListResponse(BaseModel):
    total: int
    items: list[ConnectorConfigOut]
