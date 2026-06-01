"""
FastAPI main entry point.
"""
import logging
import os
import time
import warnings
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

# Quiet noisy third-party deprecation warnings during local development.
warnings.filterwarnings(
    "ignore",
    message=r"pkg_resources is deprecated as an API\..*",
    category=UserWarning,
)
warnings.filterwarnings(
    "ignore",
    message=r"The pynvml package is deprecated\..*",
    category=FutureWarning,
)
warnings.filterwarnings(
    "ignore",
    message=r"SECRET_KEY is not configured\..*",
    category=UserWarning,
)
warnings.filterwarnings(
    "ignore",
    message=r"Using default MinIO credentials\. Change in production!",
    category=UserWarning,
)

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

# Ensure audit log models are registered for metadata creation
import app.models.audit_log  # noqa: F401

# Ensure chunk preset models are registered for metadata creation
import app.models.chunk_preset  # noqa: F401

# Ensure connector models are registered for metadata creation
import app.models.connector  # noqa: F401
import app.models.connector_config  # noqa: F401

# Ensure conversation summary models are registered for metadata creation
import app.models.conversation_summary  # noqa: F401

# Ensure dataset category models are registered for metadata creation
import app.models.dataset_category  # noqa: F401

# Ensure DB catalog models are registered for metadata creation
import app.models.db_catalog  # noqa: F401

# Ensure evaluation models are registered for metadata creation
import app.models.evaluation  # noqa: F401

# Ensure evidence suite models are registered for metadata creation
import app.models.evidence  # noqa: F401

# Ensure feedback models are registered for metadata creation
import app.models.feedback  # noqa: F401

# Ensure index drift models are registered for metadata creation
import app.models.index_drift_item  # noqa: F401

# Ensure ingestion run manifest models are registered for metadata creation
import app.models.ingestion_run  # noqa: F401

# Ensure RAG config template models are registered for metadata creation
import app.models.rag_config_template  # noqa: F401

# Ensure user models are registered for metadata creation
import app.models.user  # noqa: F401

# Ensure KG models are registered for metadata creation
import app.rag.kg.models  # noqa: F401
from app.api.dependencies.logging import bind_route_context
from app.api.middleware.process_time import ProcessTimeMiddleware
from app.api.middleware.request_id import RequestIDMiddleware
from app.api.v1 import router as api_v1_router
from app.core.config import settings
from app.core.database import Base, SessionLocal, engine
from app.core.env import is_production_env
from app.core.exceptions import register_exception_handlers
from app.core.health_checks import check_database, check_minio, check_redis, check_vector
from app.core.http_client import close_http_client_pool
from app.core.logging_config import configure_logging
from app.core.migrations import apply_runtime_migrations
from app.core.otel import init_otel, instrument_fastapi, instrument_httpx, shutdown_otel
from app.core.sentry import init_sentry
from app.core.utils import parse_csv
from app.models.document import Document as DBDocument
from app.models.document import DocumentChunk
from app.tasks.queue import close_queue, init_queue, is_queue_initialized

logger = logging.getLogger("mimirq")
_OPENAPI_EXPORT_MODE = str(os.getenv("MIMIRQ_OPENAPI_EXPORT", "") or "").strip().lower() in {"1", "true", "yes", "y", "on"}
_HEALTH_CACHE_TTL_SEC = max(0.0, float(getattr(settings, "HEALTH_CACHE_TTL_SEC", 2.0) or 2.0))
_health_cache: dict[str, object] = {"ts": 0.0, "payload": None, "key": None}
_DEV_LOCAL_CORS_PORTS = {3000, 3001, 3100}
_DOCS_PATH = "/docs"


def _health_cache_key() -> tuple[object, ...]:
    # Include endpoints so the cache doesn't hide hot-reloaded settings changes.
    return (
        (getattr(settings, "VECTOR_BACKEND", "milvus") or "milvus").lower(),
        bool(getattr(settings, "TASK_QUEUE_ENABLED", False)),
        bool(getattr(settings, "EMBEDDING_CACHE_ENABLED", False)),
        bool(getattr(settings, "MINIO_ENABLED", False)),
        str(getattr(settings, "REDIS_URL", "") or ""),
        str(getattr(settings, "MILVUS_HOST", "") or ""),
        int(getattr(settings, "MILVUS_PORT", 0) or 0),
        str(getattr(settings, "MINIO_ENDPOINT", "") or ""),
        str(getattr(settings, "UPLOAD_DIR", "") or ""),
    )


def _get_cached_health_payload(cache_key: tuple[object, ...]) -> dict | None:  # type: ignore[type-arg]
    now = time.monotonic()
    payload = _health_cache.get("payload")
    if (
        payload is not None
        and _health_cache.get("key") == cache_key
        and (now - float(_health_cache.get("ts") or 0.0)) < _HEALTH_CACHE_TTL_SEC
    ):
        return payload  # type: ignore[return-value]
    return None

def _expand_dev_cors_origins(origins: list[str]) -> list[str]:
    """
    Dev-friendly CORS: add localhost/IP aliases for local FE ports.

    This prevents common UX issues when the frontend is opened via:
    - http://0.0.0.0:3000 (Next dev prints this by default)
    - http://127.0.0.1:3000
    - http://127.0.0.1:3100 (Playwright local prod-server checks)
    while backend env only allows http://localhost:3000.
    """
    if not origins:
        return origins
    if "*" in origins:
        return origins

    expanded: set[str] = set()
    for raw in origins:
        origin = (raw or "").strip().rstrip("/")
        if origin:
            expanded.add(origin)

    local_schemes: set[str] = set()
    local_ports: set[int] = set()
    for origin in tuple(expanded):
        parsed = urlparse(origin)
        scheme = (parsed.scheme or "").lower().strip()
        host = (parsed.hostname or "").lower().strip()
        try:
            port = parsed.port
        except ValueError:
            continue
        if scheme not in {"http", "https"}:
            continue
        if host not in {"localhost", "127.0.0.1", "0.0.0.0"}:
            continue
        local_schemes.add(scheme)
        if port is not None:
            local_ports.add(port)

    candidate_local_ports = sorted(local_ports | _DEV_LOCAL_CORS_PORTS)

    # Iterate over a snapshot; we may add derived origins while expanding.
    for origin in tuple(expanded):
        parsed = urlparse(origin)
        scheme = (parsed.scheme or "").lower().strip()
        host = (parsed.hostname or "").lower().strip()
        try:
            port = parsed.port
        except ValueError:
            continue
        if scheme not in {"http", "https"}:
            continue
        if host not in {"localhost", "127.0.0.1", "0.0.0.0"}:
            continue

        for alt in {"localhost", "127.0.0.1", "0.0.0.0"}:
            if alt == host:
                continue
            expanded.add(f"{scheme}://{alt}:{port}" if port is not None else f"{scheme}://{alt}")

    for scheme in sorted(local_schemes):
        for port in candidate_local_ports:
            for host in ("localhost", "127.0.0.1", "0.0.0.0"):
                expanded.add(f"{scheme}://{host}:{port}")

    return sorted(expanded)


def _build_cors_expose_headers(raw_headers: str) -> list[str]:
    """
    Keep app-critical response headers readable even when local `.env` overrides
    the configurable CORS expose list.
    """
    required_headers = [
        "X-Request-ID",
        "X-Conversation-ID",
        "X-Assistant-Message-ID",
    ]
    seen: set[str] = set()
    headers: list[str] = []
    for header in [*parse_csv(raw_headers), *required_headers]:
        key = header.lower()
        if key in seen:
            continue
        seen.add(key)
        headers.append(header)
    return headers

# Optional JSON logging (LOG_FORMAT=json).
configure_logging(
    log_level=str(getattr(settings, "LOG_LEVEL", "INFO") or "INFO"),
    log_format=str(getattr(settings, "LOG_FORMAT", "plain") or "plain"),
    include_trace_context=bool(getattr(settings, "OTEL_ENABLED", False)),
)

# Optional error monitoring (SENTRY_DSN).
if not _OPENAPI_EXPORT_MODE:
    init_sentry()

# Optional OpenTelemetry tracing (OTEL_ENABLED).
if not _OPENAPI_EXPORT_MODE and init_otel():
    instrument_httpx()


# Lifespan management
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Operations on app startup and shutdown."""
    # Startup: create database tables.
    logger.info("Starting MimirQ backend...")

    # Ensure local directories exist (uploads/logs/vector persistence).
    for dir_path in [
        settings.UPLOAD_DIR,
        getattr(settings, "TABLE_STORE_DIR", None),
        settings.FAISS_STORE_PATH if getattr(settings, "VECTOR_BACKEND", "milvus") == "faiss" else None,
        settings.CHROMA_PERSIST_PATH if getattr(settings, "VECTOR_BACKEND", "milvus") == "chroma" else None,
    ]:
        if not dir_path:
            continue
        try:
            Path(str(dir_path)).mkdir(parents=True, exist_ok=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to ensure directory %s: %s", str(dir_path), str(exc)[:200])

    if bool(getattr(settings, "ENABLE_METRICS_LOG", False)):
        try:
            Path(str(getattr(settings, "METRICS_LOG_PATH", "./logs/rag_metrics.jsonl"))).parent.mkdir(
                parents=True, exist_ok=True
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to ensure metrics log dir: %s", str(exc)[:200])

    if bool(getattr(settings, "MINIO_ENABLED", False)):
        try:
            Path(str(getattr(settings, "MINIO_METRICS_LOG_PATH", "./logs/minio_metrics.jsonl"))).parent.mkdir(
                parents=True, exist_ok=True
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to ensure MinIO metrics log dir: %s", str(exc)[:200])

    if bool(getattr(settings, "LANGSMITH_TRACING_ENABLED", False)):
        try:
            from app.rag.tracing import setup_tracing

            setup_tracing()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to setup LangSmith tracing: %s", str(exc)[:200])
    runtime_migrations_enabled = bool(getattr(settings, "DB_RUNTIME_MIGRATIONS_ENABLED", True))
    create_all_enabled = bool(getattr(settings, "DB_CREATE_ALL_ON_STARTUP", True))

    # Best-effort runtime migrations (legacy compatibility).
    #
    # These are idempotent `ALTER TABLE ... IF NOT EXISTS` guardrails that keep older
    # DBs bootable. For production deployments, prefer deterministic Alembic migrations
    # executed out-of-band (e.g. `make db-upgrade`).
    if runtime_migrations_enabled:
        apply_runtime_migrations(engine)

    if create_all_enabled:
        logger.info("Creating database tables (create_all)...")
        Base.metadata.create_all(bind=engine)
        if runtime_migrations_enabled:
            apply_runtime_migrations(engine)
        logger.info("Database initialized")
    else:
        logger.info("DB auto-create disabled; expecting schema to be managed externally (e.g. Alembic)")

    # Initialize task queue (optional).
    try:
        await init_queue()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to init task queue: %s", str(exc)[:200])

    # Task queue observability poller (optional; keeps Prometheus gauges fresh).
    if bool(getattr(settings, "PROMETHEUS_ENABLED", False)):
        try:
            from app.services.task_queue_observability_service import start_task_queue_observability_poller

            start_task_queue_observability_poller()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to start task queue observability poller: %s", str(exc)[:200])

    # Initialize BM25 index (optional; large deployments can rely on lazy-build).
    if not bool(getattr(settings, "BM25_INDEX_ENABLED", True)):
        logger.info("BM25 indexing disabled; skipping startup build")
    elif not bool(getattr(settings, "BM25_STARTUP_BUILD_ENABLED", False)):
        logger.info("BM25 startup build disabled (BM25_STARTUP_BUILD_ENABLED=false)")
    else:
        logger.info("Initializing BM25 index (startup build)...")
        from app.rag.retriever import hybrid_retriever

        db = SessionLocal()
        try:
            from sqlalchemy import func

            max_chunks = int(getattr(settings, "BM25_STARTUP_BUILD_MAX_CHUNKS", 0) or 0)
            total_chunks = (
                db.query(func.count(DocumentChunk.id))
                .join(DBDocument)
                .filter(DBDocument.status == "completed")
                .filter(DBDocument.publication_status == "published")
                .scalar()
            ) or 0

            if max_chunks > 0 and int(total_chunks) > max_chunks:
                logger.warning(
                    "Skipping BM25 startup build: %s chunks exceeds cap %s; "
                    "enable BM25_LAZY_BUILD_ENABLED for on-demand builds",
                    int(total_chunks),
                    max_chunks,
                )
            else:
                # Stream tenant ids and build per-tenant BM25 to avoid a single `.all()` over huge corpora.
                tenant_ids: list = []
                tenant_q = (
                    db.query(DocumentChunk.tenant_id)
                    .join(DBDocument)
                    .filter(DBDocument.status == "completed")
                    .filter(DBDocument.publication_status == "published")
                    .distinct()
                    .execution_options(stream_results=True)
                    .enable_eagerloads(False)
                )
                for row in tenant_q.yield_per(2000):
                    if row and row[0]:
                        tenant_ids.append(row[0])

                if not tenant_ids:
                    logger.warning("No documents found, BM25 index will be built on first upload")
                else:
                    built_total = 0
                    for tid in tenant_ids:
                        built_total += hybrid_retriever.build_bm25_index_from_db(db, tenant_id=tid, batch_size=2000)
                    logger.info(
                        "BM25 index loaded with %s chunks across %s tenants",
                        built_total,
                        len(tenant_ids),
                    )
        finally:
            db.close()

    yield

    # Shutdown cleanup.
    logger.info("Shutting down MimirQ backend...")
    
    # Close HTTP client pool.
    await close_http_client_pool()
    logger.info("HTTP client pool closed")

    # Stop task queue observability poller (optional).
    if bool(getattr(settings, "PROMETHEUS_ENABLED", False)):
        try:
            from app.services.task_queue_observability_service import stop_task_queue_observability_poller

            await stop_task_queue_observability_poller()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to stop task queue observability poller: %s", str(exc)[:200])

    # Close task queue connection (optional).
    await close_queue()

    # Dispose DB engine pool (best-effort; avoids lingering connections in some runtimes).
    try:
        engine.dispose()
        logger.info("Database engine disposed")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to dispose database engine: %s", str(exc)[:200])

    shutdown_otel()


# Create FastAPI app
app = FastAPI(
    title="MimirQ - Knowledge Base RAG System",
    description="Knowledge Base Management and RAG Conversation System",
    version="1.0.0",
    docs_url=_DOCS_PATH if bool(getattr(settings, "API_DOCS_ENABLED", True)) else None,
    redoc_url="/redoc" if bool(getattr(settings, "API_DOCS_ENABLED", True)) else None,
    openapi_url=(
        "/openapi.json"
        if (bool(getattr(settings, "API_OPENAPI_ENABLED", True)) or _OPENAPI_EXPORT_MODE)
        else None
    ),
    lifespan=lifespan
)

# =============================================================================
# OpenAPI post-processing (contract stability)
# =============================================================================

def _patch_openapi_additional_properties(spec: dict) -> None:  # noqa: ANN401
    """
    Ensure dict-like/Any-object schemas remain useful in generated TS types.

    FastAPI/Pydantic often emit `{ "type": "object" }` for `dict[str, Any]`-ish
    payloads. `openapi-typescript` interprets that shape as `Record<string, never>`,
    which is effectively unusable and causes spurious type drift in the web app.

    We treat "object with no declared properties and no explicit additionalProperties"
    as "arbitrary object" and set `additionalProperties: true`.
    """

    def walk(node: object) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                props = node.get("properties")
                if (not props) and ("additionalProperties" not in node):
                    node["additionalProperties"] = True
            for v in node.values():
                walk(v)
            return
        if isinstance(node, list):
            for v in node:
                walk(v)

    walk(spec)


def custom_openapi():  # noqa: ANN201
    if app.openapi_schema:
        return app.openapi_schema

    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    _patch_openapi_additional_properties(schema)
    app.openapi_schema = schema
    return app.openapi_schema


# Override FastAPI's OpenAPI generator (used both for runtime docs and export tooling).
app.openapi = custom_openapi  # type: ignore[assignment]

# Optional FastAPI instrumentation (OTEL_ENABLED).
instrument_fastapi(app)

# Trusted hosts (Host header hardening; production-only by default).
if is_production_env() and bool(getattr(settings, "TRUSTED_HOSTS_ENABLED", True)):
    from starlette.middleware.trustedhost import TrustedHostMiddleware

    allowed_hosts = parse_csv(str(getattr(settings, "ALLOWED_HOSTS", "") or ""))
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

# Request body size limit (DoS guardrail).
from app.api.middleware.body_size_limit import BodySizeLimitMiddleware

app.add_middleware(
    BodySizeLimitMiddleware,
    max_body_bytes=int(getattr(settings, "REQUEST_MAX_BODY_BYTES", 0) or 0),
)

# Rate limiting middleware
if settings.RATE_LIMIT_ENABLED:
    from app.api.middleware.rate_limit import RateLimitMiddleware

    app.add_middleware(
        RateLimitMiddleware,
        requests_per_second=settings.RATE_LIMIT_REQUESTS_PER_SECOND,
        burst_size=settings.RATE_LIMIT_BURST_SIZE,
        chat_requests_per_second=settings.RATE_LIMIT_CHAT_RPS,
        chat_burst_size=settings.RATE_LIMIT_CHAT_BURST,
        chat_prefixes=["/api/v1/chat/stream"],
    )

# Response compression (safe for SSE; event-stream is excluded by Starlette).
if bool(getattr(settings, "GZIP_ENABLED", True)):
    from starlette.middleware.gzip import GZipMiddleware

    app.add_middleware(
        GZipMiddleware,
        minimum_size=int(getattr(settings, "GZIP_MIN_SIZE", 1000)),
        compresslevel=int(getattr(settings, "GZIP_COMPRESS_LEVEL", 5)),
    )

# Prometheus metrics (optional).
if bool(getattr(settings, "PROMETHEUS_ENABLED", False)):
    from app.api.v1.metrics import router as metrics_router
    from app.core.metrics import PrometheusMiddleware

    app.include_router(metrics_router, tags=["Metrics"])
    app.add_middleware(
        PrometheusMiddleware,
        exclude_paths=[
            "/metrics",
            "/health",
            "/api/v1/health",
            "/api/v1/health/ready",
            _DOCS_PATH,
            "/openapi.json",
            "/redoc",
        ],
    )

# Process-time header (useful for debugging and quick perf checks).
app.add_middleware(
    ProcessTimeMiddleware,
    server_timing_enabled=bool(getattr(settings, "SERVER_TIMING_ENABLED", True)),
)

# Security headers (lightweight hardening).
if bool(getattr(settings, "SECURITY_HEADERS_ENABLED", True)):
    from app.api.middleware.security_headers import SecurityHeadersMiddleware

    hsts_value = ""
    if bool(getattr(settings, "SECURITY_HEADERS_HSTS_ENABLED", False)):
        max_age = int(getattr(settings, "SECURITY_HEADERS_HSTS_MAX_AGE_SEC", 31536000) or 31536000)
        max_age = max(0, max_age)
        parts = [f"max-age={max_age}"]
        if bool(getattr(settings, "SECURITY_HEADERS_HSTS_INCLUDE_SUBDOMAINS", True)):
            parts.append("includeSubDomains")
        if bool(getattr(settings, "SECURITY_HEADERS_HSTS_PRELOAD", False)):
            parts.append("preload")
        hsts_value = "; ".join(parts)

    app.add_middleware(
        SecurityHeadersMiddleware,
        x_content_type_options=str(getattr(settings, "SECURITY_HEADERS_X_CONTENT_TYPE_OPTIONS", "nosniff") or "nosniff"),
        x_frame_options=str(getattr(settings, "SECURITY_HEADERS_X_FRAME_OPTIONS", "DENY") or "DENY"),
        referrer_policy=str(
            getattr(settings, "SECURITY_HEADERS_REFERRER_POLICY", "strict-origin-when-cross-origin")
            or "strict-origin-when-cross-origin"
        ),
        strict_transport_security=hsts_value,
        permissions_policy=str(getattr(settings, "SECURITY_HEADERS_PERMISSIONS_POLICY", "") or ""),
        cross_origin_opener_policy=str(getattr(settings, "SECURITY_HEADERS_CROSS_ORIGIN_OPENER_POLICY", "") or ""),
        cross_origin_resource_policy=str(getattr(settings, "SECURITY_HEADERS_CROSS_ORIGIN_RESOURCE_POLICY", "") or ""),
    )

# Response header sanitization (reduce fingerprinting).
from app.api.middleware.response_header_sanitizer import ResponseHeaderSanitizerMiddleware

app.add_middleware(ResponseHeaderSanitizerMiddleware)

# Request-id middleware (outermost; propagates X-Request-ID for tracing).
app.add_middleware(RequestIDMiddleware)

# CORS must be the final middleware added so it wraps rate-limit and security
# error responses instead of letting browsers surface them as opaque CORS failures.
cors_origins = parse_csv(settings.CORS_ORIGINS)
if not is_production_env():
    cors_origins = _expand_dev_cors_origins(cors_origins)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=bool(getattr(settings, "CORS_ALLOW_CREDENTIALS", True)),
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=_build_cors_expose_headers(getattr(settings, "CORS_EXPOSE_HEADERS", "X-Request-ID")),
)

# Register routes
app.include_router(api_v1_router, prefix="/api/v1", dependencies=[Depends(bind_route_context)])

# Register exception handlers
register_exception_handlers(app)


@app.get("/")
async def root():
    """Root path."""
    return {
        "message": "Welcome to MimirQ API",
        "version": "1.0.0",
        "docs": _DOCS_PATH
    }


@app.get("/health")
async def health_check():
    """Health check."""
    cache_key = _health_cache_key()
    cached = _get_cached_health_payload(cache_key)
    if cached is not None:
        return cached

    db_status, _db_ok = check_database(SessionLocal)

    # Vector (Milvus / local persistence backends)
    vector_backend = (getattr(settings, "VECTOR_BACKEND", "milvus") or "milvus").lower()
    milvus_get_count = None
    if vector_backend == "milvus":
        try:
            from app.storage.vector.milvus import milvus_store

            milvus_get_count = milvus_store.get_collection_count
        except ImportError:
            milvus_get_count = None

    vector_status, milvus_status, _vector_ok = check_vector(
        settings,
        mode="health",
        milvus_get_collection_count=milvus_get_count,
    )

    # MinIO (optional)
    minio_health_check = None
    if bool(getattr(settings, "MINIO_ENABLED", False)):
        try:
            from app.storage.object.minio import minio_service

            minio_health_check = minio_service.health_check
        except ImportError:
            minio_health_check = None

    minio_status, _minio_ok = check_minio(
        settings,
        mode="health",
        minio_health_check=minio_health_check,
    )

    uploads_status = {"status": "unknown", "path": settings.UPLOAD_DIR}
    try:
        upload_dir = Path(settings.UPLOAD_DIR)
        upload_dir.mkdir(parents=True, exist_ok=True)
        uploads_status["status"] = "ready"
    except Exception as exc:  # noqa: BLE001
        uploads_status["status"] = "unavailable"
        uploads_status["error"] = str(exc)[:200]

    redis_status, _redis_ok, _reset_redis_client = check_redis(settings)

    task_queue_status = {
        "enabled": bool(getattr(settings, "TASK_QUEUE_ENABLED", False)),
        "queue": getattr(settings, "TASK_QUEUE_NAME", "mimirq"),
        "status": "disabled",
    }
    if task_queue_status["enabled"]:
        task_queue_status["initialized"] = is_queue_initialized()
        task_queue_status["status"] = "connected" if task_queue_status["initialized"] else "not_initialized"

    payload = {
        "status": "healthy",
        "database": db_status,
        "vector": vector_status,
        "milvus": milvus_status,
        "redis": redis_status,
        "task_queue": task_queue_status,
        "uploads": uploads_status,
        "minio": minio_status,
    }
    _health_cache["ts"] = time.monotonic()
    _health_cache["payload"] = payload
    _health_cache["key"] = cache_key
    return payload


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=True,
        server_header=False,
    )
