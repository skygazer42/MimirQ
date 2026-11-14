"""
FastAPI main entry point.
"""

import logging
import os
import time
import warnings
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from typing import Any
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

import app.models._all  # noqa: F401
from app import __version__
from app.api.dependencies import bind_route_context
from app.api.middleware.request_context import RequestContextMiddleware, RequestTimingMiddleware
from app.api.middleware.response_headers import (
    ResponseFingerprintSanitizerMiddleware,
    ResponseSecurityHeadersMiddleware,
)
from app.api.v1 import get_router
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
from app.rag.tools.mcp_client import close_mcp_client
from app.services.initial_admin_service import (
    InitialAdminBootstrapError,
    bootstrap_initial_admin_if_configured,
)
from app.tasks.queue import close_queue, init_queue

logger = logging.getLogger("mimirq")
_OPENAPI_EXPORT_MODE = os.getenv("MIMIRQ_OPENAPI_EXPORT", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "y",
    "on",
}
_DEV_LOCAL_CORS_PORTS = {3000, 3001, 3100}
_ALL_INTERFACES_HOST = "0.0.0.0"
_DOCS_PATH = "/docs"
_LOCAL_DEV_HOSTS = {"localhost", "127.0.0.1", _ALL_INTERFACES_HOST}
_LOCAL_DEV_SCHEMES = {"http", "https"}


def _parse_local_dev_origin(origin: str) -> tuple[str, str, int | None] | None:
    parsed = urlparse(origin)
    scheme = parsed.scheme.lower().strip()
    host = parsed.hostname
    if host is None:
        return None
    host = host.lower().strip()
    try:
        port = parsed.port
    except ValueError:
        return None
    if scheme not in _LOCAL_DEV_SCHEMES or host not in _LOCAL_DEV_HOSTS:
        return None
    return scheme, host, port


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

    expanded = {origin for raw in origins if (origin := raw.strip().rstrip("/"))}

    local_schemes: set[str] = set()
    local_ports: set[int] = set()
    for origin in tuple(expanded):
        parsed_origin = _parse_local_dev_origin(origin)
        if parsed_origin is None:
            continue
        scheme, host, port = parsed_origin
        for alias in _LOCAL_DEV_HOSTS:
            if alias != host:
                expanded.add(f"{scheme}://{alias}:{port}" if port is not None else f"{scheme}://{alias}")
        local_schemes.add(scheme)
        if port is not None:
            local_ports.add(port)

    for scheme in sorted(local_schemes):
        for port in sorted(local_ports | _DEV_LOCAL_CORS_PORTS):
            for host in sorted(_LOCAL_DEV_HOSTS):
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
    log_level=settings.LOG_LEVEL,
    log_format=settings.LOG_FORMAT,
    include_trace_context=settings.OTEL_ENABLED,
)

# Optional error monitoring (SENTRY_DSN).
if not _OPENAPI_EXPORT_MODE:
    init_sentry()

# Optional OpenTelemetry tracing (OTEL_ENABLED).
if not _OPENAPI_EXPORT_MODE and init_otel():
    instrument_httpx()


def _warmup_retrieval_tokenizer() -> None:
    if not settings.BM25_INDEX_ENABLED:
        return

    from app.rag.preprocessing.tokenization import warmup_lexical_tokenizer

    started_at = time.perf_counter()
    warmup_lexical_tokenizer()
    logger.info("BM25 tokenizer initialized in %.3fs", time.perf_counter() - started_at)


def _start_runtime_warmup() -> None:
    if not settings.RAG_RUNTIME_WARMUP_ENABLED:
        return
    from app.services.rag_runtime_warmup import start_rag_runtime_warmup

    start_rag_runtime_warmup()


def _ensure_startup_directories() -> None:
    for directory in (settings.UPLOAD_DIR, settings.TABLE_STORE_DIR):
        if not directory:
            continue
        try:
            Path(directory).mkdir(parents=True, exist_ok=True)
        except Exception as exc:  # noqa: BLE001 - startup directories retain their warning policy.
            logger.warning("Failed to ensure directory %s: %s", directory, str(exc)[:200])


def _ensure_parent_directory(path_value: str, *, warning_message: str) -> None:
    try:
        Path(path_value).parent.mkdir(parents=True, exist_ok=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("%s: %s", warning_message, str(exc)[:200])


def _ensure_optional_log_directories() -> None:
    if settings.ENABLE_METRICS_LOG:
        _ensure_parent_directory(settings.METRICS_LOG_PATH, warning_message="Failed to ensure metrics log dir")
    if settings.MINIO_ENABLED:
        _ensure_parent_directory(
            settings.MINIO_METRICS_LOG_PATH, warning_message="Failed to ensure MinIO metrics log dir"
        )


def _setup_langsmith_tracing() -> None:
    if not settings.LANGSMITH_TRACING_ENABLED:
        return
    try:
        from app.rag.tracing import setup_tracing

        setup_tracing()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to setup LangSmith tracing: %s", str(exc)[:200])


def _initialize_database_for_startup() -> None:
    runtime_migrations_enabled = settings.DB_RUNTIME_MIGRATIONS_ENABLED
    create_all_enabled = settings.DB_CREATE_ALL_ON_STARTUP

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
        with SessionLocal() as db:
            if bootstrap_initial_admin_if_configured(db):
                logger.info("Bootstrapped initial local administrator")
    except InitialAdminBootstrapError as exc:
        raise RuntimeError(f"Initial administrator bootstrap failed: {exc}") from exc


async def _initialize_task_queue() -> None:
    try:
        await init_queue()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to init task queue: %s", str(exc)[:200])


def _start_task_queue_observability_poller() -> None:
    if not settings.PROMETHEUS_ENABLED:
        return
    try:
        from app.services.task_queue_observability_service import start_task_queue_observability_poller

        start_task_queue_observability_poller()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to start task queue observability poller: %s", str(exc)[:200])


def _schedule_dify_external_knowledge_warmup() -> None:
    try:
        from app.api.v1.integrations_dify import start_dify_external_knowledge_warmup

        start_dify_external_knowledge_warmup()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to schedule Dify external knowledge warmup: %s", str(exc)[:200])


async def _stop_task_queue_observability_poller() -> None:
    if not settings.PROMETHEUS_ENABLED:
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
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Operations on app startup and shutdown."""
    logger.info("Starting Ragvia backend...")
    async with AsyncExitStack() as resources:
        # Exit callbacks run in reverse order, including failed startup and cancellation.
        resources.callback(shutdown_otel)
        resources.callback(_dispose_database_engine)
        resources.push_async_callback(close_queue)
        resources.push_async_callback(_stop_task_queue_observability_poller)
        resources.push_async_callback(close_http_client_pool)
        resources.push_async_callback(close_mcp_client)
        try:
            _ensure_startup_directories()
            _ensure_optional_log_directories()
            _setup_langsmith_tracing()
            _initialize_database_for_startup()
            _bootstrap_initial_admin()
            await _initialize_task_queue()
            _start_task_queue_observability_poller()

            # Complete the process-local tokenizer before exposing readiness.
            _warmup_retrieval_tokenizer()
            _start_runtime_warmup()
            _schedule_dify_external_knowledge_warmup()
            yield
        finally:
            logger.info("Shutting down Ragvia backend...")
    logger.info("HTTP client pool closed")


# Create FastAPI app
app = FastAPI(
    title="Ragvia - Knowledge Base RAG System",
    description="Knowledge Base Management and RAG Conversation System",
    version=__version__,
    docs_url=_DOCS_PATH if settings.API_DOCS_ENABLED else None,
    redoc_url="/redoc" if settings.API_DOCS_ENABLED else None,
    openapi_url="/openapi.json" if settings.API_OPENAPI_ENABLED or _OPENAPI_EXPORT_MODE else None,
    lifespan=lifespan,
)

# =============================================================================
# OpenAPI post-processing (contract stability)
# =============================================================================


def _patch_openapi_additional_properties(spec: dict[str, Any]) -> None:
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


def custom_openapi() -> dict[str, Any]:
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
if is_production_env() and settings.TRUSTED_HOSTS_ENABLED:
    from starlette.middleware.trustedhost import TrustedHostMiddleware

    allowed_hosts = parse_csv(settings.ALLOWED_HOSTS)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

# Request body size limit (DoS guardrail).
from app.api.middleware.body_size_limit import BodySizeLimitMiddleware

app.add_middleware(BodySizeLimitMiddleware, max_body_bytes=settings.REQUEST_MAX_BODY_BYTES)

# Rate limiting middleware
if settings.RATE_LIMIT_ENABLED:
    from app.api.middleware.rate_limit import RateLimitMiddleware

    app.add_middleware(
        RateLimitMiddleware,
        requests_per_second=settings.RATE_LIMIT_REQUESTS_PER_SECOND,
        burst_size=settings.RATE_LIMIT_BURST_SIZE,
        chat_requests_per_second=settings.RATE_LIMIT_CHAT_RPS,
        chat_burst_size=settings.RATE_LIMIT_CHAT_BURST,
        chat_route_prefixes=["/api/v1/chat/stream"],
    )

# Response compression (safe for SSE; event-stream is excluded by Starlette).
if settings.GZIP_ENABLED:
    from starlette.middleware.gzip import GZipMiddleware

    app.add_middleware(GZipMiddleware, minimum_size=settings.GZIP_MIN_SIZE, compresslevel=settings.GZIP_COMPRESS_LEVEL)

# Prometheus metrics (optional).
if settings.PROMETHEUS_ENABLED:
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
app.add_middleware(RequestTimingMiddleware, server_timing_enabled=settings.SERVER_TIMING_ENABLED)

# Security headers (lightweight hardening).
if settings.SECURITY_HEADERS_ENABLED:
    hsts_value = ""
    if settings.SECURITY_HEADERS_HSTS_ENABLED:
        parts = [f"max-age={settings.SECURITY_HEADERS_HSTS_MAX_AGE_SEC}"]
        if settings.SECURITY_HEADERS_HSTS_INCLUDE_SUBDOMAINS:
            parts.append("includeSubDomains")
        if settings.SECURITY_HEADERS_HSTS_PRELOAD:
            parts.append("preload")
        hsts_value = "; ".join(parts)

    app.add_middleware(
        ResponseSecurityHeadersMiddleware,
        x_content_type_options=settings.SECURITY_HEADERS_X_CONTENT_TYPE_OPTIONS,
        x_frame_options=settings.SECURITY_HEADERS_X_FRAME_OPTIONS,
        referrer_policy=settings.SECURITY_HEADERS_REFERRER_POLICY,
        strict_transport_security=hsts_value,
        permissions_policy=settings.SECURITY_HEADERS_PERMISSIONS_POLICY,
        cross_origin_opener_policy=settings.SECURITY_HEADERS_CROSS_ORIGIN_OPENER_POLICY,
        cross_origin_resource_policy=settings.SECURITY_HEADERS_CROSS_ORIGIN_RESOURCE_POLICY,
    )

# Response header sanitization (reduce fingerprinting).
app.add_middleware(ResponseFingerprintSanitizerMiddleware)

# Request-id middleware (outermost; propagates X-Request-ID for tracing).
app.add_middleware(RequestContextMiddleware)

# CORS must be the final middleware added so it wraps rate-limit and security
# error responses instead of letting browsers surface them as opaque CORS failures.
cors_origins = parse_csv(settings.CORS_ORIGINS)
if not is_production_env():
    cors_origins = _expand_dev_cors_origins(cors_origins)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=_build_cors_expose_headers(settings.CORS_EXPOSE_HEADERS),
)

# Register routes
app.include_router(get_router(), prefix="/api/v1", dependencies=[Depends(bind_route_context)])

# Register exception handlers
register_exception_handlers(app)


@app.get("/", response_model=None)
async def root() -> dict[str, str]:
    """Root path."""
    return {"message": "Welcome to Ragvia API", "version": __version__, "docs": _DOCS_PATH}


@app.get("/health", response_model=None)
async def health_check() -> dict[str, bool | str]:
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
