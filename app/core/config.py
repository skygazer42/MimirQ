"""
Application configuration module.

Centralized settings management including:
- Security settings (SECRET_KEY, credentials, etc.)
- LLM/Embedding provider config
- RAG pipeline parameters
- Storage backend config
"""
import ipaddress
import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core import config_validation as _settings_validation
from app.core.constants import DEFAULT_OPENAI_API_BASE
from app.core.env import is_production_env
from app.rag.retrieval.contract import (
    VALID_RETRIEVAL_CONTRACT_MODES,
    normalize_retrieval_contract_mode,
)
from app.rag.retrieval.sparse import (
    VALID_SPARSE_PROVIDERS,
    normalize_sparse_provider_name,
)

_DEFAULT_RAG_EVAL_SUMMARY_PATH = "tests/rag/evaluation/fixtures/rag_eval_summary.sample.json"
_COMMA_OR_WHITESPACE_RE = r"[,\\s]+"
_LEGACY_DEV_SECRET_KEY = "".join(("your-secret-key", "-change-in-production"))
_LOCAL_MINIO_DEFAULT_CREDENTIAL = "".join(("minio", "admin"))
_ALL_INTERFACES_HOST = str(ipaddress.IPv4Address(0))
_JWT_LOCAL_HOSTS = frozenset({"localhost", "localhost.localdomain", "127.0.0.1", "::1"})
_OBJECT_STORAGE_PROVIDER_ALIASES = {
    "": "minio",
    "minio": "minio",
    "s3": "s3",
    "aws_s3": "s3",
    "s3_compatible": "s3_compatible",
    "s3compat": "s3_compatible",
    "oss": "oss",
    "aliyun_oss": "oss",
    "cos": "cos",
    "tencent_cos": "cos",
}

DEFAULT_RETRIEVAL_PARSE_RISK_AUTO_ENQUEUE_LEVELS = "high,medium"


def normalize_object_storage_provider_name(raw: object) -> str:
    requested = str(raw or "minio").strip().lower()
    try:
        return _OBJECT_STORAGE_PROVIDER_ALIASES[requested]
    except KeyError as exc:
        raise ValueError(f"unsupported object storage provider: {requested}") from exc


def parse_object_storage_region_profiles(raw: object) -> dict[str, dict[str, object]]:
    if isinstance(raw, Mapping):
        source = dict(raw)
    else:
        text = str(raw or "").strip()
        if not text:
            return {}
        try:
            source = json.loads(text)
        except (TypeError, ValueError) as exc:
            raise ValueError("OBJECT_STORAGE_REGION_PROFILES must be a valid JSON object") from exc
        if not isinstance(source, dict):
            raise ValueError("OBJECT_STORAGE_REGION_PROFILES must be a valid JSON object")

    profiles: dict[str, dict[str, object]] = {}
    for raw_region, raw_profile in source.items():
        region = str(raw_region or "").strip().lower()
        if not region or not isinstance(raw_profile, Mapping):
            raise ValueError("OBJECT_STORAGE_REGION_PROFILES entries must map a non-empty region to an object")
        profiles[region] = dict(raw_profile)
    return profiles


def _should_disable_repo_env_file() -> bool:
    """
    Avoid loading a developer's repo `.env` during test/openapi generation paths.

    Relying only on ``"pytest" in sys.modules`` is fragile because import timing can
    vary during collection and subprocess entrypoints. Accept a few stable pytest
    signals so settings instantiation stays hermetic in full-suite runs too.
    """

    if os.getenv("MIMIRQ_OPENAPI_EXPORT") == "1":
        return True
    if "pytest" in sys.modules:
        return True
    if os.getenv("PYTEST_CURRENT_TEST") or os.getenv("PYTEST_VERSION"):
        return True
    argv0 = Path(str(sys.argv[0] or "")).name.lower()
    return "pytest" in argv0


def _is_local_jwt_http_host(host: str) -> bool:
    normalized = str(host or "").strip().lower()
    if not normalized:
        return False
    if normalized in _JWT_LOCAL_HOSTS or normalized.endswith(".localhost"):
        return True
    try:
        ip = ipaddress.ip_address(normalized)
    except ValueError:
        return False
    return bool(ip.is_loopback)


def validate_jwt_remote_url(raw_url: str, *, field_name: str) -> None:
    url = str(raw_url or "").strip()
    if not url:
        return

    parsed = urlparse(url)
    scheme = str(parsed.scheme or "").strip().lower()
    host = str(parsed.hostname or "").strip().lower()
    if scheme not in {"http", "https"} or not host:
        raise ValueError(f"{field_name} must be a http(s) URL")
    if parsed.username or parsed.password:
        raise ValueError(f"{field_name} must not include userinfo")
    if scheme == "https":
        return
    if not is_production_env() and _is_local_jwt_http_host(host):
        return
    raise ValueError(f"{field_name} must use https")


# Bind shared helpers/constants onto the validation module. ``config_validation``
# holds the split-out sections of ``Settings.validate_settings`` and must not
# import any app-internal module (this module stays the dependency-tree leaf),
# so the names those sections need are injected here instead.
_settings_validation.is_production_env = is_production_env
_settings_validation.validate_jwt_remote_url = validate_jwt_remote_url
_settings_validation.normalize_object_storage_provider_name = normalize_object_storage_provider_name
_settings_validation.parse_object_storage_region_profiles = parse_object_storage_region_profiles
_settings_validation.normalize_retrieval_contract_mode = normalize_retrieval_contract_mode
_settings_validation.VALID_RETRIEVAL_CONTRACT_MODES = VALID_RETRIEVAL_CONTRACT_MODES
_settings_validation.normalize_sparse_provider_name = normalize_sparse_provider_name
_settings_validation.VALID_SPARSE_PROVIDERS = VALID_SPARSE_PROVIDERS
_settings_validation.DEFAULT_RETRIEVAL_PARSE_RISK_AUTO_ENQUEUE_LEVELS = DEFAULT_RETRIEVAL_PARSE_RISK_AUTO_ENQUEUE_LEVELS
_settings_validation._ALL_INTERFACES_HOST = _ALL_INTERFACES_HOST
_settings_validation._COMMA_OR_WHITESPACE_RE = _COMMA_OR_WHITESPACE_RE
_settings_validation._LEGACY_DEV_SECRET_KEY = _LEGACY_DEV_SECRET_KEY
_settings_validation._LOCAL_MINIO_DEFAULT_CREDENTIAL = _LOCAL_MINIO_DEFAULT_CREDENTIAL
_settings_validation._DEFAULT_RAG_EVAL_SUMMARY_PATH = _DEFAULT_RAG_EVAL_SUMMARY_PATH


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
    # Optional "shadow" Milvus collection for embedding blue-green migrations (Gap5).
    # When configured alongside EMBEDDING_SHADOW_* and enabled, ingestion can dual-write
    # vectors into both the primary and shadow collections.
    MILVUS_SHADOW_COLLECTION_NAME: str = ""
    # Guardrail: avoid building extremely long Milvus expr like
    # `document_id in ["...","...",...]` which can exceed expr limits and hurt latency.
    # 0 disables.
    MILVUS_EXPR_MAX_DOC_IDS: int = 200

    # Object Storage (MinIO / S3-compatible)
    MINIO_ENABLED: bool = False
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = ""
    MINIO_SECRET_KEY: str = ""
    MINIO_BUCKET_NAME: str = "mimirq"
    MINIO_USE_SSL: bool = False
    MINIO_METRICS_LOG_PATH: str = "./logs/minio_metrics.jsonl"
    # 0 disables. Used when uploading extracted images to MinIO to avoid huge payloads.
    MINIO_IMAGE_MAX_BYTES: int = 0
    # Store uploaded document source files in MinIO (recommended for enterprise deployments / multi-instance).
    MINIO_DOCUMENTS_ENABLED: bool = False
    # Generic object storage profile used by factory-routed S3-compatible backends
    # (e.g. S3 / OSS / COS) without changing business code.
    OBJECT_STORAGE_PROVIDER: str = "minio"
    OBJECT_STORAGE_ENABLED: bool = False
    OBJECT_STORAGE_ENDPOINT: str = ""
    OBJECT_STORAGE_ACCESS_KEY: str = ""
    OBJECT_STORAGE_SECRET_KEY: str = ""
    OBJECT_STORAGE_BUCKET_NAME: str = ""
    OBJECT_STORAGE_USE_SSL: bool = True
    OBJECT_STORAGE_METRICS_LOG_PATH: str = "./logs/object_store_metrics.jsonl"
    OBJECT_STORAGE_DOCUMENTS_ENABLED: bool = False
    # Optional data residency / region routing key used by backend factories.
    DATA_REGION: str = ""
    # Optional JSON object keyed by region, e.g.
    # {"cn-shanghai":{"provider":"oss","endpoint":"...","bucket_name":"..."}}.
    OBJECT_STORAGE_REGION_PROFILES: str = ""

    # Task Queue / Redis (ingest throughput optimization)
    # - Task queue is off by default: keeps API compatibility; when enabled,
    #   workers handle document parsing/indexing asynchronously.
    TASK_QUEUE_ENABLED: bool = False
    # When TASK_QUEUE_ENABLED=false, API background tasks process documents
    # in-process. Keep this bounded so parser/KG work cannot exhaust DB pools.
    API_DOCUMENT_BACKGROUND_MAX_CONCURRENCY: int = 2
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
    # Worker liveness heartbeat (best-effort ops observability).
    # Interval: how frequently workers update heartbeat in Redis.
    TASK_WORKER_HEARTBEAT_INTERVAL_SEC: float = 5.0
    # TTL: how long a worker can go silent before being considered inactive.
    TASK_WORKER_HEARTBEAT_TTL_SEC: int = 30
    # Task execution timeout (seconds).
    TASK_JOB_TIMEOUT_SEC: int = 60 * 30
    # Redis semaphore lease TTL for tenant/dataset concurrency slots.
    # A short lease prevents dead workers from blocking capacity for too long;
    # active jobs keep ownership alive via owner-checked heartbeats.
    TASK_SEMAPHORE_LEASE_TTL_SEC: int = 60
    # Bound how long a worker waits in-process for a semaphore slot before
    # falling back to the existing queue retry path.
    TASK_SEMAPHORE_ACQUIRE_WAIT_SEC: float = 5.0
    # Generic jobs can wait behind long-running tenant work without bypassing limits.
    TASK_JOB_MAX_TRIES: int = 80
    # Document jobs can wait behind large PDF/OCR work; keep them queued instead of
    # exhausting the generic retry budget while a per-tenant semaphore is held.
    TASK_DOCUMENT_JOB_MAX_TRIES: int = 80
    TASK_DOCUMENT_RETRY_DEFER_SEC: int = 30
    # Per-tenant concurrency limit to avoid one tenant exhausting workers (0 = unlimited).
    TASK_TENANT_MAX_CONCURRENCY_DOC: int = 2
    TASK_TENANT_MAX_CONCURRENCY_KG: int = 1
    TASK_TENANT_MAX_CONCURRENCY_CONNECTOR: int = 1
    TASK_TENANT_MAX_CONCURRENCY_EVIDENCE_REPAIR: int = 1
    # Per-dataset concurrency limit (within a tenant) to avoid single dataset starvation (0 = unlimited).
    TASK_DATASET_MAX_CONCURRENCY_DOC: int = 0
    TASK_DATASET_MAX_CONCURRENCY_KG: int = 0
    # When KG jobs back off on semaphore contention, wait long enough for the
    # in-flight extraction to finish before burning through arq's small retry budget.
    TASK_KG_JOB_MAX_TRIES: int = 80
    TASK_KG_RETRY_DEFER_SEC: int = 30
    # API-side queue observability poll interval (seconds).
    # Used only when PROMETHEUS_ENABLED=true to keep gauges fresh for scraping.
    TASK_QUEUE_OBSERVABILITY_POLL_INTERVAL_SEC: float = 10.0
    # Number of recent task job outcomes kept for the admin observability snapshot.
    TASK_QUEUE_RECENT_JOB_OUTCOMES_LIMIT: int = 20
    # Dataset-analysis PNG export shared state (Redis, fail-closed).
    DATASET_ANALYSIS_PNG_REDIS_PREFIX: str = "dataset-analysis-png"
    DATASET_ANALYSIS_PNG_STALE_AFTER_SEC: int = 60
    DATASET_ANALYSIS_PNG_TERMINAL_TTL_SEC: int = 600
    DATASET_ANALYSIS_PNG_RESULT_MAX_BYTES: int = 5_000_000

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
    # Stores fully rendered assistant replies for identical requests (guarded by
    # tenant/account/scope/config + corpus token), so repeated stateless asks do
    # not pay repeated LLM latency.
    CHAT_RESPONSE_CACHE_ENABLED: bool = True
    CHAT_RESPONSE_CACHE_TTL_SEC: int = 300
    CHAT_RESPONSE_CACHE_PREFIX: str = "chat"
    CHAT_RESPONSE_CACHE_MAX_VALUE_BYTES: int = 200_000
    # Default guardrail: only cache stateless requests (no explicit history).
    CHAT_RESPONSE_CACHE_REQUIRE_EMPTY_HISTORY: bool = True
    # Best-effort in-process de-duplication for concurrent identical cacheable
    # requests. Followers wait for the leader result instead of starting a second
    # identical LLM call.
    CHAT_RESPONSE_SINGLEFLIGHT_ENABLED: bool = True

    # Retrieval candidate singleflight (Redis lease + in-process future; safe by default).
    # Deduplicates concurrent identical retrieval work across threads/instances without
    # requiring the persistent exact-result cache to be enabled.
    RETRIEVAL_CANDIDATE_SINGLEFLIGHT_ENABLED: bool = True
    # Followers fail with a retryable response rather than duplicating still-running work.
    RETRIEVAL_CANDIDATE_SINGLEFLIGHT_WAIT_TIMEOUT_SEC: float = 60.0
    # Retrieval candidate cache (Redis, short TTL; best-effort; opt-in exact-result reuse).
    # Stores retrieval outputs for identical scoped requests to reduce repeated vector/BM25 work.
    RETRIEVAL_CANDIDATE_CACHE_ENABLED: bool = False
    RETRIEVAL_CANDIDATE_CACHE_TTL_SEC: int = 30
    RETRIEVAL_CANDIDATE_CACHE_PREFIX: str = "rcand"
    RETRIEVAL_CANDIDATE_CACHE_MAX_VALUE_BYTES: int = 400_000

    # Semantic cache (Milvus ANN + Redis payload; best-effort; safe by default).
    # Stores retrieval outputs for *similar* queries within a strict (tenant/account/scope) boundary.
    SEMANTIC_CACHE_ENABLED: bool = False
    SEMANTIC_CACHE_TTL_SEC: int = 300
    SEMANTIC_CACHE_SCORE_THRESHOLD: float = 0.95
    SEMANTIC_CACHE_SEARCH_TOP_K: int = 5
    SEMANTIC_CACHE_COLLECTION_NAME: str = "semantic_cache"
    SEMANTIC_CACHE_REDIS_PREFIX: str = "semc"
    SEMANTIC_CACHE_MAX_VALUE_BYTES: int = 400_000

    # Usage quotas (best-effort; disabled by default).
    # Applies per-tenant over a rolling time window.
    CHAT_ASSISTANT_TOKEN_QUOTA_ENABLED: bool = False
    CHAT_ASSISTANT_TOKEN_QUOTA_LIMIT: int = 0
    CHAT_ASSISTANT_TOKEN_QUOTA_WINDOW_HOURS: int = 24
    # Mode:
    # - "block": reject new requests with HTTP 429 when exceeded
    # - "warn": allow but annotate metrics (no enforcement)
    # Quota enforcement mode, not a credential.
    CHAT_ASSISTANT_TOKEN_QUOTA_MODE: str = "block"  # noqa: S105

    # Tenant resource quotas (best-effort; disabled by default).
    # These are aggregate tenant guardrails, not per-user or per-dataset allocations.
    TENANT_DOC_QUOTA_ENABLED: bool = False
    TENANT_DOC_QUOTA_LIMIT: int = 0
    TENANT_STORAGE_QUOTA_ENABLED: bool = False
    TENANT_STORAGE_QUOTA_LIMIT_BYTES: int = 0
    TENANT_EMBED_CHAR_QUOTA_ENABLED: bool = False
    TENANT_EMBED_CHAR_QUOTA_LIMIT: int = 0
    TENANT_EMBED_CHAR_QUOTA_WINDOW_HOURS: int = 24
    TENANT_EMBED_CHAR_QUOTA_MODE: str = "block"

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
    LLM_API_BASE: str = Field(default=DEFAULT_OPENAI_API_BASE, validation_alias=AliasChoices("LLM_API_BASE", "OPENAI_BASE_URL"))
    LLM_MODEL: str = Field(default="gpt-5.4-mini", validation_alias=AliasChoices("LLM_MODEL", "OPENAI_MODEL"))
    LLM_MODEL_FAST: str | None = Field(default=None, validation_alias=AliasChoices("LLM_MODEL_FAST", "LLM_MODEL_LIGHT"))
    LLM_MODEL_HEAVY: str | None = Field(default=None, validation_alias=AliasChoices("LLM_MODEL_HEAVY", "LLM_MODEL_COMPLEX"))
    ENABLE_DYNAMIC_MODEL_ROUTING: bool = False
    MODEL_COMPLEXITY_THRESHOLD: int = 160
    MODEL_COMPLEXITY_HISTORY_WEIGHT: float = 0.35
    AGENT_MAX_ITERATIONS: int = 10
    AGENT_RECURSION_LIMIT: int = 25
    ADAPTIVE_RETRIEVAL_ROUTING_ENABLED: bool = False
    ADAPTIVE_RETRIEVAL_SIMPLE_THRESHOLD: float = 80.0
    ADAPTIVE_RETRIEVAL_SIMPLE_TOP_K: int = 10
    ADAPTIVE_RETRIEVAL_COMPLEX_THRESHOLD: float = 200.0
    ADAPTIVE_RETRIEVAL_COMPLEX_TOP_K: int = 40
    ADAPTIVE_RETRIEVAL_COMPLEX_MQ_COUNT: int = 5
    INPUT_GUARD_ENABLED: bool = False
    INPUT_GUARD_MODE: Literal["warn", "block"] = "warn"
    INPUT_GUARD_SCORE_THRESHOLD: float = 0.7
    INPUT_GUARD_WARN_THRESHOLD: float = 0.35
    INPUT_GUARD_LOG_BLOCKED: bool = True
    OUTPUT_GUARD_ENABLED: bool = False
    OUTPUT_GUARD_MODE: Literal["warn", "block"] = "warn"
    OUTPUT_GUARD_SCORE_THRESHOLD: float = 0.7
    OUTPUT_GUARD_WARN_THRESHOLD: float = 0.35
    COST_PROMPT_OVERHEAD_TOKENS: int = 50
    LLM_TEMPERATURE: float = 0.7
    # Structured JSON output is latency-sensitive and benefits from deterministic decoding.
    # Keep this separate from the general chat temperature so `/api/v1/chat` can stay fast
    # for structured presets without changing the default free-form chat behavior.
    LLM_STRUCTURED_TEMPERATURE: float = 0.0
    LLM_TIMEOUT: int = 60
    LLM_MAX_RETRIES: int = 3
    # Some OpenAI-compatible providers fail when LangChain reuses the shared pooled
    # async client for chat requests. Keep this OFF by default and opt in only when
    # the target provider has been verified with the shared async transport.
    LLM_USE_POOLED_ASYNC_HTTP_CLIENT: bool = False
    # Optional provider fallback chain; default OFF.
    # Accepts JSON list/dict or comma-separated model names.
    LLM_FALLBACK_ENABLED: bool = False
    LLM_FALLBACK_MODELS: str = ""
    # Prompt cache hinting for Anthropic-compatible providers (default OFF).
    PROMPT_CACHE_ENABLED: bool = False
    PROMPT_CACHE_MIN_CHARS: int = 1000

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
    # Optional high-cardinality labels (off by default).
    # When disabled, metrics still include the label keys but collapse values to "all"
    # to keep time series count low.
    PROMETHEUS_RAG_LABEL_TENANT_ID: bool = False
    PROMETHEUS_RAG_LABEL_DATASET_ID: bool = False
    # Optional: Prometheus HTTP API base URL for SLO snapshot queries.
    # Example: http://prometheus.monitoring.svc:9090
    PROMETHEUS_QUERY_BASE_URL: str = ""
    PROMETHEUS_QUERY_TIMEOUT_SEC: float = 3.0

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
    EMBEDDING_LANGUAGE_ROUTING_ENABLED: bool = False
    EMBEDDING_MODEL_ZH: str = ""
    EMBEDDING_MODEL_EN: str = ""
    EMBEDDING_MODEL_MIXED: str = ""
    # Embedding API engineering knobs (batching + concurrency + retry/backoff).
    # Keep defaults conservative to avoid rate-limit spikes in mid-scale ingest.
    EMBEDDING_API_TIMEOUT_SEC: float = 60.0
    EMBEDDING_API_BATCH_SIZE: int = 64
    EMBEDDING_API_MAX_CONCURRENCY: int = 3
    EMBEDDING_API_MAX_RETRIES: int = 3
    EMBEDDING_API_RETRY_BACKOFF_SEC: float = 0.5
    EMBEDDING_API_RETRY_JITTER_SEC: float = 0.2
    # Optional per-process startup warmup for the active embedding + reranker providers.
    # This performs bounded synthetic probes only and does not touch business datasets.
    RAG_RUNTIME_WARMUP_ENABLED: bool = False
    RAG_RUNTIME_WARMUP_TIMEOUT_SEC: float = 15.0
    RAG_RUNTIME_WARMUP_REQUIRED_FOR_READY: bool = False

    # Embedding blue-green migration (Gap5) — shadow embedding config (optional).
    # When enabled, indexing dual-writes vectors into MILVUS_SHADOW_COLLECTION_NAME using
    # this embedding config (while primary indexing continues to use EMBEDDING_*).
    EMBEDDING_SHADOW_ENABLED: bool = False
    EMBEDDING_SHADOW_PROVIDER: str = ""
    EMBEDDING_SHADOW_MODEL: str = ""
    EMBEDDING_SHADOW_API_KEY: str = ""
    EMBEDDING_SHADOW_API_BASE: str = ""
    # Redis progress tracking for embedding migration scripts (best-effort).
    EMBEDDING_MIGRATION_PROGRESS_REDIS_PREFIX: str = "embmig"
    EMBEDDING_MIGRATION_PROGRESS_TTL_SEC: int = 7 * 24 * 3600

    UPLOAD_DIR: str = "./uploads"
    MAX_FILE_SIZE: int = 50_000_000
    USER_METADATA_FORM_JSON_MAX_CHARS: int = 20_000
    USER_METADATA_MAP_FORM_JSON_MAX_CHARS: int = 200_000
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
    PRECHECK_NEAR_DUP_HAMMING_THRESHOLD: int = 5
    PRECHECK_NEAR_DUP_MAX_PAIRS: int = 5000
    # 0 means auto: 3/1000 files, with one representative sample per present file type.
    PRECHECK_SAMPLE_SIZE: int = 0
    PRECHECK_DIRECTORY_STATS_LIMIT: int = 200
    # Whether to include chunk_size hints derived from token distribution in precheck suggestions.
    PRECHECK_SUGGEST_CHUNK_SIZE: bool = True
    # Optional: ingest documents by fetching a remote URL (connector skeleton).
    URL_INGEST_ENABLED: bool = False
    # Optional: ingest structured DB metadata (catalog/profiling) from MySQL/SQLServer.
    # Disabled by default because it requires outbound DB connectivity and careful secrets handling.
    DB_CATALOG_ENABLED: bool = False
    # Explicit CIDR allowlist for DB connector egress. Empty means only public destinations are allowed.
    CONNECTOR_DB_EGRESS_ALLOW_CIDRS: str = ""
    # Optional: ingest bounded row snapshots (for TAG recall) alongside DB catalog metadata.
    # This is off by default and intentionally bounded by strict caps.
    DB_CATALOG_ROW_SYNC_ENABLED: bool = False
    DB_CATALOG_ROW_SYNC_MAX_TABLES: int = 20
    DB_CATALOG_ROW_SYNC_MAX_ROWS_PER_TABLE: int = 50
    DB_CATALOG_ROW_SYNC_MAX_COLS: int = 50
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
    # Fast path for already-textual preview uploads (.md/.txt/source code). Heavy formats still
    # use subprocess isolation so parser hangs remain cancellable.
    PREVIEW_INLINE_TEXT_PARSE_ENABLED: bool = True
    # Persisted parse cache for document ingest/retry flows.
    # Disabled by default; enable only when MinIO is configured and you want cross-run reuse.
    PARSE_CACHE_ENABLED: bool = False
    PARSE_CACHE_TTL_SEC: int = 86_400
    PARSE_CACHE_MAX_BYTES: int = 8_000_000
    PARSE_CACHE_VERSION: str = "v1"
    PARSE_CACHE_MINIO_PREFIX: str = "parse_cache"
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
    # Optional: image-level preprocessing (deskew/orientation/watermark) before parsing.
    # This is disabled by default to keep baseline ingest behavior unchanged.
    IMAGE_PREPROCESS_ENABLED: bool = False
    DESKEW_ENABLED: bool = False
    # auto | paddle | skip
    DESKEW_BACKEND: str = "auto"
    # Example: http://localhost:9050/deskew (depends on your service wrapper).
    DESKEW_PADDLE_URL: str = ""
    DESKEW_TIMEOUT_SEC: int = 60
    ORIENTATION_ENABLED: bool = False
    # Optional: PaddleOCR DocPreprocessor for raster-image orientation/unwarp before parsing.
    PADDLE_OCR_PREPROCESS_ENABLED: bool = False
    # local | skip
    PADDLE_OCR_PREPROCESS_BACKEND: str = "local"
    PADDLE_OCR_PREPROCESS_DEVICE: str = "cpu"
    PADDLE_OCR_PREPROCESS_LANG: str = "ch"
    PADDLE_OCR_USE_DOC_ORIENTATION_CLASSIFY: bool = True
    PADDLE_OCR_USE_DOC_UNWARPING: bool = True
    PADDLE_OCR_USE_TEXTLINE_ORIENTATION: bool = False
    # Optional handwriting/noise cleanup before parsing.
    HANDWRITING_CLEANUP_ENABLED: bool = False
    # auto | heuristic | local | http | skip
    HANDWRITING_CLEANUP_BACKEND: str = "auto"
    HANDWRITING_CLEANUP_MODEL_PATH: str = ""
    HANDWRITING_CLEANUP_API_URL: str = ""
    HANDWRITING_CLEANUP_TIMEOUT_SEC: int = 60
    # Watermark removal can be destructive; keep it off by default.
    WATERMARK_REMOVAL_ENABLED: bool = False
    # auto | local | http | skip
    WATERMARK_REMOVAL_BACKEND: str = "auto"
    WATERMARK_REMOVAL_MODEL_PATH: str = ""
    # Optional: external watermark-removal backend (image or pdf -> processed bytes).
    WATERMARK_REMOVAL_API_URL: str = ""
    WATERMARK_TIMEOUT_SEC: int = 120
    # Best-effort: remove PDF watermark annotations before falling back to model-based removal.
    WATERMARK_PDF_ANNOT_STRIP_ENABLED: bool = True
    # When enabled, skip preprocessing for high-quality PDFs (best-effort; requires pdf_quality score).
    PREPROCESS_SKIP_HIGH_QUALITY: bool = True
    PREPROCESS_SAMPLE_PAGES: int = 3
    # Parse-then-correct via external VLM backend.
    VLM_CORRECTION_API_URL: str = ""
    VLM_CORRECTION_TIMEOUT_SEC: int = 60
    VLM_CORRECTION_MAX_CHARS: int = 40_000
    VLM_CORRECTION_MIN_TABLE_QUALITY: float = 0.6
    # Multi-parser competition matrix (Opt8) for workspace parsing selection.
    PARSE_COMPETITION_MATRIX_ENABLED: bool = False
    # JSON mapping like {"text":0.4,"table":0.3,"image":0.15,"reading_order":0.15}
    PARSE_COMPETITION_MATRIX_WEIGHTS_JSON: str = ""
    # Optional: VLM-backed inline image captions (Opt5).
    # Disabled by default; requires an external HTTP backend.
    IMAGE_CAPTION_VLM_ENABLED: bool = False
    IMAGE_CAPTION_VLM_API_URL: str = ""
    IMAGE_CAPTION_VLM_TIMEOUT_SEC: int = 60
    IMAGE_CAPTION_VLM_MAX_IMAGES: int = 20
    IMAGE_CAPTION_VLM_MAX_IMAGE_BYTES: int = 5_000_000
    IMAGE_CAPTION_VLM_MAX_CAPTION_CHARS: int = 200
    # Opt3: Formula OCR / LaTeX conversion (optional; external HTTP backend).
    FORMULA_OCR_ENABLED: bool = False
    FORMULA_OCR_API_URL: str = ""
    FORMULA_OCR_TIMEOUT_SEC: int = 60
    FORMULA_OCR_MAX_IMAGES: int = 12
    FORMULA_OCR_MAX_IMAGE_BYTES: int = 5_000_000
    FORMULA_OCR_MAX_LATEX_CHARS: int = 2000
    # Image understanding (caption/OCR) for image chunks during ingest.
    # Conservative defaults: disabled unless explicitly enabled via pipeline metadata.
    IMAGE_CAPTION_ENABLED: bool = False
    IMAGE_OCR_ENABLED: bool = False
    IMAGE_OCR_MAX_CHARS: int = 2000
    IMAGE_OCR_MAX_IMAGES: int = 20
    # Multi-modal retrieval (optional): CLIP embeddings for image chunks.
    # Disabled by default to avoid pulling heavyweight ML deps in minimal deployments.
    IMAGE_EMBEDDING_ENABLED: bool = False
    IMAGE_EMBEDDING_MODEL_NAME: str = "clip-ViT-B-32"
    IMAGE_EMBEDDING_DEVICE: str = "cpu"
    IMAGE_EMBEDDING_BATCH_SIZE: int = 8
    IMAGE_EMBEDDING_COLLECTION_NAME: str = "image_chunks"
    # Keep this aligned with parser_factory supported non-PDF formats.
    ALLOWED_EXTENSIONS: str = ".pdf,.txt,.md,.rst,.adoc,.asciidoc,.tex,.yaml,.yml,.toml,.sql,.log,.conf,.ini,.cfg,.env,.properties,.patch,.diff,.srt,.vtt,.mk,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.csv,.html,.htm,.json,.jsonl,.ndjson,.xml,.rss,.atom,.graphql,.gql,.proto,.tf,.hcl,.js,.jsx,.mjs,.cjs,.ts,.tsx,.mts,.cts,.py,.pyi,.rs,.go,.java,.kt,.kts,.c,.h,.cc,.cpp,.cxx,.hpp,.cs,.php,.rb,.swift,.scala,.sh,.bash,.zsh,.ps1,.lua,.r,.vue,.svelte,.astro,.css,.scss,.sass,.less,.epub,.rtf,.odt,.eml,.msg,.png,.jpg,.jpeg,.webp,.gif,.bmp"

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
    MINERU_BACKEND: str = "pipeline"
    MINERU_ENABLED: bool = False
    # MinerU local ZIP mode (Markdown + images)
    MINERU_LOCAL_SERVER_URL: str = Field(
        default="",
        validation_alias=AliasChoices("MINERU_LOCAL_SERVER_URL", "MINERU_APISERVER"),
    )
    MINERU_VL_SERVER: str = Field(
        default="",
        validation_alias=AliasChoices("MINERU_VL_SERVER", "MINERU_SERVER_URL"),
    )

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

    # Tencent Cloud ADP parser (optional).
    TCADP_SECRET_ID: str = ""
    TCADP_SECRET_KEY: str = ""
    TCADP_REGION: str = "ap-guangzhou"
    TCADP_TABLE_RESULT_TYPE: str = "1"
    TCADP_MARKDOWN_IMAGE_RESPONSE_TYPE: str = "1"
    PARSE_QUALITY_OCR_LOW_CONFIDENCE_THRESHOLD: float = 0.7

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

    # GLM-OCR (PDF -> Markdown external service; optional)
    GLM_OCR_ENABLED: bool = False
    # Full endpoint URL, e.g. http://localhost:9040/convert (depends on your GLM-OCR wrapper service).
    GLM_OCR_API_URL: str = ""
    GLM_OCR_TIMEOUT_SEC: int = 600
    # Display/audit only: expected service pipeline version/mode (not used by the backend parser directly).
    GLM_OCR_PIPELINE_VERSION: str = "v0.9b"

    # olmOCR (PDF -> Markdown external service; optional)
    OLMOCR_ENABLED: bool = False
    # Full endpoint URL, e.g. http://localhost:2085/convert (depends on your olmOCR service).
    OLMOCR_API_URL: str = ""
    OLMOCR_TIMEOUT_SEC: int = 1800

    # Qianfan-OCR (PDF/Image -> Markdown external service; optional)
    QIANFAN_OCR_ENABLED: bool = False
    # Full endpoint URL, e.g. http://localhost:2090/convert (depends on your Qianfan-OCR wrapper service).
    QIANFAN_OCR_API_URL: str = ""
    QIANFAN_OCR_TIMEOUT_SEC: int = 1800
    # Whether to request Layout-as-Thought mode from the external service.
    QIANFAN_OCR_LAYOUT_AS_THOUGHT: bool = False

    # TextIn xParse (document -> Markdown external API; optional)
    TEXTIN_ENABLED: bool = False
    # Full endpoint URL, defaults to the official xParse quickstart endpoint.
    TEXTIN_API_URL: str = "https://api.textin.com/ai/service/v1/pdf_to_markdown"
    TEXTIN_APP_ID: str = ""
    TEXTIN_SECRET_CODE: str = ""
    TEXTIN_TIMEOUT_SEC: int = 180
    # auto | scan | parse | lite | vlm
    TEXTIN_PARSE_MODE: str = "auto"
    # html | markdown
    TEXTIN_TABLE_FLAVOR: str = "html"
    TEXTIN_APPLY_DOCUMENT_TREE: bool = True
    TEXTIN_MARKDOWN_DETAILS: bool = True
    # none | objects | pages | both
    TEXTIN_GET_IMAGE: str = "none"
    TEXTIN_DPI: int = 144
    # 0 = all pages
    TEXTIN_PAGE_COUNT: int = 0

    # PDF quality OCR validation (used by parse-preview scoring)
    RAPIDOCR_ENABLED: bool = False

    # Auth
    # - jwt: require Authorization: Bearer <JWT> (validated with SECRET_KEY)
    # - header: require X-User-ID header (unsafe; intended for local/dev only)
    AUTH_MODE: Literal["jwt", "header"] = "jwt"
    # Non-production escape hatch for browser-driven asset fetches in AUTH_MODE=header.
    # Disabled by default so asset endpoints do not become anonymously readable unless
    # the operator explicitly opts in for local compatibility.
    ASSET_HEADER_AUTH_ALLOW_ANONYMOUS: bool = False

    SECRET_KEY: str = ""
    # One-time bootstrap gate for the very first local owner registration in production.
    # Provide either a raw token or `sha256:<hex>` and send it via `X-Bootstrap-Token`.
    INITIAL_REGISTRATION_TOKEN: str = ""
    # Optional previous keys for decrypting already-encrypted secrets (comma-separated).
    # This enables key rotation for connector configs without breaking existing entries.
    SECRET_KEY_FALLBACKS: str = ""
    ALGORITHM: str = "HS256"
    # Optional: verify JWTs via JWKS (typically for RS256/ES256 tokens issued by an external IdP).
    # Comma-separated list of JWKS URLs. Use https in normal deployments; non-production may use
    # http only for localhost/loopback testing.
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
    # Keep this issuer as https in normal deployments; non-production may use
    # http only for localhost/loopback testing.
    # NOTE: If you set these, tokens issued by /api/v1/auth/login will include these claims.
    JWT_ISSUER: str = ""
    JWT_AUDIENCE: str = ""
    # Optional multi-tenant binding via JWT claim (e.g. "tid" or "tenant_id").
    # When set, tokens issued by /api/v1/auth/login will include this claim when a current tenant is available.
    JWT_TENANT_CLAIM: str = ""
    # When enabled (and JWT_TENANT_CLAIM is set), require X-Tenant-ID header to match the JWT tenant claim.
    # This mitigates cross-tenant spoofing via headers in AUTH_MODE=jwt while staying backwards compatible by default.
    JWT_ENFORCE_TENANT_HEADER_MATCH: bool = False
    # Explicitly trust the client-supplied tenant header (TENANT_HEADER) as the tenant source in
    # production when no verified JWT tenant claim is configured. Only safe when a trusted gateway
    # strips/injects the header, or the deployment is effectively single-tenant.
    TENANT_HEADER_TRUSTED: bool = False
    # Optional: sync tenant groups from a verified JWT claim (enterprise directory primitive).
    # Safe defaults: disabled.
    JWT_GROUPS_SYNC_ENABLED: bool = False
    # JWT claim that contains group names/ids (supports dotted paths like "realm_access.roles").
    JWT_GROUPS_CLAIM: str = "groups"
    # Guardrail: cap claim items processed per request (best-effort).
    JWT_GROUPS_MAX_GROUPS: int = 200
    # Throttle to avoid write amplification (seconds; best-effort in-process cache; 0 disables).
    JWT_GROUPS_SYNC_TTL_SEC: int = 60
    # Optional enterprise: auto-provision tenant_members for JWT-authenticated users when a
    # verified JWT tenant claim is present. Safe default: disabled.
    JWT_TENANT_MEMBER_AUTO_PROVISION_ENABLED: bool = False

    # SAML assertion exchange (enterprise; backend validation + app JWT issuance).
    # JSON list, for example:
    # [{"id":"default","issuer":"https://idp.example.com","audience":"https://app.example.com/api/saml/metadata","acs_url":"https://app.example.com/api/saml/acs","idp_cert_pem":"-----BEGIN CERTIFICATE-----..."}]
    SAML_PROVIDERS_JSON: str = ""
    # Allow small clock drift between IdP and SP.
    SAML_ALLOWED_CLOCK_SKEW_SEC: int = 60
    # Replay-protection retention window for assertion IDs.
    SAML_REPLAY_TTL_SEC: int = 300
    # Redis-backed replay cache. Production SAML requires this for cross-process protection.
    SAML_REPLAY_REDIS_ENABLED: bool = False
    # Defense-in-depth size limit for inbound base64 SAMLResponse payloads.
    SAML_MAX_RESPONSE_BYTES: int = 500_000

    # Optional: SP metadata certificate/keypair (enterprise IdP compatibility).
    #
    # - SAML_SP_CERT_PEM is the public X.509 certificate advertised in metadata KeyDescriptor.
    # - SAML_SP_PRIVATE_KEY_PEM is used to sign SP metadata when SAML_SP_METADATA_SIGNED=true.
    SAML_SP_CERT_PEM: str = ""
    SAML_SP_PRIVATE_KEY_PEM: str = ""
    # Safe default: unsigned metadata unless explicitly enabled.
    SAML_SP_METADATA_SIGNED: bool = False

    # SCIM v2 provisioning (enterprise; opt-in).
    #
    # Design:
    # - default disabled (no extra auth surface)
    # - guarded by static bearer token (IdP-friendly)
    # - read-only endpoints first; PATCH membership is separate opt-in
    SCIM_ENABLED: bool = False
    # Bearer token auth for SCIM endpoints.
    #
    # Rotation support:
    # - You may provide a comma/space-separated active set (e.g. "tok_v1,tok_v2")
    # - Each token may be provided as raw or as `sha256:<hex>` (recommended)
    SCIM_BEARER_TOKEN: str = ""
    # Each SCIM credential set is bound to exactly one tenant.
    SCIM_TENANT_ID: str = ""
    SCIM_PAGE_SIZE_MAX: int = 200
    # Defense-in-depth: optional client IP allowlist for SCIM endpoints.
    # Comma/space-separated CIDRs (e.g. "203.0.113.0/24,198.51.100.10/32").
    # Fail-closed when set.
    SCIM_IP_ALLOWLIST_CIDRS: str = ""
    SCIM_PATCH_GROUP_MEMBERSHIP_ENABLED: bool = False
    # Optional write endpoints (default disabled).
    SCIM_USERS_CREATE_ENABLED: bool = False
    SCIM_USERS_PATCH_ACTIVE_ENABLED: bool = False
    # Deprovision policy (opt-in): when a user is deactivated via SCIM, revoke group memberships.
    SCIM_DEPROVISION_REVOKE_GROUP_MEMBERSHIPS_ENABLED: bool = False
    SCIM_GROUPS_MUTATION_ENABLED: bool = False

    # Dify External Knowledge API adapter (enterprise; opt-in).
    #
    # Dify calls MimirQ for retrieval only. By default `knowledge_id` must be
    # declared in the JSON map. Local/dev compatibility can explicitly opt into
    # direct dataset UUID pass-through.
    DIFY_EXTERNAL_KNOWLEDGE_ENABLED: bool = False
    DIFY_EXTERNAL_KNOWLEDGE_API_KEYS: str = ""
    DIFY_EXTERNAL_KNOWLEDGE_TENANT_ID: str = ""
    DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID: str = "system:dify"
    DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON: str = ""
    DIFY_EXTERNAL_KNOWLEDGE_RESOLUTION_MODE: str = "mapped_only"
    DIFY_EXTERNAL_KNOWLEDGE_TRACE_AUTO_CREATE_CONVERSATION_ENABLED: bool = True
    # Background cold-start warmup for Dify external knowledge retrieval. This
    # keeps the first real Dify request from paying tokenizer/BM25/vector setup.
    DIFY_EXTERNAL_KNOWLEDGE_WARMUP_ENABLED: bool = True
    DIFY_EXTERNAL_KNOWLEDGE_WARMUP_KNOWLEDGE_IDS: str = ""
    DIFY_EXTERNAL_KNOWLEDGE_WARMUP_QUERY: str = "warmup probe"
    DIFY_EXTERNAL_KNOWLEDGE_WARMUP_TOP_K: int = 1
    DIFY_EXTERNAL_KNOWLEDGE_WARMUP_MAX_KNOWLEDGE_IDS: int = 8
    DIFY_EXTERNAL_KNOWLEDGE_WARMUP_TIMEOUT_SEC: float = 60.0
    DIFY_EXTERNAL_KNOWLEDGE_WARMUP_START_DELAY_SEC: float = 1.0
    # When true, /health/ready returns 503 until the Dify external knowledge
    # warmup has completed. This prevents Dify/LB traffic from hitting a cold
    # process and paying BM25 lazy-build latency in the first user request.
    DIFY_EXTERNAL_KNOWLEDGE_WARMUP_REQUIRED_FOR_READY: bool = False
    DIFY_EXTERNAL_KNOWLEDGE_TOP_K_MAX: int = 5
    DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MIN: int = 20
    DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MULTIPLIER: int = 4
    DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MAX: int = 50
    DIFY_EXTERNAL_KNOWLEDGE_RETRIEVAL_OVERFETCH_MULTIPLIER: int = 1
    # Query routes are recall hints for matching queries. Unmatched route
    # datasets stay out of scope by default to avoid broad aggregate noise.
    DIFY_EXTERNAL_KNOWLEDGE_INCLUDE_UNMATCHED_ROUTE_HINTS: bool = False
    # Use the normal RAG reranker inside Dify external knowledge retrieval.
    # The global ENABLE_RERANKER still gates the actual reranker provider.
    DIFY_EXTERNAL_KNOWLEDGE_RERANKER_ENABLED: bool = True
    # 0 means cap Dify external retrieval overfetch at the resolved internal candidate top_k.
    DIFY_EXTERNAL_KNOWLEDGE_RETRIEVAL_OVERFETCH_MAX_K: int = 0
    DIFY_EXTERNAL_KNOWLEDGE_PRIMARY_SCOPE_ENABLED: bool = True
    DIFY_EXTERNAL_KNOWLEDGE_PRIMARY_MIN_RECORDS: int = 1
    DIFY_EXTERNAL_KNOWLEDGE_PRIMARY_MIN_TOP_SCORE: float = 0.45
    # Short in-process cache for Dify external retrieval records. This is not an
    # answer fallback; it removes duplicate retrieval work inside one workflow run.
    DIFY_EXTERNAL_KNOWLEDGE_RESPONSE_CACHE_ENABLED: bool = True
    DIFY_EXTERNAL_KNOWLEDGE_RESPONSE_CACHE_TTL_SEC: int = 30
    DIFY_EXTERNAL_KNOWLEDGE_RESPONSE_CACHE_MAX_ENTRIES: int = 512
    # Coalesce identical in-flight retries before they consume another RAG slot.
    DIFY_EXTERNAL_KNOWLEDGE_SINGLEFLIGHT_ENABLED: bool = True
    DIFY_EXTERNAL_KNOWLEDGE_COMPACT_HIGH_CONFIDENCE_ENABLED: bool = True
    DIFY_EXTERNAL_KNOWLEDGE_COMPACT_MIN_TOP_SCORE: float = 0.7
    DIFY_EXTERNAL_KNOWLEDGE_COMPACT_RELATIVE_SCORE_FLOOR: float = 0.65
    DIFY_EXTERNAL_KNOWLEDGE_COMPACT_MIN_RECORDS: int = 1
    DIFY_EXTERNAL_KNOWLEDGE_FAST_CANDIDATE_TOP_K_MAX: int = 3
    DIFY_EXTERNAL_KNOWLEDGE_FAST_RESPONSE_TOP_K_MAX: int = 2
    DIFY_EXTERNAL_KNOWLEDGE_FAST_CONTENT_MAX_CHARS: int = 1400
    DIFY_EXTERNAL_KNOWLEDGE_FAST_TOTAL_CONTENT_MAX_CHARS: int = 2200
    # Fast preflight is only a latency shortcut. It must never dominate the
    # request; if it cannot prove an exact anchor quickly, normal RAG should run.
    DIFY_EXTERNAL_KNOWLEDGE_FAST_METADATA_PREFLIGHT_STATEMENT_TIMEOUT_MS: int = 600
    DIFY_EXTERNAL_KNOWLEDGE_FAST_METADATA_PREFLIGHT_MAX_ELAPSED_MS: int = 900
    # Dify external retrieval is latency-sensitive and query strings are often
    # short entity/fact questions, so keep lexical DB as a parallel sparse
    # candidate channel instead of only a late fallback.
    DIFY_EXTERNAL_KNOWLEDGE_LEXICAL_DB_HYBRID_FALLBACK_ONLY: bool = False
    DIFY_EXTERNAL_KNOWLEDGE_LEXICAL_METADATA_EXACT_FALLBACK_ENABLED: bool = False
    DIFY_EXTERNAL_KNOWLEDGE_METADATA_EXACT_DB_FALLBACK_ENABLED: bool = False
    # Optional exact metadata-anchor DB safety net. Keep it opt-in for Dify's
    # latency-sensitive path; normal quality should come from RAG/KG plus
    # plugin-provided metadata and ranking policy.
    DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_ENABLED: bool = False
    DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_PREFLIGHT_ENABLED: bool = False
    DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_MAX_SCAN: int = 80
    DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_MAX_RECORDS: int = 4
    DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_STATEMENT_TIMEOUT_MS: int = 2500
    # Cumulative DB-fallback execution budget for one quality-profile request.
    # Zero preserves the legacy unbounded behavior.
    DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_TOTAL_BUDGET_MS: int = 1500
    # Exact-anchor lookup must stay inside the requested knowledge scope unless
    # a deployment explicitly opts into cross-sibling recovery.
    DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_EXTEND_SIBLING_POLICY_SCOPE_ENABLED: bool = False
    DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_EXTENDED_SCOPE_MAX_DATASETS: int = 80
    # Avoid unindexed JSON text scans on the latency-sensitive Dify path.
    # Structured metadata fields remain available through the anchor fallback.
    DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_TEXT_SCAN_ENABLED: bool = False
    # Compound/mixed-intent retrieval fans out into subqueries, then merges and
    # reranks once. Keep these generic budget controls out of business plugins.
    DIFY_EXTERNAL_KNOWLEDGE_MIXED_INTENT_SUPPLEMENT_ENABLED: bool = True
    DIFY_EXTERNAL_KNOWLEDGE_MIXED_INTENT_MAX_SUBQUERIES: int = 4
    # 0 means use the Dify response top_k for each mixed-intent subquery.
    DIFY_EXTERNAL_KNOWLEDGE_MIXED_INTENT_SUBQUERY_TOP_K: int = 0
    # When KG is enabled for Dify external retrieval, first run normal RAG and
    # invoke KG only if the normal result lacks a confident metadata anchor.
    DIFY_EXTERNAL_KNOWLEDGE_KG_ON_DEMAND_ENABLED: bool = True
    DIFY_EXTERNAL_KNOWLEDGE_KG_ON_DEMAND_PROBE_ENABLED: bool = True
    DIFY_EXTERNAL_KNOWLEDGE_KG_QUERY_EXPANSION_ENABLED: bool = False
    DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_INJECTION_ENABLED: bool = False
    DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_INJECTION_MAX_CHUNKS: int = 3
    DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_BOOST_ENABLED: bool = False
    DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_BOOST_WEIGHT: float = 0.25
    DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_BOOST_MAX_PROMOTED: int = 2

    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    PASSWORD_MIN_LENGTH: int = 8

    CORS_ORIGINS: str = "http" + "://localhost:3000,http" + "://localhost:3001"
    # Whether CORS responses include `Access-Control-Allow-Credentials: true`.
    #
    # Prod strategy (Option A):
    # - Default false in production unless explicitly enabled.
    # - Default true outside production for local dev ergonomics.
    CORS_ALLOW_CREDENTIALS: bool = True
    # Allow browsers to read diagnostic headers from cross-origin responses.
    # NOTE: This does not affect which headers the backend sends, only what the browser exposes to JS.
    CORS_EXPOSE_HEADERS: str = (
        "X-Request-ID,X-Process-Time-Ms,Server-Timing,Retry-After,"
        "X-Conversation-ID,X-Assistant-Message-ID"
    )
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

    # Comma-separated admin-controlled frontend modules visible to ordinary
    # tenant members. Admin roles always see these modules.
    NAVIGATION_USER_VISIBLE_MODULES: str = ""

    # Emit Server-Timing response header for quick perf debugging.
    SERVER_TIMING_ENABLED: bool = True

    # Health/readiness cache TTL (seconds). Keeps probes cheap under load.
    HEALTH_CACHE_TTL_SEC: float = 2.0
    READY_CACHE_TTL_SEC: float = 2.0

    HOST: str = "127.0.0.1"
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
    RETRIEVAL_MODE: str = "hybrid"
    SIMILARITY_THRESHOLD: float = 0.7
    # Concurrent retrieval across query variants (multi-query / decompose / HyDE).
    RETRIEVAL_QUERY_PARALLELISM: int = 1
    # Deterministic, no-LLM fan-out for obvious multi-intent questions. This is
    # bounded so external retrieval can improve coverage without adding model latency.
    RETRIEVAL_LIGHTWEIGHT_SUBQUERY_ENABLED: bool = False
    RETRIEVAL_LIGHTWEIGHT_SUBQUERY_MAX_QUERIES: int = 3
    RETRIEVAL_LIGHTWEIGHT_SUBQUERY_MIN_QUERY_CHARS: int = 28
    # MMR (Maximal Marginal Relevance) settings
    RETRIEVAL_MMR_LAMBDA: float = 0.7  # Balance relevance vs diversity (0=diversity, 1=relevance)
    RETRIEVAL_MMR_FETCH_K_MULTIPLIER: int = 4  # Fetch k*multiplier candidates for MMR selection
    # Retrieval fusion strategy:
    # - linear: min-max normalize each channel then alpha-blend
    # - rrf: reciprocal-rank fusion (normalized for UI)
    # - budgeted_rrf: RRF scoring but enforce per-channel quotas in the visible top-k prefix
    RETRIEVAL_FUSION_STRATEGY: Literal["linear", "rrf", "budgeted_rrf"] = "budgeted_rrf"
    # Single source for dense-vs-keyword blend defaults across request schemas and retrievers.
    RETRIEVAL_DEFAULT_ALPHA: float = 0.6
    RETRIEVAL_RRF_K: int = 60
    # Post-retrieval guards (dedup/diversity)
    RETRIEVAL_DEDUP_ENABLED: bool = True
    RETRIEVAL_DEDUP_JACCARD_THRESHOLD: float = 0.92
    RETRIEVAL_DEDUP_MAX_COMPARE: int = 50
    # Optional: cross-document near-duplicate dropping using per-chunk simhash64 metadata.
    # Safe-by-default: disabled unless explicitly enabled.
    RETRIEVAL_NEAR_DEDUP_ENABLED: bool = False
    # Hamming distance threshold (0 = exact simhash match only).
    RETRIEVAL_NEAR_DEDUP_HAMMING_THRESHOLD: int = 3
    # Cap comparisons against previously-kept simhash values (0 disables cap).
    RETRIEVAL_NEAR_DEDUP_MAX_COMPARE: int = 60
    # Per-document diversity (0 disables)
    RETRIEVAL_MAX_CHUNKS_PER_DOC: int = 3
    # Per plugin-declared business record identity (0 disables). Applies only
    # when chunk metadata contains the generic `_record_identity` view.
    RETRIEVAL_MAX_CHUNKS_PER_RECORD_IDENTITY: int = 2
    # Optional final-context compaction. Disabled by default unless a retrieval
    # policy or deployment config opts in, because returning fewer than top_k is
    # a precision-over-recall tradeoff.
    RETRIEVAL_COMPACT_HIGH_CONFIDENCE_ENABLED: bool = False
    RETRIEVAL_COMPACT_MIN_TOP_SCORE: float = 0.8
    RETRIEVAL_COMPACT_RELATIVE_SCORE_FLOOR: float = 0.65
    RETRIEVAL_COMPACT_MIN_RECORDS: int = 1
    # Per-page diversity within a document (0 disables). Only applies when a chunk has page_number/page metadata.
    RETRIEVAL_MAX_CHUNKS_PER_PAGE: int = 0
    # Metadata filtering for vector search
    RETRIEVAL_METADATA_FILTER_ENABLED: bool = True
    RETRIEVAL_MIN_DISTINCT_DOCS: int = 0
    # Optional field-aware recall signal (disabled by default).
    # When enabled, vector candidates sourced from title/heading auxiliary embeddings
    # receive a small bounded additive score during channel fusion.
    RETRIEVAL_FIELD_AWARE_RECALL_ENABLED: bool = False
    RETRIEVAL_FIELD_AWARE_TITLE_BOOST: float = 0.08
    RETRIEVAL_FIELD_AWARE_HEADING_BOOST: float = 0.05
    RETRIEVAL_FIELD_AWARE_MAX_BOOST: float = 0.10
    RETRIEVAL_EXACT_PHRASE_RERANK_BOOST: float = 0.35
    # Optional chunk-type-aware recall signal (disabled by default).
    # When enabled, candidates whose standardized chunk_type matches the query intent
    # receive a small bounded additive score during channel fusion.
    RETRIEVAL_CHUNK_TYPE_WEIGHTING_ENABLED: bool = False
    RETRIEVAL_CHUNK_TYPE_MATCH_BOOST: float = 0.08
    # When retrieval is not pre-scoped by explicit document_ids (open scope / dataset scope),
    # we may need to over-fetch to compensate for candidate-level ACL + active-pipeline trimming.
    # 1 disables.
    RETRIEVAL_OVERFETCH_MULTIPLIER: int = 4
    # Hard cap for the over-fetched k (0 disables).
    RETRIEVAL_OVERFETCH_MAX_K: int = 50
    # Optional hierarchy-aware recall overlay. Safe-off defaults preserve legacy retrieval behavior.
    HIERARCHY_RECALL_ENABLED: bool = False
    HIERARCHY_RECALL_FAMILY_COLLAPSE: bool = True
    HIERARCHY_RECALL_FAMILY_AGGREGATION: str = "combined"  # frequency | score | combined
    HIERARCHY_RECALL_TREE_DEDUP: bool = False
    HIERARCHY_RECALL_PARENT_DEPTH: int = 0
    HIERARCHY_RECALL_SIBLING_WINDOW: int = 0
    HIERARCHY_RECALL_OVERFETCH_FACTOR: int = 4
    # Retrieval contract mode (opt-in behavior packs).
    # - "" (default): no contract override
    # - deterministic_recall: force deterministic fallback-first safeguards for empty evidence
    # - must_recall_strict: deterministic fallback + partial-miss second pass + strict fail reasons
    # - evidence_strict: force span-level evidence gating + visible-evidence-only grounding
    # - audit_trace: reserved for high-verbosity retrieval tracing (no scoring behavior change)
    RETRIEVAL_CONTRACT_MODE: str = ""
    # Must-recall contract controls (opt-in, additive).
    RETRIEVAL_MUST_RECALL_DEFAULT_ENABLED: bool = False
    # CSV of expected source keys (table_id/document/source aliases); empty means "no explicit source key contract".
    RETRIEVAL_MUST_RECALL_REQUIRED_SOURCE_KEYS: str = ""
    # CSV of citation keys that must exist when must-recall is enabled.
    RETRIEVAL_MUST_RECALL_REQUIRED_ANCHOR_FIELDS: str = "chunk_id,document_id"
    RETRIEVAL_MUST_RECALL_SECOND_PASS_ENABLED: bool = True
    RETRIEVAL_MUST_RECALL_SECOND_PASS_MODE: str = "keyword"  # noqa: S105  # hybrid | vector | keyword | mmr
    RETRIEVAL_MUST_RECALL_SECOND_PASS_TOP_K: int = 80
    # Contextual follow-up pass (deterministic):
    # build one bounded query from already retrieved docs, then run a second retrieval pass.
    RETRIEVAL_CONTEXTUAL_FOLLOWUP_ENABLED: bool = False
    RETRIEVAL_CONTEXTUAL_FOLLOWUP_MODE: str = "keyword"  # hybrid | vector | keyword | mmr
    RETRIEVAL_CONTEXTUAL_FOLLOWUP_TOP_K: int = 40
    RETRIEVAL_CONTEXTUAL_FOLLOWUP_MAX_DOCS: int = 4
    RETRIEVAL_CONTEXTUAL_FOLLOWUP_MAX_TERMS: int = 4
    RETRIEVAL_CONTEXTUAL_FOLLOWUP_MIN_TERM_CHARS: int = 4
    RETRIEVAL_CONTEXTUAL_FOLLOWUP_MAX_QUERY_CHARS: int = 500
    RETRIEVAL_CONTEXTUAL_FOLLOWUP_MAX_HOPS: int = 1
    RETRIEVAL_CONTEXTUAL_FOLLOWUP_LATENCY_BUDGET_MS: float = 500.0
    # Emit immutable provenance capsule for retrieval responses (PII-safe, replay-friendly).
    RAG_EVIDENCE_CAPSULE_ENABLED: bool = True
    # Deterministic hard fallback (opt-in):
    # when primary retrieval yields no citations, run one bounded fallback pass.
    RETRIEVAL_HARD_FALLBACK_ENABLED: bool = False
    RETRIEVAL_HARD_FALLBACK_MODE: str = "keyword"  # hybrid | vector | keyword | mmr
    RETRIEVAL_HARD_FALLBACK_TOP_K: int = 30
    # Optional hardcase emission hook for downstream EvidenceSuite/LTR automation.
    RETRIEVAL_HARDCASE_EMIT_ENABLED: bool = False
    # Parse-quality retrieval diagnostics (operator-facing; no ranking change by default).
    RETRIEVAL_PARSE_QUALITY_LOW_THRESHOLD: float = 0.35
    RETRIEVAL_PARSE_QUALITY_ALERT_RATIO: float = 0.5
    # Parse quality gate profile for retrieval responses:
    # - off: no gate action
    # - warn: annotate diagnostics only
    # - strict: mark gate failure and force abstain
    RETRIEVAL_PARSE_QUALITY_GATE_PROFILE: str = "warn"  # off | warn | strict
    # Parse-risk remediation policy (operator-facing, bounded, optional).
    # - when enabled, high parse-risk tails can emit hardcase candidates even if retrieval is non-empty.
    RETRIEVAL_PARSE_RISK_HARDCASE_EMIT_ENABLED: bool = False
    RETRIEVAL_PARSE_RISK_HARDCASE_MIN_LOW_RATIO: float = 0.5
    RETRIEVAL_PARSE_RISK_HARDCASE_MIN_CONSIDERED: int = 3
    RETRIEVAL_PARSE_RISK_AUTO_ENQUEUE_LEVELS: str = DEFAULT_RETRIEVAL_PARSE_RISK_AUTO_ENQUEUE_LEVELS
    RETRIEVAL_PARSE_RISK_AUTO_ENQUEUE_MIN_SCORE: float = 0.0
    # Default upper-bound for parse-risk driven reparse planning CLI.
    RETRIEVAL_PARSE_RISK_REPARSE_MAX_DOCS: int = 100

    # Lifecycle governance-aware retrieval policy over already-enriched candidates.
    #
    # Goal: keep enterprise knowledge bases fresh + authoritative without changing default retrieval behavior.
    # - prefer_authority/latest: adds a small scoring bias at the candidate ranking stage
    # - filter_superseded: optionally drop documents that have been superseded by another active doc
    RETRIEVAL_GOVERNANCE_PREFER_AUTHORITY: bool = True
    RETRIEVAL_GOVERNANCE_PREFER_LATEST: bool = True
    RETRIEVAL_GOVERNANCE_FILTER_SUPERSEDED: bool = True
    # Max additive score boosts (keep small to avoid overpowering semantic relevance).
    RETRIEVAL_GOVERNANCE_AUTHORITY_BOOST_MAX: float = 0.02
    RETRIEVAL_GOVERNANCE_LATEST_BOOST_MAX: float = 0.02
    # Consider a document "latest" when updated within this window (older docs taper to 0 boost).
    RETRIEVAL_GOVERNANCE_LATEST_WINDOW_DAYS: int = 180

    # Persistent lexical fallback (Postgres FTS / pg_trgm).
    # Helps reduce false negatives for numbers, codes, and exact phrases.
    LEXICAL_DB_ENABLED: bool = True
    # Hybrid/MMR modes use lexical DB as a fallback by default; keyword mode remains lexical-first.
    LEXICAL_DB_HYBRID_FALLBACK_ONLY: bool = True
    # Enables the expensive CJK metadata-anchor lexical fallback in hybrid/MMR modes.
    # External low-latency callers can disable this per request without changing global recall defaults.
    LEXICAL_DB_HYBRID_METADATA_EXACT_FALLBACK_ENABLED: bool = True
    # In keyword-only mode, lexical DB is the primary keyword channel by default.
    # BM25 stays available as an opt-in secondary channel for recall comparison/back-compat.
    RETRIEVAL_KEYWORD_BM25_SECONDARY_ENABLED: bool = False
    LEXICAL_DB_FTS_CONFIG: str = "simple"
    LEXICAL_DB_TRGM_ENABLED: bool = True
    # Candidate overfetch inside the lexical channel (applied before metadata trimming).
    LEXICAL_DB_FETCH_MULTIPLIER: int = 4
    LEXICAL_DB_MAX_CANDIDATES: int = 200
    LEXICAL_DB_TRGM_MIN_QUERY_CHARS: int = 3
    # CJK short-entity queries often fail whole-string FTS/trigram because the
    # relevant phrase is a small substring inside a long chunk. Use tokenizer
    # terms as an indexed lexical candidate channel.
    LEXICAL_DB_CJK_TOKEN_CONTAINMENT_ENABLED: bool = True
    LEXICAL_DB_CJK_TOKEN_MAX_TERMS: int = 6
    LEXICAL_DB_CJK_TOKEN_MIN_HITS: int = 0
    # Dataset-scoped metadata exact fallback for CJK FAQ/title anchors.
    # This is a candidate safety net for plugin-provided `_evaluable_metadata`
    # fields such as question/aliases/service_name when content lexical search
    # is diluted by broad semantic matches.
    RETRIEVAL_METADATA_EXACT_DB_FALLBACK_ENABLED: bool = True
    RETRIEVAL_METADATA_EXACT_DB_MAX_CANDIDATES: int = 80
    RETRIEVAL_METADATA_EXACT_PRE_FUSION_ENABLED: bool = True

    # Optional sparse retrieval channel (SPLADE-style scaffolding).
    #
    # Notes:
    # - Disabled by default (no behavior change).
    # - The default provider is deterministic and intended for tests/offline use.
    # - Production SPLADE models (HF/transformers) must be loaded lazily and are optional.
    SPARSE_RETRIEVAL_ENABLED: bool = False
    SPARSE_RETRIEVAL_PROVIDER: str = "deterministic"  # deterministic | splade
    # Persist sparse indices to disk (scoped by tenant/dataset/document_ids).
    # This is safe because sparse retrieval is disabled by default.
    SPARSE_RETRIEVAL_INDEX_PERSIST_ENABLED: bool = True
    SPARSE_RETRIEVAL_INDEX_DIR: str = "./data/sparse_indexes"
    # Comma-separated synonym pairs like: "kubernetes:k8s,postgresql:postgres"
    # Used only by deterministic provider (test scaffold).
    SPARSE_RETRIEVAL_SYNONYMS: str = ""
    # SPLADE provider (optional, opt-in): requires transformers + a local or HF model.
    SPARSE_SPLADE_MODEL_NAME: str = ""
    SPARSE_SPLADE_DEVICE: str = "cpu"  # cpu | cuda | auto
    SPARSE_SPLADE_BATCH_SIZE: int = 8
    SPARSE_SPLADE_MAX_LENGTH: int = 256
    SPARSE_SPLADE_TOP_K: int = 128
    SPARSE_SPLADE_MIN_WEIGHT: float = 0.0

    # Optional ColBERT-style retrieval (ANN) channel.
    #
    # Notes:
    # - Disabled by default (no behavior change).
    # - The deterministic provider is intended for tests/offline gating.
    # - The HF provider is opt-in and requires a local/HF model.
    COLBERT_RETRIEVAL_ENABLED: bool = False
    COLBERT_RETRIEVAL_PROVIDER: str = "deterministic"  # deterministic | hf
    COLBERT_RETRIEVAL_INDEX_PERSIST_ENABLED: bool = True
    COLBERT_RETRIEVAL_INDEX_DIR: str = "./data/colbert_indexes"
    COLBERT_RETRIEVAL_MODEL_NAME: str = ""
    COLBERT_RETRIEVAL_DEVICE: str = "cpu"  # cpu | cuda | auto
    COLBERT_RETRIEVAL_BATCH_SIZE: int = 16
    COLBERT_RETRIEVAL_MAX_LENGTH: int = 256
    # Safety cap: avoid building huge in-memory ANN matrices by accident.
    # 0 disables the cap (not recommended for production).
    COLBERT_RETRIEVAL_MAX_DOCS: int = 10_000
    # Used only by deterministic provider.
    COLBERT_RETRIEVAL_EMBED_DIM: int = 64
    # Optional visual-document retrieval scaffold (ColPali / ColQwen parser outputs).
    COLPALI_RETRIEVAL_ENABLED: bool = False
    # Optional ColBERT-style reranker provider.
    #
    # Notes:
    # - Disabled by default via provider=deterministic to preserve existing behavior.
    # - The HF provider is opt-in and requires a local/HF transformer model.
    COLBERT_RERANK_PROVIDER: str = "deterministic"  # deterministic | hf
    COLBERT_RERANK_MODEL_NAME: str = ""
    COLBERT_RERANK_DEVICE: str = "cpu"  # cpu | cuda | auto
    COLBERT_RERANK_BATCH_SIZE: int = 16
    COLBERT_RERANK_MAX_LENGTH: int = 256
    # Used only by deterministic provider.
    COLBERT_RERANK_EMBED_DIM: int = 64
    # Provider readiness guard for ColBERT reranker.
    # strict=false: fallback to deterministic provider on readiness/warmup failure.
    # strict=true: raise an error when requested provider is not ready.
    COLBERT_RERANK_HEALTHCHECK_STRICT: bool = False
    # Optional one-time warmup probe for model-backed providers.
    COLBERT_RERANK_WARMUP_ENABLED: bool = False
    # Optional: load fusion channel budget policy (generated from offline ablations).
    # When configured, orchestrator can auto-apply budgeted_rrf channel quotas.
    RAG_CHANNEL_BUDGET_POLICY_PATH: str = ""
    # Async API endpoints offload blocking retrieval work to threads; cap concurrent
    # heavy retrieval jobs so Milvus/embedding backends queue instead of saturating.
    # Set 0 to disable the process-local gate.
    RAG_RETRIEVAL_OFFLOAD_MAX_CONCURRENCY: int = 1
    # Maximum time to wait for a retrieval slot. Set 0 to wait indefinitely.
    RAG_RETRIEVAL_ADMISSION_TIMEOUT_SEC: float = 15.0
    # Optional best-effort cross-instance retrieval admission gate via Redis leases.
    RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_ENABLED: bool = False
    RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_MAX_CONCURRENCY: int = 0
    RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_PREFIX: str = "ragadm"
    # Bound retrieval input before embedding/query-rewrite work starts.
    RETRIEVAL_QUERY_MAX_CHARS: int = Field(default=8_000, ge=1, le=100_000)
    # Parallel searches across distinct embedding runtimes within one request.
    RAG_VECTOR_SHARD_MAX_CONCURRENCY: int = Field(default=4, ge=1, le=32)

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
    # Optional deterministic boost for KG-linked chunks after injection.
    RAG_KG_CHUNK_BOOST_ENABLED: bool = False
    RAG_KG_CHUNK_BOOST_WEIGHT: float = 0.15
    RAG_KG_CHUNK_BOOST_MAX_PROMOTED: int = 2
    # Optional: KG-derived query expansion (entity names -> extra retrieval queries).
    RAG_KG_QUERY_EXPANSION_ENABLED: bool = False
    RAG_KG_QUERY_EXPANSION_MAX_ENTITIES: int = 5
    RAG_KG_QUERY_EXPANSION_MAX_QUERIES: int = 5
    RAG_KG_QUERY_EXPANSION_MIN_ENTITY_WEIGHT: float = 0.15
    # Comma-separated entity types to exclude from KG query expansion (e.g. SkillNet taxonomy nodes).
    #
    # Note: query expansion is disabled by default, so this only matters when RAG_KG_QUERY_EXPANSION_ENABLED=true.
    RAG_KG_QUERY_EXPANSION_EXCLUDE_ENTITY_TYPES: str = "Skill,SkillTag,SkillCategory"
    # Optional: route retrieval defaults by question type when `retrieval_mode=auto`.
    RAG_RECALL_BUCKETS_ENABLED: bool = False
    # Optional: route retrieval presets/profiles by query intent (faq/howto/api/log).
    # Deterministic and PII-safe by design; disabled by default to avoid behavior surprises.
    RAG_INTENT_ROUTER_ENABLED: bool = False
    # Optional learned-assist intent router model (JSON artifact).
    # Deterministic fallback always remains active; learned hints are confidence-gated.
    RAG_INTENT_ROUTER_MODEL_PATH: str = ""
    RAG_INTENT_ROUTER_MODEL_CONFIDENCE_MIN: float = 0.7
    # Optional industry-specific glossary expansion. The platform only wires rulesets;
    # business terms remain in ruleset data, not in retrieval code.
    RAG_INDUSTRY_RULES_ENABLED: bool = False
    RAG_INDUSTRY_RULES_RULESETS: str = ""
    RAG_INDUSTRY_RULES_MAX_ALIASES: int = 16
    RAG_INDUSTRY_RULES_MAX_QUERY_CHARS: int = 2000
    # Optional: apply adaptive routing overrides from a versioned policy artifact.
    RAG_ADAPTIVE_ROUTER_ENABLED: bool = False
    RAG_ADAPTIVE_ROUTER_POLICY_PATH: str = "ci/adaptive_router_policy.v1.json"
    # Optional: include adjacent chunks around top hits to improve continuity (0 disables).
    RAG_CONTEXT_NEIGHBOR_WINDOW: int = 0
    # Max number of neighbor chunks to add in total (0 disables the cap).
    RAG_CONTEXT_NEIGHBOR_MAX_ADDED: int = 20
    # Optional: expand all chunks from short documents around a strong anchor hit.
    RAG_CONTEXT_SIBLING_EXPAND_ENABLED: bool = False
    # Route to sibling expansion when the active pipeline version has at most this many chunks.
    RAG_CONTEXT_SIBLING_SHORT_DOC_MAX_CHUNKS: int = 8
    # Max number of sibling chunks to add in total (0 disables the cap).
    RAG_CONTEXT_SIBLING_MAX_ADDED: int = 40
    RAG_RETRIEVAL_RAIL_ENABLED: bool = False
    RAG_RETRIEVAL_RAIL_MASK_PII: bool = False
    RAG_RETRIEVAL_RAIL_PII_MASK: str = "[REDACTED]"
    # Optional: reorder returned context chunks to improve continuity by stitching contiguous
    # (document_id, chunk_index) sequences together. Default off to preserve legacy ordering.
    RAG_CONTEXT_STITCHING_ENABLED: bool = False
    # Optional: parent-child auto merge (retrieve children, return/append parents).
    RAG_PARENT_CHILD_AUTO_MERGE_ENABLED: bool = False
    # - replace: collapse multiple children under the same parent into one parent chunk
    # - append: keep children and append the parent chunk (deduped)
    RAG_PARENT_CHILD_AUTO_MERGE_MODE: str = "replace"
    RAG_PARENT_CHILD_AUTO_MERGE_MIN_CHILDREN: int = 2
    RAG_PARENT_CHILD_AUTO_MERGE_MAX_PARENTS: int = 20
    WEB_SEARCH_ENABLED: bool = False
    WEB_SEARCH_TIMEOUT_SEC: float = 8.0
    WEB_SEARCH_MAX_RESULTS: int = 5
    TAVILY_API_KEY: str = ""
    SERPER_API_KEY: str = ""
    BRAVE_SEARCH_API_KEY: str = ""
    # Optional context compression before final prompt formatting.
    RAG_CONTEXT_COMPRESSION_ENABLED: bool = False
    # Optional lightweight generation-time reordering for better reading flow.
    RAG_CONTEXT_REORDER_ENABLED: bool = False
    # Optional lost-in-middle mitigation at context de-noise stage.
    # Disabled by default to preserve historical ordering.
    RAG_CONTEXT_LOST_IN_MIDDLE_REORDER_ENABLED: bool = False
    # Optional token-budget-aware trim during context de-noise.
    # Disabled by default; when enabled, keeps docs in order until the budget is exhausted.
    RAG_CONTEXT_TOKEN_BUDGET_TRIM_ENABLED: bool = False
    RAG_CONTEXT_DENOISE_MAX_TOTAL_TOKENS: int = 0
    # Optional query-aware LLM compression for final prompt context assembly.
    RAG_CONTEXT_LLM_COMPRESSION_ENABLED: bool = False
    RAG_CONTEXT_LLM_COMPRESSION_TARGET_RATIO: float = 0.5
    # Context Cliff warning threshold (2026 follow-up literature suggests quality drops sharply
    # once effective prompt context exceeds ~2500 tokens).
    RAG_CONTEXT_CLIFF_THRESHOLD_TOKENS: int = 2500
    # Context evidence extraction (query-focused sentence selection)
    RAG_CONTEXT_EVIDENCE_ENABLED: bool = False
    RAG_CONTEXT_EVIDENCE_MAX_SENTENCES_PER_CHUNK: int = 6
    RAG_CONTEXT_EVIDENCE_MIN_SENTENCE_CHARS: int = 10
    # Grounding guard: abstain when evidence is weak/empty.
    RAG_ABSTAIN_ENABLED: bool = False
    RAG_ABSTAIN_MIN_CITATIONS: int = 1
    # Optional live out-of-scope guard: only upgrades weak/no-evidence abstain paths when the
    # verifier says the question appears outside the current knowledge base.
    RAG_OUT_OF_SCOPE_LIVE_GUARD_ENABLED: bool = False
    RAG_OUT_OF_SCOPE_RULESET: str = ""
    RAG_OUT_OF_SCOPE_VECTOR_THRESHOLD: float = 0.35
    RAG_OUT_OF_SCOPE_HYDE_THRESHOLD: float = 0.4
    RAG_ABSTAIN_MIN_TOP_RELEVANCE_SCORE: float = 0.0  # 0 disables
    # Strict evidence contract: when enabled, citations without span offsets are discarded.
    RAG_EVIDENCE_REQUIRE_SPANS_ENABLED: bool = False
    # Evidence API (retrieval-only) iterative fallback:
    # When enabled, `POST /api/v1/rag/retrieve` may run one extra bounded retrieval pass
    # (e.g. switch retrieval_mode/profile) if the primary pass finds no usable evidence.
    EVIDENCE_ITERATIVE_RETRIEVE_ENABLED: bool = False
    EVIDENCE_ITERATIVE_RETRIEVE_MAX_PASSES: int = 2
    EVIDENCE_ITERATIVE_RETRIEVE_FALLBACK_PROFILE: str = "coverage80"  # recall20|recall50|coverage80
    EVIDENCE_ITERATIVE_RETRIEVE_FALLBACK_MODE: str = "keyword"  # hybrid|vector|keyword|mmr
    # Optional post-fusion rerank for retrieval-only Evidence API (runs after query expansion fusion).
    # Intended for deterministic/fast rerankers like LTR; do not enable heavyweight LLM rerank here.
    EVIDENCE_POST_RERANK_ENABLED: bool = False
    EVIDENCE_POST_RERANK_PROVIDER: str = "ltr"  # ltr | colbert | ...
    EVIDENCE_POST_RERANK_TOP_N: int = 30
    # Optional calibrated blending between retrieval fusion score and rerank score.
    # Final score = alpha * norm(rerank_score) + (1 - alpha) * norm(retrieval_score).
    EVIDENCE_POST_RERANK_SCORE_CALIBRATION_ENABLED: bool = False
    EVIDENCE_POST_RERANK_SCORE_CALIBRATION_ALPHA: float = 0.7
    # Optional: multi-stage post-rerank pipeline for Evidence API (budgeted by stage top_n).
    #
    # When enabled and EVIDENCE_POST_RERANK_PIPELINE is non-empty, the orchestrator will apply
    # the configured stages sequentially (stage2 runs on the prefix produced by stage1, etc.).
    #
    # Expected format (JSON):
    #   [{"provider":"ltr","top_n":50},{"provider":"colbert","top_n":20}]
    #
    # Notes:
    # - Keep providers deterministic/fast by default (LTR, ColBERT late-interaction).
    # - Do not embed model_path/api_key values here; use env vars for those.
    EVIDENCE_POST_RERANK_PIPELINE_ENABLED: bool = False
    EVIDENCE_POST_RERANK_PIPELINE: str = ""
    # Optional: short TTL in-memory rerank result cache for Evidence API post-rerank.
    # PII-safe by construction: cache key is a stable hash; values store only ids + numeric scores.
    EVIDENCE_POST_RERANK_CACHE_ENABLED: bool = False
    EVIDENCE_POST_RERANK_CACHE_BACKEND: str = "memory"  # memory | redis
    EVIDENCE_POST_RERANK_CACHE_MAX_ENTRIES: int = 1024
    EVIDENCE_POST_RERANK_CACHE_TTL_SEC: int = 30
    EVIDENCE_POST_RERANK_CACHE_PREFIX: str = "eprr"
    # Post-generation grounding guard: verify each claim against evidence and drop unsupported ones.
    # Disabled by default because it may delay streaming (answer is buffered for claim-check).
    RAG_CLAIM_CHECK_ENABLED: bool = False
    RAG_CLAIM_CHECK_MAX_CLAIMS: int = 24
    # Claim verifier mode for claim-check / claim-evidence mapping.
    # - token_overlap: historical deterministic overlap heuristic
    # - semantic_heuristic: overlap + contradiction checks (numeric / negation)
    # - strict: stronger overlap threshold + contradiction checks
    RAG_CLAIM_VERIFIER_MODE: str = "token_overlap"
    RAG_CLAIM_VERIFIER_ENABLE_CONTRADICTION_CHECK: bool = True
    # Optional NLI fallback verifier. Disabled by default to preserve deterministic local behavior.
    RAG_CLAIM_NLI_VERIFIER_ENABLED: bool = False
    RAG_CLAIM_NLI_VERIFIER_PROVIDER: str = "none"  # none | openai_compatible
    RAG_CLAIM_NLI_VERIFIER_MODEL: str = ""
    RAG_CLAIM_NLI_VERIFIER_API_BASE: str = ""
    RAG_CLAIM_NLI_VERIFIER_API_KEY: str = ""
    RAG_CLAIM_NLI_VERIFIER_TIMEOUT_SEC: int = 8
    # Strict grounding: treat missing evidence as non-existent. When enabled:
    # - Force abstain gate even if RAG_ABSTAIN_ENABLED=false
    # - Force claim-check (non-structured output) even if RAG_CLAIM_CHECK_ENABLED=false
    RAG_VISIBLE_EVIDENCE_ONLY_ENABLED: bool = False
    USE_LANGGRAPH_PIPELINE: bool = False
    RAG_GRAPH_MAX_RETRIES: int = 2
    RAG_GRAPH_CACHE_TTL_SEC: int = 0
    # LangGraph 1.0+ Functional API (preferred when available)
    LANGGRAPH_USE_FUNCTIONAL_API: bool = True
    LANGGRAPH_RECURSION_LIMIT: int = 25
    LANGGRAPH_USE_SUBGRAPHS: bool = False

    # Middleware System Configuration
    MIDDLEWARE_ENABLED: bool = True
    # Tool-call middleware (logging wrapper)
    TOOL_CALL_LOG_ENABLED: bool = False
    TOOL_CALL_LOG_INCLUDE_PREVIEW: bool = False
    TOOL_CALL_LOG_MAX_PREVIEW_CHARS: int = 500
    # Agent/workflow lifecycle logging
    AGENT_LOG_ENABLED: bool = False
    AGENT_LOG_INCLUDE_EXECUTION_PATH: bool = False
    AGENT_LOG_MAX_PREVIEW_CHARS: int = 500

    VECTOR_BACKEND: Literal["milvus", "memory", "faiss", "chroma", "qdrant", "pgvector"] = "milvus"
    # Optional JSON object keyed by region -> backend, e.g. {"cn-shanghai":"qdrant"}.
    VECTOR_REGION_BACKENDS: str = ""
    # Indexing toggles (to reduce duplicate pipelines when desired)
    CHUNK_VECTOR_ENABLED: bool = True
    # Index-consistency controls for manual chunk operations (create/patch/delete/disable/reembed).
    INDEX_CONSISTENCY_ENABLED: bool = False
    INDEX_CONSISTENCY_STRICTNESS: str = "off"  # off | warn | strict
    # Optional endpoint-specific strict toggle for patch-chunk workflow.
    INDEX_CONSISTENCY_PATCH_CHUNK_STRICT: bool = False
    # Emit bounded drift markers into chunk/document metadata when index operation partial failures occur.
    INDEX_CONSISTENCY_EMIT_DRIFT_MARKERS: bool = True
    # When true, allow per-dataset/document pipeline to prefix chunk content with structural context
    # (e.g. header_path) before embedding. Default is off to keep backward-compatible vectors.
    EMBEDDING_CONTEXT_PREFIX_ENABLED: bool = False
    # When true, inject a short document/section-level context prefix before embedding (vector-only).
    # Default off to keep backward-compatible vectors and ingestion costs stable.
    CONTEXTUAL_RETRIEVAL_ENABLED: bool = False
    # When true, contextual retrieval prefixes are only generated for chunks with an explicit
    # enrichment trigger (for example evidence_gap feedback or contextual_enrichment_required=true).
    CONTEXTUAL_RETRIEVAL_LAZY_MODE: bool = False
    # Best-effort deterministic contextual prefix knobs (no LLM calls by default).
    CONTEXTUAL_RETRIEVAL_PREFIX_MAX_CHARS: int = 240
    CONTEXTUAL_RETRIEVAL_KEYWORDS_TOP_K: int = 6
    CONTEXTUAL_RETRIEVAL_KEYWORDS_MAX_CHARS: int = 2000
    # Optional LLM enrichment mode for contextual retrieval prefixes (default off).
    # When enabled, the indexer first asks an LLM for a short summary prefix and falls
    # back to deterministic prefix generation on any error.
    CONTEXTUAL_RETRIEVAL_LLM_ENRICHMENT_ENABLED: bool = False
    CONTEXTUAL_RETRIEVAL_LLM_MAX_INPUT_CHARS: int = 2400
    CONTEXTUAL_RETRIEVAL_LLM_MAX_SUMMARY_CHARS: int = 180
    # Optional chart-to-data enrichment backend (disabled by default).
    CHART_TO_DATA_ENABLED: bool = False
    CHART_TO_DATA_API_URL: str = ""
    CHART_TO_DATA_TIMEOUT_SEC: float = 20.0
    CHART_TO_DATA_MAX_IMAGES: int = 8
    CHART_TO_DATA_MAX_IMAGE_BYTES: int = 5_000_000
    MATHPIX_APP_ID: str = ""
    MATHPIX_APP_KEY: str = ""
    EVENT_VECTOR_ENABLED: bool = True
    ENTITY_VECTOR_ENABLED: bool = True
    BM25_INDEX_ENABLED: bool = True
    # BM25 cold-start mitigation (build on first query when index missing).
    BM25_LAZY_BUILD_ENABLED: bool = True
    # When true and document_ids not provided, build BM25 for the whole tenant (can be expensive).
    BM25_LAZY_BUILD_FULL_TENANT: bool = False
    # Upper bound for lazy-built chunks (0 disables the cap).
    BM25_LAZY_BUILD_MAX_CHUNKS: int = 8000
    # Above this scope size, ingestion defers BM25 retriever rebuild to first query (0 disables the cap).
    BM25_EAGER_UPSERT_MAX_CHUNKS: int = 8000
    # Startup BM25 bootstrap (can be expensive; prefer lazy-build for large deployments).
    BM25_STARTUP_BUILD_ENABLED: bool = False
    # Upper bound for startup-built chunks across the whole instance (0 disables the cap).
    BM25_STARTUP_BUILD_MAX_CHUNKS: int = 8000
    # Hard cap for operator-triggered retrieval rebuilds across BM25/sparse/ColBERT.
    # 0 disables the cap (not recommended in production).
    RETRIEVAL_REBUILD_MAX_CHUNKS: int = 8000
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
    # When true, parser-emitted table segments (e.g. PDF table blocks) are treated as TAG sidecar only:
    # they are imported to table_store but excluded from vector/BM25 ingestion.
    TABLE_STORE_SIDECAR_EXCLUSIVE_ROUTING: bool = False
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
    # Multi-table TAG query controls.
    TABLE_QUERY_MAX_JOIN_TABLES: int = 4
    TABLE_QUERY_ALLOW_CROSS_JOIN: bool = False
    TABLE_TAG_PLAN_CANDIDATES_TOP_N: int = 3
    TABLE_TAG_AMBIGUITY_SCORE_GAP: float = 0.03
    TABLE_TAG_AMBIGUITY_STRICT_ENABLED: bool = True
    TABLE_TAG_PLANNER_MISMATCH_STRICT: bool = False
    # TAG planner cost model (join candidate ranking).
    TABLE_TAG_COST_MODEL_ENABLED: bool = True
    TABLE_TAG_COST_FANOUT_PENALTY_WEIGHT: float = 0.08
    TABLE_TAG_COST_SELECTIVITY_PENALTY_WEIGHT: float = 0.12
    TABLE_TAG_COST_FANOUT_RATIO_ALERT: float = 20.0
    TABLE_TAG_COST_SELECTIVITY_MIN: float = 0.2
    # Low-confidence join plan guard.
    TABLE_TAG_PLAN_LOW_CONFIDENCE_THRESHOLD: float = 0.55
    TABLE_TAG_PLAN_LOW_CONFIDENCE_STRICT_ENABLED: bool = False
    # NL->SQL / TAG answer generation (optional; requires LLM credentials).
    TABLE_NL2SQL_ENABLED: bool = False
    # Deterministic fallback for NL->SQL:
    # - if no LLM key is configured, or LLM generation fails, use bounded rule-based SQL synthesis.
    TABLE_NL2SQL_DETERMINISTIC_FALLBACK_ENABLED: bool = True
    # Force deterministic mode even when LLM is configured (debug/benchmark-friendly).
    TABLE_NL2SQL_DETERMINISTIC_ONLY: bool = False
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
    EVIDENCE_CAPSULE_STORE_DIR: str = "./runs/evidence_capsules"
    EVIDENCE_CAPSULE_PERSIST_ENABLED: bool = True
    EVIDENCE_CAPSULE_STRICT_VALIDATION_ENABLED: bool = True
    EVIDENCE_CAPSULE_VERIFY_HASH_ON_PERSIST: bool = True
    EVIDENCE_CAPSULE_ALLOW_OVERWRITE: bool = False
    EVIDENCE_CAPSULE_SIGNING_ENABLED: bool = False
    EVIDENCE_CAPSULE_SIGNING_SECRET: str = ""
    EVIDENCE_CAPSULE_SIGNING_KEY_ID: str = "default"
    EVIDENCE_CAPSULE_REQUIRE_SIGNATURE_ON_PERSIST: bool = False
    RETRIEVAL_MUST_RECALL_AUTO_EXPECTED_SOURCE_KEYS_ENABLED: bool = True
    RETRIEVAL_MUST_RECALL_AUTO_EXPECTED_SOURCE_KEYS_MAX: int = 12
    RETRIEVAL_MUST_RECALL_AUTO_INFER_FROM_METADATA_FILTER: bool = True
    RETRIEVAL_MUST_RECALL_AUTO_REQUIRED_ANCHOR_FIELDS_ENABLED: bool = True
    # When false (default), omit raw question/query/snippets from metrics logs to reduce PII leakage.
    METRICS_LOG_INCLUDE_TEXT: bool = False
    QUERYSET_HEALTH_HISTORY_PATH: str = "./runs/queryset_health/history.jsonl"

    # Online evaluation (production sampling; PII-minimal by construction).
    ONLINE_EVAL_ENABLED: bool = False
    ONLINE_EVAL_SAMPLE_RATE: float = 0.05
    ONLINE_EVAL_QUEUE_MAX: int = 500
    ONLINE_EVAL_ALERT_MIN_SAMPLES_PER_BUCKET: int = 10
    ONLINE_EVAL_ALERT_FAITHFULNESS_DET_MIN: float = 0.6
    ONLINE_EVAL_ALERT_CHUNK_UTILIZATION_MIN: float = 0.12

    # Offline RAG evaluation quality gate (CI-oriented, default-off).
    RAG_EVAL_GATE_ENABLED: bool = False
    RAG_EVAL_GATE_SUMMARY_PATH: str = _DEFAULT_RAG_EVAL_SUMMARY_PATH
    RAG_EVAL_GATE_FAITHFULNESS_MIN: float = 0.80
    RAG_EVAL_GATE_ANSWER_RELEVANCY_MIN: float = 0.75
    RAG_EVAL_GATE_CONTEXT_PRECISION_MIN: float = 0.70
    # 0 = auto. Some OpenAI-compatible providers (for example DeepSeek) reject
    # chat completions with n > 1, while RAGAS defaults response relevancy to 3.
    RAGAS_RESPONSE_RELEVANCY_STRICTNESS: int = 0
    RAGAS_RUN_TIMEOUT_SEC: int = 60
    RAGAS_RUN_MAX_RETRIES: int = 1
    RAGAS_RUN_MAX_WAIT_SEC: int = 2
    RAGAS_RUN_MAX_WORKERS: int = 4
    RAGAS_CONVERSATION_WALL_TIMEOUT_SEC: int = 90
    RAGAS_CONVERSATION_DETERMINISTIC_MODE_ENABLED: bool = False

    # Observability: simple anomaly detection (rolling baseline; PII-safe).
    # Used by query analytics to flag spikes in zero-hit/error rates.
    OBS_ANOMALY_ENABLED: bool = True
    OBS_ANOMALY_BASELINE_WINDOW_MINUTES: int = 60
    OBS_ANOMALY_CURRENT_WINDOW_MINUTES: int = 5
    OBS_ANOMALY_MIN_REQUESTS_PER_BUCKET: int = 5
    OBS_ANOMALY_MIN_BASELINE_BUCKETS: int = 10

    OBS_ANOMALY_ZERO_HIT_RATE_ABS_THRESHOLD: float = 0.6
    OBS_ANOMALY_ZERO_HIT_RATE_RATIO_THRESHOLD: float = 2.0
    OBS_ANOMALY_ZERO_HIT_RATE_ZSCORE_THRESHOLD: float = 3.0

    OBS_ANOMALY_ERROR_RATE_ABS_THRESHOLD: float = 0.05
    OBS_ANOMALY_ERROR_RATE_RATIO_THRESHOLD: float = 3.0
    OBS_ANOMALY_ERROR_RATE_ZSCORE_THRESHOLD: float = 3.0
    ENABLE_QUERY_REWRITE: bool = False
    # Chat endpoint default retrieval profile (applied only when caller omits retrieval knobs).
    # Empty string disables profile coercion.
    CHAT_DEFAULT_RETRIEVAL_PROFILE: str = "hybrid_ce"
    # Optional strict grounding default when request relies on CHAT_DEFAULT_RETRIEVAL_PROFILE.
    CHAT_DEFAULT_VISIBLE_EVIDENCE_ONLY: bool = False
    # Versioned query rewrite strategy id (used for evaluation gating / rollback).
    # The strategy identifier is intentionally low-cardinality and should not contain raw prompt text.
    QUERY_REWRITE_STRATEGY: str = "kb_followup.v1"
    QUERY_REWRITE_TEMPERATURE: float = 0.2
    QUERY_REWRITE_MAX_CHARS: int = 120
    ENABLE_MULTI_QUERY: bool = False
    MULTI_QUERY_COUNT: int = 3
    # Safety cap for LLM-generated multi-query fanout (prevents accidental 100+ queries).
    # Set this to 40+ only when you have explicit retrieval budgets/parallelism configured.
    MULTI_QUERY_COUNT_CAP: int = 8
    MULTI_QUERY_TEMPERATURE: float = 0.2
    MULTI_QUERY_MAX_CHARS: int = 200
    # Multi-query diversification: cap how many final top_k citations can come from `mq` query variants.
    # Safe defaults: disabled (feature can be rolled back by flipping the flag).
    MULTI_QUERY_DIVERSIFY_ENABLED: bool = False
    MULTI_QUERY_DIVERSIFY_BUDGET: int = 0
    ENABLE_HYDE: bool = False
    HYDE_TEMPERATURE: float = 0.2
    HYDE_MAX_CHARS: int = 200
    HYDE_OUTPUT_MAX_CHARS: int = 800
    ENABLE_STEP_BACK_QUERY: bool = False
    STEP_BACK_TEMPERATURE: float = 0.2
    STEP_BACK_MAX_CHARS: int = 200
    STEP_BACK_OUTPUT_MAX_CHARS: int = 300
    ENABLE_QUERY_DECOMPOSITION: bool = False
    RAG_DECOMPOSITION_CHAIN_ENABLED: bool = False
    QUERY_DECOMPOSITION_MAX_SUBQUESTIONS: int = 3
    QUERY_DECOMPOSITION_TEMPERATURE: float = 0.2
    QUERY_DECOMPOSITION_MIN_CHARS: int = 60
    QUERY_DECOMPOSITION_MAX_CHARS: int = 400
    # Temporal intelligence (optional): detect "latest/current/as-of" intent and apply a small
    # recency-aware boost to retrieved documents (re-ranking only; no filtering).
    RAG_TEMPORAL_INTENT_ENABLED: bool = False
    RAG_TEMPORAL_INTENT_RECENCY_BOOST_ENABLED: bool = True
    RAG_TEMPORAL_INTENT_MAX_DOCS: int = 200
    # Online faithfulness proxy (claim support ratio against retrieved evidence text).
    FAITHFULNESS_SCORE_ENABLED: bool = True
    FAITHFULNESS_SCORE_MAX_CLAIMS: int = 24
    FAITHFULNESS_SCORE_MAX_EVIDENCE_CHARS: int = 24_000
    RAG_FOLLOWUP_SUGGESTIONS_ENABLED: bool = False
    SENTENCE_CITATIONS_INLINE_ENABLED: bool = False
    # appendix (default): add a compact "Sentence Citations" section at the end of the answer
    # inline: rewrite the answer into one-claim-per-line with inline citation brackets
    SENTENCE_CITATIONS_INLINE_STYLE: str = "appendix"  # appendix | inline
    SENTENCE_CITATIONS_INLINE_MAX_ITEMS: int = 8
    SENTENCE_CITATIONS_INLINE_MAX_EVIDENCE_PER_CLAIM: int = 2
    # Ragviz similarity matrices are returned in full JSON; keep both the axis
    # length and the total pair count bounded to avoid large dense responses.
    RAGVIZ_SIMILARITY_MAX_AXIS_ITEMS: int = 500
    RAGVIZ_SIMILARITY_MAX_PAIRS: int = 200_000
    # Corrective RAG (CRAG-like) loop: retry retrieval with a recall-first profile when
    # evidence is weak (abstain) or answer faithfulness is low. Default off.
    RAG_CORRECTIVE_ENABLED: bool = False
    RAG_CORRECTIVE_MAX_ATTEMPTS: int = 2
    RAG_CORRECTIVE_MIN_FAITHFULNESS_SCORE: float = 0.75
    # Retrieval profile label, not a credential.
    RAG_CORRECTIVE_SECOND_PASS_PROFILE: str = "recall50"  # noqa: S105
    RAG_CORRECTIVE_SECOND_PASS_ENABLE_MULTI_QUERY: bool = True
    RAG_CORRECTIVE_SECOND_PASS_MULTI_QUERY_COUNT: int = 5
    RAG_AGENTIC_MODE_ENABLED: bool = False
    RAG_AGENTIC_COMPLEXITY_THRESHOLD: float = 250.0
    RAG_AGENTIC_MAX_RETRIEVE_ROUNDS: int = 3
    RAG_AGENTIC_TOOLS_ENABLED: bool = False
    RAG_CRAG_STREAMING_ENABLED: bool = False
    RAG_CRAG_STREAMING_MAX_RESULTS: int = 5
    RAG_CRAG_STREAMING_MIN_CITATIONS: int = 1
    RAG_CRAG_STREAMING_MIN_TOP_SCORE: float = 0.35
    RAG_SELF_RAG_ENABLED: bool = False
    RAG_CRITIC_ENABLED: bool = False
    RAG_MULTI_AGENT_ENABLED: bool = False
    RAG_MULTI_AGENT_MAX_SUB_AGENTS: int = 4
    RAG_AGENTIC_REFLECT_TOP_CITATIONS_MIN: int = 1
    RAG_AGENTIC_REFLECT_TOP_SCORE_MIN: float = 0.35
    RAG_AGENTIC_REFLECT_MODEL: str = ""
    RAG_STREAM_STATUS_EVENTS_ENABLED: bool = False
    RAG_STREAM_RETRIEVAL_PROGRESS_ENABLED: bool = False
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
    # Comma-separated import prefixes allowed for legacy runtime Python plugin refs.
    # Blank by default so business logic lives in registered plugin packages.
    PYTHON_PIPELINE_PLUGIN_ALLOW_PREFIXES: str = ""
    # Comma-separated external plugin directories scanned at runtime. New
    # published+tested plugin packages can be added without restarting the API.
    PYTHON_PIPELINE_PLUGIN_DIRS: str = "plugins/pipelines"
    # Require the local runner report to match the current plugin package hash
    # before a registered plugin can execute.
    PYTHON_PIPELINE_PLUGIN_REQUIRE_TEST_REPORT: bool = True
    # Debug-only escape hatch for generating plugin Golden drafts from chunks
    # that were not produced by the selected plugin. Keep disabled in normal
    # operation so plugin Golden cases stay tied to plugin-owned chunk outputs.
    PYTHON_PIPELINE_PLUGIN_ALLOW_UNMARKED_GOLDEN_CHUNKS: bool = False
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
    GOVERNANCE_PII_MODE: Literal["mask", "token"] = "mask"
    GOVERNANCE_PII_MASK: str = "[REDACTED]"
    # Compliance gate: if >=0, quarantine/drop a document when total PII hits exceed this threshold (sum across kinds).
    GOVERNANCE_PII_MAX_HITS: int = -1
    GOVERNANCE_LLM_AUTO_TAGGING_ENABLED: bool = False
    GOVERNANCE_LLM_AUTO_TAGGING_MAX_CHARS: int = 3000
    GOVERNANCE_LLM_AUTO_TAGGING_MAX_ITEMS: int = 16
    INGEST_PRE_POC_SCANNER_ENABLED: bool = False
    INGEST_PRE_POC_QUALITY_GATE_MODE: str = "warn"  # off | warn | strict
    INGEST_PRE_POC_TEXT_SAMPLE_BYTES: int = 200_000
    INGEST_PRE_POC_PII_MAX_HITS: int = -1
    INGEST_PRE_POC_SECRETS_MAX_HITS: int = 0
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
    PARSE_FALLBACK_MIN_PARSE_SCORE: float = 0.55
    PARSE_FALLBACK_MAX_RETRIES: int = 1
    # Cross-page structure restoration.
    CROSS_PAGE_MERGE_ENABLED: bool = False
    CROSS_PAGE_MERGE_MAX_PAGE_GAP: int = 1
    # Reading-order scoring is lightweight and only affects parse-quality metadata/selection.
    READING_ORDER_ENABLED: bool = True
    # Optional VLM correction for low-quality PDF pages.
    VLM_CORRECTION_ENABLED: bool = False
    VLM_CORRECTION_MIN_TABLE_SCORE: float = 0.6
    VLM_CORRECTION_MAX_PAGES: int = 2
    # Persist parsed markdown (raw+clean) for audit/debug.
    PERSIST_PARSED_CONTENT: bool = False
    PERSIST_PARSED_CONTENT_MAX_CHARS: int = 200_000
    # Cross-document near-duplicate chunk drop (SimHash; best-effort).
    NEAR_DEDUP_ENABLED: bool = False
    NEAR_DEDUP_HAMMING_THRESHOLD: int = 3
    NEAR_DEDUP_MAX_BUCKET_SIZE: int = 256
    # Reranker (optional: use LLM to rerank candidates for better quality).
    ENABLE_RERANKER: bool = False
    RERANKER_PROVIDER: str = "llm"  # llm | pc | ltr | colbert | cross_encoder | long_context | mmr | none
    # Local Learning-to-Rank model path (xgboost JSON/UBJ).
    # Used when reranker_provider="ltr" and by Evidence API post-rerank when enabled.
    LTR_MODEL_PATH: str = ""
    # Optional: sidecar manifest path for LTR model artifact (JSON).
    # When provided (or when a sidecar `<model>.manifest.json` is present), the LTR reranker
    # validates feature schema + model hash for safer production deployment.
    LTR_MODEL_MANIFEST_PATH: str = ""
    # LTR feature spec version (must match the model artifact's feature count/order).
    # - v1: base retrieval scores + retrieval_role one-hot
    # - v2: v1 + KG ranking features (kg_pagerank/path/etc)
    LTR_FEATURE_SPEC_VERSION: int = 1
    RERANKER_MODEL: str | None = None
    # Optional rerank budget/search profile. Example: "sweet_spot" -> keep coarse retrieval at SEARCH_K=20.
    RERANK_PROFILE: str = ""
    # Optional: use a dedicated API key/base for API-style rerankers (openai/dashscope),
    # falls back to LLM_API_KEY/LLM_API_BASE when empty.
    RERANKER_API_KEY: str = ""
    RERANKER_API_BASE: str = ""
    RERANKER_TOP_N: int = 20  # Rerank candidate count (higher = slower).
    RERANKER_MAX_CHARS: int = 800  # Max chars per candidate.
    RERANKER_TEMPERATURE: float = 0.0
    # Local model-backed rerankers (for example cross-encoder) should not block
    # user traffic on first-use remote downloads. Allow a short bounded wait, then
    # degrade to base retrieval order while the background load can continue.
    RERANKER_LOCAL_LOAD_TIMEOUT_SEC: float = 2.0
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
    RERANKER_LLM_WEIGHT: float = 0.7
    RERANKER_LLM_FALLBACK_SCORE: float = 0.5
    RERANKER_LLM_WEIGHT_BY_TENANT: str = ""
    RERANKER_LLM_WEIGHT_BY_QUERY_TYPE: str = ""
    RERANK_CONDITIONAL_ENABLED: bool = False
    RERANK_SKIP_THRESHOLD: float = 0.85
    RERANK_SKIP_GAP: float = 0.15
    DEFAULT_PARSER_BACKEND: str = "auto"
    DEFAULT_CHUNK_STRATEGY: str = "langchain_recursive"
    DEEPDOC_ENABLED: bool = False
    # DeepDoc PDF seal/stamp recognition enrichment (best-effort, recognition-only ONNX).
    # Disabled by default; when enabled, DeepDoc PDF parsing may emit extra "seal" documents.
    SEAL_RECOGNITION_ENABLED: bool = False
    SEAL_RECOGNITION_MODEL_DIR: str = ""
    SEAL_RECOGNITION_THRESHOLD: float = 0.88
    SEAL_RECOGNITION_PDF_DPI: int = 144
    # 0 = scan all pages.
    SEAL_RECOGNITION_MAX_PAGES: int = 0
    # Max candidate seal regions recognized per rendered page.
    SEAL_RECOGNITION_MAX_REGIONS_PER_PAGE: int = 3
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
    # OpenAI-compatible vision model id, e.g. "gpt-5.4-mini".
    VISION_LLM_MODEL: str = Field(
        default="gpt-5.4-mini",
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
    # Vision-native RAG (VLM-as-Reader): use a VLM to read retrieved image evidence
    # and inject extracted text into the RAG context.
    #
    # Notes:
    # - Requires VISION_LLM_ENABLED=true and valid VISION_LLM_* config.
    # - Disabled by default to keep out-of-the-box deployments lightweight.
    VISION_RAG_READER_ENABLED: bool = Field(
        default=False,
        validation_alias=AliasChoices("MIMIRQ_VISION_RAG_READER_ENABLED", "VISION_RAG_READER_ENABLED"),
    )
    VISION_RAG_READER_MAX_IMAGES: int = Field(
        default=2,
        validation_alias=AliasChoices("MIMIRQ_VISION_RAG_READER_MAX_IMAGES", "VISION_RAG_READER_MAX_IMAGES"),
    )
    VISION_RAG_READER_MAX_IMAGE_BYTES: int = Field(
        default=3_000_000,
        validation_alias=AliasChoices("MIMIRQ_VISION_RAG_READER_MAX_IMAGE_BYTES", "VISION_RAG_READER_MAX_IMAGE_BYTES"),
    )
    VISION_RAG_READER_MAX_OUTPUT_CHARS: int = Field(
        default=1500,
        validation_alias=AliasChoices("MIMIRQ_VISION_RAG_READER_MAX_OUTPUT_CHARS", "VISION_RAG_READER_MAX_OUTPUT_CHARS"),
    )
    # Optional: generate the final answer directly with the Vision LLM when image evidence is present.
    # This is closer to "Vision-native RAG" but can be more expensive than VLM-as-Reader.
    VISION_RAG_GENERATION_ENABLED: bool = Field(
        default=False,
        validation_alias=AliasChoices("MIMIRQ_VISION_RAG_GENERATION_ENABLED", "VISION_RAG_GENERATION_ENABLED"),
    )
    VISION_RAG_GENERATION_MAX_IMAGES: int = Field(
        default=2,
        validation_alias=AliasChoices("MIMIRQ_VISION_RAG_GENERATION_MAX_IMAGES", "VISION_RAG_GENERATION_MAX_IMAGES"),
    )
    VISION_RAG_GENERATION_MAX_IMAGE_BYTES: int = Field(
        default=3_000_000,
        validation_alias=AliasChoices(
            "MIMIRQ_VISION_RAG_GENERATION_MAX_IMAGE_BYTES",
            "VISION_RAG_GENERATION_MAX_IMAGE_BYTES",
        ),
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
    # Preferred production mode: external MagicPDF HTTP sidecar.
    MAGIC_PDF_API_URL: str = ""
    MAGIC_PDF_REQUEST_TIMEOUT_SEC: int = 600
    MAGIC_PDF_MAX_CONCURRENT_JOBS: int = 1
    # Local CLI fallback (kept for development/debug deployments).
    MAGIC_PDF_CLI: str = "magic-pdf"
    MAGIC_PDF_METHOD: str = "auto"  # auto | ocr | txt
    MAGIC_PDF_LANG: str = ""  # optional PaddleOCR language code, e.g. "ch"
    MAGIC_PDF_DEBUG: bool = False
    MAGIC_PDF_TIMEOUT_SEC: int = 600
    MAGIC_PDF_MODELS_DIR: str = ""
    MAGIC_PDF_DEVICE_MODE: str = ""  # service default cuda; local CLI fallback default cpu
    MAGIC_PDF_FORMULA_ENABLED: bool = False
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
    # KG extraction backend routing.
    # - llm: existing extraction path (default)
    # - gliner: lightweight entity-first extraction (optional dependency)
    # - hybrid: GLiNER pre-extract + LLM fallback
    KG_EXTRACTION_BACKEND: str = "llm"
    # Optional: override the default backend for very large documents when no
    # explicit extraction_backend is requested.
    KG_EXTRACT_LONG_DOC_BACKEND: str = "heuristic"
    KG_EXTRACT_LONG_DOC_MIN_CHUNKS: int = 300
    # Safe default-off switch for GLiNER/hybrid routing.
    KG_GLINER_ENABLED: bool = False
    KG_GLINER_MODEL_NAME: str = "urchade/gliner_multi_pii-v1"
    KG_GLINER_DEVICE: str = "cpu"
    KG_GLINER_ENTITY_THRESHOLD: float = 0.5
    KG_GLINER_DEFAULT_ENTITY_TYPES: str = "person,organization,location,event,date,concept"
    KG_HYBRID_LLM_THRESHOLD: float = 0.7
    KG_HYBRID_REFINE_RELATIONS: bool = False
    # Evidence-first skill extraction (optional; improves precision for Skill/SOP nodes + taxonomy edges).
    # When enabled, the extractor will only persist Skill nodes/edges that can be grounded to a chunk-local
    # evidence quote/span (verbatim substring).
    KG_SKILL_EVIDENCE_REQUIRED: bool = True
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
    # Keep KG embedding batches conservative because OpenAI-compatible
    # providers such as DashScope text-embedding-v4 reject larger batches even
    # though document chunk indexing can often use a higher global embedding
    # batch size.
    KG_EXTRACT_EMBED_BATCH_SIZE: int = 8
    KG_EXTRACT_MAX_EVENTS_PER_CHUNK: int = 6
    KG_EXTRACT_MAX_ENTITIES_PER_EVENT: int = 30
    # Document-level guardrail for long-document KG extraction (0 disables).
    # When enabled, only a bounded subset of chunks is extracted per document.
    KG_EXTRACT_MAX_CHUNKS_PER_DOCUMENT: int = 120
    # Strategy when KG_EXTRACT_MAX_CHUNKS_PER_DOCUMENT is enabled:
    # - head: keep the first N chunks
    # - uniform: deterministically sample chunks across the whole document span
    KG_EXTRACT_MAX_CHUNKS_PER_DOCUMENT_STRATEGY: str = "uniform"
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
    # Default false because backend/model/extraction-option changes are not yet part of the skip fingerprint.
    KG_EXTRACT_SKIP_UNCHANGED_CHUNKS: bool = False
    # Evidence-first extraction (optional; improves KG precision and debuggability).
    # When enabled, the extractor will attempt to ground each entity/relation to a chunk-local evidence quote/span.
    #
    # NOTE: Default is True because ungrounded entities/relations degrade relation-driven recall expansion and
    # downstream RAG quality more than a smaller-but-correct graph.
    KG_EXTRACT_EVIDENCE_REQUIRED: bool = True
    # Multi-pass verification (optional; higher quality, higher cost).
    KG_EXTRACT_ENTITY_VERIFY_ENABLED: bool = False
    KG_EXTRACT_RELATION_VERIFY_ENABLED: bool = False
    # Graph co-occurrence computation guardrail: cap entity count per event when building co-occurrence edges.
    KG_ENTITY_LINK_MAX_ENTITIES_PER_EVENT: int = 60
    # KG API guardrails.
    KG_API_MAX_DOCUMENT_IDS: int = 500
    KG_API_METRICS_ENABLED: bool = False
    # KG search guardrails/observability.
    # Dataset-scoped KG vector recall enumerates up to this many ACL-readable
    # documents for exact Milvus pushdown; larger datasets fall back to one
    # tenant-scoped ANN query plus SQL ACL filtering.
    KG_SEARCH_DATASET_SCOPE_MAX_ENUM_DOCS: int = 2000
    # - Max clue items returned by KG search (0 disables).
    KG_SEARCH_MAX_CLUES: int = 2000
    # - Upper bound for event candidates passed into rerank (0 disables).
    KG_SEARCH_MAX_RERANK_CANDIDATES: int = 500
    # - Vector recall (Milvus + embedding model) for KG search.
    #
    # When disabled, KG search falls back to:
    # - alias-matched entity keys (lexical, deterministic), and
    # - event recall via event<->entity links + optional relation expansion.
    #
    # This is useful for CI/offline scenarios where Milvus and/or embedding models
    # are intentionally unavailable.
    KG_SEARCH_VECTOR_RECALL_ENABLED: bool = True
    # Graph embeddings (node2vec-like) for entity recall (Wave16).
    #
    # When enabled and vector recall is unavailable/disabled, KG search can use an offline,
    # deterministic structural signal to pull in additional entity candidates from the
    # local KG (events + optional relations).
    KG_SEARCH_GRAPH_EMBEDDINGS_ENABLED: bool = False
    KG_SEARCH_GRAPH_EMBEDDINGS_DIM: int = 64
    KG_SEARCH_GRAPH_EMBEDDINGS_NUM_WALKS: int = 8
    KG_SEARCH_GRAPH_EMBEDDINGS_WALK_LENGTH: int = 20
    KG_SEARCH_GRAPH_EMBEDDINGS_WINDOW_SIZE: int = 5
    KG_SEARCH_GRAPH_EMBEDDINGS_SEED: int = 42
    # Upper bounds for building the local subgraph (keeps CI/unit tests fast).
    KG_SEARCH_GRAPH_EMBEDDINGS_MAX_EVENTS: int = 200
    KG_SEARCH_GRAPH_EMBEDDINGS_MAX_ENTITIES: int = 400
    KG_SEARCH_GRAPH_EMBEDDINGS_MAX_RELATIONS: int = 1500
    KG_SEARCH_GRAPH_EMBEDDINGS_TOP_K: int = 20
    KG_SEARCH_GRAPH_EMBEDDINGS_MIN_SIMILARITY: float = 0.35
    # - Disable clue generation entirely (saves CPU/memory; response still contains `clues: []`).
    KG_SEARCH_CLUES_ENABLED: bool = True
    # - Truncate clue node content/description (0 disables).
    KG_SEARCH_NODE_TEXT_MAX_CHARS: int = 400
    # - Global KG search timeout (seconds, 0 disables).
    KG_SEARCH_TIMEOUT_SEC: float = 0.0
    # - Skip KG expand when recall alone consumes this budget (seconds, 0 disables).
    KG_SEARCH_EXPAND_BUDGET_SEC: float = 0.0
    # - Per-query KG latency SLO target for stats/metrics only (milliseconds, 0 disables).
    KG_SEARCH_LATENCY_SLO_MS: int = 0
    KG_SEARCH_METRICS_ENABLED: bool = False
    # KG search cache (best-effort, per-process). Safe by default because keys bind
    # tenant/account/scope/query/config and dataset/document corpus fingerprints.
    KG_SEARCH_CACHE_ENABLED: bool = True
    KG_SEARCH_CACHE_TTL_SEC: int = 30
    KG_SEARCH_CACHE_MAX_ENTRIES: int = 256
    KG_SEARCH_MULTI_DATASET_MAX_CONCURRENCY: int = 4
    KG_SEARCH_MULTI_DATASET_MAX_EVENTS: int = 80
    KG_SEARCH_MULTI_DATASET_MAX_ENTITIES: int = 80
    # KG quality diagnostics (best-effort; aggregate-only).
    KG_QUALITY_LOW_CONFIDENCE_THRESHOLD: float = 0.30
    # Upper bound for relation edges loaded into component analysis (0 disables component analysis).
    KG_QUALITY_RELATION_EDGES_LIMIT: int = 50_000
    # KG query-mode routing (no GraphRAG dependency): auto -> local/global/drift.
    KG_SEARCH_QUERY_MODE_DEFAULT: str = "auto"  # auto | local | global | drift
    KG_SEARCH_QUERY_MODE_CLASSIFIER_ENABLED: bool = True
    KG_SEARCH_QUERY_MODE_LOCAL_MAX_EVENTS: int = 40
    KG_SEARCH_QUERY_MODE_GLOBAL_MIN_EVENTS: int = 120
    KG_SEARCH_QUERY_MODE_LOW_CONFIDENCE_GLOBAL_MAX_EVENTS: int = 40
    KG_SEARCH_QUERY_MODE_DRIFT_MIN_EVENTS: int = 140
    KG_SEARCH_QUERY_MODE_LOCAL_ENTITY_WEIGHT_BONUS: float = 0.05
    KG_SEARCH_EXACT_PHRASE_RERANK_BOOST: float = 0.25
    # KG serving-layer budget: full KG remains stored, but normal online RAG only
    # sends a high-value subset into expand/rerank.
    KG_SEARCH_SERVING_LAYER_ENABLED: bool = True
    KG_SEARCH_SERVING_MAX_EVENTS_PER_CHUNK: int = 2
    KG_SEARCH_SERVING_MAX_EVENTS_PER_DOCUMENT: int = 80
    KG_SEARCH_SERVING_MIN_SCORE: float = 0.0
    KG_SEARCH_SERVING_CANDIDATE_MULTIPLIER: int = 3
    # KG global-search (GraphRAG-like) community detection + community/global summaries.
    #
    # Important:
    # - This runs on the *recall subgraph* (events/entities recalled for the query), not the whole dataset.
    # - Default OFF to preserve backward-compatible KG behavior and latency.
    KG_COMMUNITY_ENABLED: bool = False
    # Only run community detection when the query-mode classifier saw explicit global/overview intent.
    # This avoids adding latency to normal factoid queries that still route to "global" by fallback.
    KG_COMMUNITY_REQUIRE_GLOBAL_PATTERN: bool = True
    KG_COMMUNITY_MAX_EVENTS: int = 200
    KG_COMMUNITY_MAX_ENTITIES_PER_EVENT: int = 12
    KG_COMMUNITY_MIN_EDGE_WEIGHT: float = 2.0
    KG_COMMUNITY_LABEL_PROPAGATION_ITERS: int = 25
    KG_COMMUNITY_MAX_COMMUNITIES: int = 12
    KG_COMMUNITY_MAX_ENTITIES_PER_COMMUNITY: int = 12
    KG_COMMUNITY_MAX_EVENTS_PER_COMMUNITY: int = 6
    KG_COMMUNITY_GLOBAL_SUMMARY_MAX_CHARS: int = 3200
    # Query-aware LLM community summaries (LazyGraphRAG style).
    # Disabled by default to preserve latency/cost characteristics.
    KG_LAZY_COMMUNITY_SUMMARY_ENABLED: bool = False
    KG_LAZY_COMMUNITY_SUMMARY_TOP_N: int = 3
    KG_LAZY_COMMUNITY_SUMMARY_CACHE_TTL_SEC: int = 86400
    KG_LAZY_COMMUNITY_SUMMARY_CACHE_MAX_ENTRIES: int = 1024
    KG_LAZY_COMMUNITY_SUMMARY_MAX_TOKENS: int = 300
    # Entity resolution (Wave15): merge/split actions may optionally update KG entity vectors.
    #
    # Why off by default:
    # - Unit tests should not require Milvus.
    # - Some deployments may prefer running vector maintenance as an async job.
    KG_ENTITY_RESOLUTION_UPDATE_VECTORS_ENABLED: bool = False
    # Relation-driven recall expansion: seed entities -> relation neighbors -> events.
    # Disabled by default to avoid behavioral changes in KG search without opt-in.
    KG_SEARCH_RELATION_EXPANSION_ENABLED: bool = False
    KG_SEARCH_RELATION_MIN_CONFIDENCE: float = 0.5
    # Coarse confidence buckets for provenance/debugging.
    # - low:  conf < LOW_MAX
    # - mid:  LOW_MAX <= conf < MID_MAX
    # - high: conf >= MID_MAX
    KG_SEARCH_RELATION_CONF_BUCKET_LOW_MAX: float = 0.4
    KG_SEARCH_RELATION_CONF_BUCKET_MID_MAX: float = 0.7
    KG_SEARCH_RELATION_MAX_EDGES: int = 500
    KG_SEARCH_RELATION_MAX_NEIGHBORS: int = 20
    KG_SEARCH_RELATION_NEIGHBOR_WEIGHT_FACTOR: float = 0.7
    # Evidence weighting: downweight relation edges whose evidence was derived from a surface mention
    # rather than matched from an explicit evidence_quote substring.
    # - 1.0 means no penalty, lower values reduce drift from low-signal edges (recommended <= 0.8).
    KG_SEARCH_RELATION_MENTION_EVIDENCE_MULTIPLIER: float = 0.7
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
    # For dbrows/table-sidecar assets, prefer deterministic SQL synthesis (stronger reproducibility).
    CHAT_TAG_DBROWS_SQL_FIRST_ENABLED: bool = True
    # When must-recall is requested, enforce source-key matching in TAG selection.
    CHAT_TAG_MUST_RECALL_SOURCE_KEY_MATCH: bool = True
    LONG_TERM_MEMORY_ENABLED: bool = False
    LONG_TERM_MEMORY_TOP_K: int = 3
    LONG_TERM_MEMORY_MIN_LEN: int = 20
    LONG_TERM_MEMORY_MAX_MESSAGES: int = 200
    MEMORY_STORE_TYPE: str = "memory"  # memory | sqlite
    MEMORY_SQLITE_PATH: str = "./data/memory.db"
    # Structured memory (entity memory + lightweight fact memory), stored per assistant turn in
    # Message.message_metadata to avoid schema migrations for a first iteration.
    STRUCTURED_MEMORY_ENABLED: bool = False
    STRUCTURED_MEMORY_LOOKBACK_MESSAGES: int = 80
    STRUCTURED_MEMORY_MAX_ENTITIES: int = 20
    STRUCTURED_MEMORY_MAX_FACTS: int = 8
    STRUCTURED_MEMORY_MAX_CONTEXT_CHARS: int = 1200
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
    # Deprecated compatibility setting. When JWT_TENANT_CLAIM is configured,
    # tenant resolution is always bound to the verified claim.
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

    # Tenant QPS quota (aggregate across callers; best-effort).
    #
    # This is independent of rate-limit middleware, which keys by user/ip. The quota
    # is keyed by tenant_id (+ scope key) and is useful as a guardrail to protect
    # shared retrieval backends in multi-tenant deployments.
    TENANT_QPS_QUOTA_ENABLED: bool = False
    TENANT_QPS_QUOTA_MODE: str = "block"  # block | warn
    TENANT_QPS_QUOTA_REQUESTS_PER_SECOND: float = 0.0
    TENANT_QPS_QUOTA_BURST_SIZE: int = 0
    TENANT_QPS_QUOTA_REDIS_PREFIX: str = "tq"
    TENANT_QPS_QUOTA_REDIS_KEY_TTL_SEC: int = 600

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
        # Note: unit tests and generated OpenAPI artifacts should not be influenced by
        # a developer's local `.env`, so disable dotenv loading for those paths.
        env_file=None if _should_disable_repo_env_file() else str(_env_file),
        case_sensitive=True,
        extra="ignore",
    )

    @model_validator(mode="after")
    def validate_settings(self) -> "Settings":
        """Validate configuration settings at startup."""
        _settings_validation.validate_uvicorn_workers_and_distributed_limits(self)
        _settings_validation.validate_saml_replay(self)
        _settings_validation.validate_trusted_hosts(self)
        _settings_validation.validate_production_api_surface(self)
        _settings_validation.validate_cors(self)
        _settings_validation.validate_auth_mode_and_jwt_claims(self)
        _settings_validation.validate_scim(self)
        _settings_validation.validate_dify_resolution_mode(self)
        _settings_validation.validate_rag_runtime_warmup(self)
        _settings_validation.validate_dify_external_knowledge(self)
        _settings_validation.validate_secret_key_and_jwt_key_source(self)
        _settings_validation.validate_minio(self)
        _settings_validation.validate_object_storage(self)
        _settings_validation.validate_chunk_llm_and_retrieval(self)
        _settings_validation.validate_embedding_and_migration(self)
        _settings_validation.validate_chat_and_retrieval_caches(self)
        _settings_validation.validate_kg_search(self)
        _settings_validation.validate_vector_write_and_table_catalog(self)
        _settings_validation.validate_evidence_governance_and_quotas(self)
        _settings_validation.validate_workflow_and_retrieval_profiles(self)
        _settings_validation.validate_claim_verifier(self)
        _settings_validation.validate_retrieval_fallback_modes(self)
        _settings_validation.validate_parse_quality(self)
        _settings_validation.validate_sparse_and_colbert_providers(self)
        _settings_validation.validate_checkpoint_memory_reranker(self)
        _settings_validation.validate_rag_eval_gate(self)
        return self


settings = Settings()
