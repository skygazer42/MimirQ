"""
Connector-related Pydantic schemas.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

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


class WebCrawlAuthConfig(BaseModel):
    """
    Authentication config for website crawling.

    Security notes:
    - Secrets (cookie/token/password) are stored encrypted in connector_runs.config by the API layer.
    - The API redacts secrets when returning run.config.
    """

    type: Literal["none", "cookie", "bearer", "basic"] = "none"
    cookie: Optional[str] = Field(default=None, max_length=20_000, description="Cookie header value (login session)")
    token: Optional[str] = Field(default=None, max_length=10_000, description="Bearer token")
    username: Optional[str] = Field(default=None, max_length=500)
    password: Optional[str] = Field(default=None, max_length=10_000)

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

    urls: List[str] = Field(..., min_length=1, max_length=50, description="One URL per entry")
    filename: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Optional: override filename for display/extension inference (applies to all urls).",
    )
    # Optional: authenticated fetch (cookie/bearer/basic) for private pages.
    user_agent: Optional[str] = Field(default=None, max_length=200)
    auth: Optional[WebCrawlAuthConfig] = None

    parser_backend: str = Field(default="auto")
    chunk_strategy: str = Field(default="langchain_recursive")
    pipeline: Optional[DocumentPipelineOptions] = None
    access: Optional[DocumentAccessUpdateRequest] = None

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

    start_urls: List[str] = Field(..., min_length=1, max_length=5, description="One or more seed URLs")
    max_pages: int = Field(default=50, ge=1, le=500)
    max_depth: int = Field(default=3, ge=0, le=10)
    same_host_only: bool = Field(default=True, description="Only follow links under the same host as start_urls")
    include_patterns: List[str] = Field(default_factory=list, description="Regex patterns; if set, only matched URLs are crawled")
    exclude_patterns: List[str] = Field(default_factory=list, description="Regex patterns to exclude URLs")
    use_sitemaps: bool = Field(
        default=False,
        description="If true, try sitemap.xml (and robots.txt Sitemap hints) before link crawling (best-effort).",
    )
    sitemap_urls: List[str] = Field(
        default_factory=list,
        description="Optional explicit sitemap URLs (one or more sitemap.xml / sitemapindex.xml).",
    )
    respect_robots: bool = Field(default=False, description="If true, respect robots.txt allow/deny rules (best-effort).")
    dedup_canonical: bool = Field(
        default=True,
        description="If true, deduplicate pages by <link rel='canonical'> when crawling HTML (best-effort).",
    )
    user_agent: Optional[str] = Field(default=None, max_length=200)
    auth: Optional[WebCrawlAuthConfig] = None

    # Ingest options for each discovered URL.
    filename: Optional[str] = Field(default=None, max_length=500, description="Optional: override filename for display/extension inference")
    parser_backend: str = Field(default="auto")
    chunk_strategy: str = Field(default="langchain_recursive")
    pipeline: Optional[DocumentPipelineOptions] = None
    access: Optional[DocumentAccessUpdateRequest] = None

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


class ConnectorRunCreateRequest(BaseModel):
    connector_id: ConnectorId = "url_batch"
    dataset_id: Optional[UUID] = None
    # Connector-specific config payload (validated in the API layer).
    config: Dict[str, Any] = Field(default_factory=dict)


class ConnectorRunDocumentOut(BaseModel):
    document_id: UUID
    source_ref: Optional[str] = None
    status: str = "created"


class ConnectorRunOut(BaseModel):
    id: UUID
    tenant_id: UUID
    dataset_id: Optional[UUID] = None
    connector_id: str
    requested_by: Optional[str] = None
    status: ConnectorRunStatus
    config: Dict[str, Any] = Field(default_factory=dict)
    stats: Dict[str, Any] = Field(default_factory=dict)
    error_message: Optional[str] = None
    task_id: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    documents: List[ConnectorRunDocumentOut] = Field(default_factory=list)


class ConnectorRunListResponse(BaseModel):
    total: int
    items: List[ConnectorRunOut]


class ConnectorConfigCreateRequest(BaseModel):
    connector_id: str
    dataset_id: UUID
    name: str = Field(..., max_length=255)
    enabled: bool = True
    schedule_cron: Optional[str] = Field(default=None, max_length=64)
    config: Dict[str, Any] = Field(default_factory=dict)


class ConnectorConfigUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, max_length=255)
    enabled: Optional[bool] = None
    schedule_cron: Optional[str] = Field(default=None, max_length=64)
    config: Optional[Dict[str, Any]] = None
    state: Optional[Dict[str, Any]] = None


class ConnectorConfigOut(BaseModel):
    id: UUID
    tenant_id: UUID
    dataset_id: UUID
    connector_id: str
    name: str
    enabled: bool
    schedule_cron: Optional[str] = None
    config: Dict[str, Any] = Field(default_factory=dict)
    state: Dict[str, Any] = Field(default_factory=dict)
    last_run_at: Optional[datetime] = None
    last_error: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ConnectorConfigListResponse(BaseModel):
    total: int
    items: List[ConnectorConfigOut]
