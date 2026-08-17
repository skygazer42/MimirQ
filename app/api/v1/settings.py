"""
Settings API - system configuration management.
Supports reading and updating .env configuration.
"""

import contextlib
import importlib.util
import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Annotated, Any, Callable
from urllib.parse import urlparse, urlunparse
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.utils.url_ingest import (
    _URL_HOST_RESOLUTION_FAILED_DETAIL,
    _build_pinned_http_clients,
    _validated_fetch_target,
    _ValidatedFetchTarget,
)
from app.core.config import (
    normalize_object_storage_provider_name,
    parse_object_storage_region_profiles,
    settings,
)
from app.core.database import get_db
from app.core.jwt_inspect import format_unix_ts_utc, try_get_jwt_exp
from app.services.navigation_visibility import normalize_navigation_modules, serialize_navigation_modules
from app.services.rbac_service import TenantPermissions, ensure_tenant_permission

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)

# .env file path.
ENV_FILE = Path(__file__).parent.parent.parent.parent / ".env"

_ENV_UPDATE_LOCK = threading.Lock()
_MISSING_API_URL_MESSAGE = "missing api_url"
_CONFIGURED_HEALTH_UNREACHABLE_MESSAGE = "configured (health_unreachable)"
_MINERU_BACKENDS = {"pipeline", "vlm-http-client"}
_SYSTEM_DIFY_ACCOUNT_ID = "system:dify"
_VECTOR_STORE_EMBEDDING_RESET_KEYS = frozenset(
    {
        "EMBEDDING_PROVIDER",
        "EMBEDDING_MODEL",
        "EMBEDDING_API_KEY",
        "EMBEDDING_API_BASE",
        "EMBEDDING_DIMENSION",
        "LLM_API_KEY",
        "LLM_API_BASE",
    }
)
_LEGACY_MINIO_RUNTIME_KEYS = frozenset(
    {
        "MINIO_ENABLED",
        "MINIO_ENDPOINT",
        "MINIO_ACCESS_KEY",
        "MINIO_SECRET_KEY",
        "MINIO_BUCKET_NAME",
        "MINIO_USE_SSL",
        "MINIO_DOCUMENTS_ENABLED",
        "MINIO_METRICS_LOG_PATH",
    }
)
_OBJECT_STORAGE_RUNTIME_KEYS = frozenset(
    {
        "OBJECT_STORAGE_PROVIDER",
        "OBJECT_STORAGE_ENABLED",
        "OBJECT_STORAGE_ENDPOINT",
        "OBJECT_STORAGE_ACCESS_KEY",
        "OBJECT_STORAGE_SECRET_KEY",
        "OBJECT_STORAGE_BUCKET_NAME",
        "OBJECT_STORAGE_USE_SSL",
        "OBJECT_STORAGE_METRICS_LOG_PATH",
        "OBJECT_STORAGE_DOCUMENTS_ENABLED",
        "DATA_REGION",
        "OBJECT_STORAGE_REGION_PROFILES",
    }
)


def _normalize_mineru_backend(value: Any) -> str:
    backend = str(value or "pipeline").strip().lower().replace("_", "-")
    aliases = {
        "": "pipeline",
        "auto": "pipeline",
        "vlm": "vlm-http-client",
        "vlm-http": "vlm-http-client",
        "vlm-httpclient": "vlm-http-client",
    }
    backend = aliases.get(backend, backend)
    if backend not in _MINERU_BACKENDS:
        raise ValueError("MinerU backend must be pipeline or vlm-http-client")
    return backend


@contextlib.contextmanager
def _env_file_lock():
    """
    Best-effort cross-process lock for `.env` updates.

    - In-process: guarded by a thread lock.
    - POSIX: additionally uses `fcntl.flock` on a sibling lockfile.
    """
    with _ENV_UPDATE_LOCK:
        fcntl = None
        if os.name == "posix":
            with contextlib.suppress(Exception):
                import fcntl as _fcntl  # noqa: WPS433

                fcntl = _fcntl

        if fcntl is None:
            yield
            return

        lock_path = ENV_FILE.with_name(f"{ENV_FILE.name}.lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with open(lock_path, "a", encoding="utf-8") as lockf:
            fcntl.flock(lockf.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                with contextlib.suppress(Exception):
                    fcntl.flock(lockf.fileno(), fcntl.LOCK_UN)


def _sanitize_env_value(key: str, value: Any) -> str:
    text = "" if value is None else str(value)
    if "\x00" in text or "\n" in text or "\r" in text:
        raise HTTPException(status_code=400, detail=f"Invalid value for {key}")
    if len(text) > 10_000:
        raise HTTPException(status_code=400, detail=f"Value too long for {key}")
    return text.strip()


def _convert_service_url_to_health_url(api_url: str) -> str:
    """
    Best-effort mapping for external parser services:
    - .../convert -> .../health
    - otherwise: join path with /health
    """
    raw = (api_url or "").strip()
    if not raw:
        return ""

    try:
        parsed = urlparse(raw)
    except Exception:
        return ""

    path = (parsed.path or "").strip()
    if path.endswith("/convert"):
        path = path[: -len("/convert")] + "/health"
    else:
        base = path.rstrip("/")
        path = f"{base}/health" if base else "/health"

    return urlunparse(parsed._replace(path=path, params="", query="", fragment=""))


async def _probe_http_json(url: str, *, timeout_sec: float = 0.6) -> tuple[dict[str, Any] | None, str | None]:
    """
    Best-effort GET+JSON probe with short timeout.

    Returns (data, error). `data` is only returned when the payload is a JSON object.
    """
    url = (url or "").strip()
    if not url:
        return None, "empty url"

    try:
        async with httpx.AsyncClient(timeout=float(timeout_sec or 0.6)) as client:
            resp = await client.get(url)
    except Exception as exc:  # noqa: BLE001
        return None, f"request_failed: {str(exc)[:160]}"

    if int(getattr(resp, "status_code", 0) or 0) != 200:
        return None, f"bad_status: {int(getattr(resp, 'status_code', 0) or 0)}"

    try:
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        return None, f"invalid_json: {str(exc)[:120]}"

    if not isinstance(data, dict):
        return None, "invalid_payload"
    return data, None


def _ensure_settings_readable(db: Session, tenant_id: UUID, account_id: str) -> None:
    ensure_tenant_permission(
        db,
        tenant_id,
        account_id,
        TenantPermissions.SETTINGS_READ,
        detail="No permission to access system settings",
    )


def _ensure_settings_writable(db: Session, tenant_id: UUID, account_id: str) -> None:
    try:
        system_tenant_id = UUID(str(getattr(settings, "DEFAULT_TENANT_ID", "") or ""))
    except ValueError as exc:
        raise HTTPException(status_code=500, detail="DEFAULT_TENANT_ID is invalid") from exc
    if tenant_id != system_tenant_id:
        raise HTTPException(status_code=403, detail="No permission to manage system settings")
    member = ensure_tenant_permission(
        db,
        tenant_id,
        account_id,
        TenantPermissions.SETTINGS_WRITE,
        detail="No permission to manage system settings",
    )
    if str(getattr(member, "role", "") or "").strip().lower() != "owner":
        raise HTTPException(status_code=403, detail="No permission to manage system settings")


async def _validate_public_base_url(base_url: str) -> _ValidatedFetchTarget:
    try:
        return await _validated_fetch_target(base_url, enforce_allowlists=False)
    except HTTPException as exc:
        detail = str(exc.detail or "")
        if detail in {"url is required", "url hostname is required"}:
            detail = "api_base must include host"
        elif detail == "url scheme must be http or https":
            detail = "api_base must be http(s) URL"
        elif detail == "url credentials are not allowed":
            detail = "api_base must not include userinfo"
        elif detail == "url port is not allowed":
            detail = "api_base port is not allowed"
        elif detail == _URL_HOST_RESOLUTION_FAILED_DETAIL:
            detail = "failed to resolve api_base host"
        else:
            detail = "api_base host not allowed"
        raise HTTPException(status_code=400, detail=detail) from exc


class FeatureFlags(BaseModel):
    """Feature flags."""

    kg_enabled: bool = False
    deepdoc_enabled: bool = False
    docling_enabled: bool = False
    etl4llm_enabled: bool = False
    marker_enabled: bool = False
    paddle_vl_enabled: bool = False
    textin_enabled: bool = False
    markitdown_enabled: bool = False
    llama_index_enabled: bool = False
    mineru_enabled: bool = False
    magicpdf_enabled: bool = False


class KGConfig(BaseModel):
    """KG-related config."""

    chat_enabled: bool = False
    extract_prompt_template_id: str = ""
    extract_prompt_template_key: str = ""
    extract_prompt_ab_experiment_key: str = ""
    extract_replace_existing: bool = True
    extract_prune_orphan_entities: bool = True


def _default_llm_api_base() -> str:
    return settings.LLM_API_BASE


class LLMConfig(BaseModel):
    """LLM config."""

    api_key: str = ""
    api_base: str = Field(default_factory=_default_llm_api_base)
    model: str = "gpt-5.4-mini"
    temperature: float = 0.7
    timeout: int = 60
    max_retries: int = 3


class EmbeddingConfig(BaseModel):
    """Embedding config."""

    provider: str = "openai_compatible"
    model: str = "text-embedding-3-small"
    api_key: str = ""
    api_base: str = ""


class MilvusConfig(BaseModel):
    """Milvus config."""

    host: str = "localhost"
    port: int = 19530
    user: str = ""
    password: str = ""
    collection_name: str = "documents"


class MinioConfig(BaseModel):
    """MinIO / S3-compatible object storage config."""

    enabled: bool = False
    endpoint: str = "localhost:9000"
    access_key: str = ""
    secret_key: str = ""
    bucket_name: str = "mimirq"
    use_ssl: bool = False
    documents_enabled: bool = False
    image_max_bytes: int = Field(default=0, ge=0)


class RAGConfig(BaseModel):
    """RAG parameter config."""

    chunk_size: int = 1000
    chunk_overlap: int = 200
    chunk_min_chars: int = 30
    retrieval_top_k: int = 5
    similarity_threshold: float = 0.7
    default_parser_backend: str = "auto"
    default_chunk_strategy: str = "langchain_recursive"
    bm25_index_enabled: bool = True
    enable_reranker: bool = False
    reranker_provider: str = "llm"
    reranker_top_n: int = Field(default=20, ge=1, le=200)
    show_image_in_answer: bool = True
    image_append_max: int = Field(default=3, ge=0, le=10)

    @field_validator("reranker_provider", mode="before")
    @classmethod
    def _normalize_reranker_provider(cls, value):  # noqa: ANN001
        provider = str(value or "llm").strip().lower().replace("-", "_")
        aliases = {
            "sentence_transformers": "cross_encoder",
            "sentence_transformer": "cross_encoder",
            "sentence-transformers": "cross_encoder",
            "crossencoder": "cross_encoder",
            "cross-encoder": "cross_encoder",
            "parent_child": "pc",
            "bge_v2_m3": "local_bge_v2_m3",
            "xgboost_ltr": "ltr",
            "off": "none",
            "false": "none",
            "0": "none",
        }
        provider = aliases.get(provider, provider)
        valid = {
            "llm",
            "pc",
            "weighted",
            "openai",
            "dashscope",
            "aliyun",
            "colbert",
            "late_interaction",
            "ltr",
            "cross_encoder",
            "local_bge_v2_m3",
            "long_context",
            "mmr",
            "kg_pagerank",
            "kg_rrf",
            "none",
        }
        if provider not in valid:
            raise ValueError(f"reranker_provider must be one of: {', '.join(sorted(valid))}")
        return provider


class UrlIngestConfig(BaseModel):
    """URL ingestion config (server-side fetch; connectors)."""

    enabled: bool = False
    max_bytes: int = 50_000_000
    timeout_sec: float = 30.0
    allow_private_ips: bool = False
    follow_redirects: bool = False


class GovernanceConfig(BaseModel):
    """Global governance defaults (used when pipeline overrides are absent)."""

    enabled: bool = False
    pii_anonymize: bool = False
    secrets_redact: bool = False
    quarantine_on_drop: bool = False


class ObservabilityConfig(BaseModel):
    """Observability/debug config."""

    tool_call_log_enabled: bool = False
    tool_call_log_include_preview: bool = False
    tool_call_log_max_preview_chars: int = Field(default=500, ge=0, le=5000)

    agent_log_enabled: bool = False
    agent_log_include_execution_path: bool = False
    agent_log_max_preview_chars: int = Field(default=500, ge=0, le=5000)

    # JSONL metrics log (RAG trace dashboard)
    metrics_log_enabled: bool = False
    metrics_log_include_text: bool = False


class SafetyConfig(BaseModel):
    """Security/privacy config."""

    pii_redaction_enabled: bool = False
    pii_redaction_mask: str = "[REDACTED]"
    pii_stream_holdback_chars: int = Field(default=128, ge=0, le=4096)


class ChatConfig(BaseModel):
    """Chat streaming/runtime config."""

    stream_heartbeat_sec: float = Field(default=10.0, ge=0.0, le=120.0)
    stream_cancel_on_disconnect: bool = True


class LangGraphConfig(BaseModel):
    """LangGraph execution mode config."""

    use_subgraphs: bool = False


class CacheConfig(BaseModel):
    """Performance / cache config."""

    upload_dedup_enabled: bool = False

    # Chat response cache (Redis, best-effort).
    chat_response_cache_enabled: bool = False
    chat_response_cache_ttl_sec: int = Field(default=300, ge=0, le=86_400)
    chat_response_cache_max_value_bytes: int = Field(default=200_000, ge=0, le=5_000_000)
    chat_response_cache_require_empty_history: bool = True


class MinerUConfig(BaseModel):
    """MinerU config."""

    api_token: str = ""
    api_base: str = "https://mineru.net/api/v4"
    model_version: str = "vlm"
    backend: str = "pipeline"
    local_server_url: str = ""
    vl_server: str = ""

    @field_validator("backend", mode="before")
    @classmethod
    def _normalize_backend(cls, value):  # noqa: ANN001
        return _normalize_mineru_backend(value)


class MagicPDFConfig(BaseModel):
    """MagicPDF (magic-pdf) config."""

    api_url: str = ""
    request_timeout_sec: int = 600
    max_concurrent_jobs: int = 1
    cli: str = "magic-pdf"
    method: str = "auto"  # auto | ocr | txt
    lang: str = ""
    debug: bool = False
    timeout_sec: int = 600
    models_dir: str = ""
    device_mode: str = "cpu"
    keep_artifacts: bool = False


class Etl4LlmConfig(BaseModel):
    """ETL4LLM (layout/table/image parsing) config."""

    api_url: str = ""
    timeout_sec: int = 120
    mode: str = "partition"  # partition | text
    force_ocr: bool = False
    enable_formula: bool = True
    extract_images: bool = True
    filter_page_header_footer: bool = False


class MarkerConfig(BaseModel):
    """Marker external PDF->Markdown service config."""

    api_url: str = ""
    timeout_sec: int = 600


class PaddleVLConfig(BaseModel):
    """PaddleOCR-VL external PDF->Markdown service config."""

    api_url: str = ""
    timeout_sec: int = 600
    # Display/audit only: expected service pipeline version/mode (not used by the backend parser directly).
    pipeline_version: str = "v1.5"
    mode: str = "doc_parser"


class TextInConfig(BaseModel):
    """TextIn xParse external document->Markdown API config."""

    api_url: str = "https://api.textin.com/ai/service/v1/pdf_to_markdown"
    app_id: str = ""
    secret_code: str = ""
    timeout_sec: int = 180
    parse_mode: str = "auto"
    table_flavor: str = "html"
    apply_document_tree: bool = True
    markdown_details: bool = True
    get_image: str = "none"
    dpi: int = 144
    page_count: int = 0


class NavigationConfig(BaseModel):
    """Frontend navigation visibility for ordinary tenant members."""

    user_visible_modules: list[str] = Field(default_factory=list)

    @field_validator("user_visible_modules", mode="before")
    @classmethod
    def _normalize_modules(cls, value):  # noqa: ANN001
        return normalize_navigation_modules(value, reject_unknown=True)


class DifyExternalKnowledgeConfig(BaseModel):
    """Dify External Knowledge API adapter settings."""

    enabled: bool = False
    api_keys: str = ""
    tenant_id: str = ""
    account_id: str = _SYSTEM_DIFY_ACCOUNT_ID
    knowledge_map_json: str = ""
    top_k_max: int = Field(default=5, ge=1, le=200)
    endpoint_path: str = "/api/v1/integrations/dify/retrieval"


class SystemSettings(BaseModel):
    """Full system config."""

    feature_flags: FeatureFlags
    kg: KGConfig
    llm: LLMConfig
    embedding: EmbeddingConfig
    milvus: MilvusConfig
    minio: MinioConfig
    rag: RAGConfig
    cache: CacheConfig
    url_ingest: UrlIngestConfig
    governance: GovernanceConfig
    mineru: MinerUConfig
    etl4llm: Etl4LlmConfig
    marker: MarkerConfig
    paddle_vl: PaddleVLConfig
    textin: TextInConfig
    magicpdf: MagicPDFConfig
    observability: ObservabilityConfig
    safety: SafetyConfig
    chat: ChatConfig
    langgraph: LangGraphConfig
    navigation: NavigationConfig
    dify_external_knowledge: DifyExternalKnowledgeConfig


class UpdateSettingsRequest(BaseModel):
    """Update config request."""

    feature_flags: FeatureFlags | None = None
    kg: KGConfig | None = None
    llm: LLMConfig | None = None
    embedding: EmbeddingConfig | None = None
    milvus: MilvusConfig | None = None
    minio: MinioConfig | None = None
    rag: RAGConfig | None = None
    cache: CacheConfig | None = None
    url_ingest: UrlIngestConfig | None = None
    governance: GovernanceConfig | None = None
    mineru: MinerUConfig | None = None
    etl4llm: Etl4LlmConfig | None = None
    marker: MarkerConfig | None = None
    paddle_vl: PaddleVLConfig | None = None
    textin: TextInConfig | None = None
    magicpdf: MagicPDFConfig | None = None
    observability: ObservabilityConfig | None = None
    safety: SafetyConfig | None = None
    chat: ChatConfig | None = None
    langgraph: LangGraphConfig | None = None
    navigation: NavigationConfig | None = None
    dify_external_knowledge: DifyExternalKnowledgeConfig | None = None


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "y", "on"}


def _parse_int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _parse_float(value: Any, *, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _apply_runtime_specs(
    env_vars: dict[str, str],
    updated_keys: set[str],
    specs: tuple[tuple[str, Callable[[str], Any]], ...],
) -> None:
    for key, parser in specs:
        if key in updated_keys and key in env_vars:
            setattr(settings, key, parser(env_vars[key]))


def _apply_feature_flag_runtime_settings(env_vars: dict[str, str], updated_keys: set[str]) -> None:
    _apply_runtime_specs(
        env_vars,
        updated_keys,
        (
            ("KG_ENABLED", _parse_bool),
            ("KG_CHAT_ENABLED", _parse_bool),
            ("DEEPDOC_ENABLED", _parse_bool),
            ("DOCLING_ENABLED", _parse_bool),
            ("ETL4LLM_ENABLED", _parse_bool),
            ("MARKER_ENABLED", _parse_bool),
            ("PADDLE_VL_ENABLED", _parse_bool),
            ("MARKITDOWN_ENABLED", _parse_bool),
            ("LLAMA_INDEX_ENABLED", _parse_bool),
            ("MINERU_ENABLED", _parse_bool),
            ("MAGIC_PDF_ENABLED", _parse_bool),
        ),
    )


def _apply_kg_runtime_settings(env_vars: dict[str, str], updated_keys: set[str]) -> None:
    _apply_runtime_specs(
        env_vars,
        updated_keys,
        (
            ("KG_EXTRACT_PROMPT_TEMPLATE_ID", str),
            ("KG_EXTRACT_PROMPT_TEMPLATE_KEY", str),
            ("KG_EXTRACT_PROMPT_AB_EXPERIMENT_KEY", str),
            ("KG_EXTRACT_REPLACE_EXISTING", _parse_bool),
            ("KG_EXTRACT_PRUNE_ORPHAN_ENTITIES", _parse_bool),
        ),
    )


def _apply_llm_runtime_settings(env_vars: dict[str, str], updated_keys: set[str]) -> None:
    _apply_runtime_specs(
        env_vars,
        updated_keys,
        (
            ("LLM_API_KEY", str),
            ("LLM_API_BASE", str),
            ("LLM_MODEL", str),
            ("LLM_TEMPERATURE", lambda value: _parse_float(value, default=settings.LLM_TEMPERATURE)),
            ("LLM_TIMEOUT", lambda value: _parse_int(value, default=settings.LLM_TIMEOUT)),
            ("LLM_MAX_RETRIES", lambda value: _parse_int(value, default=settings.LLM_MAX_RETRIES)),
        ),
    )


def _apply_embedding_runtime_settings(env_vars: dict[str, str], updated_keys: set[str]) -> None:
    _apply_runtime_specs(
        env_vars,
        updated_keys,
        (
            ("EMBEDDING_PROVIDER", str),
            ("EMBEDDING_MODEL", str),
            ("EMBEDDING_API_KEY", str),
            ("EMBEDDING_API_BASE", str),
        ),
    )
    if _VECTOR_STORE_EMBEDDING_RESET_KEYS.intersection(updated_keys):
        from app.storage.vector.factory import reset_vector_store_singletons

        reset_vector_store_singletons()


def _apply_milvus_runtime_settings(env_vars: dict[str, str], updated_keys: set[str]) -> None:
    _apply_runtime_specs(
        env_vars,
        updated_keys,
        (
            ("MILVUS_HOST", str),
            ("MILVUS_PORT", lambda value: _parse_int(value, default=settings.MILVUS_PORT)),
            ("MILVUS_USER", str),
            ("MILVUS_PASSWORD", str),
            ("MILVUS_COLLECTION_NAME", str),
        ),
    )


def _apply_storage_runtime_settings(env_vars: dict[str, str], updated_keys: set[str]) -> None:
    _apply_runtime_specs(
        env_vars,
        updated_keys,
        (
            ("MINIO_ENABLED", _parse_bool),
            ("MINIO_ENDPOINT", str),
            ("MINIO_ACCESS_KEY", str),
            ("MINIO_SECRET_KEY", str),
            ("MINIO_BUCKET_NAME", str),
            ("MINIO_USE_SSL", _parse_bool),
            ("MINIO_DOCUMENTS_ENABLED", _parse_bool),
            (
                "MINIO_IMAGE_MAX_BYTES",
                lambda value: _parse_int(value, default=int(getattr(settings, "MINIO_IMAGE_MAX_BYTES", 0) or 0)),
            ),
            ("MINIO_METRICS_LOG_PATH", str),
            ("OBJECT_STORAGE_PROVIDER", normalize_object_storage_provider_name),
            ("OBJECT_STORAGE_ENABLED", _parse_bool),
            ("OBJECT_STORAGE_USE_SSL", _parse_bool),
            ("OBJECT_STORAGE_DOCUMENTS_ENABLED", _parse_bool),
            ("OBJECT_STORAGE_ENDPOINT", str),
            ("OBJECT_STORAGE_ACCESS_KEY", str),
            ("OBJECT_STORAGE_SECRET_KEY", str),
            ("OBJECT_STORAGE_BUCKET_NAME", str),
            ("OBJECT_STORAGE_METRICS_LOG_PATH", str),
            ("DATA_REGION", lambda value: str(value or "").strip().lower()),
        ),
    )
    if "OBJECT_STORAGE_REGION_PROFILES" in updated_keys and "OBJECT_STORAGE_REGION_PROFILES" in env_vars:
        parse_object_storage_region_profiles(env_vars["OBJECT_STORAGE_REGION_PROFILES"])
        settings.OBJECT_STORAGE_REGION_PROFILES = env_vars["OBJECT_STORAGE_REGION_PROFILES"]

    storage_runtime_keys = _LEGACY_MINIO_RUNTIME_KEYS.union(_OBJECT_STORAGE_RUNTIME_KEYS)
    if storage_runtime_keys.intersection(updated_keys):
        from app.storage.object.factory import reset_object_store_cache

        reset_object_store_cache()
        if _LEGACY_MINIO_RUNTIME_KEYS.intersection(updated_keys):
            from app.storage.object.minio import minio_service

            minio_service.reset_runtime_state()
        from app.api.v1.health import invalidate_ready_cache

        invalidate_ready_cache()


def _apply_rag_runtime_settings(env_vars: dict[str, str], updated_keys: set[str]) -> None:
    _apply_runtime_specs(
        env_vars,
        updated_keys,
        (
            ("CHUNK_SIZE", lambda value: _parse_int(value, default=settings.CHUNK_SIZE)),
            ("CHUNK_OVERLAP", lambda value: _parse_int(value, default=settings.CHUNK_OVERLAP)),
            ("CHUNK_MIN_CHARS", lambda value: _parse_int(value, default=getattr(settings, "CHUNK_MIN_CHARS", 0))),
            ("RETRIEVAL_TOP_K", lambda value: _parse_int(value, default=settings.RETRIEVAL_TOP_K)),
            ("SIMILARITY_THRESHOLD", lambda value: _parse_float(value, default=settings.SIMILARITY_THRESHOLD)),
            ("DEFAULT_PARSER_BACKEND", str),
            ("DEFAULT_CHUNK_STRATEGY", str),
            ("ENABLE_RERANKER", _parse_bool),
            ("RERANKER_PROVIDER", str),
            ("RERANKER_TOP_N", lambda value: _parse_int(value, default=settings.RERANKER_TOP_N)),
            ("SHOW_IMAGE_IN_ANSWER", _parse_bool),
            (
                "IMAGE_APPEND_MAX",
                lambda value: _parse_int(value, default=int(getattr(settings, "IMAGE_APPEND_MAX", 3) or 3)),
            ),
        ),
    )

    if "BM25_INDEX_ENABLED" in updated_keys and "BM25_INDEX_ENABLED" in env_vars:
        old_bm25 = bool(getattr(settings, "BM25_INDEX_ENABLED", True))
        new_bm25 = _parse_bool(env_vars["BM25_INDEX_ENABLED"])
        settings.BM25_INDEX_ENABLED = new_bm25
        if old_bm25 and not new_bm25:
            with contextlib.suppress(Exception):
                from app.rag.retriever import hybrid_retriever

                hybrid_retriever.clear_bm25_cache()


def _apply_cache_runtime_settings(env_vars: dict[str, str], updated_keys: set[str]) -> None:
    _apply_runtime_specs(
        env_vars,
        updated_keys,
        (
            ("UPLOAD_DEDUP_ENABLED", _parse_bool),
            ("CHAT_RESPONSE_CACHE_ENABLED", _parse_bool),
            (
                "CHAT_RESPONSE_CACHE_TTL_SEC",
                lambda value: _parse_int(
                    value, default=int(getattr(settings, "CHAT_RESPONSE_CACHE_TTL_SEC", 300) or 300)
                ),
            ),
            (
                "CHAT_RESPONSE_CACHE_MAX_VALUE_BYTES",
                lambda value: _parse_int(
                    value,
                    default=int(getattr(settings, "CHAT_RESPONSE_CACHE_MAX_VALUE_BYTES", 200_000) or 200_000),
                ),
            ),
            ("CHAT_RESPONSE_CACHE_REQUIRE_EMPTY_HISTORY", _parse_bool),
        ),
    )


def _apply_url_ingest_runtime_settings(env_vars: dict[str, str], updated_keys: set[str]) -> None:
    _apply_runtime_specs(
        env_vars,
        updated_keys,
        (
            ("URL_INGEST_ENABLED", _parse_bool),
            (
                "URL_INGEST_MAX_BYTES",
                lambda value: _parse_int(value, default=getattr(settings, "URL_INGEST_MAX_BYTES", 0)),
            ),
            (
                "URL_INGEST_TIMEOUT_SEC",
                lambda value: _parse_float(value, default=getattr(settings, "URL_INGEST_TIMEOUT_SEC", 30.0)),
            ),
            ("URL_INGEST_ALLOW_PRIVATE_IPS", _parse_bool),
            ("URL_INGEST_FOLLOW_REDIRECTS", _parse_bool),
        ),
    )


def _apply_governance_runtime_settings(env_vars: dict[str, str], updated_keys: set[str]) -> None:
    _apply_runtime_specs(
        env_vars,
        updated_keys,
        (
            ("GOVERNANCE_ENABLED", _parse_bool),
            ("GOVERNANCE_PII_ANONYMIZE", _parse_bool),
            ("GOVERNANCE_SECRETS_REDACT", _parse_bool),
            ("GOVERNANCE_QUARANTINE_ON_DROP", _parse_bool),
        ),
    )


def _apply_mineru_runtime_settings(env_vars: dict[str, str], updated_keys: set[str]) -> None:
    _apply_runtime_specs(
        env_vars,
        updated_keys,
        (
            ("MINERU_API_TOKEN", str),
            ("MINERU_API_BASE", str),
            ("MINERU_MODEL_VERSION", str),
            ("MINERU_BACKEND", _normalize_mineru_backend),
            ("MINERU_LOCAL_SERVER_URL", str),
            ("MINERU_VL_SERVER", str),
        ),
    )


def _apply_etl4llm_runtime_settings(env_vars: dict[str, str], updated_keys: set[str]) -> None:
    _apply_runtime_specs(
        env_vars,
        updated_keys,
        (
            ("ETL4LLM_API_URL", str),
            ("ETL4LLM_TIMEOUT_SEC", lambda value: _parse_int(value, default=settings.ETL4LLM_TIMEOUT_SEC)),
            ("ETL4LLM_MODE", str),
            ("ETL4LLM_FORCE_OCR", _parse_bool),
            ("ETL4LLM_ENABLE_FORMULA", _parse_bool),
            ("ETL4LLM_EXTRACT_IMAGES", _parse_bool),
            ("ETL4LLM_FILTER_PAGE_HEADER_FOOTER", _parse_bool),
        ),
    )


def _apply_marker_runtime_settings(env_vars: dict[str, str], updated_keys: set[str]) -> None:
    _apply_runtime_specs(
        env_vars,
        updated_keys,
        (
            ("MARKER_API_URL", str),
            ("MARKER_TIMEOUT_SEC", lambda value: _parse_int(value, default=settings.MARKER_TIMEOUT_SEC)),
        ),
    )


def _apply_paddle_vl_runtime_settings(env_vars: dict[str, str], updated_keys: set[str]) -> None:
    _apply_runtime_specs(
        env_vars,
        updated_keys,
        (
            ("PADDLE_VL_API_URL", str),
            ("PADDLE_VL_TIMEOUT_SEC", lambda value: _parse_int(value, default=settings.PADDLE_VL_TIMEOUT_SEC)),
            ("PADDLE_VL_PIPELINE_VERSION", str),
            ("PADDLE_VL_MODE", str),
        ),
    )


def _apply_magicpdf_runtime_settings(env_vars: dict[str, str], updated_keys: set[str]) -> None:
    _apply_runtime_specs(
        env_vars,
        updated_keys,
        (
            ("MAGIC_PDF_API_URL", str),
            (
                "MAGIC_PDF_REQUEST_TIMEOUT_SEC",
                lambda value: _parse_int(
                    value, default=int(getattr(settings, "MAGIC_PDF_REQUEST_TIMEOUT_SEC", 600) or 600)
                ),
            ),
            (
                "MAGIC_PDF_MAX_CONCURRENT_JOBS",
                lambda value: _parse_int(
                    value, default=int(getattr(settings, "MAGIC_PDF_MAX_CONCURRENT_JOBS", 1) or 1)
                ),
            ),
            ("MAGIC_PDF_CLI", str),
            ("MAGIC_PDF_METHOD", str),
            ("MAGIC_PDF_LANG", str),
            ("MAGIC_PDF_DEBUG", _parse_bool),
            ("MAGIC_PDF_TIMEOUT_SEC", lambda value: _parse_int(value, default=settings.MAGIC_PDF_TIMEOUT_SEC)),
            ("MAGIC_PDF_MODELS_DIR", str),
            ("MAGIC_PDF_DEVICE_MODE", str),
            ("MAGIC_PDF_KEEP_ARTIFACTS", _parse_bool),
        ),
    )


def _apply_observability_runtime_settings(env_vars: dict[str, str], updated_keys: set[str]) -> None:
    _apply_runtime_specs(
        env_vars,
        updated_keys,
        (
            ("TOOL_CALL_LOG_ENABLED", _parse_bool),
            ("TOOL_CALL_LOG_INCLUDE_PREVIEW", _parse_bool),
            (
                "TOOL_CALL_LOG_MAX_PREVIEW_CHARS",
                lambda value: _parse_int(value, default=settings.TOOL_CALL_LOG_MAX_PREVIEW_CHARS),
            ),
            ("AGENT_LOG_ENABLED", _parse_bool),
            ("AGENT_LOG_INCLUDE_EXECUTION_PATH", _parse_bool),
            (
                "AGENT_LOG_MAX_PREVIEW_CHARS",
                lambda value: _parse_int(value, default=settings.AGENT_LOG_MAX_PREVIEW_CHARS),
            ),
            ("ENABLE_METRICS_LOG", _parse_bool),
            ("METRICS_LOG_INCLUDE_TEXT", _parse_bool),
        ),
    )


def _apply_safety_runtime_settings(env_vars: dict[str, str], updated_keys: set[str]) -> None:
    _apply_runtime_specs(
        env_vars,
        updated_keys,
        (
            ("PII_REDACTION_ENABLED", _parse_bool),
            ("PII_REDACTION_MASK", str),
            ("PII_STREAM_HOLDBACK_CHARS", lambda value: _parse_int(value, default=settings.PII_STREAM_HOLDBACK_CHARS)),
        ),
    )


def _apply_chat_runtime_settings(env_vars: dict[str, str], updated_keys: set[str]) -> None:
    _apply_runtime_specs(
        env_vars,
        updated_keys,
        (
            (
                "CHAT_STREAM_HEARTBEAT_SEC",
                lambda value: _parse_float(value, default=getattr(settings, "CHAT_STREAM_HEARTBEAT_SEC", 10.0)),
            ),
            ("CHAT_STREAM_CANCEL_ON_DISCONNECT", _parse_bool),
        ),
    )


def _apply_langgraph_runtime_settings(env_vars: dict[str, str], updated_keys: set[str]) -> None:
    _apply_runtime_specs(env_vars, updated_keys, (("LANGGRAPH_USE_SUBGRAPHS", _parse_bool),))


def _apply_navigation_runtime_settings(env_vars: dict[str, str], updated_keys: set[str]) -> None:
    _apply_runtime_specs(env_vars, updated_keys, (("NAVIGATION_USER_VISIBLE_MODULES", str),))


def _apply_dify_runtime_settings(env_vars: dict[str, str], updated_keys: set[str]) -> None:
    _apply_runtime_specs(
        env_vars,
        updated_keys,
        (
            ("DIFY_EXTERNAL_KNOWLEDGE_ENABLED", _parse_bool),
            ("DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", str),
            ("DIFY_EXTERNAL_KNOWLEDGE_TENANT_ID", str),
            ("DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", str),
            ("DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON", str),
            (
                "DIFY_EXTERNAL_KNOWLEDGE_TOP_K_MAX",
                lambda value: _parse_int(
                    value, default=int(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_TOP_K_MAX", 5) or 5)
                ),
            ),
        ),
    )


def _apply_runtime_settings(env_vars: dict[str, str], updated_keys: list[str]) -> None:
    """
    Best-effort: apply updated .env values to the in-memory settings object so
    config changes can take effect without a restart.
    """
    updated_key_set = set(updated_keys)
    _apply_feature_flag_runtime_settings(env_vars, updated_key_set)
    _apply_kg_runtime_settings(env_vars, updated_key_set)
    _apply_llm_runtime_settings(env_vars, updated_key_set)
    _apply_embedding_runtime_settings(env_vars, updated_key_set)
    _apply_milvus_runtime_settings(env_vars, updated_key_set)
    _apply_storage_runtime_settings(env_vars, updated_key_set)
    _apply_rag_runtime_settings(env_vars, updated_key_set)
    _apply_cache_runtime_settings(env_vars, updated_key_set)
    _apply_url_ingest_runtime_settings(env_vars, updated_key_set)
    _apply_governance_runtime_settings(env_vars, updated_key_set)
    _apply_mineru_runtime_settings(env_vars, updated_key_set)
    _apply_etl4llm_runtime_settings(env_vars, updated_key_set)
    _apply_marker_runtime_settings(env_vars, updated_key_set)
    _apply_paddle_vl_runtime_settings(env_vars, updated_key_set)
    _apply_magicpdf_runtime_settings(env_vars, updated_key_set)
    _apply_observability_runtime_settings(env_vars, updated_key_set)
    _apply_safety_runtime_settings(env_vars, updated_key_set)
    _apply_chat_runtime_settings(env_vars, updated_key_set)
    _apply_langgraph_runtime_settings(env_vars, updated_key_set)
    _apply_navigation_runtime_settings(env_vars, updated_key_set)
    _apply_dify_runtime_settings(env_vars, updated_key_set)


def read_env_file() -> dict[str, str]:
    """Read .env file."""
    env_vars = {}
    if ENV_FILE.exists():
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    env_vars[key.strip()] = value.strip()
    return env_vars


def write_env_file(env_vars: dict[str, str]):
    """Write .env file, preserving comments and formatting (atomic best-effort)."""
    lines = []
    existing_keys = set()

    # Read existing file and preserve comments.
    if ENV_FILE.exists():
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith("#") or not stripped:
                    lines.append(line.rstrip("\n"))
                elif "=" in stripped:
                    key = stripped.split("=")[0].strip()
                    existing_keys.add(key)
                    if key in env_vars:
                        lines.append(f"{key}={env_vars[key]}")
                    else:
                        lines.append(line.rstrip("\n"))

    # Add new key-value pairs.
    for key, value in env_vars.items():
        if key not in existing_keys:
            lines.append(f"{key}={value}")

    content = "\n".join(lines) + "\n"
    target_dir = ENV_FILE.parent
    target_dir.mkdir(parents=True, exist_ok=True)

    # Atomic replace to avoid partial writes when the process is interrupted.
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(target_dir),
            prefix=f"{ENV_FILE.name}.",
            suffix=".tmp",
            delete=False,
        ) as tf:
            tmp_path = Path(tf.name)
            tf.write(content)
            tf.flush()
            os.fsync(tf.fileno())

        if ENV_FILE.exists():
            with contextlib.suppress(Exception):
                os.chmod(tmp_path, ENV_FILE.stat().st_mode)

        os.replace(str(tmp_path), str(ENV_FILE))
    finally:
        if tmp_path is not None:
            with contextlib.suppress(OSError):
                tmp_path.unlink(missing_ok=True)


def mask_secret(value: str) -> str:
    """Mask sensitive info."""
    if not value or len(value) < 8:
        return "***" if value else ""
    return value[:4] + "***" + value[-4:]


@router.get("", response_model=SystemSettings, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_settings(
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Get current system config."""
    _ensure_settings_readable(db, tenant_id, account_id)
    return SystemSettings(
        feature_flags=FeatureFlags(
            kg_enabled=settings.KG_ENABLED,
            deepdoc_enabled=settings.DEEPDOC_ENABLED,
            docling_enabled=bool(getattr(settings, "DOCLING_ENABLED", False)),
            etl4llm_enabled=bool(getattr(settings, "ETL4LLM_ENABLED", False)),
            marker_enabled=bool(getattr(settings, "MARKER_ENABLED", False)),
            paddle_vl_enabled=bool(getattr(settings, "PADDLE_VL_ENABLED", False)),
            textin_enabled=bool(getattr(settings, "TEXTIN_ENABLED", False)),
            markitdown_enabled=settings.MARKITDOWN_ENABLED,
            llama_index_enabled=settings.LLAMA_INDEX_ENABLED,
            mineru_enabled=settings.MINERU_ENABLED,
            magicpdf_enabled=bool(getattr(settings, "MAGIC_PDF_ENABLED", False)),
        ),
        kg=KGConfig(
            chat_enabled=settings.KG_CHAT_ENABLED,
            extract_prompt_template_id=getattr(settings, "KG_EXTRACT_PROMPT_TEMPLATE_ID", "") or "",
            extract_prompt_template_key=getattr(settings, "KG_EXTRACT_PROMPT_TEMPLATE_KEY", "") or "",
            extract_prompt_ab_experiment_key=getattr(settings, "KG_EXTRACT_PROMPT_AB_EXPERIMENT_KEY", "") or "",
            extract_replace_existing=bool(getattr(settings, "KG_EXTRACT_REPLACE_EXISTING", True)),
            extract_prune_orphan_entities=bool(getattr(settings, "KG_EXTRACT_PRUNE_ORPHAN_ENTITIES", True)),
        ),
        llm=LLMConfig(
            api_key=mask_secret(settings.LLM_API_KEY),
            api_base=settings.LLM_API_BASE,
            model=settings.LLM_MODEL,
            temperature=settings.LLM_TEMPERATURE,
            timeout=settings.LLM_TIMEOUT,
            max_retries=settings.LLM_MAX_RETRIES,
        ),
        embedding=EmbeddingConfig(
            provider=settings.EMBEDDING_PROVIDER,
            model=settings.EMBEDDING_MODEL,
            api_key=mask_secret(settings.EMBEDDING_API_KEY),
            api_base=settings.EMBEDDING_API_BASE,
        ),
        milvus=MilvusConfig(
            host=settings.MILVUS_HOST,
            port=settings.MILVUS_PORT,
            user=settings.MILVUS_USER,
            password=mask_secret(settings.MILVUS_PASSWORD),
            collection_name=settings.MILVUS_COLLECTION_NAME,
        ),
        minio=MinioConfig(
            enabled=bool(getattr(settings, "MINIO_ENABLED", False)),
            endpoint=str(getattr(settings, "MINIO_ENDPOINT", "localhost:9000") or ""),
            access_key=mask_secret(str(getattr(settings, "MINIO_ACCESS_KEY", "") or "")),
            secret_key=mask_secret(str(getattr(settings, "MINIO_SECRET_KEY", "") or "")),
            bucket_name=str(getattr(settings, "MINIO_BUCKET_NAME", "mimirq") or "mimirq"),
            use_ssl=bool(getattr(settings, "MINIO_USE_SSL", False)),
            documents_enabled=bool(getattr(settings, "MINIO_DOCUMENTS_ENABLED", False)),
            image_max_bytes=int(getattr(settings, "MINIO_IMAGE_MAX_BYTES", 0) or 0),
        ),
        rag=RAGConfig(
            chunk_size=settings.CHUNK_SIZE,
            chunk_overlap=settings.CHUNK_OVERLAP,
            chunk_min_chars=int(getattr(settings, "CHUNK_MIN_CHARS", 0) or 0),
            retrieval_top_k=settings.RETRIEVAL_TOP_K,
            similarity_threshold=settings.SIMILARITY_THRESHOLD,
            default_parser_backend=settings.DEFAULT_PARSER_BACKEND,
            default_chunk_strategy=settings.DEFAULT_CHUNK_STRATEGY,
            bm25_index_enabled=bool(getattr(settings, "BM25_INDEX_ENABLED", True)),
            enable_reranker=bool(getattr(settings, "ENABLE_RERANKER", False)),
            reranker_provider=str(getattr(settings, "RERANKER_PROVIDER", "llm") or "llm"),
            reranker_top_n=int(getattr(settings, "RERANKER_TOP_N", 20) or 20),
            show_image_in_answer=bool(getattr(settings, "SHOW_IMAGE_IN_ANSWER", True)),
            image_append_max=int(getattr(settings, "IMAGE_APPEND_MAX", 3) or 0),
        ),
        cache=CacheConfig(
            upload_dedup_enabled=bool(getattr(settings, "UPLOAD_DEDUP_ENABLED", False)),
            chat_response_cache_enabled=bool(getattr(settings, "CHAT_RESPONSE_CACHE_ENABLED", False)),
            chat_response_cache_ttl_sec=int(getattr(settings, "CHAT_RESPONSE_CACHE_TTL_SEC", 300) or 0),
            chat_response_cache_max_value_bytes=int(
                getattr(settings, "CHAT_RESPONSE_CACHE_MAX_VALUE_BYTES", 200_000) or 0
            ),
            chat_response_cache_require_empty_history=bool(
                getattr(settings, "CHAT_RESPONSE_CACHE_REQUIRE_EMPTY_HISTORY", True)
            ),
        ),
        url_ingest=UrlIngestConfig(
            enabled=bool(getattr(settings, "URL_INGEST_ENABLED", False)),
            max_bytes=int(getattr(settings, "URL_INGEST_MAX_BYTES", 0) or 0),
            timeout_sec=float(getattr(settings, "URL_INGEST_TIMEOUT_SEC", 0.0) or 0.0),
            allow_private_ips=bool(getattr(settings, "URL_INGEST_ALLOW_PRIVATE_IPS", False)),
            follow_redirects=bool(getattr(settings, "URL_INGEST_FOLLOW_REDIRECTS", False)),
        ),
        governance=GovernanceConfig(
            enabled=bool(getattr(settings, "GOVERNANCE_ENABLED", False)),
            pii_anonymize=bool(getattr(settings, "GOVERNANCE_PII_ANONYMIZE", False)),
            secrets_redact=bool(getattr(settings, "GOVERNANCE_SECRETS_REDACT", False)),
            quarantine_on_drop=bool(getattr(settings, "GOVERNANCE_QUARANTINE_ON_DROP", False)),
        ),
        mineru=MinerUConfig(
            api_token=mask_secret(settings.MINERU_API_TOKEN),
            api_base=settings.MINERU_API_BASE,
            model_version=settings.MINERU_MODEL_VERSION,
            backend=_normalize_mineru_backend(getattr(settings, "MINERU_BACKEND", "pipeline")),
            local_server_url=str(getattr(settings, "MINERU_LOCAL_SERVER_URL", "") or ""),
            vl_server=str(getattr(settings, "MINERU_VL_SERVER", "") or ""),
        ),
        etl4llm=Etl4LlmConfig(
            api_url=getattr(settings, "ETL4LLM_API_URL", "") or "",
            timeout_sec=int(getattr(settings, "ETL4LLM_TIMEOUT_SEC", 120) or 120),
            mode=str(getattr(settings, "ETL4LLM_MODE", "partition") or "partition"),
            force_ocr=bool(getattr(settings, "ETL4LLM_FORCE_OCR", False)),
            enable_formula=bool(getattr(settings, "ETL4LLM_ENABLE_FORMULA", True)),
            extract_images=bool(getattr(settings, "ETL4LLM_EXTRACT_IMAGES", True)),
            filter_page_header_footer=bool(getattr(settings, "ETL4LLM_FILTER_PAGE_HEADER_FOOTER", False)),
        ),
        marker=MarkerConfig(
            api_url=str(getattr(settings, "MARKER_API_URL", "") or ""),
            timeout_sec=int(getattr(settings, "MARKER_TIMEOUT_SEC", 600) or 600),
        ),
        paddle_vl=PaddleVLConfig(
            api_url=str(getattr(settings, "PADDLE_VL_API_URL", "") or ""),
            timeout_sec=int(getattr(settings, "PADDLE_VL_TIMEOUT_SEC", 600) or 600),
            pipeline_version=str(getattr(settings, "PADDLE_VL_PIPELINE_VERSION", "v1.5") or "v1.5"),
            mode=str(getattr(settings, "PADDLE_VL_MODE", "doc_parser") or "doc_parser"),
        ),
        textin=TextInConfig(
            api_url=str(
                getattr(settings, "TEXTIN_API_URL", "") or "https://api.textin.com/ai/service/v1/pdf_to_markdown"
            ),
            app_id=str(getattr(settings, "TEXTIN_APP_ID", "") or ""),
            secret_code=mask_secret(str(getattr(settings, "TEXTIN_SECRET_CODE", "") or "")),
            timeout_sec=int(getattr(settings, "TEXTIN_TIMEOUT_SEC", 180) or 180),
            parse_mode=str(getattr(settings, "TEXTIN_PARSE_MODE", "auto") or "auto"),
            table_flavor=str(getattr(settings, "TEXTIN_TABLE_FLAVOR", "html") or "html"),
            apply_document_tree=bool(getattr(settings, "TEXTIN_APPLY_DOCUMENT_TREE", True)),
            markdown_details=bool(getattr(settings, "TEXTIN_MARKDOWN_DETAILS", True)),
            get_image=str(getattr(settings, "TEXTIN_GET_IMAGE", "none") or "none"),
            dpi=int(getattr(settings, "TEXTIN_DPI", 144) or 144),
            page_count=int(getattr(settings, "TEXTIN_PAGE_COUNT", 0) or 0),
        ),
        magicpdf=MagicPDFConfig(
            api_url=str(getattr(settings, "MAGIC_PDF_API_URL", "") or ""),
            request_timeout_sec=int(getattr(settings, "MAGIC_PDF_REQUEST_TIMEOUT_SEC", 600) or 600),
            max_concurrent_jobs=int(getattr(settings, "MAGIC_PDF_MAX_CONCURRENT_JOBS", 1) or 1),
            cli=getattr(settings, "MAGIC_PDF_CLI", "magic-pdf") or "magic-pdf",
            method=getattr(settings, "MAGIC_PDF_METHOD", "auto") or "auto",
            lang=getattr(settings, "MAGIC_PDF_LANG", "") or "",
            debug=bool(getattr(settings, "MAGIC_PDF_DEBUG", False)),
            timeout_sec=int(getattr(settings, "MAGIC_PDF_TIMEOUT_SEC", 600) or 600),
            models_dir=getattr(settings, "MAGIC_PDF_MODELS_DIR", "") or "",
            device_mode=getattr(settings, "MAGIC_PDF_DEVICE_MODE", "cpu") or "cpu",
            keep_artifacts=bool(getattr(settings, "MAGIC_PDF_KEEP_ARTIFACTS", False)),
        ),
        observability=ObservabilityConfig(
            tool_call_log_enabled=settings.TOOL_CALL_LOG_ENABLED,
            tool_call_log_include_preview=settings.TOOL_CALL_LOG_INCLUDE_PREVIEW,
            tool_call_log_max_preview_chars=settings.TOOL_CALL_LOG_MAX_PREVIEW_CHARS,
            agent_log_enabled=settings.AGENT_LOG_ENABLED,
            agent_log_include_execution_path=settings.AGENT_LOG_INCLUDE_EXECUTION_PATH,
            agent_log_max_preview_chars=settings.AGENT_LOG_MAX_PREVIEW_CHARS,
            metrics_log_enabled=bool(getattr(settings, "ENABLE_METRICS_LOG", False)),
            metrics_log_include_text=bool(getattr(settings, "METRICS_LOG_INCLUDE_TEXT", False)),
        ),
        safety=SafetyConfig(
            pii_redaction_enabled=settings.PII_REDACTION_ENABLED,
            pii_redaction_mask=settings.PII_REDACTION_MASK,
            pii_stream_holdback_chars=settings.PII_STREAM_HOLDBACK_CHARS,
        ),
        chat=ChatConfig(
            stream_heartbeat_sec=float(getattr(settings, "CHAT_STREAM_HEARTBEAT_SEC", 10.0) or 10.0),
            stream_cancel_on_disconnect=bool(getattr(settings, "CHAT_STREAM_CANCEL_ON_DISCONNECT", True)),
        ),
        langgraph=LangGraphConfig(
            use_subgraphs=settings.LANGGRAPH_USE_SUBGRAPHS,
        ),
        navigation=NavigationConfig(
            user_visible_modules=normalize_navigation_modules(
                getattr(settings, "NAVIGATION_USER_VISIBLE_MODULES", "") or ""
            ),
        ),
        dify_external_knowledge=DifyExternalKnowledgeConfig(
            enabled=bool(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", False)),
            api_keys=mask_secret(str(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", "") or "")),
            tenant_id=str(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_TENANT_ID", "") or ""),
            account_id=str(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "") or _SYSTEM_DIFY_ACCOUNT_ID),
            knowledge_map_json=str(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON", "") or ""),
            top_k_max=int(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_TOP_K_MAX", 5) or 5),
            endpoint_path="/api/v1/integrations/dify/retrieval",
        ),
    )


def _set_bool_env(env_vars: dict[str, str], key: str, value: Any) -> None:
    env_vars[key] = str(bool(value)).lower()


def _set_int_env(env_vars: dict[str, str], key: str, value: Any) -> None:
    env_vars[key] = str(int(value))


def _set_float_env(env_vars: dict[str, str], key: str, value: Any) -> None:
    env_vars[key] = str(float(value))


def _set_non_negative_int_env(env_vars: dict[str, str], key: str, value: Any) -> None:
    env_vars[key] = str(max(0, int(value or 0)))


def _set_sanitized_env(env_vars: dict[str, str], key: str, value: Any) -> None:
    env_vars[key] = _sanitize_env_value(key, value)


def _set_maskable_secret_env(env_vars: dict[str, str], updated_keys: list[str], key: str, value: str) -> None:
    if value and "***" not in value:
        env_vars[key] = _sanitize_env_value(key, value)
        updated_keys.append(key)


def _normalize_choice(value: str, *, default: str, allowed: set[str]) -> str:
    normalized = (value or default).strip().lower() or default
    if normalized not in allowed:
        return default
    return normalized


def _validate_optional_uuid_setting(key: str, value: str, *, detail: str) -> str:
    sanitized = _sanitize_env_value(key, value or "")
    if sanitized:
        try:
            UUID(sanitized)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=detail) from exc
    return sanitized


def _validate_json_object_setting(
    key: str,
    value: str,
    *,
    invalid_detail: str,
    non_object_detail: str,
) -> str:
    sanitized = _sanitize_env_value(key, value or "")
    if not sanitized:
        return sanitized
    try:
        parsed = json.loads(sanitized)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=invalid_detail) from exc
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=400, detail=non_object_detail)
    return sanitized


def _update_feature_flag_env(env_vars: dict[str, str], updated_keys: list[str], feature_flags: FeatureFlags) -> None:
    values = (
        ("KG_ENABLED", feature_flags.kg_enabled),
        ("DEEPDOC_ENABLED", feature_flags.deepdoc_enabled),
        ("DOCLING_ENABLED", getattr(feature_flags, "docling_enabled", False)),
        ("ETL4LLM_ENABLED", getattr(feature_flags, "etl4llm_enabled", False)),
        ("MARKER_ENABLED", getattr(feature_flags, "marker_enabled", False)),
        ("PADDLE_VL_ENABLED", getattr(feature_flags, "paddle_vl_enabled", False)),
        ("TEXTIN_ENABLED", getattr(feature_flags, "textin_enabled", False)),
        ("MARKITDOWN_ENABLED", feature_flags.markitdown_enabled),
        ("LLAMA_INDEX_ENABLED", feature_flags.llama_index_enabled),
        ("MINERU_ENABLED", feature_flags.mineru_enabled),
        ("MAGIC_PDF_ENABLED", getattr(feature_flags, "magicpdf_enabled", False)),
    )
    for key, value in values:
        _set_bool_env(env_vars, key, value)
    updated_keys.extend(key for key, _value in values)


def _update_kg_env(env_vars: dict[str, str], updated_keys: list[str], kg: KGConfig) -> None:
    _set_bool_env(env_vars, "KG_CHAT_ENABLED", kg.chat_enabled)
    env_vars["KG_EXTRACT_PROMPT_TEMPLATE_ID"] = _validate_optional_uuid_setting(
        "KG_EXTRACT_PROMPT_TEMPLATE_ID",
        kg.extract_prompt_template_id or "",
        detail="Invalid KG_EXTRACT_PROMPT_TEMPLATE_ID",
    )
    _set_sanitized_env(env_vars, "KG_EXTRACT_PROMPT_TEMPLATE_KEY", kg.extract_prompt_template_key or "")
    _set_sanitized_env(env_vars, "KG_EXTRACT_PROMPT_AB_EXPERIMENT_KEY", kg.extract_prompt_ab_experiment_key or "")
    _set_bool_env(env_vars, "KG_EXTRACT_REPLACE_EXISTING", getattr(kg, "extract_replace_existing", True))
    _set_bool_env(env_vars, "KG_EXTRACT_PRUNE_ORPHAN_ENTITIES", getattr(kg, "extract_prune_orphan_entities", True))
    updated_keys.extend(
        [
            "KG_CHAT_ENABLED",
            "KG_EXTRACT_PROMPT_TEMPLATE_ID",
            "KG_EXTRACT_PROMPT_TEMPLATE_KEY",
            "KG_EXTRACT_PROMPT_AB_EXPERIMENT_KEY",
            "KG_EXTRACT_REPLACE_EXISTING",
            "KG_EXTRACT_PRUNE_ORPHAN_ENTITIES",
        ]
    )


def _update_llm_env(env_vars: dict[str, str], updated_keys: list[str], llm: LLMConfig) -> None:
    _set_maskable_secret_env(env_vars, updated_keys, "LLM_API_KEY", llm.api_key)
    _set_sanitized_env(env_vars, "LLM_API_BASE", llm.api_base)
    _set_sanitized_env(env_vars, "LLM_MODEL", llm.model)
    env_vars["LLM_TEMPERATURE"] = str(llm.temperature)
    env_vars["LLM_TIMEOUT"] = str(llm.timeout)
    env_vars["LLM_MAX_RETRIES"] = str(llm.max_retries)
    updated_keys.extend(["LLM_API_BASE", "LLM_MODEL", "LLM_TEMPERATURE", "LLM_TIMEOUT", "LLM_MAX_RETRIES"])


def _update_embedding_env(env_vars: dict[str, str], updated_keys: list[str], embedding: EmbeddingConfig) -> None:
    _set_sanitized_env(env_vars, "EMBEDDING_PROVIDER", embedding.provider)
    _set_sanitized_env(env_vars, "EMBEDDING_MODEL", embedding.model)
    _set_maskable_secret_env(env_vars, updated_keys, "EMBEDDING_API_KEY", embedding.api_key)
    _set_sanitized_env(env_vars, "EMBEDDING_API_BASE", embedding.api_base)
    updated_keys.extend(["EMBEDDING_PROVIDER", "EMBEDDING_MODEL", "EMBEDDING_API_BASE"])


def _update_milvus_env(env_vars: dict[str, str], updated_keys: list[str], milvus: MilvusConfig) -> None:
    _set_sanitized_env(env_vars, "MILVUS_HOST", milvus.host)
    env_vars["MILVUS_PORT"] = str(milvus.port)
    _set_sanitized_env(env_vars, "MILVUS_USER", milvus.user)
    _set_maskable_secret_env(env_vars, updated_keys, "MILVUS_PASSWORD", milvus.password)
    _set_sanitized_env(env_vars, "MILVUS_COLLECTION_NAME", milvus.collection_name)
    updated_keys.extend(["MILVUS_HOST", "MILVUS_PORT", "MILVUS_USER", "MILVUS_COLLECTION_NAME"])


def _update_minio_env(env_vars: dict[str, str], updated_keys: list[str], minio: MinioConfig) -> None:
    _set_bool_env(env_vars, "MINIO_ENABLED", minio.enabled)
    _set_sanitized_env(env_vars, "MINIO_ENDPOINT", minio.endpoint)
    _set_maskable_secret_env(env_vars, updated_keys, "MINIO_ACCESS_KEY", minio.access_key)
    _set_maskable_secret_env(env_vars, updated_keys, "MINIO_SECRET_KEY", minio.secret_key)
    _set_sanitized_env(env_vars, "MINIO_BUCKET_NAME", minio.bucket_name)
    _set_bool_env(env_vars, "MINIO_USE_SSL", minio.use_ssl)
    _set_bool_env(env_vars, "MINIO_DOCUMENTS_ENABLED", minio.documents_enabled)
    _set_non_negative_int_env(env_vars, "MINIO_IMAGE_MAX_BYTES", minio.image_max_bytes)
    updated_keys.extend(
        [
            "MINIO_ENABLED",
            "MINIO_ENDPOINT",
            "MINIO_BUCKET_NAME",
            "MINIO_USE_SSL",
            "MINIO_DOCUMENTS_ENABLED",
            "MINIO_IMAGE_MAX_BYTES",
        ]
    )


def _update_rag_env(env_vars: dict[str, str], updated_keys: list[str], rag: RAGConfig) -> None:
    env_vars["CHUNK_SIZE"] = str(rag.chunk_size)
    env_vars["CHUNK_OVERLAP"] = str(rag.chunk_overlap)
    _set_non_negative_int_env(env_vars, "CHUNK_MIN_CHARS", getattr(rag, "chunk_min_chars", 0))
    env_vars["RETRIEVAL_TOP_K"] = str(rag.retrieval_top_k)
    env_vars["SIMILARITY_THRESHOLD"] = str(rag.similarity_threshold)
    _set_sanitized_env(env_vars, "DEFAULT_PARSER_BACKEND", rag.default_parser_backend)
    _set_sanitized_env(env_vars, "DEFAULT_CHUNK_STRATEGY", rag.default_chunk_strategy)
    _set_bool_env(env_vars, "BM25_INDEX_ENABLED", getattr(rag, "bm25_index_enabled", True))
    _set_bool_env(env_vars, "ENABLE_RERANKER", getattr(rag, "enable_reranker", False))
    _set_sanitized_env(env_vars, "RERANKER_PROVIDER", rag.reranker_provider)
    env_vars["RERANKER_TOP_N"] = str(int(getattr(rag, "reranker_top_n", 20) or 20))
    _set_bool_env(env_vars, "SHOW_IMAGE_IN_ANSWER", getattr(rag, "show_image_in_answer", True))
    env_vars["IMAGE_APPEND_MAX"] = str(max(0, min(10, int(getattr(rag, "image_append_max", 3) or 0))))
    updated_keys.extend(
        [
            "CHUNK_SIZE",
            "CHUNK_OVERLAP",
            "CHUNK_MIN_CHARS",
            "RETRIEVAL_TOP_K",
            "SIMILARITY_THRESHOLD",
            "DEFAULT_PARSER_BACKEND",
            "DEFAULT_CHUNK_STRATEGY",
            "BM25_INDEX_ENABLED",
            "ENABLE_RERANKER",
            "RERANKER_PROVIDER",
            "RERANKER_TOP_N",
            "SHOW_IMAGE_IN_ANSWER",
            "IMAGE_APPEND_MAX",
        ]
    )


def _update_cache_env(env_vars: dict[str, str], updated_keys: list[str], cache: CacheConfig) -> None:
    _set_bool_env(env_vars, "UPLOAD_DEDUP_ENABLED", getattr(cache, "upload_dedup_enabled", False))
    _set_bool_env(env_vars, "CHAT_RESPONSE_CACHE_ENABLED", getattr(cache, "chat_response_cache_enabled", False))
    env_vars["CHAT_RESPONSE_CACHE_TTL_SEC"] = str(int(getattr(cache, "chat_response_cache_ttl_sec", 0) or 0))
    env_vars["CHAT_RESPONSE_CACHE_MAX_VALUE_BYTES"] = str(
        int(getattr(cache, "chat_response_cache_max_value_bytes", 0) or 0)
    )
    _set_bool_env(
        env_vars,
        "CHAT_RESPONSE_CACHE_REQUIRE_EMPTY_HISTORY",
        getattr(cache, "chat_response_cache_require_empty_history", True),
    )
    updated_keys.extend(
        [
            "UPLOAD_DEDUP_ENABLED",
            "CHAT_RESPONSE_CACHE_ENABLED",
            "CHAT_RESPONSE_CACHE_TTL_SEC",
            "CHAT_RESPONSE_CACHE_MAX_VALUE_BYTES",
            "CHAT_RESPONSE_CACHE_REQUIRE_EMPTY_HISTORY",
        ]
    )


def _update_url_ingest_env(env_vars: dict[str, str], updated_keys: list[str], url_ingest: UrlIngestConfig) -> None:
    _set_bool_env(env_vars, "URL_INGEST_ENABLED", url_ingest.enabled)
    _set_int_env(env_vars, "URL_INGEST_MAX_BYTES", getattr(url_ingest, "max_bytes", 0) or 0)
    _set_float_env(env_vars, "URL_INGEST_TIMEOUT_SEC", getattr(url_ingest, "timeout_sec", 0.0) or 0.0)
    _set_bool_env(env_vars, "URL_INGEST_ALLOW_PRIVATE_IPS", getattr(url_ingest, "allow_private_ips", False))
    _set_bool_env(env_vars, "URL_INGEST_FOLLOW_REDIRECTS", getattr(url_ingest, "follow_redirects", False))
    updated_keys.extend(
        [
            "URL_INGEST_ENABLED",
            "URL_INGEST_MAX_BYTES",
            "URL_INGEST_TIMEOUT_SEC",
            "URL_INGEST_ALLOW_PRIVATE_IPS",
            "URL_INGEST_FOLLOW_REDIRECTS",
        ]
    )


def _update_governance_env(env_vars: dict[str, str], updated_keys: list[str], governance: GovernanceConfig) -> None:
    _set_bool_env(env_vars, "GOVERNANCE_ENABLED", getattr(governance, "enabled", False))
    _set_bool_env(env_vars, "GOVERNANCE_PII_ANONYMIZE", getattr(governance, "pii_anonymize", False))
    _set_bool_env(env_vars, "GOVERNANCE_SECRETS_REDACT", getattr(governance, "secrets_redact", False))
    _set_bool_env(env_vars, "GOVERNANCE_QUARANTINE_ON_DROP", getattr(governance, "quarantine_on_drop", False))
    updated_keys.extend(
        [
            "GOVERNANCE_ENABLED",
            "GOVERNANCE_PII_ANONYMIZE",
            "GOVERNANCE_SECRETS_REDACT",
            "GOVERNANCE_QUARANTINE_ON_DROP",
        ]
    )


def _update_mineru_env(env_vars: dict[str, str], updated_keys: list[str], mineru: MinerUConfig) -> None:
    _set_maskable_secret_env(env_vars, updated_keys, "MINERU_API_TOKEN", mineru.api_token)
    _set_sanitized_env(env_vars, "MINERU_API_BASE", mineru.api_base)
    _set_sanitized_env(env_vars, "MINERU_MODEL_VERSION", mineru.model_version)
    env_vars["MINERU_BACKEND"] = _normalize_mineru_backend(mineru.backend)
    _set_sanitized_env(env_vars, "MINERU_LOCAL_SERVER_URL", mineru.local_server_url)
    _set_sanitized_env(env_vars, "MINERU_VL_SERVER", mineru.vl_server)
    updated_keys.extend(
        [
            "MINERU_API_BASE",
            "MINERU_MODEL_VERSION",
            "MINERU_BACKEND",
            "MINERU_LOCAL_SERVER_URL",
            "MINERU_VL_SERVER",
        ]
    )


def _update_etl4llm_env(env_vars: dict[str, str], updated_keys: list[str], etl4llm: Etl4LlmConfig) -> None:
    _set_sanitized_env(env_vars, "ETL4LLM_API_URL", etl4llm.api_url or "")
    env_vars["ETL4LLM_TIMEOUT_SEC"] = str(int(etl4llm.timeout_sec or 0))
    env_vars["ETL4LLM_MODE"] = _sanitize_env_value(
        "ETL4LLM_MODE",
        _normalize_choice(etl4llm.mode or "partition", default="partition", allowed={"partition", "text"}),
    )
    _set_bool_env(env_vars, "ETL4LLM_FORCE_OCR", etl4llm.force_ocr)
    _set_bool_env(env_vars, "ETL4LLM_ENABLE_FORMULA", etl4llm.enable_formula)
    _set_bool_env(env_vars, "ETL4LLM_EXTRACT_IMAGES", etl4llm.extract_images)
    _set_bool_env(env_vars, "ETL4LLM_FILTER_PAGE_HEADER_FOOTER", etl4llm.filter_page_header_footer)
    updated_keys.extend(
        [
            "ETL4LLM_API_URL",
            "ETL4LLM_TIMEOUT_SEC",
            "ETL4LLM_MODE",
            "ETL4LLM_FORCE_OCR",
            "ETL4LLM_ENABLE_FORMULA",
            "ETL4LLM_EXTRACT_IMAGES",
            "ETL4LLM_FILTER_PAGE_HEADER_FOOTER",
        ]
    )


def _update_marker_env(env_vars: dict[str, str], updated_keys: list[str], marker: MarkerConfig) -> None:
    _set_sanitized_env(env_vars, "MARKER_API_URL", marker.api_url or "")
    env_vars["MARKER_TIMEOUT_SEC"] = str(int(marker.timeout_sec or 0))
    updated_keys.extend(["MARKER_API_URL", "MARKER_TIMEOUT_SEC"])


def _update_paddle_vl_env(env_vars: dict[str, str], updated_keys: list[str], paddle_vl: PaddleVLConfig) -> None:
    _set_sanitized_env(env_vars, "PADDLE_VL_API_URL", paddle_vl.api_url or "")
    env_vars["PADDLE_VL_TIMEOUT_SEC"] = str(int(paddle_vl.timeout_sec or 0))
    pipeline_version = (paddle_vl.pipeline_version or "v1.5").strip() or "v1.5"
    env_vars["PADDLE_VL_PIPELINE_VERSION"] = _sanitize_env_value("PADDLE_VL_PIPELINE_VERSION", pipeline_version)
    env_vars["PADDLE_VL_MODE"] = _sanitize_env_value(
        "PADDLE_VL_MODE",
        _normalize_choice(paddle_vl.mode or "doc_parser", default="doc_parser", allowed={"doc_parser"}),
    )
    updated_keys.extend(["PADDLE_VL_API_URL", "PADDLE_VL_TIMEOUT_SEC", "PADDLE_VL_PIPELINE_VERSION", "PADDLE_VL_MODE"])


def _update_textin_env(env_vars: dict[str, str], updated_keys: list[str], textin: TextInConfig) -> None:
    _set_sanitized_env(env_vars, "TEXTIN_API_URL", textin.api_url or "")
    _set_sanitized_env(env_vars, "TEXTIN_APP_ID", textin.app_id or "")
    _set_maskable_secret_env(env_vars, updated_keys, "TEXTIN_SECRET_CODE", textin.secret_code or "")
    env_vars["TEXTIN_TIMEOUT_SEC"] = str(int(textin.timeout_sec or 0))
    env_vars["TEXTIN_PARSE_MODE"] = _sanitize_env_value(
        "TEXTIN_PARSE_MODE",
        _normalize_choice(
            textin.parse_mode or "auto", default="auto", allowed={"auto", "scan", "parse", "lite", "vlm"}
        ),
    )
    env_vars["TEXTIN_TABLE_FLAVOR"] = _sanitize_env_value(
        "TEXTIN_TABLE_FLAVOR",
        _normalize_choice(textin.table_flavor or "html", default="html", allowed={"html", "markdown"}),
    )
    env_vars["TEXTIN_GET_IMAGE"] = _sanitize_env_value(
        "TEXTIN_GET_IMAGE",
        _normalize_choice(textin.get_image or "none", default="none", allowed={"none", "objects", "pages", "both"}),
    )
    _set_bool_env(env_vars, "TEXTIN_APPLY_DOCUMENT_TREE", textin.apply_document_tree)
    _set_bool_env(env_vars, "TEXTIN_MARKDOWN_DETAILS", textin.markdown_details)
    _set_non_negative_int_env(env_vars, "TEXTIN_DPI", textin.dpi)
    _set_non_negative_int_env(env_vars, "TEXTIN_PAGE_COUNT", textin.page_count)
    updated_keys.extend(
        [
            "TEXTIN_API_URL",
            "TEXTIN_APP_ID",
            "TEXTIN_TIMEOUT_SEC",
            "TEXTIN_PARSE_MODE",
            "TEXTIN_TABLE_FLAVOR",
            "TEXTIN_GET_IMAGE",
            "TEXTIN_APPLY_DOCUMENT_TREE",
            "TEXTIN_MARKDOWN_DETAILS",
            "TEXTIN_DPI",
            "TEXTIN_PAGE_COUNT",
        ]
    )


def _update_magicpdf_env(env_vars: dict[str, str], updated_keys: list[str], magicpdf: MagicPDFConfig) -> None:
    _set_sanitized_env(env_vars, "MAGIC_PDF_API_URL", magicpdf.api_url)
    env_vars["MAGIC_PDF_REQUEST_TIMEOUT_SEC"] = str(max(1, int(magicpdf.request_timeout_sec or 0)))
    env_vars["MAGIC_PDF_MAX_CONCURRENT_JOBS"] = str(max(1, int(magicpdf.max_concurrent_jobs or 1)))
    _set_sanitized_env(env_vars, "MAGIC_PDF_CLI", magicpdf.cli)
    _set_sanitized_env(env_vars, "MAGIC_PDF_METHOD", magicpdf.method)
    _set_sanitized_env(env_vars, "MAGIC_PDF_LANG", magicpdf.lang)
    _set_bool_env(env_vars, "MAGIC_PDF_DEBUG", magicpdf.debug)
    env_vars["MAGIC_PDF_TIMEOUT_SEC"] = str(int(magicpdf.timeout_sec or 0))
    _set_sanitized_env(env_vars, "MAGIC_PDF_MODELS_DIR", magicpdf.models_dir)
    _set_sanitized_env(env_vars, "MAGIC_PDF_DEVICE_MODE", magicpdf.device_mode)
    _set_bool_env(env_vars, "MAGIC_PDF_KEEP_ARTIFACTS", magicpdf.keep_artifacts)
    updated_keys.extend(
        [
            "MAGIC_PDF_API_URL",
            "MAGIC_PDF_REQUEST_TIMEOUT_SEC",
            "MAGIC_PDF_MAX_CONCURRENT_JOBS",
            "MAGIC_PDF_CLI",
            "MAGIC_PDF_METHOD",
            "MAGIC_PDF_LANG",
            "MAGIC_PDF_DEBUG",
            "MAGIC_PDF_TIMEOUT_SEC",
            "MAGIC_PDF_MODELS_DIR",
            "MAGIC_PDF_DEVICE_MODE",
            "MAGIC_PDF_KEEP_ARTIFACTS",
        ]
    )


def _update_observability_env(
    env_vars: dict[str, str],
    updated_keys: list[str],
    observability: ObservabilityConfig,
) -> None:
    _set_bool_env(env_vars, "TOOL_CALL_LOG_ENABLED", observability.tool_call_log_enabled)
    _set_bool_env(env_vars, "TOOL_CALL_LOG_INCLUDE_PREVIEW", observability.tool_call_log_include_preview)
    env_vars["TOOL_CALL_LOG_MAX_PREVIEW_CHARS"] = str(int(observability.tool_call_log_max_preview_chars or 0))
    _set_bool_env(env_vars, "AGENT_LOG_ENABLED", observability.agent_log_enabled)
    _set_bool_env(env_vars, "AGENT_LOG_INCLUDE_EXECUTION_PATH", observability.agent_log_include_execution_path)
    env_vars["AGENT_LOG_MAX_PREVIEW_CHARS"] = str(int(observability.agent_log_max_preview_chars or 0))
    updated_keys.extend(
        [
            "TOOL_CALL_LOG_ENABLED",
            "TOOL_CALL_LOG_INCLUDE_PREVIEW",
            "TOOL_CALL_LOG_MAX_PREVIEW_CHARS",
            "AGENT_LOG_ENABLED",
            "AGENT_LOG_INCLUDE_EXECUTION_PATH",
            "AGENT_LOG_MAX_PREVIEW_CHARS",
        ]
    )
    model_fields_set = getattr(observability, "model_fields_set", set())
    if "metrics_log_enabled" in model_fields_set:
        _set_bool_env(env_vars, "ENABLE_METRICS_LOG", getattr(observability, "metrics_log_enabled", False))
        updated_keys.append("ENABLE_METRICS_LOG")
    if "metrics_log_include_text" in model_fields_set:
        _set_bool_env(env_vars, "METRICS_LOG_INCLUDE_TEXT", getattr(observability, "metrics_log_include_text", False))
        updated_keys.append("METRICS_LOG_INCLUDE_TEXT")


def _update_safety_env(env_vars: dict[str, str], updated_keys: list[str], safety: SafetyConfig) -> None:
    _set_bool_env(env_vars, "PII_REDACTION_ENABLED", safety.pii_redaction_enabled)
    _set_sanitized_env(env_vars, "PII_REDACTION_MASK", safety.pii_redaction_mask)
    env_vars["PII_STREAM_HOLDBACK_CHARS"] = str(int(safety.pii_stream_holdback_chars or 0))
    updated_keys.extend(["PII_REDACTION_ENABLED", "PII_REDACTION_MASK", "PII_STREAM_HOLDBACK_CHARS"])


def _update_chat_env(env_vars: dict[str, str], updated_keys: list[str], chat: ChatConfig) -> None:
    model_fields_set = getattr(chat, "model_fields_set", set())
    if "stream_heartbeat_sec" in model_fields_set:
        env_vars["CHAT_STREAM_HEARTBEAT_SEC"] = str(float(chat.stream_heartbeat_sec or 0.0))
        updated_keys.append("CHAT_STREAM_HEARTBEAT_SEC")
    if "stream_cancel_on_disconnect" in model_fields_set:
        _set_bool_env(env_vars, "CHAT_STREAM_CANCEL_ON_DISCONNECT", chat.stream_cancel_on_disconnect)
        updated_keys.append("CHAT_STREAM_CANCEL_ON_DISCONNECT")


def _update_langgraph_env(env_vars: dict[str, str], updated_keys: list[str], langgraph: LangGraphConfig) -> None:
    _set_bool_env(env_vars, "LANGGRAPH_USE_SUBGRAPHS", langgraph.use_subgraphs)
    updated_keys.append("LANGGRAPH_USE_SUBGRAPHS")


def _update_navigation_env(env_vars: dict[str, str], updated_keys: list[str], navigation: NavigationConfig) -> None:
    env_vars["NAVIGATION_USER_VISIBLE_MODULES"] = serialize_navigation_modules(navigation.user_visible_modules)
    updated_keys.append("NAVIGATION_USER_VISIBLE_MODULES")


def _update_dify_external_knowledge_env(
    env_vars: dict[str, str],
    updated_keys: list[str],
    dify_external_knowledge: DifyExternalKnowledgeConfig,
) -> None:
    _set_bool_env(env_vars, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", dify_external_knowledge.enabled)
    updated_keys.append("DIFY_EXTERNAL_KNOWLEDGE_ENABLED")
    _set_maskable_secret_env(
        env_vars,
        updated_keys,
        "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS",
        dify_external_knowledge.api_keys,
    )
    env_vars["DIFY_EXTERNAL_KNOWLEDGE_TENANT_ID"] = _validate_optional_uuid_setting(
        "DIFY_EXTERNAL_KNOWLEDGE_TENANT_ID",
        dify_external_knowledge.tenant_id or "",
        detail="Invalid DIFY_EXTERNAL_KNOWLEDGE_TENANT_ID",
    )
    _set_sanitized_env(
        env_vars,
        "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID",
        dify_external_knowledge.account_id or _SYSTEM_DIFY_ACCOUNT_ID,
    )
    env_vars["DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON"] = _validate_json_object_setting(
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        dify_external_knowledge.knowledge_map_json or "",
        invalid_detail="Invalid DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        non_object_detail="DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON must be a JSON object",
    )
    top_k_max = int(dify_external_knowledge.top_k_max or 5)
    if top_k_max < 1 or top_k_max > 200:
        raise HTTPException(status_code=400, detail="DIFY_EXTERNAL_KNOWLEDGE_TOP_K_MAX must be between 1 and 200")
    env_vars["DIFY_EXTERNAL_KNOWLEDGE_TOP_K_MAX"] = str(top_k_max)
    updated_keys.extend(
        [
            "DIFY_EXTERNAL_KNOWLEDGE_TENANT_ID",
            "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID",
            "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
            "DIFY_EXTERNAL_KNOWLEDGE_TOP_K_MAX",
        ]
    )


def _apply_request_settings_updates(
    request: UpdateSettingsRequest,
    env_vars: dict[str, str],
    updated_keys: list[str],
) -> None:
    updaters = (
        ("feature_flags", _update_feature_flag_env),
        ("kg", _update_kg_env),
        ("llm", _update_llm_env),
        ("embedding", _update_embedding_env),
        ("milvus", _update_milvus_env),
        ("minio", _update_minio_env),
        ("rag", _update_rag_env),
        ("cache", _update_cache_env),
        ("url_ingest", _update_url_ingest_env),
        ("governance", _update_governance_env),
        ("mineru", _update_mineru_env),
        ("etl4llm", _update_etl4llm_env),
        ("marker", _update_marker_env),
        ("paddle_vl", _update_paddle_vl_env),
        ("textin", _update_textin_env),
        ("magicpdf", _update_magicpdf_env),
        ("observability", _update_observability_env),
        ("safety", _update_safety_env),
        ("chat", _update_chat_env),
        ("langgraph", _update_langgraph_env),
        ("navigation", _update_navigation_env),
        ("dify_external_knowledge", _update_dify_external_knowledge_env),
    )
    for field_name, updater in updaters:
        section = getattr(request, field_name)
        if section is not None:
            updater(env_vars, updated_keys, section)


@router.put("", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def update_settings(
    request: UpdateSettingsRequest,
    http_request: Request,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Update system config (write .env file)."""
    if not bool(getattr(settings, "SETTINGS_ENV_WRITE_ENABLED", True)):
        raise HTTPException(
            status_code=403,
            detail="Settings writes are disabled. Set SETTINGS_ENV_WRITE_ENABLED=true to allow updating .env.",
        )
    _ensure_settings_writable(db, tenant_id, account_id)
    lock_ctx = _env_file_lock()
    lock_ctx.__enter__()
    try:
        env_vars = read_env_file()
        updated_keys = []
        _apply_request_settings_updates(request, env_vars, updated_keys)

        write_env_file(env_vars)
        with contextlib.suppress(Exception):
            # Best-effort, PII-minimal audit record (no secret values).
            from app.services.audit_log_service import audit_log_event

            request_id = (
                (http_request.headers.get("X-Request-ID") or "").strip()
                or str(getattr(http_request.state, "request_id", "") or "").strip()
                or None
            )

            ip = None
            with contextlib.suppress(Exception):
                ip = str(getattr(getattr(http_request, "client", None), "host", "") or "").strip() or None

            user_agent = (http_request.headers.get("User-Agent") or "").strip() or None

            audit_log_event(
                db,
                tenant_id=tenant_id,
                actor_id=account_id,
                action="settings.update",
                resource_type="settings",
                resource_id="env",
                request_id=request_id,
                ip=ip,
                user_agent=user_agent,
                details={"updated_keys": list(dict.fromkeys(updated_keys))},
            )
            with contextlib.suppress(Exception):
                db.commit()
        with contextlib.suppress(Exception):
            # Best-effort only.
            _apply_runtime_settings(env_vars, updated_keys)
        if request.llm is not None:
            # RAG engine caches LLM clients; reset so new settings take effect.
            with contextlib.suppress(Exception):
                from app.rag.engine import reset_rag_engine

                reset_rag_engine()

        return {
            "success": True,
            "message": "配置已保存，大多数修改会影响后续请求；外部解析器仍需对应服务已启动。",
            "updated_keys": updated_keys,
        }
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to save configuration: {str(e)}") from e
    finally:
        with contextlib.suppress(Exception):
            lock_ctx.__exit__(None, None, None)


def _check_status_import(module: str) -> tuple[bool, str]:
    try:
        spec = importlib.util.find_spec(module)
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)[:120]
    if spec is None:
        return False, "not installed"
    return True, "ok"


def _configured_status_message(enabled: bool, configured: bool, missing_message: str) -> str:
    if enabled and configured:
        return "configured"
    if enabled:
        return missing_message
    return "disabled"


def _health_not_ok_status_message(data: dict[str, Any]) -> str:
    reason = data.get("reason") or data.get("error") or data.get("message") or "health_not_ok"
    return f"configured (health_not_ok: {str(reason)[:120]})"


def _configured_parts_message(*parts: Any) -> str | None:
    text_parts = [part for part in parts if isinstance(part, str) and part.strip()]
    if not text_parts:
        return None
    return f"configured ({', '.join(text_parts[:2])})"


def _build_import_parser_status(module: str, *, enabled: bool, available_message: str) -> dict[str, object]:
    available, message = _check_status_import(module)
    return {
        "enabled": enabled,
        "available": available,
        "message": available_message if available else message,
    }


def _build_cli_parser_status(enabled: bool, cli: str) -> dict[str, object]:
    cli_ok = bool(cli)
    return {
        "enabled": enabled,
        "available": bool(enabled and cli_ok),
        "message": _configured_status_message(enabled, cli_ok, f"missing cli: {cli}"),
    }


def _build_configured_parser_status(enabled: bool, configured: bool, missing_message: str) -> dict[str, object]:
    return {
        "enabled": enabled,
        "available": bool(enabled and configured),
        "message": _configured_status_message(enabled, configured, missing_message),
    }


async def _build_probed_parser_status(
    *,
    enabled: bool,
    api_url: str,
    success_message_builder: Callable[[dict[str, Any]], str | None] | None = None,
) -> dict[str, object]:
    url_ok = bool(api_url)
    entry: dict[str, object] = _build_configured_parser_status(enabled, url_ok, _MISSING_API_URL_MESSAGE)
    if not (enabled and url_ok):
        return entry

    health_url = _convert_service_url_to_health_url(api_url)
    data, err = await _probe_http_json(health_url, timeout_sec=0.6)
    if data is None:
        entry["health"] = {"ok": False, "error": err}
        entry["available"] = False
        entry["message"] = _CONFIGURED_HEALTH_UNREACHABLE_MESSAGE
        return entry

    entry["health"] = data
    if data.get("ok") is False:
        entry["available"] = False
        entry["message"] = _health_not_ok_status_message(data)
        return entry

    if success_message_builder is not None:
        message = success_message_builder(data)
        if message:
            entry["message"] = message
    return entry


def _build_textin_parser_status() -> dict[str, object]:
    textin_enabled = bool(getattr(settings, "TEXTIN_ENABLED", False))
    textin_api_url = bool((getattr(settings, "TEXTIN_API_URL", "") or "").strip())
    textin_app_id = bool((getattr(settings, "TEXTIN_APP_ID", "") or "").strip())
    textin_secret = bool((getattr(settings, "TEXTIN_SECRET_CODE", "") or "").strip())
    if not textin_enabled:
        message = "disabled"
    elif not textin_api_url:
        message = "missing api_url"
    elif not textin_app_id:
        message = "missing app_id"
    elif not textin_secret:
        message = "missing secret_code"
    else:
        message = "configured"
    return {
        "enabled": textin_enabled,
        "available": bool(textin_enabled and textin_api_url and textin_app_id and textin_secret),
        "message": message,
    }


def _build_mineru_parser_status() -> dict[str, object]:
    mineru_enabled = bool(getattr(settings, "MINERU_ENABLED", False))
    mineru_local = bool((getattr(settings, "MINERU_LOCAL_SERVER_URL", "") or "").strip())
    mineru_token = (getattr(settings, "MINERU_API_TOKEN", "") or "").strip()
    mineru_exp = try_get_jwt_exp(mineru_token) if mineru_token else None
    mineru_token_expired = bool(mineru_exp is not None and int(mineru_exp) <= int(time.time()))
    if not mineru_enabled:
        message = "disabled"
    elif mineru_local:
        message = "configured (local)"
    elif not mineru_token:
        message = "missing api_token or local_server_url"
    elif mineru_token_expired and mineru_exp is not None:
        message = f"api_token expired at {format_unix_ts_utc(int(mineru_exp))}"
    else:
        message = "configured"
    return {
        "enabled": mineru_enabled,
        "available": bool(mineru_enabled and (mineru_local or (mineru_token and not mineru_token_expired))),
        "message": message,
    }


def _build_magicpdf_parser_status(
    *,
    resolve_cli_command: Callable[[str], str | None],
    resolve_magicpdf_models_dir: Callable[[str], str | None],
) -> dict[str, object]:
    enabled = bool(getattr(settings, "MAGIC_PDF_ENABLED", False))
    api_url = (getattr(settings, "MAGIC_PDF_API_URL", "") or "").strip()
    cli = (getattr(settings, "MAGIC_PDF_CLI", "") or "magic-pdf").strip() or "magic-pdf"
    cli_ok = bool(resolve_cli_command(cli))
    models_dir = resolve_magicpdf_models_dir(getattr(settings, "MAGIC_PDF_MODELS_DIR", ""))
    if not enabled:
        message = "disabled"
        available = False
    elif api_url:
        message = "configured (service)"
        available = True
    elif not cli_ok:
        message = f"missing cli: {cli}"
        available = False
    elif models_dir is None:
        message = "missing models"
        available = False
    else:
        message = f"configured (models: {models_dir})"
        available = True
    return {
        "enabled": enabled,
        "available": available,
        "message": message,
    }


async def _build_parser_statuses(
    *,
    resolve_cli_command: Callable[[str], str | None],
    resolve_magicpdf_models_dir: Callable[[str], str | None],
) -> dict[str, dict[str, object]]:
    pandoc_cli = (getattr(settings, "PANDOC_CLI", "") or "pandoc").strip() or "pandoc"
    libreoffice_cli = (getattr(settings, "LIBREOFFICE_CLI", "") or "soffice").strip() or "soffice"
    parsers: dict[str, dict[str, object]] = {
        "basic": {"enabled": True, "available": True, "message": "built-in"},
        "markitdown": _build_import_parser_status(
            "markitdown",
            enabled=bool(getattr(settings, "MARKITDOWN_ENABLED", False)),
            available_message="installed",
        ),
        "pandoc": _build_cli_parser_status(
            bool(getattr(settings, "PANDOC_ENABLED", False)),
            resolve_cli_command(pandoc_cli) or "",
        ),
        "libreoffice": _build_cli_parser_status(
            bool(getattr(settings, "LIBREOFFICE_ENABLED", False)),
            resolve_cli_command(libreoffice_cli) or "",
        ),
        "deepdoc": _build_import_parser_status(
            "app.deepdoc.parser",
            enabled=bool(getattr(settings, "DEEPDOC_ENABLED", False)),
            available_message="available",
        ),
        "deepseek_ocr": _build_configured_parser_status(
            bool(getattr(settings, "DEEPSEEK_OCR_ENABLED", False)),
            bool((getattr(settings, "SILICONFLOW_API_KEY", "") or "").strip()),
            "missing api_key",
        ),
        "etl4llm": _build_configured_parser_status(
            bool(getattr(settings, "ETL4LLM_ENABLED", False)),
            bool((getattr(settings, "ETL4LLM_API_URL", "") or "").strip()),
            _MISSING_API_URL_MESSAGE,
        ),
        "marker": _build_configured_parser_status(
            bool(getattr(settings, "MARKER_ENABLED", False)),
            bool((getattr(settings, "MARKER_API_URL", "") or "").strip()),
            _MISSING_API_URL_MESSAGE,
        ),
        "textin": _build_textin_parser_status(),
        "docling": _build_import_parser_status(
            "docling",
            enabled=bool(getattr(settings, "DOCLING_ENABLED", False)),
            available_message="installed",
        ),
        "mineru": _build_mineru_parser_status(),
        "magicpdf": _build_magicpdf_parser_status(
            resolve_cli_command=resolve_cli_command,
            resolve_magicpdf_models_dir=resolve_magicpdf_models_dir,
        ),
    }
    parsers["qianfan_ocr"] = await _build_probed_parser_status(
        enabled=bool(getattr(settings, "QIANFAN_OCR_ENABLED", False)),
        api_url=(getattr(settings, "QIANFAN_OCR_API_URL", "") or "").strip(),
        success_message_builder=lambda data: _configured_parts_message(data.get("model"), data.get("mode")),
    )
    parsers["paddle_vl"] = await _build_probed_parser_status(
        enabled=bool(getattr(settings, "PADDLE_VL_ENABLED", False)),
        api_url=(getattr(settings, "PADDLE_VL_API_URL", "") or "").strip(),
        success_message_builder=lambda data: _configured_parts_message(
            data.get("pipeline_version") or data.get("version"),
            data.get("mode"),
        ),
    )
    parsers["olmocr"] = await _build_probed_parser_status(
        enabled=bool(getattr(settings, "OLMOCR_ENABLED", False)),
        api_url=(getattr(settings, "OLMOCR_API_URL", "") or "").strip(),
    )
    return parsers


def _get_database_status(session_local_factory: Callable[[], Any], text: Callable[[str], Any]) -> dict[str, object]:
    status = {"connected": False, "message": ""}
    try:
        db_session = session_local_factory()
        db_session.execute(text("SELECT 1"))
        db_session.close()
        status["connected"] = True
        status["message"] = "connected"
    except Exception as exc:  # noqa: BLE001
        status["message"] = str(exc)[:100]
    return status


def _get_milvus_status(connections: Any) -> dict[str, object]:
    status = {"connected": False, "message": ""}
    try:
        connections.connect(
            alias="status_check",
            host=settings.MILVUS_HOST,
            port=settings.MILVUS_PORT,
            user=settings.MILVUS_USER or None,
            password=settings.MILVUS_PASSWORD or None,
        )
        connections.disconnect("status_check")
        status["connected"] = True
        status["message"] = "connected"
    except Exception as exc:  # noqa: BLE001
        status["message"] = str(exc)[:100]
    return status


@router.get("/status", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def get_system_status(
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Get system status."""
    _ensure_settings_readable(db, tenant_id, account_id)
    from pymilvus import connections
    from sqlalchemy import text

    from app.core.database import SessionLocal
    from app.parsing.parsers.magic_pdf_parser import resolve_magicpdf_models_dir
    from app.parsing.utils.cli import resolve_cli_command

    return {
        "database": _get_database_status(SessionLocal, text),
        "milvus": _get_milvus_status(connections),
        "llm": {"configured": bool(settings.LLM_API_KEY), "model": settings.LLM_MODEL},
        "embedding": {
            "configured": bool(settings.EMBEDDING_API_KEY or settings.LLM_API_KEY),
            "model": settings.EMBEDDING_MODEL,
        },
        "parsers": await _build_parser_statuses(
            resolve_cli_command=resolve_cli_command,
            resolve_magicpdf_models_dir=resolve_magicpdf_models_dir,
        ),
    }


class TestLLMRequest(BaseModel):
    api_key: str
    api_base: str = Field(default_factory=_default_llm_api_base)
    model: str
    temperature: float = 0.0
    timeout: int = 20
    max_retries: int = 1


@router.post("/llm/test", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def test_llm_connection(
    request: TestLLMRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Test LLM connection (no config write)."""
    _ensure_settings_writable(db, tenant_id, account_id)
    from langchain_core.messages import HumanMessage
    from langchain_openai import ChatOpenAI

    from app.core.openai_compat import normalize_openai_compatible_base_url
    from app.rag.core.http import httpx_trust_env
    from app.rag.core.logging import get_logger

    logger = get_logger("settings.llm_test")

    if not request.api_key.strip():
        raise HTTPException(status_code=400, detail="api_key is required")
    if not request.model.strip():
        raise HTTPException(status_code=400, detail="model is required")

    normalized_base_url = normalize_openai_compatible_base_url(request.api_base)
    validated_target = await _validate_public_base_url(normalized_base_url)
    trust_env = httpx_trust_env(logger=logger)
    timeout = float(request.timeout) if request.timeout else 20.0

    try:
        http_client, http_async_client = _build_pinned_http_clients(
            validated_target, trust_env=trust_env, timeout=timeout
        )
        with http_client:
            async with http_async_client:
                llm = ChatOpenAI(
                    model=request.model,
                    api_key=request.api_key,
                    base_url=validated_target.connect_url,
                    temperature=float(request.temperature or 0.0),
                    streaming=False,
                    timeout=timeout,
                    max_retries=int(request.max_retries or 1),
                    http_client=http_client,
                    http_async_client=http_async_client,
                )
                resp = await llm.ainvoke([HumanMessage(content="Say 1")])
                content = (getattr(resp, "content", "") or "").strip()
                if not content:
                    return {"success": False, "message": "Empty response"}
                return {"success": True, "message": content[:200]}
    except Exception as exc:
        msg = str(exc)
        logger.warning("LLM test failed: %s", msg[:200])
        return {"success": False, "message": msg[:400]}
