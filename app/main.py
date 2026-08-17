"""
FastAPI main entry point.
"""

import logging
import os
import time
import warnings
from contextlib import asynccontextmanager
from ipaddress import IPv4Address
from pathlib import Path
from urllib.parse import urlparse

from app.core.local_proxy import ensure_local_no_proxy

ensure_local_no_proxy()

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
from sqlalchemy.orm import Session

import app.models._all  # noqa: F401
from app import __version__
from app.api.dependencies.logging import bind_route_context
from app.api.middleware.process_time import ProcessTimeMiddleware
from app.api.middleware.request_id import RequestIDMiddleware
from app.api.v1 import router as api_v1_router
from app.core.config import settings
from app.core.database import Base, SessionLocal, engine
from app.core.env import is_production_env
from app.core.exceptions import register_exception_handlers
from app.core.http_client import close_http_client_pool
from app.core.logging_config import configure_logging
from app.core.migrations import apply_runtime_migrations
from app.core.otel import init_otel, instrument_fastapi, instrument_httpx, shutdown_otel
from app.core.sentry import init_sentry
from app.core.utils import parse_csv
from app.models.document import Document as DBDocument
from app.models.document import DocumentChunk
from app.services.initial_admin_service import (
    InitialAdminBootstrapError,
    bootstrap_initial_admin_if_configured,
)
from app.tasks.queue import close_queue, init_queue

logger = logging.getLogger("mimirq")
_OPENAPI_EXPORT_MODE = str(os.getenv("MIMIRQ_OPENAPI_EXPORT", "") or "").strip().lower() in {
    "1",
    "true",
    "yes",
    "y",
    "on",
}
_DEV_LOCAL_CORS_PORTS = {3000, 3001, 3100}
_ALL_INTERFACES_HOST = str(IPv4Address(0))
_DOCS_PATH = "/docs"
_LOCAL_DEV_HOSTS = {"localhost", "127.0.0.1", _ALL_INTERFACES_HOST}
_LOCAL_DEV_SCHEMES = {"http", "https"}


def _normalize_dev_origin(raw: str) -> str | None:
    origin = (raw or "").strip().rstrip("/")
    return origin or None


def _parse_local_dev_origin(origin: str) -> tuple[str, str, int | None] | None:
    parsed = urlparse(origin)
    scheme = (parsed.scheme or "").lower().strip()
    host = (parsed.hostname or "").lower().strip()
    try:
        port = parsed.port
    except ValueError:
        return None
    if scheme not in _LOCAL_DEV_SCHEMES or host not in _LOCAL_DEV_HOSTS:
        return None
    return scheme, host, port


def _expand_origin_aliases(expanded: set[str], origin: str) -> tuple[str, int | None] | None:
    parsed_origin = _parse_local_dev_origin(origin)
    if parsed_origin is None:
        return None
    scheme, host, port = parsed_origin
    for alt in _LOCAL_DEV_HOSTS:
        if alt == host:
            continue
        expanded.add(f"{scheme}://{alt}:{port}" if port is not None else f"{scheme}://{alt}")
    return scheme, port


def _expand_port_matrix(expanded: set[str], schemes: set[str], ports: set[int]) -> None:
    for scheme in sorted(schemes):
        for port in sorted(ports | _DEV_LOCAL_CORS_PORTS):
            for host in sorted(_LOCAL_DEV_HOSTS):
                expanded.add(f"{scheme}://{host}:{port}")


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

    expanded = {origin for raw in origins if (origin := _normalize_dev_origin(raw))}

    local_schemes: set[str] = set()
    local_ports: set[int] = set()
    for origin in tuple(expanded):
        parsed_origin = _expand_origin_aliases(expanded, origin)
        if parsed_origin is None:
            continue
        scheme, port = parsed_origin
        local_schemes.add(scheme)
        if port is not None:
            local_ports.add(port)

    _expand_port_matrix(expanded, local_schemes, local_ports)

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


def _warmup_retrieval_tokenizer() -> None:
    if not bool(getattr(settings, "BM25_INDEX_ENABLED", True)):
        return

    from app.rag.preprocessing.tokenization import warmup_bm25_tokenizer

    started_at = time.perf_counter()
    warmup_bm25_tokenizer()
    logger.info("BM25 tokenizer initialized in %.3fs", time.perf_counter() - started_at)


def start_rag_runtime_warmup():
    from app.services.rag_runtime_warmup import start_rag_runtime_warmup as _impl

    return _impl()


def _start_runtime_warmup():
    if not bool(getattr(settings, "RAG_RUNTIME_WARMUP_ENABLED", False)):
        return None
    return start_rag_runtime_warmup()


def _iter_startup_directories() -> list[object]:
    vector_backend = getattr(settings, "VECTOR_BACKEND", "milvus")
    return [
        settings.UPLOAD_DIR,
        getattr(settings, "TABLE_STORE_DIR", None),
        settings.FAISS_STORE_PATH if vector_backend == "faiss" else None,
        settings.CHROMA_PERSIST_PATH if vector_backend == "chroma" else None,
    ]


def _ensure_directory(path_value: object, *, warning_prefix: str) -> None:
    if not path_value:
        return
    try:
        Path(str(path_value)).mkdir(parents=True, exist_ok=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("%s %s: %s", warning_prefix, str(path_value), str(exc)[:200])


def _ensure_startup_directories() -> None:
    for dir_path in _iter_startup_directories():
        _ensure_directory(dir_path, warning_prefix="Failed to ensure directory")


def _ensure_parent_directory(path_value: object, *, warning_message: str) -> None:
    try:
        Path(str(path_value)).parent.mkdir(parents=True, exist_ok=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("%s: %s", warning_message, str(exc)[:200])


def _ensure_optional_log_directories() -> None:
    if bool(getattr(settings, "ENABLE_METRICS_LOG", False)):
        _ensure_parent_directory(
            getattr(settings, "METRICS_LOG_PATH", "./logs/rag_metrics.jsonl"),
            warning_message="Failed to ensure metrics log dir",
        )
    if bool(getattr(settings, "MINIO_ENABLED", False)):
        _ensure_parent_directory(
            getattr(settings, "MINIO_METRICS_LOG_PATH", "./logs/minio_metrics.jsonl"),
            warning_message="Failed to ensure MinIO metrics log dir",
        )


def _setup_langsmith_tracing() -> None:
    if not bool(getattr(settings, "LANGSMITH_TRACING_ENABLED", False)):
        return
    try:
        from app.rag.tracing import setup_tracing

        setup_tracing()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to setup LangSmith tracing: %s", str(exc)[:200])


def _initialize_database_for_startup() -> None:
    runtime_migrations_enabled = bool(getattr(settings, "DB_RUNTIME_MIGRATIONS_ENABLED", True))
    create_all_enabled = bool(getattr(settings, "DB_CREATE_ALL_ON_STARTUP", True))

    if runtime_migrations_enabled:
        apply_runtime_migrations(engine)

    if not create_all_enabled:
        logger.info("DB auto-create disabled; expecting schema to be managed externally (e.g. Alembic)")
        return

    logger.info("Creating database tables (create_all)...")
    Base.metadata.create_all(bind=engine)
    if runtime_migrations_enabled:
        apply_runtime_migrations(engine)
    logger.info("Database initialized")


def _bootstrap_initial_admin() -> None:
    try:
        db = SessionLocal()
        try:
            if bootstrap_initial_admin_if_configured(db):
                logger.info("Bootstrapped initial local administrator from environment")
        finally:
            db.close()
    except InitialAdminBootstrapError as exc:
        raise RuntimeError(f"Initial administrator bootstrap failed: {exc}") from exc


async def _initialize_task_queue() -> None:
    try:
        await init_queue()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to init task queue: %s", str(exc)[:200])


def _start_task_queue_observability_poller() -> None:
    if not bool(getattr(settings, "PROMETHEUS_ENABLED", False)):
        return
    try:
        from app.services.task_queue_observability_service import start_task_queue_observability_poller

        start_task_queue_observability_poller()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to start task queue observability poller: %s", str(exc)[:200])


def _bm25_startup_skip_message() -> str | None:
    if not bool(getattr(settings, "BM25_INDEX_ENABLED", True)):
        return "BM25 indexing disabled; skipping startup build"
    if not bool(getattr(settings, "BM25_STARTUP_BUILD_ENABLED", False)):
        return "BM25 startup build disabled (BM25_STARTUP_BUILD_ENABLED=false)"
    return None


def _load_bm25_startup_tenant_ids(db: Session) -> list[object]:
    tenant_ids: list[object] = []
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
    return tenant_ids


def _build_bm25_startup_indexes() -> None:
    skip_message = _bm25_startup_skip_message()
    if skip_message is not None:
        logger.info(skip_message)
        return

    logger.info("Initializing BM25 index (startup build)...")
    from sqlalchemy import func

    from app.rag.retriever import hybrid_retriever

    db = SessionLocal()
    try:
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
            return

        tenant_ids = _load_bm25_startup_tenant_ids(db)
        if not tenant_ids:
            logger.warning("No documents found, BM25 index will be built on first upload")
            return

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


def _schedule_dify_external_knowledge_warmup() -> None:
    try:
        from app.api.v1.integrations_dify import start_dify_external_knowledge_warmup

        start_dify_external_knowledge_warmup()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to schedule Dify external knowledge warmup: %s", str(exc)[:200])


async def _stop_task_queue_observability_poller() -> None:
    if not bool(getattr(settings, "PROMETHEUS_ENABLED", False)):
        return
    try:
        from app.services.task_queue_observability_service import stop_task_queue_observability_poller

        await stop_task_queue_observability_poller()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to stop task queue observability poller: %s", str(exc)[:200])


def _dispose_database_engine() -> None:
    try:
        engine.dispose()
        logger.info("Database engine disposed")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to dispose database engine: %s", str(exc)[:200])


# Lifespan management
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Operations on app startup and shutdown."""
    # Startup: create database tables.
    logger.info("Starting MimirQ backend...")
    _ensure_startup_directories()
    _ensure_optional_log_directories()
    _setup_langsmith_tracing()
    _initialize_database_for_startup()
    _bootstrap_initial_admin()
    await _initialize_task_queue()
    _start_task_queue_observability_poller()

    # Tokenizer initialization is process-local. Complete it before readiness so a
    # newly added API replica does not serialize its first concurrent requests.
    _warmup_retrieval_tokenizer()
    _start_runtime_warmup()
    _build_bm25_startup_indexes()
    _schedule_dify_external_knowledge_warmup()

    yield

    # Shutdown cleanup.
    logger.info("Shutting down MimirQ backend...")

    # Close HTTP client pool.
    await close_http_client_pool()
    logger.info("HTTP client pool closed")

    # Stop task queue observability poller (optional).
    await _stop_task_queue_observability_poller()

    # Close task queue connection (optional).
    await close_queue()

    # Dispose DB engine pool (best-effort; avoids lingering connections in some runtimes).
    _dispose_database_engine()

    shutdown_otel()


# Create FastAPI app
app = FastAPI(
    title="MimirQ - Knowledge Base RAG System",
    description="Knowledge Base Management and RAG Conversation System",
    version=__version__,
    docs_url=_DOCS_PATH if bool(getattr(settings, "API_DOCS_ENABLED", True)) else None,
    redoc_url="/redoc" if bool(getattr(settings, "API_DOCS_ENABLED", True)) else None,
    openapi_url=(
        "/openapi.json" if (bool(getattr(settings, "API_OPENAPI_ENABLED", True)) or _OPENAPI_EXPORT_MODE) else None
    ),
    lifespan=lifespan,
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
        x_content_type_options=str(
            getattr(settings, "SECURITY_HEADERS_X_CONTENT_TYPE_OPTIONS", "nosniff") or "nosniff"
        ),
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
    return {"message": "Welcome to MimirQ API", "version": __version__, "docs": _DOCS_PATH}


@app.get("/health")
async def health_check():
    """Public liveness probe."""
    return {"ok": True, "status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=True,
        server_header=False,
    )
