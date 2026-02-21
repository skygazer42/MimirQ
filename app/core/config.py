"""
Application configuration module.

Centralized settings management including:
- Security settings (SECRET_KEY, credentials, etc.)
- LLM/Embedding provider config
- RAG pipeline parameters
- Storage backend config
"""
import sys
import warnings
from pathlib import Path
from typing import Literal, Optional
from urllib.parse import urlparse

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.env import is_production_env


class Settings(BaseSettings):
    """
    Application settings with validation.

    All settings can be overridden via environment variables or .env file.
    """

    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/mimirq"
    # SQLAlchemy connection pool (ignored for SQLite).
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT_SEC: int = 30
    DB_POOL_RECYCLE_SEC: int = 1800
    DB_POOL_PRE_PING: bool = True

    # DB schema management (enterprise hardening)
    # - When enabled, the app will run `Base.metadata.create_all()` on startup.
    #   This is convenient for local/dev but is not recommended for production.
    # - Runtime migrations are best-effort `ALTER TABLE ... IF NOT EXISTS` guardrails
    #   for legacy deployments; prefer Alembic migrations for deterministic upgrades.
    DB_CREATE_ALL_ON_STARTUP: bool = Field(
        default=True,
        validation_alias=AliasChoices("MIMIRQ_DB_CREATE_ALL_ON_STARTUP", "DB_CREATE_ALL_ON_STARTUP"),
    )
    DB_RUNTIME_MIGRATIONS_ENABLED: bool = Field(
        default=True,
        validation_alias=AliasChoices("MIMIRQ_DB_RUNTIME_MIGRATIONS_ENABLED", "DB_RUNTIME_MIGRATIONS_ENABLED"),
    )
    MILVUS_HOST: str = "localhost"
    MILVUS_PORT: int = 19530
    MILVUS_USER: str = ""
    MILVUS_PASSWORD: str = ""
    MILVUS_COLLECTION_NAME: str = "documents"
    # Guardrail: avoid building extremely long Milvus expr like
    # `document_id in ["...","...",...]` which can exceed expr limits and hurt latency.
    # 0 disables.
    MILVUS_EXPR_MAX_DOC_IDS: int = 200

    # Object Storage (MinIO / S3-compatible)
    MINIO_ENABLED: bool = False
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET_NAME: str = "mimirq"
    MINIO_USE_SSL: bool = False
    MINIO_METRICS_LOG_PATH: str = "./logs/minio_metrics.jsonl"
    # 0 disables. Used when uploading extracted images to MinIO to avoid huge payloads.
    MINIO_IMAGE_MAX_BYTES: int = 0
    # Store uploaded document source files in MinIO (recommended for enterprise deployments / multi-instance).
    MINIO_DOCUMENTS_ENABLED: bool = False

    # Task Queue / Redis (ingest throughput optimization)
    # - Task queue is off by default: keeps API compatibility; when enabled,
    #   workers handle document parsing/indexing asynchronously.
    TASK_QUEUE_ENABLED: bool = False
    REDIS_URL: str = "redis://localhost:6379/0"
    # Arq worker Redis connection retries.
    # Used to reduce crash loops on cold start when Redis isn't ready yet.
    TASK_WORKER_REDIS_CONN_TIMEOUT_SEC: int = 1
    TASK_WORKER_REDIS_CONN_RETRIES: int = 60
    TASK_WORKER_REDIS_CONN_RETRY_DELAY_SEC: int = 1
    # Arq queue name
    TASK_QUEUE_NAME: str = "mimirq"
    # Worker concurrency (Arq max_jobs).
    TASK_WORKER_MAX_JOBS: int = 10
    # Task execution timeout (seconds).
    TASK_JOB_TIMEOUT_SEC: int = 60 * 30
    # Default retry count (network/external API jitter).
    TASK_JOB_MAX_TRIES: int = 3
    # Per-tenant concurrency limit to avoid one tenant exhausting workers (0 = unlimited).
    TASK_TENANT_MAX_CONCURRENCY_DOC: int = 2
    TASK_TENANT_MAX_CONCURRENCY_KG: int = 1
    TASK_TENANT_MAX_CONCURRENCY_CONNECTOR: int = 1

    # Subprocess worker guardrails (parsing backends).
    # 0 disables.
    SUBPROCESS_PAYLOAD_MAX_BYTES: int = 2_000_000
    SUBPROCESS_RESULT_MAX_BYTES: int = 50_000_000
    SUBPROCESS_LOG_MAX_BYTES: int = 20_000_000

    # Embedding cache (Redis, improves ingest throughput; best-effort).
    EMBEDDING_CACHE_ENABLED: bool = True
    EMBEDDING_CACHE_TTL_SEC: int = 7 * 24 * 3600
    EMBEDDING_CACHE_PREFIX: str = "emb"

    # Chat response cache (Redis; best-effort; safe by default).
    # Stores fully rendered assistant replies for identical requests (guarded by doc scope + config).
    CHAT_RESPONSE_CACHE_ENABLED: bool = False
    CHAT_RESPONSE_CACHE_TTL_SEC: int = 300
    CHAT_RESPONSE_CACHE_PREFIX: str = "chat"
    CHAT_RESPONSE_CACHE_MAX_VALUE_BYTES: int = 200_000
    # Default guardrail: only cache stateless requests (no explicit history).
    CHAT_RESPONSE_CACHE_REQUIRE_EMPTY_HISTORY: bool = True

    # Retrieval candidate cache (Redis, short TTL; best-effort; safe by default).
    # Stores retrieval outputs for identical scoped requests to reduce repeated vector/BM25 work.
    RETRIEVAL_CANDIDATE_CACHE_ENABLED: bool = False
    RETRIEVAL_CANDIDATE_CACHE_TTL_SEC: int = 30
    RETRIEVAL_CANDIDATE_CACHE_PREFIX: str = "rcand"
    RETRIEVAL_CANDIDATE_CACHE_MAX_VALUE_BYTES: int = 400_000

    # Usage quotas (best-effort; disabled by default).
    # Applies per-tenant over a rolling time window.
    CHAT_ASSISTANT_TOKEN_QUOTA_ENABLED: bool = False
    CHAT_ASSISTANT_TOKEN_QUOTA_LIMIT: int = 0
    CHAT_ASSISTANT_TOKEN_QUOTA_WINDOW_HOURS: int = 24
    # Mode:
    # - "block": reject new requests with HTTP 429 when exceeded
    # - "warn": allow but annotate metrics (no enforcement)
    CHAT_ASSISTANT_TOKEN_QUOTA_MODE: str = "block"

    # Vector write batching (Milvus/Chroma/etc). Smaller batches reduce tail latency and memory spikes.
    VECTOR_WRITE_BATCH_SIZE: int = 256
    # Adaptive write batching: when chunks are large, reduce batch size to avoid
    # large embedding payloads / insert spikes (default: enabled).
    VECTOR_WRITE_ADAPTIVE_BATCHING_ENABLED: bool = True
    # Max total characters per vector write batch (best-effort; 0 disables adaptive batching).
    VECTOR_WRITE_BATCH_MAX_CHARS: int = 200_000
    VECTOR_WRITE_MAX_RETRIES: int = 1
    VECTOR_WRITE_RETRY_BACKOFF_SEC: float = 0.5

    LLM_API_KEY: str = Field(default="", validation_alias=AliasChoices("LLM_API_KEY", "OPENAI_API_KEY"))
    LLM_API_BASE: str = Field(default="https://api.openai.com/v1", validation_alias=AliasChoices("LLM_API_BASE", "OPENAI_BASE_URL"))
    LLM_MODEL: str = Field(default="gpt-4-turbo-preview", validation_alias=AliasChoices("LLM_MODEL", "OPENAI_MODEL"))
    LLM_MODEL_FAST: Optional[str] = Field(default=None, validation_alias=AliasChoices("LLM_MODEL_FAST", "LLM_MODEL_LIGHT"))
    LLM_MODEL_HEAVY: Optional[str] = Field(default=None, validation_alias=AliasChoices("LLM_MODEL_HEAVY", "LLM_MODEL_COMPLEX"))
    ENABLE_DYNAMIC_MODEL_ROUTING: bool = False
    MODEL_COMPLEXITY_THRESHOLD: int = 160
    MODEL_COMPLEXITY_HISTORY_WEIGHT: float = 0.35
    LLM_TEMPERATURE: float = 0.7
    LLM_TIMEOUT: int = 60
    LLM_MAX_RETRIES: int = 3

    # Dev/test helper: bypass external LLM calls with a deterministic fake streaming model.
    # Useful for E2E tests and offline development.
    LLM_MOCK_ENABLED: bool = False
    LLM_MOCK_RESPONSE: str = "Hello from mock LLM."

    # HTTP client (httpx) knobs for external API calls
    HTTP_CLIENT_HTTP2_ENABLED: bool = True
    HTTP_CLIENT_MAX_CONNECTIONS: int = 100
    HTTP_CLIENT_MAX_KEEPALIVE_CONNECTIONS: int = 20
    HTTP_CLIENT_KEEPALIVE_EXPIRY_SEC: float = 30.0
    HTTP_CLIENT_TIMEOUT_CONNECT_SEC: float = 10.0
    HTTP_CLIENT_TIMEOUT_READ_SEC: float = 60.0
    HTTP_CLIENT_TIMEOUT_WRITE_SEC: float = 30.0
    HTTP_CLIENT_TIMEOUT_POOL_SEC: float = 5.0
    HTTP_CLIENT_RETRY_MAX_RETRIES: int = 3
    HTTP_CLIENT_RETRY_INITIAL_DELAY_SEC: float = 1.0
    HTTP_CLIENT_RETRY_BACKOFF_FACTOR: float = 2.0
    HTTP_CLIENT_RETRY_JITTER_SEC: float = 0.2

    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: Literal["plain", "json"] = "plain"

    # Security headers (backend hardening)
    SECURITY_HEADERS_ENABLED: bool = True
    SECURITY_HEADERS_X_CONTENT_TYPE_OPTIONS: str = "nosniff"
    SECURITY_HEADERS_X_FRAME_OPTIONS: str = "DENY"
    SECURITY_HEADERS_REFERRER_POLICY: str = "strict-origin-when-cross-origin"
    # HSTS is off by default because TLS termination is deployment-specific.
    SECURITY_HEADERS_HSTS_ENABLED: bool = False
    SECURITY_HEADERS_HSTS_MAX_AGE_SEC: int = 31536000  # 1 year
    SECURITY_HEADERS_HSTS_INCLUDE_SUBDOMAINS: bool = True
    SECURITY_HEADERS_HSTS_PRELOAD: bool = False
    # Optional modern headers (empty => not set).
    SECURITY_HEADERS_PERMISSIONS_POLICY: str = ""
    SECURITY_HEADERS_CROSS_ORIGIN_OPENER_POLICY: str = ""
    SECURITY_HEADERS_CROSS_ORIGIN_RESOURCE_POLICY: str = ""

    # Prometheus metrics
    PROMETHEUS_ENABLED: bool = False

    # Error monitoring
    SENTRY_DSN: str = ""
    SENTRY_TRACES_SAMPLE_RATE: float = 0.0

    # OpenTelemetry tracing (optional)
    OTEL_ENABLED: bool = False
    OTEL_SERVICE_NAME: str = "mimirq"
    OTEL_EXPORTER_OTLP_ENDPOINT: str = ""
    OTEL_EXPORTER_OTLP_HEADERS: str = ""
    OTEL_EXPORTER_OTLP_TIMEOUT_SEC: int = 10

    EMBEDDING_PROVIDER: str = "openai_compatible"
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_API_KEY: str = ""
    EMBEDDING_API_BASE: str = ""
    # Embedding API engineering knobs (batching + concurrency + retry/backoff).
    # Keep defaults conservative to avoid rate-limit spikes in mid-scale ingest.
    EMBEDDING_API_TIMEOUT_SEC: float = 60.0
    EMBEDDING_API_BATCH_SIZE: int = 64
    EMBEDDING_API_MAX_CONCURRENCY: int = 3
    EMBEDDING_API_MAX_RETRIES: int = 3
    EMBEDDING_API_RETRY_BACKOFF_SEC: float = 0.5
    EMBEDDING_API_RETRY_JITTER_SEC: float = 0.2

    UPLOAD_DIR: str = "./uploads"
    MAX_FILE_SIZE: int = 50_000_000
    # Hard cap for HTTP request bodies (Content-Length gate; 0 disables).
    # Keep slightly above MAX_FILE_SIZE to account for multipart overhead.
    REQUEST_MAX_BODY_BYTES: int = 60_000_000
    # Optional: deduplicate uploads by (file_sha256 + pipeline_hash) within a dataset.
    # When enabled, re-uploading the same file with the same pipeline options returns the existing document
    # instead of creating a new record + re-embedding.
    UPLOAD_DEDUP_ENABLED: bool = False

    # Local filesystem scan (precheck) - disabled by default for safety.
    # Enable explicitly for local/on-prem deployments where the API process is allowed to read a mounted folder.
    LOCAL_SCAN_ENABLED: bool = False
    # CSV list of allowed root directories for scanning. Empty => only allow UPLOAD_DIR.
    LOCAL_SCAN_ROOTS: str = ""
    # Precheck scan safety limits.
    PRECHECK_SCAN_MAX_FILES: int = 20_000
    PRECHECK_SCAN_MAX_TOTAL_BYTES: int = 5_000_000_000  # 5GB
    PRECHECK_TEXT_EXTRACT_MAX_BYTES: int = 2_000_000  # per file
    PRECHECK_PDF_SAMPLE_PAGES: int = 3
    PRECHECK_PDF_MIN_TEXT_CHARS_PER_PAGE: int = 50
    PRECHECK_PDF_TEXT_CHARS_PER_PAGE: int = 200
    PRECHECK_PDF_SCAN_RATIO_THRESHOLD: float = 0.7
    PRECHECK_SPREADSHEET_LARGE_ROW_THRESHOLD: int = 5000
    PRECHECK_SPREADSHEET_WIDE_COL_THRESHOLD: int = 80
    PRECHECK_SPREADSHEET_SHEET_THRESHOLD: int = 5
    PRECHECK_SPREADSHEET_MERGED_RATIO_THRESHOLD: float = 0.15
    PRECHECK_LANGUAGE_MIN_CHARS: int = 40
    PRECHECK_TEXT_SHORT_CHARS_THRESHOLD: int = 200
    PRECHECK_TEXT_LOW_DENSITY_THRESHOLD: float = 0.12
    PRECHECK_TEXT_GIBBERISH_DENSITY_THRESHOLD: float = 0.06
    PRECHECK_TEXT_HIGH_REPLACEMENT_RATIO_THRESHOLD: float = 0.08
    PRECHECK_PDF_LOW_DENSITY_RATIO_THRESHOLD: float = 0.3
    PRECHECK_DIRECTORY_STATS_LIMIT: int = 200
    # Whether to include chunk_size hints derived from token distribution in precheck suggestions.
    PRECHECK_SUGGEST_CHUNK_SIZE: bool = True
    # Optional: ingest documents by fetching a remote URL (connector skeleton).
    URL_INGEST_ENABLED: bool = False
    # Optional: ingest structured DB metadata (catalog/profiling) from MySQL/SQLServer.
    # Disabled by default because it requires outbound DB connectivity and careful secrets handling.
    DB_CATALOG_ENABLED: bool = False
    URL_INGEST_MAX_BYTES: int = 50_000_000
    URL_INGEST_TIMEOUT_SEC: float = 30.0
    # Allowlist (CSV) for outbound URL ingestion. Empty means "allow any public host/port"
    # after applying SSRF guards (private/loopback/link-local are blocked by default).
    # Supports wildcard suffix patterns like "*.example.com" (matches "a.example.com" but not "example.com").
    URL_INGEST_ALLOWED_HOSTS: str = ""
    # CSV list of allowed ports (e.g. "80,443"). Empty means allow any.
    URL_INGEST_ALLOWED_PORTS: str = ""
    # Redirect hop cap when follow_redirects=true (defense-in-depth).
    URL_INGEST_MAX_REDIRECTS: int = 5
    # Security: disallow private/loopback/link-local hosts by default (SSRF guard).
    URL_INGEST_ALLOW_PRIVATE_IPS: bool = False
    # Security: do not follow redirects by default (avoid redirect-to-private SSRF).
    URL_INGEST_FOLLOW_REDIRECTS: bool = False
    # Max JSON size (chars) for `pipeline` form field on multipart endpoints (documents upload/preview).
    PIPELINE_FORM_JSON_MAX_CHARS: int = 200_000
    # Best-effort in-process parse cache for interactive preview endpoints (e.g. /documents/chunk-preview).
    # Note: cache is per-worker; set to False/0 to disable.
    PREVIEW_PARSE_CACHE_ENABLED: bool = True
    PREVIEW_PARSE_CACHE_TTL_SEC: int = 600
    PREVIEW_PARSE_CACHE_MAX_ENTRIES: int = 32
    PREVIEW_PARSE_CACHE_MAX_DOC_CHARS: int = 2_000_000
    # Manual cache-bust key for preview parse cache (include parser changes, model changes, etc.).
    PREVIEW_PARSE_CACHE_VERSION: str = "v1"
    # ZIP extraction safety limits (for Markdown+images archives).
    ZIP_MAX_FILES: int = 2000
    ZIP_MAX_TOTAL_UNCOMPRESSED_BYTES: int = 500_000_000
    ZIP_MAX_SINGLE_UNCOMPRESSED_BYTES: int = 100_000_000
    ZIP_MAX_IMAGES: int = 300
    # Inline/local image upload safety limits (Markdown/HTML image refs -> MinIO).
    MAX_INLINE_IMAGE_BYTES: int = 10_000_000
    MAX_INLINE_IMAGES: int = 200
    # Static asset caching for upload-served images (GET /api/v1/documents/image/{id}).
    # 0 disables caching headers.
    ASSET_CACHE_MAX_AGE_SEC: int = 3600
    # Image understanding (caption/OCR) for image chunks during ingest.
    # Conservative defaults: disabled unless explicitly enabled via pipeline metadata.
    IMAGE_CAPTION_ENABLED: bool = False
    IMAGE_OCR_ENABLED: bool = False
    IMAGE_OCR_MAX_CHARS: int = 2000
    IMAGE_OCR_MAX_IMAGES: int = 20
    # Keep this aligned with parser_factory supported non-PDF formats.
    ALLOWED_EXTENSIONS: str = ".pdf,.txt,.md,.rst,.adoc,.asciidoc,.tex,.yaml,.yml,.toml,.sql,.log,.conf,.ini,.cfg,.env,.properties,.patch,.diff,.srt,.vtt,.mk,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.csv,.html,.htm,.json,.jsonl,.ndjson,.xml,.rss,.atom,.graphql,.gql,.proto,.tf,.hcl"

    @property
    def allowed_extensions_list(self) -> list[str]:
        raw = [ext.strip().lower() for ext in str(self.ALLOWED_EXTENSIONS or "").split(",")]
        normalized: list[str] = []
        seen: set[str] = set()
        for ext in raw:
            if not ext:
                continue
            if not ext.startswith("."):
                ext = f".{ext}"
            if ext in seen:
                continue
            seen.add(ext)
            normalized.append(ext)
        return normalized

    MINERU_API_TOKEN: str = ""
    MINERU_API_BASE: str = "https://mineru.net/api/v4"
    MINERU_MODEL_VERSION: str = "vlm"
    MINERU_ENABLED: bool = False
    # MinerU local ZIP mode (Markdown + images)
    MINERU_LOCAL_SERVER_URL: str = ""
    MINERU_VL_SERVER: str = ""

    # DeepSeek OCR (SiliconFlow)
    DEEPSEEK_OCR_ENABLED: bool = False
    SILICONFLOW_API_KEY: str = ""
    SILICONFLOW_API_BASE: str = "https://api.siliconflow.cn/v1"
    DEEPSEEK_OCR_MODEL: str = "deepseek-ai/DeepSeek-OCR"
    DEEPSEEK_OCR_TIMEOUT_SEC: int = 120
    DEEPSEEK_OCR_MAX_TOKENS: int = 4096
    DEEPSEEK_OCR_TEMPERATURE: float = 0.1
    DEEPSEEK_OCR_PDF_DPI: int = 200
    # Page-level parallelism (1 = sequential). Higher values can reduce latency but may hit rate limits.
    DEEPSEEK_OCR_CONCURRENCY: int = 1
    # Include a rendered page image per page in the Markdown output (so preview can show images
    # even when the OCR model returns text-only markdown).
    DEEPSEEK_OCR_INCLUDE_PAGE_IMAGES: bool = True
    # 0 = unlimited.
    DEEPSEEK_OCR_PAGE_IMAGE_MAX_PAGES: int = 0
    # png | jpg (affects the inserted `images/page_XXXX.*` refs; both variants may still be written for compatibility)
    DEEPSEEK_OCR_PAGE_IMAGE_FORMAT: str = "jpg"

    # ETL4LLM (layout/table/image parsing via etl4llm service)
    # Backward-compatible env aliases (deprecated): BISHENG_UNSTRUCTURED_*
    ETL4LLM_ENABLED: bool = Field(default=False, validation_alias=AliasChoices("ETL4LLM_ENABLED", "BISHENG_UNSTRUCTURED_ENABLED"))
    # Example: http://localhost:10001/v1/etl4llm/predict
    ETL4LLM_API_URL: str = Field(default="", validation_alias=AliasChoices("ETL4LLM_API_URL", "BISHENG_UNSTRUCTURED_API_URL"))
    ETL4LLM_TIMEOUT_SEC: int = Field(default=120, validation_alias=AliasChoices("ETL4LLM_TIMEOUT_SEC", "BISHENG_UNSTRUCTURED_TIMEOUT_SEC"))
    # partition | text
    ETL4LLM_MODE: str = Field(default="partition", validation_alias=AliasChoices("ETL4LLM_MODE", "BISHENG_UNSTRUCTURED_MODE"))
    ETL4LLM_FORCE_OCR: bool = Field(default=False, validation_alias=AliasChoices("ETL4LLM_FORCE_OCR", "BISHENG_UNSTRUCTURED_FORCE_OCR"))
    ETL4LLM_ENABLE_FORMULA: bool = Field(default=True, validation_alias=AliasChoices("ETL4LLM_ENABLE_FORMULA", "BISHENG_UNSTRUCTURED_ENABLE_FORMULA"))
    # If partitions contain Image elements, crop them from PDF and emit `![](images/<id>.png)` refs.
    ETL4LLM_EXTRACT_IMAGES: bool = Field(default=True, validation_alias=AliasChoices("ETL4LLM_EXTRACT_IMAGES", "BISHENG_UNSTRUCTURED_EXTRACT_IMAGES"))
    # Best-effort: drop obvious header/footer partitions by type (if provided by the service).
    ETL4LLM_FILTER_PAGE_HEADER_FOOTER: bool = Field(default=False, validation_alias=AliasChoices("ETL4LLM_FILTER_PAGE_HEADER_FOOTER", "BISHENG_UNSTRUCTURED_FILTER_PAGE_HEADER_FOOTER"))
    # Fallback: when the service returns no image refs/crops, include page render images at the top.
    ETL4LLM_INCLUDE_PAGE_IMAGES_IF_EMPTY: bool = True
    ETL4LLM_PAGE_IMAGE_DPI: int = 150
    # 0 = unlimited.
    ETL4LLM_PAGE_IMAGE_MAX_PAGES: int = 20

    # Marker (PDF -> Markdown external service; optional)
    MARKER_ENABLED: bool = False
    # Full endpoint URL, e.g. http://localhost:2080/convert (depends on your Marker service).
    MARKER_API_URL: str = ""
    MARKER_TIMEOUT_SEC: int = 600

    # PaddleOCR-VL (PDF -> Markdown external service; optional)
    PADDLE_VL_ENABLED: bool = False
    # Full endpoint URL, e.g. http://localhost:9030/convert (depends on your PaddleOCR-VL service).
    PADDLE_VL_API_URL: str = ""
    PADDLE_VL_TIMEOUT_SEC: int = 600
    # Display/audit only: expected service pipeline version/mode (not used by the backend parser directly).
    PADDLE_VL_PIPELINE_VERSION: str = "v1.5"
    PADDLE_VL_MODE: str = "doc_parser"

    # olmOCR (PDF -> Markdown external service; optional)
    OLMOCR_ENABLED: bool = False
    # Full endpoint URL, e.g. http://localhost:2085/convert (depends on your olmOCR service).
    OLMOCR_API_URL: str = ""
    OLMOCR_TIMEOUT_SEC: int = 1800

    # PDF quality OCR validation (used by parse-preview scoring)
    RAPIDOCR_ENABLED: bool = False

    # Auth
    # - jwt: require Authorization: Bearer <JWT> (validated with SECRET_KEY)
    # - header: require X-User-ID header (unsafe; intended for local/dev only)
    AUTH_MODE: Literal["jwt", "header"] = "header"

    SECRET_KEY: str = "your-secret-key-change-in-production"
    # Optional previous keys for decrypting already-encrypted secrets (comma-separated).
    # This enables key rotation for connector configs without breaking existing entries.
    SECRET_KEY_FALLBACKS: str = ""
    ALGORITHM: str = "HS256"
    # Optional: verify JWTs via JWKS (typically for RS256/ES256 tokens issued by an external IdP).
    # Comma-separated list of JWKS URLs, e.g. https://issuer.example/.well-known/jwks.json
    JWT_JWKS_URLS: str = ""
    # Optional: derive JWKS URL via OIDC discovery when JWT_JWKS_URLS is empty.
    # Uses {JWT_ISSUER}/.well-known/openid-configuration and reads jwks_uri.
    JWT_JWKS_DISCOVERY_ENABLED: bool = False
    # JWKS cache TTL. Avoids fetching keys on every request.
    JWT_JWKS_CACHE_TTL_SEC: int = 300
    # When refresh fails, allow using cached keys for up to this many seconds before failing closed.
    JWT_JWKS_MAX_STALE_SEC: int = 3600
    # HTTP timeout for JWKS fetches.
    JWT_JWKS_HTTP_TIMEOUT_SEC: float = 5.0
    # OIDC discovery cache/timeout (used only when JWT_JWKS_DISCOVERY_ENABLED=true).
    JWT_OIDC_DISCOVERY_CACHE_TTL_SEC: int = 3600
    JWT_OIDC_DISCOVERY_MAX_STALE_SEC: int = 86400
    JWT_OIDC_DISCOVERY_HTTP_TIMEOUT_SEC: float = 5.0
    # Optional JWT claim enforcement. When set, incoming JWTs must match.
    # NOTE: If you set these, tokens issued by /api/v1/auth/login will include these claims.
    JWT_ISSUER: str = ""
    JWT_AUDIENCE: str = ""
    # Optional multi-tenant binding via JWT claim (e.g. "tid" or "tenant_id").
    # When set, tokens issued by /api/v1/auth/login will include this claim when a current tenant is available.
    JWT_TENANT_CLAIM: str = ""
    # When enabled (and JWT_TENANT_CLAIM is set), require X-Tenant-ID header to match the JWT tenant claim.
    # This mitigates cross-tenant spoofing via headers in AUTH_MODE=jwt while staying backwards compatible by default.
    JWT_ENFORCE_TENANT_HEADER_MATCH: bool = False
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    PASSWORD_MIN_LENGTH: int = 8

    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:3001"
    # Whether CORS responses include `Access-Control-Allow-Credentials: true`.
    #
    # Prod strategy (Option A):
    # - Default false in production unless explicitly enabled.
    # - Default true outside production for local dev ergonomics.
    CORS_ALLOW_CREDENTIALS: bool = True
    # Allow browsers to read diagnostic headers from cross-origin responses.
    # NOTE: This does not affect which headers the backend sends, only what the browser exposes to JS.
    CORS_EXPOSE_HEADERS: str = "X-Request-ID,X-Process-Time-Ms,Server-Timing,Retry-After"
    # Allowed Host header values (Starlette TrustedHostMiddleware).
    # - Dev default: empty => middleware disabled outside production.
    # - Production: required when TRUSTED_HOSTS_ENABLED=true.
    ALLOWED_HOSTS: str = ""
    TRUSTED_HOSTS_ENABLED: bool = True

    # API surface exposure (docs / schema).
    # Prod strategy (Option A): default disabled in production unless explicitly enabled.
    API_DOCS_ENABLED: bool = True
    API_OPENAPI_ENABLED: bool = True

    # Settings API `.env` mutation guard.
    #
    # Prod strategy (Option A): default disabled in production unless explicitly enabled.
    # This reduces the blast radius of a compromised admin token and aligns with
    # "config via deploy pipeline" practices.
    SETTINGS_ENV_WRITE_ENABLED: bool = True

    # Emit Server-Timing response header for quick perf debugging.
    SERVER_TIMING_ENABLED: bool = True

    # Health/readiness cache TTL (seconds). Keeps probes cheap under load.
    HEALTH_CACHE_TTL_SEC: float = 2.0
    READY_CACHE_TTL_SEC: float = 2.0

    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Response compression (Starlette GZipMiddleware).
    # NOTE: text/event-stream is excluded by default (safe for SSE).
    GZIP_ENABLED: bool = True
    GZIP_MIN_SIZE: int = 1000
    GZIP_COMPRESS_LEVEL: int = 5

    CHUNK_SIZE: int = 1000
    CHUNK_OVERLAP: int = 200
    # Drop extremely short chunks during indexing (0 disables).
    CHUNK_MIN_CHARS: int = 30
    # Optional: merge extremely short chunks with neighbors before indexing (0 disables).
    # This helps reduce "over-fragmentation" in some structured splitters.
    CHUNK_MERGE_SMALL_MIN_CHARS: int = 0
    # Guardrail: cap chunk count per document during ingest (0 disables).
    # Useful for huge PDFs that would otherwise generate excessive chunks and indexing load.
    MAX_CHUNKS_PER_DOCUMENT: int = 0
    # Strategy when MAX_CHUNKS_PER_DOCUMENT is enabled:
    # - head: keep first N
    # - asset_uniform: always keep first chunk + asset chunks, then uniformly sample remaining text chunks
    MAX_CHUNKS_PER_DOCUMENT_STRATEGY: str = "head"
    # Optional: drop exact-duplicate text chunks within a single document.
    # Useful for PDFs that repeat headers/footers or boilerplate blocks.
    CHUNK_DEDUP_ENABLED: bool = False
    # Mid-scale default: keep recall reasonable without exploding context/token cost.
    RETRIEVAL_TOP_K: int = 10
    SIMILARITY_THRESHOLD: float = 0.7
    # Concurrent retrieval across query variants (multi-query / decompose / HyDE).
    RETRIEVAL_QUERY_PARALLELISM: int = 1
    # MMR (Maximal Marginal Relevance) settings
    RETRIEVAL_MMR_LAMBDA: float = 0.7  # Balance relevance vs diversity (0=diversity, 1=relevance)
    RETRIEVAL_MMR_FETCH_K_MULTIPLIER: int = 4  # Fetch k*multiplier candidates for MMR selection
    # Retrieval fusion strategy:
    # - linear: min-max normalize each channel then alpha-blend
    # - rrf: reciprocal-rank fusion (normalized for UI)
    RETRIEVAL_FUSION_STRATEGY: str = "linear"  # linear | rrf
    RETRIEVAL_RRF_K: int = 60
    # Post-retrieval guards (dedup/diversity)
    RETRIEVAL_DEDUP_ENABLED: bool = True
    RETRIEVAL_DEDUP_JACCARD_THRESHOLD: float = 0.92
    RETRIEVAL_DEDUP_MAX_COMPARE: int = 50
    # Per-document diversity (0 disables)
    RETRIEVAL_MAX_CHUNKS_PER_DOC: int = 3
    # Metadata filtering for vector search
    RETRIEVAL_METADATA_FILTER_ENABLED: bool = True
    RETRIEVAL_MIN_DISTINCT_DOCS: int = 0
    # When retrieval is not pre-scoped by explicit document_ids (open scope / dataset scope),
    # we may need to over-fetch to compensate for candidate-level ACL + active-pipeline trimming.
    # 1 disables.
    RETRIEVAL_OVERFETCH_MULTIPLIER: int = 4
    # Hard cap for the over-fetched k (0 disables).
    RETRIEVAL_OVERFETCH_MAX_K: int = 50

    # Persistent lexical fallback (Postgres FTS / pg_trgm).
    # Helps reduce false negatives for numbers, codes, and exact phrases.
    LEXICAL_DB_ENABLED: bool = True
    LEXICAL_DB_FTS_CONFIG: str = "simple"
    LEXICAL_DB_TRGM_ENABLED: bool = True
    # Candidate overfetch inside the lexical channel (applied before metadata trimming).
    LEXICAL_DB_FETCH_MULTIPLIER: int = 4
    LEXICAL_DB_MAX_CANDIDATES: int = 200
    LEXICAL_DB_TRGM_MIN_QUERY_CHARS: int = 3

    # Prompt context guards (0 disables)
    RAG_CONTEXT_MAX_CHARS_PER_CHUNK: int = 1500
    RAG_CONTEXT_MAX_TOTAL_CHARS: int = 12_000
    RAG_CONTEXT_MAX_KG_CHARS: int = 3_000
    # Optional token-based guards (0 disables). When enabled, takes precedence over char guards.
    RAG_CONTEXT_MAX_TOKENS_PER_CHUNK: int = 0
    RAG_CONTEXT_MAX_TOTAL_TOKENS: int = 0
    RAG_CONTEXT_MAX_KG_TOKENS: int = 0
    # Optional: inject KG-linked chunks (via KG event chunk_id) into RAG retrieval results.
    RAG_KG_CHUNK_INJECTION_ENABLED: bool = False
    RAG_KG_CHUNK_INJECTION_MAX_CHUNKS: int = 5
    # Optional: KG-derived query expansion (entity names -> extra retrieval queries).
    RAG_KG_QUERY_EXPANSION_ENABLED: bool = False
    RAG_KG_QUERY_EXPANSION_MAX_ENTITIES: int = 5
    RAG_KG_QUERY_EXPANSION_MAX_QUERIES: int = 5
    RAG_KG_QUERY_EXPANSION_MIN_ENTITY_WEIGHT: float = 0.15
    # Optional: route retrieval defaults by question type when `retrieval_mode=auto`.
    RAG_RECALL_BUCKETS_ENABLED: bool = False
    # Optional: include adjacent chunks around top hits to improve continuity (0 disables).
    RAG_CONTEXT_NEIGHBOR_WINDOW: int = 0
    # Max number of neighbor chunks to add in total (0 disables the cap).
    RAG_CONTEXT_NEIGHBOR_MAX_ADDED: int = 20
    # Optional: parent-child auto merge (retrieve children, return/append parents).
    RAG_PARENT_CHILD_AUTO_MERGE_ENABLED: bool = False
    # - replace: collapse multiple children under the same parent into one parent chunk
    # - append: keep children and append the parent chunk (deduped)
    RAG_PARENT_CHILD_AUTO_MERGE_MODE: str = "replace"
    RAG_PARENT_CHILD_AUTO_MERGE_MIN_CHILDREN: int = 2
    RAG_PARENT_CHILD_AUTO_MERGE_MAX_PARENTS: int = 20
    # Context evidence extraction (query-focused sentence selection)
    RAG_CONTEXT_EVIDENCE_ENABLED: bool = False
    RAG_CONTEXT_EVIDENCE_MAX_SENTENCES_PER_CHUNK: int = 6
    RAG_CONTEXT_EVIDENCE_MIN_SENTENCE_CHARS: int = 10
    # Grounding guard: abstain when evidence is weak/empty.
    RAG_ABSTAIN_ENABLED: bool = False
    RAG_ABSTAIN_MIN_CITATIONS: int = 1
    RAG_ABSTAIN_MIN_TOP_RELEVANCE_SCORE: float = 0.0  # 0 disables
    # Post-generation grounding guard: verify each claim against evidence and drop unsupported ones.
    # Disabled by default because it may delay streaming (answer is buffered for claim-check).
    RAG_CLAIM_CHECK_ENABLED: bool = False
    RAG_CLAIM_CHECK_MAX_CLAIMS: int = 24
    # Strict grounding: treat missing evidence as non-existent. When enabled:
    # - Force abstain gate even if RAG_ABSTAIN_ENABLED=false
    # - Force claim-check (non-structured output) even if RAG_CLAIM_CHECK_ENABLED=false
    RAG_VISIBLE_EVIDENCE_ONLY_ENABLED: bool = False
    USE_LANGGRAPH_PIPELINE: bool = False
    RAG_GRAPH_MAX_RETRIES: int = 2
    RAG_GRAPH_TIMEOUT_SEC: int = 20
    RAG_GRAPH_CACHE_TTL_SEC: int = 0
    # LangGraph 1.0+ Functional API (preferred when available)
    LANGGRAPH_USE_FUNCTIONAL_API: bool = True
    LANGGRAPH_RECURSION_LIMIT: int = 25
    LANGGRAPH_USE_SUBGRAPHS: bool = False

    # Middleware System Configuration
    MIDDLEWARE_ENABLED: bool = True
    MIDDLEWARE_ERROR_HANDLER_ENABLED: bool = True
    MIDDLEWARE_ERROR_HANDLER_MAX_RETRIES: int = 3
    MIDDLEWARE_DYNAMIC_MODEL_ENABLED: bool = False  # Syncs with ENABLE_DYNAMIC_MODEL_ROUTING
    MIDDLEWARE_DYNAMIC_PROMPT_ENABLED: bool = True
    MIDDLEWARE_INJECT_TIME_CONTEXT: bool = True
    MIDDLEWARE_DEFAULT_RESPONSE_STYLE: str = ""  # professional | casual | technical | concise | detailed
    # Tool-call middleware (logging wrapper)
    TOOL_CALL_LOG_ENABLED: bool = False
    TOOL_CALL_LOG_INCLUDE_PREVIEW: bool = False
    TOOL_CALL_LOG_MAX_PREVIEW_CHARS: int = 500
    # Agent/workflow lifecycle logging
    AGENT_LOG_ENABLED: bool = False
    AGENT_LOG_INCLUDE_EXECUTION_PATH: bool = False
    AGENT_LOG_MAX_PREVIEW_CHARS: int = 500

    VECTOR_BACKEND: str = "milvus"  # milvus | memory | faiss | chroma
    # Indexing toggles (to reduce duplicate pipelines when desired)
    CHUNK_VECTOR_ENABLED: bool = True
    # When true, allow per-dataset/document pipeline to prefix chunk content with structural context
    # (e.g. header_path) before embedding. Default is off to keep backward-compatible vectors.
    EMBEDDING_CONTEXT_PREFIX_ENABLED: bool = False
    EVENT_VECTOR_ENABLED: bool = True
    ENTITY_VECTOR_ENABLED: bool = True
    BM25_INDEX_ENABLED: bool = True
    # BM25 cold-start mitigation (build on first query when index missing).
    BM25_LAZY_BUILD_ENABLED: bool = True
    # When true and document_ids not provided, build BM25 for the whole tenant (can be expensive).
    BM25_LAZY_BUILD_FULL_TENANT: bool = False
    # Upper bound for lazy-built chunks (0 disables the cap).
    BM25_LAZY_BUILD_MAX_CHUNKS: int = 8000
    # Startup BM25 bootstrap (can be expensive; prefer lazy-build for large deployments).
    BM25_STARTUP_BUILD_ENABLED: bool = False
    # Upper bound for startup-built chunks across the whole instance (0 disables the cap).
    BM25_STARTUP_BUILD_MAX_CHUNKS: int = 8000
    # Max cached BM25 indices kept in memory (0 = unlimited). Useful for multi-tenant deployments.
    BM25_CACHE_MAX_TENANTS: int = 32
    # BM25 tokenization knobs (recall tuning).
    # These defaults are intentionally "recall-friendly" but still avoid full CJK char-ngram indexing
    # (which can explode index size in pure-Python BM25 implementations).
    BM25_TOKENIZE_ASCII_EXPAND_ENABLED: bool = True
    BM25_TOKENIZE_NUMERIC_NORMALIZATION_ENABLED: bool = True
    BM25_TOKENIZE_CJK_OOV_BIGRAM_ENABLED: bool = True
    # When jieba emits single-character CJK tokens (often OOV), we may add the concatenated term
    # itself as a token if it's short enough (e.g., entity names).
    BM25_TOKENIZE_CJK_OOV_MAX_TERM_CHARS: int = 8
    # Upper bound for extra fallback tokens added per tokenization call.
    BM25_TOKENIZE_CJK_OOV_MAX_EXTRA_TOKENS: int = 128
    # =========================
    # Structured Table Store (TAG)
    # =========================
    # When enabled (globally or via per-dataset/document pipeline), supported table-like files
    # (.csv/.xls/.xlsx) are imported into a per-document SQLite store for SQL/TAG workflows.
    TABLE_STORE_ENABLED: bool = False
    TABLE_STORE_DIR: str = "./uploads/table_store"
    # sqlite3 connection timeout (seconds) for TAG import/query. Keep low to avoid hanging requests.
    TABLE_STORE_SQLITE_TIMEOUT_SEC: float = 30.0
    TABLE_STORE_MAX_ROWS: int = 200_000  # 0 disables cap
    TABLE_STORE_MAX_COLS: int = 500      # 0 disables cap
    TABLE_STORE_MAX_SHEETS: int = 50     # 0 disables cap
    TABLE_STORE_SAMPLE_ROWS: int = 20    # 0 disables sample persistence
    # When enabled, redact common PII/secrets patterns from table rows returned by TAG APIs
    # for non-admin roles. This is a UI/data-egress safety guard (independent from LLM usage).
    TABLE_ROW_REDACTION_ENABLED: bool = False
    # Auto routing (optional): when table_store_enabled=true, decide per-file whether to use TAG (table_store)
    # or fall back to normal parsing+RAG based on table size/complexity signals.
    #
    # This is useful when you want:
    # - small tables -> parse to Markdown / chunk / index (RAG)
    # - large/complex tables -> import to SQLite (TAG / Text-to-SQL)
    TABLE_STORE_AUTO_ROUTE: bool = False
    TABLE_STORE_AUTO_ROW_THRESHOLD: int = 5000
    TABLE_STORE_AUTO_COL_THRESHOLD: int = 80
    TABLE_STORE_AUTO_SHEET_THRESHOLD: int = 5
    TABLE_STORE_AUTO_FILE_BYTES_THRESHOLD: int = 5_000_000
    # Query/runtime guards (server-side safety, independent from LLM usage).
    TABLE_QUERY_MAX_ROWS: int = 200
    TABLE_QUERY_MAX_COLS: int = 200
    TABLE_QUERY_MAX_BYTES: int = 1_000_000
    TABLE_QUERY_MAX_SQL_CHARS: int = 20_000
    # Abort long-running SQL queries (SQLite VM instruction budget via progress handler).
    TABLE_QUERY_TIMEOUT_SEC: float = 5.0
    TABLE_QUERY_PROGRESS_OPS: int = 10_000
    # NL->SQL / TAG answer generation (optional; requires LLM credentials).
    TABLE_NL2SQL_ENABLED: bool = False
    # Data egress controls for LLM-backed table operations.
    # - RESULT_EGRESS: allow sending SQL query results (rows) to an LLM (for answer drafting).
    # - ROW_EGRESS: allow sending raw table rows to an LLM (e.g. semantic filter).
    TABLE_LLM_ALLOW_RESULT_EGRESS: bool = False
    TABLE_LLM_ALLOW_ROW_EGRESS: bool = False
    # LOTUS semantic operators (optional/experimental).
    TABLE_LOTUS_ENABLED: bool = False
    TABLE_LOTUS_MAX_ROWS: int = 20_000
    # Built-in semantic filter guards (LOTUS-like). These protect against accidental high-cost scans.
    TABLE_SEM_FILTER_MAX_IN_ROWS: int = 2000
    TABLE_SEM_FILTER_MAX_COLS: int = 30
    TABLE_SEM_FILTER_MAX_CELL_CHARS: int = 200
    TABLE_SEM_FILTER_BATCH_SIZE: int = 25
    FAISS_STORE_PATH: str = "./vector_faiss"
    # FAISS persistence uses pickle; enable only when the index directory is fully trusted.
    FAISS_ALLOW_DANGEROUS_DESERIALIZATION: bool = False
    CHROMA_PERSIST_PATH: str = "./vector_chroma"
    ENABLE_METRICS_LOG: bool = False
    METRICS_LOG_PATH: str = "./logs/rag_metrics.jsonl"
    # When false (default), omit raw question/query/snippets from metrics logs to reduce PII leakage.
    METRICS_LOG_INCLUDE_TEXT: bool = False
    ENABLE_QUERY_REWRITE: bool = False
    QUERY_REWRITE_TEMPERATURE: float = 0.2
    QUERY_REWRITE_MAX_CHARS: int = 120
    ENABLE_MULTI_QUERY: bool = False
    MULTI_QUERY_COUNT: int = 3
    MULTI_QUERY_TEMPERATURE: float = 0.2
    MULTI_QUERY_MAX_CHARS: int = 200
    ENABLE_HYDE: bool = False
    HYDE_TEMPERATURE: float = 0.2
    HYDE_MAX_CHARS: int = 200
    HYDE_OUTPUT_MAX_CHARS: int = 800
    ENABLE_QUERY_DECOMPOSITION: bool = False
    QUERY_DECOMPOSITION_MAX_SUBQUESTIONS: int = 3
    QUERY_DECOMPOSITION_TEMPERATURE: float = 0.2
    QUERY_DECOMPOSITION_MIN_CHARS: int = 60
    QUERY_DECOMPOSITION_MAX_CHARS: int = 400
    # When enabled, use a deterministic heuristic decomposition fallback when LLM decomposition
    # is unavailable/fails. Keeps "no LLM" deployments usable.
    QUERY_DECOMPOSITION_HEURISTIC_FALLBACK_ENABLED: bool = True
    GOVERNANCE_ENABLED: bool = False
    GOVERNANCE_REMOVE_TOC_LINES: bool = True
    GOVERNANCE_REMOVE_NOISE_LINES: bool = True
    GOVERNANCE_UNWRAP_LINES: bool = True
    GOVERNANCE_REMOVE_COMMON_LINES: bool = True
    GOVERNANCE_UNWRAP_MAX_LINE_LENGTH: int = 120
    GOVERNANCE_NOISE_MIN_CHARS: int = 2
    GOVERNANCE_NOISE_RATIO_THRESHOLD: float = 0.2
    GOVERNANCE_COMMON_LINES_MIN_DOCS: int = 3
    GOVERNANCE_COMMON_LINES_MIN_RATIO: float = 0.35
    # Best-effort runtime guard for governance regex substitutions (ReDoS mitigation).
    GOVERNANCE_REGEX_TIMEOUT_MS: int = 100
    # Optional governance extensions (safe defaults; can be overridden per-dataset/document pipeline config).
    GOVERNANCE_REMOVE_BOILERPLATE: bool = False
    GOVERNANCE_REMOVE_IMAGES: str = "none"  # none | decorative | all
    GOVERNANCE_EXTRACT_FRONTMATTER: bool = False
    GOVERNANCE_STRIP_FRONTMATTER: bool = False
    GOVERNANCE_DETECT_LANGUAGE: bool = False
    GOVERNANCE_LANGUAGE_MIN_CHARS: int = 40
    GOVERNANCE_NORMALIZE_URLS: bool = False
    GOVERNANCE_NORMALIZE_URLS_STRIP_TRACKING: bool = True
    GOVERNANCE_DROP_DUPLICATE_PARAGRAPHS: bool = False
    GOVERNANCE_DROP_DUPLICATE_PARAGRAPHS_MIN_OCCURRENCES: int = 3
    GOVERNANCE_DROP_DUPLICATE_PARAGRAPHS_MIN_CHARS: int = 40
    GOVERNANCE_DROP_DUPLICATE_PARAGRAPHS_MAX_CHARS: int = 1200
    GOVERNANCE_TRIM_REFERENCES: bool = False
    GOVERNANCE_EXTRACT_KEYWORDS: bool = False
    GOVERNANCE_KEYWORDS_PROVIDER: str = "auto"
    GOVERNANCE_KEYWORDS_TOP_K: int = 10
    GOVERNANCE_KEYWORDS_MAX_CHARS: int = 20_000
    GOVERNANCE_NORMALIZE_TABLES: bool = False
    GOVERNANCE_STRIP_CODE_LINE_NUMBERS: bool = False
    GOVERNANCE_PII_ANONYMIZE: bool = False
    GOVERNANCE_PII_MODE: str = "mask"  # mask | token
    GOVERNANCE_PII_MASK: str = "[REDACTED]"
    # Compliance gate: if >=0, quarantine/drop a document when total PII hits exceed this threshold (sum across kinds).
    GOVERNANCE_PII_MAX_HITS: int = -1
    GOVERNANCE_SECRETS_REDACT: bool = False
    GOVERNANCE_SECRETS_MODE: str = "mask"  # mask | token
    GOVERNANCE_SECRETS_MASK: str = "[SECRET]"
    # Compliance gate: if >=0, quarantine/drop a document when total secrets hits exceed this threshold (sum across kinds).
    GOVERNANCE_SECRETS_MAX_HITS: int = -1
    GOVERNANCE_MAX_BLANK_LINES: int = 1
    GOVERNANCE_HTML_XPATH: str = ""
    GOVERNANCE_DROP_OUTLINE_ONLY: bool = False
    GOVERNANCE_DROP_OUTLINE_MIN_CONTENT_CHARS: int = 200
    GOVERNANCE_DROP_OUTLINE_MAX_HEADING_RATIO: float = 0.85
    GOVERNANCE_DROP_LOW_DENSITY: bool = False
    GOVERNANCE_DROP_LOW_DENSITY_THRESHOLD: float = 0.12
    # When governance drop filters trigger, mark document as "quarantined" instead of "failed".
    GOVERNANCE_QUARANTINE_ON_DROP: bool = False
    # Parsing fallback (PDF only): retry with a different backend when output quality is low.
    PARSE_FALLBACK_ENABLED: bool = False
    PARSE_FALLBACK_MIN_CONTENT_CHARS: int = 120
    PARSE_FALLBACK_MAX_RETRIES: int = 1
    # Persist parsed markdown (raw+clean) for audit/debug.
    PERSIST_PARSED_CONTENT: bool = False
    PERSIST_PARSED_CONTENT_MAX_CHARS: int = 200_000
    # Cross-document near-duplicate chunk drop (SimHash; best-effort).
    NEAR_DEDUP_ENABLED: bool = False
    NEAR_DEDUP_HAMMING_THRESHOLD: int = 3
    NEAR_DEDUP_MAX_BUCKET_SIZE: int = 256
    # Reranker (optional: use LLM to rerank candidates for better quality).
    ENABLE_RERANKER: bool = False
    RERANKER_PROVIDER: str = "llm"  # llm | pc | none
    RERANKER_MODEL: Optional[str] = None
    # Optional: use a dedicated API key/base for API-style rerankers (openai/dashscope),
    # falls back to LLM_API_KEY/LLM_API_BASE when empty.
    RERANKER_API_KEY: str = ""
    RERANKER_API_BASE: str = ""
    RERANKER_TOP_N: int = 20  # Rerank candidate count (higher = slower).
    RERANKER_MAX_CHARS: int = 800  # Max chars per candidate.
    RERANKER_TEMPERATURE: float = 0.0
    # API Reranker engineering knobs (batch/concurrency/rate-limit/circuit/cache)
    RERANKER_API_TIMEOUT_SEC: float = 30.0
    RERANKER_API_BATCH_SIZE: int = 32
    RERANKER_API_MAX_CONCURRENCY: int = 4
    RERANKER_API_RATE_LIMIT_QPS: float = 0.0  # 0 disables
    RERANKER_API_MAX_RETRIES: int = 2
    RERANKER_API_RETRY_BACKOFF_SEC: float = 0.5
    RERANKER_API_CIRCUIT_BREAKER_FAILURE_THRESHOLD: int = 5
    RERANKER_API_CIRCUIT_BREAKER_RESET_SEC: int = 60
    RERANKER_API_CACHE_ENABLED: bool = True
    RERANKER_API_CACHE_MAX_ENTRIES: int = 2000
    RERANKER_API_CACHE_TTL_SEC: int = 3600
    DEFAULT_PARSER_BACKEND: str = "auto"
    DEFAULT_CHUNK_STRATEGY: str = "langchain_recursive"
    DEEPDOC_ENABLED: bool = False
    # Vision LLM (optional): used by integrated chunkers/parsers for vision parsing/enrichment.
    # Disabled by default to keep out-of-the-box behavior (fallback to plaintext).
    VISION_LLM_ENABLED: bool = Field(
        default=False,
        validation_alias=AliasChoices("MIMIRQ_VISION_LLM_ENABLED", "VISION_LLM_ENABLED"),
    )
    # Optional: use a dedicated API key/base for vision calls; falls back to LLM_API_KEY/LLM_API_BASE when empty.
    VISION_LLM_API_KEY: str = Field(
        default="",
        validation_alias=AliasChoices("MIMIRQ_VISION_LLM_API_KEY", "VISION_LLM_API_KEY"),
    )
    VISION_LLM_API_BASE: str = Field(
        default="",
        validation_alias=AliasChoices("MIMIRQ_VISION_LLM_API_BASE", "VISION_LLM_API_BASE"),
    )
    # OpenAI-compatible vision model id, e.g. "gpt-4o-mini".
    VISION_LLM_MODEL: str = Field(
        default="gpt-4o-mini",
        validation_alias=AliasChoices("MIMIRQ_VISION_LLM_MODEL", "VISION_LLM_MODEL"),
    )
    VISION_LLM_TIMEOUT_SEC: int = Field(
        default=120,
        validation_alias=AliasChoices("MIMIRQ_VISION_LLM_TIMEOUT_SEC", "VISION_LLM_TIMEOUT_SEC"),
    )
    VISION_LLM_MAX_TOKENS: int = Field(
        default=4096,
        validation_alias=AliasChoices("MIMIRQ_VISION_LLM_MAX_TOKENS", "VISION_LLM_MAX_TOKENS"),
    )
    VISION_LLM_TEMPERATURE: float = Field(
        default=0.0,
        validation_alias=AliasChoices("MIMIRQ_VISION_LLM_TEMPERATURE", "VISION_LLM_TEMPERATURE"),
    )
    MARKITDOWN_ENABLED: bool = False
    # Pandoc Office/HTML -> Markdown parser (optional; requires system pandoc)
    PANDOC_ENABLED: bool = False
    PANDOC_CLI: str = "pandoc"
    PANDOC_TIMEOUT_SEC: int = 180
    PANDOC_TO_FORMAT: str = "gfm"  # gfm | markdown | commonmark | ...
    PANDOC_WRAP: str = "none"  # none | auto | preserve
    PANDOC_EXTRACT_MEDIA: bool = True
    PANDOC_HTML_USE_READABILITY: bool = True
    # LibreOffice CLI used as a fallback converter for legacy Office formats (optional; heavy)
    LIBREOFFICE_ENABLED: bool = False
    LIBREOFFICE_CLI: str = "soffice"
    LIBREOFFICE_TIMEOUT_SEC: int = 300
    # MagicPDF (magic-pdf) local parser (optional; heavy dependencies)
    MAGIC_PDF_ENABLED: bool = False
    MAGIC_PDF_CLI: str = "magic-pdf"
    MAGIC_PDF_METHOD: str = "auto"  # auto | ocr | txt
    MAGIC_PDF_LANG: str = ""  # optional PaddleOCR language code, e.g. "ch"
    MAGIC_PDF_DEBUG: bool = False
    MAGIC_PDF_TIMEOUT_SEC: int = 600
    MAGIC_PDF_KEEP_ARTIFACTS: bool = False
    # MagicPDF upstream config file path override (env var name used by magic-pdf).
    # - When empty, the backend generates a minimal config per run.
    # - If set to a relative path, magic-pdf resolves it under the OS user home directory.
    MINERU_TOOLS_CONFIG_JSON: str = ""
    MARKITDOWN_USE_PLUGINS: bool = False
    MARKITDOWN_DOCINTEL_ENDPOINT: str = ""
    MARKITDOWN_DOCINTEL_KEY: str = ""
    LLAMA_INDEX_ENABLED: bool = False
    # Docling advanced document parser
    DOCLING_ENABLED: bool = False
    DOCLING_OCR_ENABLED: bool = True
    DOCLING_TABLE_MODE: str = "markdown"  # markdown | html | plain
    DOCLING_EXTRACT_IMAGES: bool = True
    # Fallback: when Docling yields no image segments, include rendered page images.
    DOCLING_INCLUDE_PAGE_IMAGES_IF_EMPTY: bool = True
    # 0 = unlimited.
    DOCLING_PAGE_IMAGE_MAX_PAGES: int = 20
    # Knowledge Graph (KG) feature flags.
    # Canonical env names: KG_ENABLED / KG_CHAT_ENABLED
    KG_ENABLED: bool = False
    KG_CHAT_ENABLED: bool = False
    # Hybrid KG extensions (disabled by default; safe opt-in).
    KG_RELATION_ENABLED: bool = False
    KG_RELATION_MAX_RELATIONS_PER_CHUNK: int = 20
    # Comma/newline separated predicate allowlist override (optional). When empty, defaults are used.
    KG_RELATION_ALLOWED_PREDICATES: str = ""
    # Heuristics for alias/canonicalization (high precision; helps reduce entity fragmentation).
    KG_RELATION_ALIAS_HEURISTIC_ENABLED: bool = True
    KG_RELATION_ALIAS_MAX_CANDIDATES_PER_CHUNK: int = 10
    KG_RELATION_ALIAS_CONFIDENCE: float = 0.95
    KG_ENTITY_CANONICALIZE_PARENTHESES_ALIAS: bool = True
    KG_SKILL_ENABLED: bool = False
    KG_SKILL_MAX_SKILLS_PER_CHUNK: int = 3
    # KG extraction prompt selector (optional; tenant-scoped PromptTemplate).
    # - Prefer using `KG_EXTRACT_PROMPT_TEMPLATE_KEY` (latest active version).
    # - Or set `KG_EXTRACT_PROMPT_TEMPLATE_ID` to pin a specific template.
    # - Or set `KG_EXTRACT_PROMPT_AB_EXPERIMENT_KEY` for A/B variants (seeded by account_id when available).
    KG_EXTRACT_PROMPT_TEMPLATE_ID: str = ""
    KG_EXTRACT_PROMPT_TEMPLATE_KEY: str = ""
    KG_EXTRACT_PROMPT_AB_EXPERIMENT_KEY: str = ""
    # KG extraction behavior.
    # - replace_existing: removes previously extracted events for the processed chunks (prevents duplicates on re-run).
    # - prune_orphan_entities: removes entities that have no remaining event links after replacement/deletion.
    KG_EXTRACT_REPLACE_EXISTING: bool = True
    KG_EXTRACT_PRUNE_ORPHAN_ENTITIES: bool = True
    # KG extraction performance/guardrails.
    KG_EXTRACT_MAX_CONCURRENCY: int = 3
    KG_EXTRACT_EMBED_BATCH_SIZE: int = 128
    KG_EXTRACT_MAX_EVENTS_PER_CHUNK: int = 6
    KG_EXTRACT_MAX_ENTITIES_PER_EVENT: int = 30
    # Skip low-signal chunks (0 disables).
    KG_EXTRACT_MIN_CHARS: int = 0
    KG_EXTRACT_CONTEXT_MAX_CHARS: int = 8000
    # 0 disables. When enabled, KG extraction wraps each per-chunk LLM call in a timeout.
    KG_EXTRACT_CHUNK_TIMEOUT_SEC: int = 0
    # Per-chunk retry (0 disables). Applies to transient failures in the extraction call.
    KG_EXTRACT_CHUNK_MAX_RETRIES: int = 0
    KG_EXTRACT_CHUNK_RETRY_BACKOFF_SEC: float = 0.5
    # Optional context window: include neighbor chunks as background (0 disables).
    KG_EXTRACT_CONTEXT_WINDOW_CHUNKS: int = 0
    # Optional incremental extraction: skip unchanged chunks when prompt selection matches.
    # Default false to preserve backward-compatible behavior (prompt changes should re-extract).
    KG_EXTRACT_SKIP_UNCHANGED_CHUNKS: bool = False
    # Graph co-occurrence computation guardrail: cap entity count per event when building co-occurrence edges.
    KG_ENTITY_LINK_MAX_ENTITIES_PER_EVENT: int = 60
    # KG API guardrails.
    KG_API_MAX_DOCUMENT_IDS: int = 500
    # KG search guardrails/observability.
    # - Max clue items returned by KG search (0 disables).
    KG_SEARCH_MAX_CLUES: int = 2000
    # - Upper bound for event candidates passed into rerank (0 disables).
    KG_SEARCH_MAX_RERANK_CANDIDATES: int = 500
    # - Disable clue generation entirely (saves CPU/memory; response still contains `clues: []`).
    KG_SEARCH_CLUES_ENABLED: bool = True
    # - Truncate clue node content/description (0 disables).
    KG_SEARCH_NODE_TEXT_MAX_CHARS: int = 400
    # - Global KG search timeout (seconds, 0 disables).
    KG_SEARCH_TIMEOUT_SEC: float = 0.0
    KG_SEARCH_METRICS_ENABLED: bool = False
    # Relation-driven recall expansion: seed entities -> relation neighbors -> events.
    # Disabled by default to avoid behavioral changes in KG search without opt-in.
    KG_SEARCH_RELATION_EXPANSION_ENABLED: bool = False
    KG_SEARCH_RELATION_MIN_CONFIDENCE: float = 0.5
    KG_SEARCH_RELATION_MAX_EDGES: int = 500
    KG_SEARCH_RELATION_MAX_NEIGHBORS: int = 20
    KG_SEARCH_RELATION_NEIGHBOR_WEIGHT_FACTOR: float = 0.7
    CHAT_HISTORY_WINDOW: int = 5
    # Allow chat even when no accessible documents exist (dev-friendly).
    CHAT_ALLOW_EMPTY_DOCUMENTS: bool = True
    # Disable tenant-level "open scope" chat retrieval by default.
    # When false, chat requests must include either:
    # - explicit `document_ids`, or
    # - a `dataset_id` (or an existing conversation bound to a dataset).
    CHAT_ALLOW_OPEN_SCOPE: bool = False
    # Optional: Chat + TAG (Table Store) bridge. When enabled, chat will try to answer table-like
    # questions by running a bounded NL->SQL query over ingested Table Store assets and injecting
    # the result as additional context.
    #
    # Safety: this is guarded by TABLE_NL2SQL_ENABLED + TABLE_LLM_ALLOW_RESULT_EGRESS, and query
    # execution remains SELECT-only with strict caps.
    CHAT_TAG_ENABLED: bool = False
    CHAT_TAG_MAX_TABLES: int = 2
    CHAT_TAG_MAX_DOC_IDS: int = 1000
    CHAT_TAG_MAX_ROWS: int = 50
    CHAT_TAG_MAX_COLS: int = 30
    CHAT_TAG_MAX_BYTES: int = 200_000
    CHAT_TAG_MIN_MATCH_SCORE: int = 1
    LONG_TERM_MEMORY_ENABLED: bool = False
    LONG_TERM_MEMORY_TOP_K: int = 3
    LONG_TERM_MEMORY_MIN_LEN: int = 20
    LONG_TERM_MEMORY_MAX_MESSAGES: int = 200
    MEMORY_STORE_TYPE: str = "memory"  # memory | sqlite
    MEMORY_SQLITE_PATH: str = "./data/memory.db"
    # Short-term memory management
    SHORT_TERM_MEMORY_MAX_TOKENS: int = 4000
    SHORT_TERM_MEMORY_STRATEGY: str = "last"  # first | last
    SUMMARIZATION_THRESHOLD: int = 10  # Messages before auto-summarization
    SUMMARIZATION_ENABLED: bool = True

    # Persistent summary memory (conversation-level; disabled by default).
    PERSISTENT_SUMMARY_MEMORY_ENABLED: bool = False
    # When enabled, update the persistent summary after each assistant turn when the request opts in
    # (ChatRequest.enable_summary_memory=true). Best-effort and fail-open.
    PERSISTENT_SUMMARY_MEMORY_AUTO_UPDATE: bool = False
    PERSISTENT_SUMMARY_MEMORY_LOOKBACK_MESSAGES: int = 20
    PERSISTENT_SUMMARY_MEMORY_MAX_SUMMARY_TOKENS: int = 500

    # Workflow mode configuration
    WORKFLOW_MODE: str = "chain"  # chain | routing | parallel | react | planner | evaluator
    EVALUATOR_MAX_ITERATIONS: int = 3
    EVALUATOR_THRESHOLD: float = 0.8
    # Human-in-the-loop configuration
    HUMAN_REVIEW_ENABLED: bool = False
    INTERRUPT_TIMEOUT_SEC: int = 3600  # 1 hour
    # Stream writer configuration
    STREAM_WRITER_ENABLED: bool = True
    STREAM_BUFFER_SIZE: int = 100
    # Chat streaming (SSE) robustness
    CHAT_STREAM_HEARTBEAT_SEC: float = 10.0
    CHAT_STREAM_CANCEL_ON_DISCONNECT: bool = True
    # Optional: reduce SSE tail latency by persisting the assistant turn in a background task
    # after sending the "done" event. Trade-off: a crash after response may drop persistence.
    CHAT_STREAM_PERSIST_IN_BACKGROUND: bool = False
    # PII redaction (disabled by default)
    PII_REDACTION_ENABLED: bool = False
    PII_REDACTION_MASK: str = "[REDACTED]"
    PII_STREAM_HOLDBACK_CHARS: int = 128
    # Checkpoint persistence configuration
    CHECKPOINT_BACKEND: str = "memory"  # memory | sqlite
    CHECKPOINT_SQLITE_PATH: str = "./data/checkpoints.db"
    # LangGraph Store (long-term memory scaffold; default disabled)
    LANGGRAPH_STORE_ENABLED: bool = False
    LANGGRAPH_STORE_BACKEND: str = "memory"  # memory | postgres (future)

    # Image display strategy.
    SHOW_IMAGE_IN_ANSWER: bool = True  # Include image segments in the answer body.
    IMAGE_APPEND_MAX: int = 3          # Max images appended to the answer.

    # Multi-tenant defaults
    DEFAULT_TENANT_ID: str = "00000000-0000-0000-0000-000000000000"
    TENANT_HEADER: str = "X-Tenant-ID"
    # Optional hardening: when enabled (and JWT tenant claim is available), prefer the verified
    # tenant from the token over a spoofable header.
    TENANT_PREFER_JWT_TENANT: bool = False

    # Rate Limiting
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_REQUESTS_PER_SECOND: float = 10.0
    RATE_LIMIT_BURST_SIZE: int = 20
    RATE_LIMIT_CHAT_RPS: float = 2.0  # Stricter limit for chat endpoints
    RATE_LIMIT_CHAT_BURST: int = 5
    # Optional: Redis-backed distributed limiter (recommended for multi-process deployments).
    RATE_LIMIT_REDIS_ENABLED: bool = False
    RATE_LIMIT_REDIS_PREFIX: str = "rl"
    RATE_LIMIT_REDIS_KEY_TTL_SEC: int = 600

    # MCP (Model Context Protocol) configuration
    MCP_ENABLED: bool = False
    MCP_SERVER_URL: str = ""
    MCP_TIMEOUT: int = 30
    MCP_MAX_RETRIES: int = 3

    # Agent evaluation framework
    AGENT_EVALS_ENABLED: bool = False

    # LangSmith Studio tracing
    LANGSMITH_API_KEY: str = ""
    LANGSMITH_PROJECT: str = "mimirq"
    LANGSMITH_ENDPOINT: str = "https://api.smith.langchain.com"
    LANGSMITH_TRACING_ENABLED: bool = False

    _env_file = Path(__file__).resolve().parents[2] / ".env"
    model_config = SettingsConfigDict(
        # Load `.env` from repo root (stable even when running with a different CWD).
        #
        # Note: unit tests should not be influenced by a developer's local `.env`,
        # so we disable dotenv loading when running under pytest.
        env_file=None if "pytest" in sys.modules else str(_env_file),
        case_sensitive=True,
        extra="ignore",
    )

    @model_validator(mode="after")
    def validate_settings(self) -> "Settings":
        """Validate configuration settings at startup."""
        is_production = is_production_env()

        # Security: Host header hardening (production-only by default).
        if is_production and bool(getattr(self, "TRUSTED_HOSTS_ENABLED", True)):
            raw_allowed = str(getattr(self, "ALLOWED_HOSTS", "") or "").strip()
            allowed = [p.strip() for p in raw_allowed.split(",") if p.strip()]
            if not allowed:
                raise ValueError("ALLOWED_HOSTS required in production (comma-separated)")
            if "*" in allowed:
                raise ValueError("ALLOWED_HOSTS must not include '*' in production")

        # Security: Reduce public API surface in production by default.
        if is_production:
            fields_set = getattr(self, "model_fields_set", set()) or set()
            if "API_DOCS_ENABLED" not in fields_set:
                self.API_DOCS_ENABLED = False
            if "API_OPENAPI_ENABLED" not in fields_set:
                self.API_OPENAPI_ENABLED = False
            if "SETTINGS_ENV_WRITE_ENABLED" not in fields_set:
                self.SETTINGS_ENV_WRITE_ENABLED = False
            # Docs require OpenAPI; if a deploy explicitly enables docs, keep the schema endpoint available.
            if bool(getattr(self, "API_DOCS_ENABLED", False)) and not bool(getattr(self, "API_OPENAPI_ENABLED", False)):
                self.API_OPENAPI_ENABLED = True

        # Security: CORS hardening (production guardrails).
        if is_production:
            # Production default: do not allow credentialed cross-origin calls unless explicitly enabled.
            # This avoids accidentally running a cookie-bearing API with permissive CORS defaults.
            if "CORS_ALLOW_CREDENTIALS" not in (getattr(self, "model_fields_set", set()) or set()):
                self.CORS_ALLOW_CREDENTIALS = False

            cors_raw = str(getattr(self, "CORS_ORIGINS", "") or "")
            cors_origins = [p.strip() for p in cors_raw.split(",") if p.strip()]
            if not cors_origins:
                raise ValueError("CORS_ORIGINS required in production")
            if "*" in cors_origins:
                # Note: FastAPI/Starlette forbids credentials with wildcard origins; keep signal high in prod.
                raise ValueError("CORS_ORIGINS must not include '*' in production")

            for origin in cors_origins:
                if origin.lower().strip() == "null":
                    raise ValueError("CORS_ORIGINS must not include 'null' in production")
                parsed = urlparse(origin)
                scheme = (parsed.scheme or "").lower().strip()
                host = (parsed.hostname or "").lower().strip()
                if scheme not in {"http", "https"} or not host:
                    raise ValueError("CORS_ORIGINS must be a comma-separated list of http(s) origins in production")
                if host in {"localhost", "127.0.0.1", "0.0.0.0"} or host.endswith(".localhost"):
                    raise ValueError("CORS_ORIGINS must not include localhost origins in production")

        # Security: Auth mode guard
        auth_mode = (getattr(self, "AUTH_MODE", "jwt") or "jwt").lower()
        if auth_mode not in ("jwt", "header"):
            raise ValueError(f"Unsupported AUTH_MODE: {auth_mode}")
        if auth_mode == "header" and is_production:
            raise ValueError("AUTH_MODE=header is not allowed in production")

        # Security: Validate SECRET_KEY (required for JWT verification)
        if auth_mode == "jwt":
            if (
                not self.SECRET_KEY
                or self.SECRET_KEY == "your-secret-key-change-in-production"
                or len(self.SECRET_KEY) < 32
            ):
                raise ValueError("SECRET_KEY required for JWT auth (min 32 chars)")

            algorithm = str(getattr(self, "ALGORITHM", "HS256") or "HS256").strip() or "HS256"
            if algorithm.upper().startswith("HS"):
                # HS* uses SECRET_KEY.
                pass
            else:
                # RS*/ES* require a key source (JWKS) for verification.
                jwks_urls = str(getattr(self, "JWT_JWKS_URLS", "") or "").strip()
                if not jwks_urls:
                    discovery_enabled = bool(getattr(self, "JWT_JWKS_DISCOVERY_ENABLED", False))
                    issuer = str(getattr(self, "JWT_ISSUER", "") or "").strip()
                    if not discovery_enabled:
                        raise ValueError(f"JWT_JWKS_URLS required for ALGORITHM={algorithm}")
                    if not issuer:
                        raise ValueError("JWT_ISSUER required when JWT_JWKS_DISCOVERY_ENABLED=true")
        else:
            # Best-effort warning for other uses (sessions, future JWT issuance, etc.)
            if self.SECRET_KEY == "your-secret-key-change-in-production":
                warnings.warn(
                    "Using default SECRET_KEY. Change this in production!",
                    UserWarning,
                    stacklevel=2,
                )

        # Security: Warn about default MinIO credentials
        if self.MINIO_ENABLED:
            access_key = (self.MINIO_ACCESS_KEY or "").strip()
            secret_key = (self.MINIO_SECRET_KEY or "").strip()
            missing_access_key = not access_key
            missing_secret_key = not secret_key

            used_default_minio_credentials = False
            if missing_access_key or missing_secret_key:
                if is_production:
                    raise ValueError("MINIO_ACCESS_KEY and MINIO_SECRET_KEY are required when MINIO_ENABLED=true")
                if missing_access_key and missing_secret_key:
                    self.MINIO_ACCESS_KEY = "minioadmin"
                    self.MINIO_SECRET_KEY = "minioadmin"
                    used_default_minio_credentials = True
                    warnings.warn(
                        "MINIO_ACCESS_KEY/MINIO_SECRET_KEY are empty; defaulting to minioadmin for local/dev.",
                        UserWarning,
                        stacklevel=2,
                    )
                else:
                    raise ValueError("MINIO_ACCESS_KEY and MINIO_SECRET_KEY must both be set when MINIO_ENABLED=true")
            else:
                if self.MINIO_ACCESS_KEY != access_key:
                    self.MINIO_ACCESS_KEY = access_key
                if self.MINIO_SECRET_KEY != secret_key:
                    self.MINIO_SECRET_KEY = secret_key

            if self.MINIO_ACCESS_KEY == "minioadmin" or self.MINIO_SECRET_KEY == "minioadmin":
                if is_production:
                    raise ValueError("Default MinIO credentials are not allowed in production when MINIO_ENABLED=true")
                if not used_default_minio_credentials:
                    warnings.warn(
                        "Using default MinIO credentials. Change in production!",
                        UserWarning,
                        stacklevel=2,
                    )

        if is_production and bool(getattr(self, "FAISS_ALLOW_DANGEROUS_DESERIALIZATION", False)):
            raise ValueError("FAISS_ALLOW_DANGEROUS_DESERIALIZATION is not allowed in production")

        # Validate chunk settings
        if self.CHUNK_OVERLAP >= self.CHUNK_SIZE:
            raise ValueError(
                f"CHUNK_OVERLAP ({self.CHUNK_OVERLAP}) must be less than "
                f"CHUNK_SIZE ({self.CHUNK_SIZE})"
            )

        # Validate LLM temperature
        if not 0 <= self.LLM_TEMPERATURE <= 2:
            raise ValueError(
                f"LLM_TEMPERATURE ({self.LLM_TEMPERATURE}) must be between 0 and 2"
            )

        # Validate retrieval settings
        if self.SIMILARITY_THRESHOLD < 0 or self.SIMILARITY_THRESHOLD > 1:
            raise ValueError(
                f"SIMILARITY_THRESHOLD ({self.SIMILARITY_THRESHOLD}) must be between 0 and 1"
            )

        if int(getattr(self, "RETRIEVAL_TOP_K", 0) or 0) < 1:
            raise ValueError(f"RETRIEVAL_TOP_K ({getattr(self, 'RETRIEVAL_TOP_K', None)}) must be >= 1")

        if self.RETRIEVAL_MMR_LAMBDA < 0 or self.RETRIEVAL_MMR_LAMBDA > 1:
            raise ValueError(
                f"RETRIEVAL_MMR_LAMBDA ({self.RETRIEVAL_MMR_LAMBDA}) must be between 0 and 1"
            )
        if int(getattr(self, "RETRIEVAL_RRF_K", 0) or 0) < 1:
            raise ValueError(f"RETRIEVAL_RRF_K ({getattr(self, 'RETRIEVAL_RRF_K', None)}) must be >= 1")
        dedup_thr = float(getattr(self, "RETRIEVAL_DEDUP_JACCARD_THRESHOLD", 0.0) or 0.0)
        if dedup_thr < 0.0 or dedup_thr > 1.0:
            raise ValueError(f"RETRIEVAL_DEDUP_JACCARD_THRESHOLD ({dedup_thr}) must be between 0 and 1")
        if int(getattr(self, "RETRIEVAL_DEDUP_MAX_COMPARE", 0) or 0) < 0:
            raise ValueError("RETRIEVAL_DEDUP_MAX_COMPARE must be >= 0")
        if int(getattr(self, "RETRIEVAL_MAX_CHUNKS_PER_DOC", 0) or 0) < 0:
            raise ValueError("RETRIEVAL_MAX_CHUNKS_PER_DOC must be >= 0")
        if int(getattr(self, "RETRIEVAL_MIN_DISTINCT_DOCS", 0) or 0) < 0:
            raise ValueError("RETRIEVAL_MIN_DISTINCT_DOCS must be >= 0")
        if int(self.RETRIEVAL_QUERY_PARALLELISM or 0) < 1:
            raise ValueError(
                f"RETRIEVAL_QUERY_PARALLELISM ({self.RETRIEVAL_QUERY_PARALLELISM}) must be >= 1"
            )
        if int(getattr(self, "RETRIEVAL_OVERFETCH_MULTIPLIER", 1) or 1) < 1:
            raise ValueError("RETRIEVAL_OVERFETCH_MULTIPLIER must be >= 1")
        if int(getattr(self, "RETRIEVAL_OVERFETCH_MAX_K", 0) or 0) < 0:
            raise ValueError("RETRIEVAL_OVERFETCH_MAX_K must be >= 0")
        if int(getattr(self, "MILVUS_EXPR_MAX_DOC_IDS", 0) or 0) < 0:
            raise ValueError("MILVUS_EXPR_MAX_DOC_IDS must be >= 0")

        if int(getattr(self, "BM25_CACHE_MAX_TENANTS", 0) or 0) < 0:
            raise ValueError("BM25_CACHE_MAX_TENANTS must be >= 0")
        if int(getattr(self, "BM25_TOKENIZE_CJK_OOV_MAX_TERM_CHARS", 0) or 0) < 2:
            raise ValueError("BM25_TOKENIZE_CJK_OOV_MAX_TERM_CHARS must be >= 2")
        if int(getattr(self, "BM25_TOKENIZE_CJK_OOV_MAX_EXTRA_TOKENS", 0) or 0) < 0:
            raise ValueError("BM25_TOKENIZE_CJK_OOV_MAX_EXTRA_TOKENS must be >= 0")

        if int(getattr(self, "EMBEDDING_CACHE_TTL_SEC", 0) or 0) < 0:
            raise ValueError("EMBEDDING_CACHE_TTL_SEC must be >= 0")

        emb_prefix = (getattr(self, "EMBEDDING_CACHE_PREFIX", "") or "").strip()
        if not emb_prefix:
            raise ValueError("EMBEDDING_CACHE_PREFIX must be non-empty")
        if any(ch.isspace() for ch in emb_prefix):
            raise ValueError("EMBEDDING_CACHE_PREFIX must not contain whitespace")
        if self.EMBEDDING_CACHE_PREFIX != emb_prefix:
            self.EMBEDDING_CACHE_PREFIX = emb_prefix

        if float(getattr(self, "EMBEDDING_API_TIMEOUT_SEC", 0.0) or 0.0) <= 0:
            raise ValueError("EMBEDDING_API_TIMEOUT_SEC must be > 0")
        if int(getattr(self, "EMBEDDING_API_BATCH_SIZE", 0) or 0) < 1:
            raise ValueError("EMBEDDING_API_BATCH_SIZE must be >= 1")
        if int(getattr(self, "EMBEDDING_API_MAX_CONCURRENCY", 0) or 0) < 1:
            raise ValueError("EMBEDDING_API_MAX_CONCURRENCY must be >= 1")
        if int(getattr(self, "EMBEDDING_API_MAX_RETRIES", 0) or 0) < 0:
            raise ValueError("EMBEDDING_API_MAX_RETRIES must be >= 0")
        if float(getattr(self, "EMBEDDING_API_RETRY_BACKOFF_SEC", 0.0) or 0.0) < 0:
            raise ValueError("EMBEDDING_API_RETRY_BACKOFF_SEC must be >= 0")
        if float(getattr(self, "EMBEDDING_API_RETRY_JITTER_SEC", 0.0) or 0.0) < 0:
            raise ValueError("EMBEDDING_API_RETRY_JITTER_SEC must be >= 0")

        if int(getattr(self, "CHAT_RESPONSE_CACHE_TTL_SEC", 0) or 0) < 0:
            raise ValueError("CHAT_RESPONSE_CACHE_TTL_SEC must be >= 0")
        if int(getattr(self, "CHAT_RESPONSE_CACHE_MAX_VALUE_BYTES", 0) or 0) < 0:
            raise ValueError("CHAT_RESPONSE_CACHE_MAX_VALUE_BYTES must be >= 0")

        if int(getattr(self, "RETRIEVAL_CANDIDATE_CACHE_TTL_SEC", 0) or 0) < 0:
            raise ValueError("RETRIEVAL_CANDIDATE_CACHE_TTL_SEC must be >= 0")
        if int(getattr(self, "RETRIEVAL_CANDIDATE_CACHE_MAX_VALUE_BYTES", 0) or 0) < 0:
            raise ValueError("RETRIEVAL_CANDIDATE_CACHE_MAX_VALUE_BYTES must be >= 0")

        cand_prefix = (getattr(self, "RETRIEVAL_CANDIDATE_CACHE_PREFIX", "") or "").strip()
        if not cand_prefix:
            raise ValueError("RETRIEVAL_CANDIDATE_CACHE_PREFIX must be non-empty")
        if any(ch.isspace() for ch in cand_prefix):
            raise ValueError("RETRIEVAL_CANDIDATE_CACHE_PREFIX must not contain whitespace")
        if self.RETRIEVAL_CANDIDATE_CACHE_PREFIX != cand_prefix:
            self.RETRIEVAL_CANDIDATE_CACHE_PREFIX = cand_prefix
        if int(getattr(self, "VECTOR_WRITE_BATCH_SIZE", 0) or 0) < 1:
            raise ValueError("VECTOR_WRITE_BATCH_SIZE must be >= 1")
        if int(getattr(self, "VECTOR_WRITE_BATCH_MAX_CHARS", 0) or 0) < 0:
            raise ValueError("VECTOR_WRITE_BATCH_MAX_CHARS must be >= 0")

        if int(getattr(self, "CHAT_ASSISTANT_TOKEN_QUOTA_LIMIT", 0) or 0) < 0:
            raise ValueError("CHAT_ASSISTANT_TOKEN_QUOTA_LIMIT must be >= 0")
        if int(getattr(self, "CHAT_ASSISTANT_TOKEN_QUOTA_WINDOW_HOURS", 0) or 0) <= 0:
            raise ValueError("CHAT_ASSISTANT_TOKEN_QUOTA_WINDOW_HOURS must be > 0")
        quota_mode = str(getattr(self, "CHAT_ASSISTANT_TOKEN_QUOTA_MODE", "block") or "block").lower()
        if quota_mode not in {"block", "warn"}:
            raise ValueError("CHAT_ASSISTANT_TOKEN_QUOTA_MODE must be one of: block, warn")

        if int(getattr(self, "PERSISTENT_SUMMARY_MEMORY_LOOKBACK_MESSAGES", 0) or 0) <= 0:
            raise ValueError("PERSISTENT_SUMMARY_MEMORY_LOOKBACK_MESSAGES must be > 0")
        if int(getattr(self, "PERSISTENT_SUMMARY_MEMORY_MAX_SUMMARY_TOKENS", 0) or 0) <= 0:
            raise ValueError("PERSISTENT_SUMMARY_MEMORY_MAX_SUMMARY_TOKENS must be > 0")

        # Validate workflow mode
        valid_workflow_modes = {"chain", "routing", "parallel", "react", "planner", "evaluator"}
        if self.WORKFLOW_MODE not in valid_workflow_modes:
            raise ValueError(
                f"WORKFLOW_MODE ({self.WORKFLOW_MODE}) must be one of {valid_workflow_modes}"
            )

        # Validate vector backend
        valid_vector_backends = {"milvus", "memory", "faiss", "chroma"}
        if self.VECTOR_BACKEND not in valid_vector_backends:
            raise ValueError(
                f"VECTOR_BACKEND ({self.VECTOR_BACKEND}) must be one of {valid_vector_backends}"
            )

        # Validate checkpoint backend
        valid_checkpoint_backends = {"memory", "sqlite"}
        if self.CHECKPOINT_BACKEND not in valid_checkpoint_backends:
            raise ValueError(
                f"CHECKPOINT_BACKEND ({self.CHECKPOINT_BACKEND}) must be one of {valid_checkpoint_backends}"
            )

        # Validate memory store type
        valid_memory_stores = {"memory", "sqlite"}
        if self.MEMORY_STORE_TYPE not in valid_memory_stores:
            raise ValueError(
                f"MEMORY_STORE_TYPE ({self.MEMORY_STORE_TYPE}) must be one of {valid_memory_stores}"
            )

        # Validate reranker provider
        valid_reranker_providers = {"llm", "pc", "none"}
        if self.RERANKER_PROVIDER not in valid_reranker_providers:
            raise ValueError(
                f"RERANKER_PROVIDER ({self.RERANKER_PROVIDER}) must be one of {valid_reranker_providers}"
            )

        # Validate retrieval fusion strategy
        valid_fusion_strategies = {"linear", "rrf"}
        if self.RETRIEVAL_FUSION_STRATEGY not in valid_fusion_strategies:
            raise ValueError(
                f"RETRIEVAL_FUSION_STRATEGY ({self.RETRIEVAL_FUSION_STRATEGY}) must be one of {valid_fusion_strategies}"
            )

        return self


settings = Settings()
