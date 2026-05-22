"""
Settings API - system configuration management.
Supports reading and updating .env configuration.
"""

import contextlib
import importlib.util
import ipaddress
import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlparse, urlunparse
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.config import settings
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
    ensure_tenant_permission(
        db,
        tenant_id,
        account_id,
        TenantPermissions.SETTINGS_WRITE,
        detail="No permission to manage system settings",
    )


def _validate_public_base_url(base_url: str) -> None:
    parsed = urlparse(str(base_url or "").strip())
    if parsed.scheme not in {"https", "http"}:
        raise HTTPException(status_code=400, detail="api_base must be http(s) URL")
    if not parsed.netloc:
        raise HTTPException(status_code=400, detail="api_base must include host")
    if parsed.username or parsed.password:
        raise HTTPException(status_code=400, detail="api_base must not include userinfo")

    host = (parsed.hostname or "").strip()
    if not host:
        raise HTTPException(status_code=400, detail="api_base must include host")
    host_lower = host.lower()
    if host_lower in {"localhost"} or host_lower.endswith(".localhost"):
        raise HTTPException(status_code=400, detail="api_base host not allowed")

    # Block private/loopback/link-local IPs to reduce SSRF risk.
    try:
        ip = ipaddress.ip_address(host_lower)
    except ValueError:
        # hostname (best-effort): allow
        return
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
        raise HTTPException(status_code=400, detail="api_base host not allowed")


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
    account_id: str = "system:dify"
    knowledge_map_json: str = ""
    top_k_max: int = Field(default=50, ge=1, le=200)
    endpoint_path: str = "/api/v1/integrations/dify/retrieval"


class SystemSettings(BaseModel):
    """Full system config."""
    feature_flags: FeatureFlags
    kg: KGConfig
    llm: LLMConfig
    embedding: EmbeddingConfig
    milvus: MilvusConfig
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


def _apply_runtime_settings(env_vars: dict[str, str], updated_keys: list[str]) -> None:
    """
    Best-effort: apply updated .env values to the in-memory settings object so
    config changes can take effect without a restart.
    """
    # Feature flags
    if "KG_ENABLED" in updated_keys and "KG_ENABLED" in env_vars:
        settings.KG_ENABLED = _parse_bool(env_vars["KG_ENABLED"])
    if "KG_CHAT_ENABLED" in updated_keys and "KG_CHAT_ENABLED" in env_vars:
        settings.KG_CHAT_ENABLED = _parse_bool(env_vars["KG_CHAT_ENABLED"])
    if "DEEPDOC_ENABLED" in updated_keys and "DEEPDOC_ENABLED" in env_vars:
        settings.DEEPDOC_ENABLED = _parse_bool(env_vars["DEEPDOC_ENABLED"])
    if "DOCLING_ENABLED" in updated_keys and "DOCLING_ENABLED" in env_vars:
        settings.DOCLING_ENABLED = _parse_bool(env_vars["DOCLING_ENABLED"])
    if "ETL4LLM_ENABLED" in updated_keys and "ETL4LLM_ENABLED" in env_vars:
        settings.ETL4LLM_ENABLED = _parse_bool(env_vars["ETL4LLM_ENABLED"])
    if "MARKER_ENABLED" in updated_keys and "MARKER_ENABLED" in env_vars:
        settings.MARKER_ENABLED = _parse_bool(env_vars["MARKER_ENABLED"])
    if "PADDLE_VL_ENABLED" in updated_keys and "PADDLE_VL_ENABLED" in env_vars:
        settings.PADDLE_VL_ENABLED = _parse_bool(env_vars["PADDLE_VL_ENABLED"])
    if "MARKITDOWN_ENABLED" in updated_keys and "MARKITDOWN_ENABLED" in env_vars:
        settings.MARKITDOWN_ENABLED = _parse_bool(env_vars["MARKITDOWN_ENABLED"])
    if "LLAMA_INDEX_ENABLED" in updated_keys and "LLAMA_INDEX_ENABLED" in env_vars:
        settings.LLAMA_INDEX_ENABLED = _parse_bool(env_vars["LLAMA_INDEX_ENABLED"])
    if "MINERU_ENABLED" in updated_keys and "MINERU_ENABLED" in env_vars:
        settings.MINERU_ENABLED = _parse_bool(env_vars["MINERU_ENABLED"])
    if "MAGIC_PDF_ENABLED" in updated_keys and "MAGIC_PDF_ENABLED" in env_vars:
        settings.MAGIC_PDF_ENABLED = _parse_bool(env_vars["MAGIC_PDF_ENABLED"])

    # KG prompt selector
    if "KG_EXTRACT_PROMPT_TEMPLATE_ID" in updated_keys and "KG_EXTRACT_PROMPT_TEMPLATE_ID" in env_vars:
        settings.KG_EXTRACT_PROMPT_TEMPLATE_ID = env_vars["KG_EXTRACT_PROMPT_TEMPLATE_ID"]
    if "KG_EXTRACT_PROMPT_TEMPLATE_KEY" in updated_keys and "KG_EXTRACT_PROMPT_TEMPLATE_KEY" in env_vars:
        settings.KG_EXTRACT_PROMPT_TEMPLATE_KEY = env_vars["KG_EXTRACT_PROMPT_TEMPLATE_KEY"]
    if "KG_EXTRACT_PROMPT_AB_EXPERIMENT_KEY" in updated_keys and "KG_EXTRACT_PROMPT_AB_EXPERIMENT_KEY" in env_vars:
        settings.KG_EXTRACT_PROMPT_AB_EXPERIMENT_KEY = env_vars["KG_EXTRACT_PROMPT_AB_EXPERIMENT_KEY"]
    if "KG_EXTRACT_REPLACE_EXISTING" in updated_keys and "KG_EXTRACT_REPLACE_EXISTING" in env_vars:
        settings.KG_EXTRACT_REPLACE_EXISTING = _parse_bool(env_vars["KG_EXTRACT_REPLACE_EXISTING"])
    if "KG_EXTRACT_PRUNE_ORPHAN_ENTITIES" in updated_keys and "KG_EXTRACT_PRUNE_ORPHAN_ENTITIES" in env_vars:
        settings.KG_EXTRACT_PRUNE_ORPHAN_ENTITIES = _parse_bool(env_vars["KG_EXTRACT_PRUNE_ORPHAN_ENTITIES"])

    # LLM
    if "LLM_API_KEY" in updated_keys and "LLM_API_KEY" in env_vars:
        settings.LLM_API_KEY = env_vars["LLM_API_KEY"]
    if "LLM_API_BASE" in updated_keys and "LLM_API_BASE" in env_vars:
        settings.LLM_API_BASE = env_vars["LLM_API_BASE"]
    if "LLM_MODEL" in updated_keys and "LLM_MODEL" in env_vars:
        settings.LLM_MODEL = env_vars["LLM_MODEL"]
    if "LLM_TEMPERATURE" in updated_keys and "LLM_TEMPERATURE" in env_vars:
        settings.LLM_TEMPERATURE = _parse_float(env_vars["LLM_TEMPERATURE"], default=settings.LLM_TEMPERATURE)
    if "LLM_TIMEOUT" in updated_keys and "LLM_TIMEOUT" in env_vars:
        settings.LLM_TIMEOUT = _parse_int(env_vars["LLM_TIMEOUT"], default=settings.LLM_TIMEOUT)
    if "LLM_MAX_RETRIES" in updated_keys and "LLM_MAX_RETRIES" in env_vars:
        settings.LLM_MAX_RETRIES = _parse_int(env_vars["LLM_MAX_RETRIES"], default=settings.LLM_MAX_RETRIES)

    # Embedding
    if "EMBEDDING_PROVIDER" in updated_keys and "EMBEDDING_PROVIDER" in env_vars:
        settings.EMBEDDING_PROVIDER = env_vars["EMBEDDING_PROVIDER"]
    if "EMBEDDING_MODEL" in updated_keys and "EMBEDDING_MODEL" in env_vars:
        settings.EMBEDDING_MODEL = env_vars["EMBEDDING_MODEL"]
    if "EMBEDDING_API_KEY" in updated_keys and "EMBEDDING_API_KEY" in env_vars:
        settings.EMBEDDING_API_KEY = env_vars["EMBEDDING_API_KEY"]
    if "EMBEDDING_API_BASE" in updated_keys and "EMBEDDING_API_BASE" in env_vars:
        settings.EMBEDDING_API_BASE = env_vars["EMBEDDING_API_BASE"]

    # Milvus
    if "MILVUS_HOST" in updated_keys and "MILVUS_HOST" in env_vars:
        settings.MILVUS_HOST = env_vars["MILVUS_HOST"]
    if "MILVUS_PORT" in updated_keys and "MILVUS_PORT" in env_vars:
        settings.MILVUS_PORT = _parse_int(env_vars["MILVUS_PORT"], default=settings.MILVUS_PORT)
    if "MILVUS_USER" in updated_keys and "MILVUS_USER" in env_vars:
        settings.MILVUS_USER = env_vars["MILVUS_USER"]
    if "MILVUS_PASSWORD" in updated_keys and "MILVUS_PASSWORD" in env_vars:
        settings.MILVUS_PASSWORD = env_vars["MILVUS_PASSWORD"]
    if "MILVUS_COLLECTION_NAME" in updated_keys and "MILVUS_COLLECTION_NAME" in env_vars:
        settings.MILVUS_COLLECTION_NAME = env_vars["MILVUS_COLLECTION_NAME"]

    # RAG knobs
    if "CHUNK_SIZE" in updated_keys and "CHUNK_SIZE" in env_vars:
        settings.CHUNK_SIZE = _parse_int(env_vars["CHUNK_SIZE"], default=settings.CHUNK_SIZE)
    if "CHUNK_OVERLAP" in updated_keys and "CHUNK_OVERLAP" in env_vars:
        settings.CHUNK_OVERLAP = _parse_int(env_vars["CHUNK_OVERLAP"], default=settings.CHUNK_OVERLAP)
    if "CHUNK_MIN_CHARS" in updated_keys and "CHUNK_MIN_CHARS" in env_vars:
        settings.CHUNK_MIN_CHARS = _parse_int(env_vars["CHUNK_MIN_CHARS"], default=getattr(settings, "CHUNK_MIN_CHARS", 0))
    if "RETRIEVAL_TOP_K" in updated_keys and "RETRIEVAL_TOP_K" in env_vars:
        settings.RETRIEVAL_TOP_K = _parse_int(env_vars["RETRIEVAL_TOP_K"], default=settings.RETRIEVAL_TOP_K)
    if "SIMILARITY_THRESHOLD" in updated_keys and "SIMILARITY_THRESHOLD" in env_vars:
        settings.SIMILARITY_THRESHOLD = _parse_float(
            env_vars["SIMILARITY_THRESHOLD"],
            default=settings.SIMILARITY_THRESHOLD,
        )
    if "DEFAULT_PARSER_BACKEND" in updated_keys and "DEFAULT_PARSER_BACKEND" in env_vars:
        settings.DEFAULT_PARSER_BACKEND = env_vars["DEFAULT_PARSER_BACKEND"]
    if "DEFAULT_CHUNK_STRATEGY" in updated_keys and "DEFAULT_CHUNK_STRATEGY" in env_vars:
        settings.DEFAULT_CHUNK_STRATEGY = env_vars["DEFAULT_CHUNK_STRATEGY"]
    if "BM25_INDEX_ENABLED" in updated_keys and "BM25_INDEX_ENABLED" in env_vars:
        old_bm25 = bool(getattr(settings, "BM25_INDEX_ENABLED", True))
        new_bm25 = _parse_bool(env_vars["BM25_INDEX_ENABLED"])
        settings.BM25_INDEX_ENABLED = new_bm25
        if old_bm25 and not new_bm25:
            # Ensure the toggle takes effect immediately even if an in-memory BM25 cache exists.
            with contextlib.suppress(Exception):
                from app.rag.retriever import hybrid_retriever

                hybrid_retriever.clear_bm25_cache()
    if "ENABLE_RERANKER" in updated_keys and "ENABLE_RERANKER" in env_vars:
        settings.ENABLE_RERANKER = _parse_bool(env_vars["ENABLE_RERANKER"])
    if "RERANKER_PROVIDER" in updated_keys and "RERANKER_PROVIDER" in env_vars:
        settings.RERANKER_PROVIDER = env_vars["RERANKER_PROVIDER"]
    if "RERANKER_TOP_N" in updated_keys and "RERANKER_TOP_N" in env_vars:
        settings.RERANKER_TOP_N = _parse_int(env_vars["RERANKER_TOP_N"], default=settings.RERANKER_TOP_N)
    if "SHOW_IMAGE_IN_ANSWER" in updated_keys and "SHOW_IMAGE_IN_ANSWER" in env_vars:
        settings.SHOW_IMAGE_IN_ANSWER = _parse_bool(env_vars["SHOW_IMAGE_IN_ANSWER"])
    if "IMAGE_APPEND_MAX" in updated_keys and "IMAGE_APPEND_MAX" in env_vars:
        settings.IMAGE_APPEND_MAX = _parse_int(
            env_vars["IMAGE_APPEND_MAX"],
            default=int(getattr(settings, "IMAGE_APPEND_MAX", 3) or 3),
        )

    # Cache / performance (best-effort).
    if "UPLOAD_DEDUP_ENABLED" in updated_keys and "UPLOAD_DEDUP_ENABLED" in env_vars:
        settings.UPLOAD_DEDUP_ENABLED = _parse_bool(env_vars["UPLOAD_DEDUP_ENABLED"])

    if "CHAT_RESPONSE_CACHE_ENABLED" in updated_keys and "CHAT_RESPONSE_CACHE_ENABLED" in env_vars:
        settings.CHAT_RESPONSE_CACHE_ENABLED = _parse_bool(env_vars["CHAT_RESPONSE_CACHE_ENABLED"])
    if "CHAT_RESPONSE_CACHE_TTL_SEC" in updated_keys and "CHAT_RESPONSE_CACHE_TTL_SEC" in env_vars:
        settings.CHAT_RESPONSE_CACHE_TTL_SEC = _parse_int(
            env_vars["CHAT_RESPONSE_CACHE_TTL_SEC"],
            default=int(getattr(settings, "CHAT_RESPONSE_CACHE_TTL_SEC", 300) or 300),
        )
    if "CHAT_RESPONSE_CACHE_MAX_VALUE_BYTES" in updated_keys and "CHAT_RESPONSE_CACHE_MAX_VALUE_BYTES" in env_vars:
        settings.CHAT_RESPONSE_CACHE_MAX_VALUE_BYTES = _parse_int(
            env_vars["CHAT_RESPONSE_CACHE_MAX_VALUE_BYTES"],
            default=int(getattr(settings, "CHAT_RESPONSE_CACHE_MAX_VALUE_BYTES", 200_000) or 200_000),
        )
    if "CHAT_RESPONSE_CACHE_REQUIRE_EMPTY_HISTORY" in updated_keys and "CHAT_RESPONSE_CACHE_REQUIRE_EMPTY_HISTORY" in env_vars:
        settings.CHAT_RESPONSE_CACHE_REQUIRE_EMPTY_HISTORY = _parse_bool(env_vars["CHAT_RESPONSE_CACHE_REQUIRE_EMPTY_HISTORY"])

    # URL ingest / SSRF guardrails
    if "URL_INGEST_ENABLED" in updated_keys and "URL_INGEST_ENABLED" in env_vars:
        settings.URL_INGEST_ENABLED = _parse_bool(env_vars["URL_INGEST_ENABLED"])
    if "URL_INGEST_MAX_BYTES" in updated_keys and "URL_INGEST_MAX_BYTES" in env_vars:
        settings.URL_INGEST_MAX_BYTES = _parse_int(
            env_vars["URL_INGEST_MAX_BYTES"], default=getattr(settings, "URL_INGEST_MAX_BYTES", 0)
        )
    if "URL_INGEST_TIMEOUT_SEC" in updated_keys and "URL_INGEST_TIMEOUT_SEC" in env_vars:
        settings.URL_INGEST_TIMEOUT_SEC = _parse_float(
            env_vars["URL_INGEST_TIMEOUT_SEC"], default=getattr(settings, "URL_INGEST_TIMEOUT_SEC", 30.0)
        )
    if "URL_INGEST_ALLOW_PRIVATE_IPS" in updated_keys and "URL_INGEST_ALLOW_PRIVATE_IPS" in env_vars:
        settings.URL_INGEST_ALLOW_PRIVATE_IPS = _parse_bool(env_vars["URL_INGEST_ALLOW_PRIVATE_IPS"])
    if "URL_INGEST_FOLLOW_REDIRECTS" in updated_keys and "URL_INGEST_FOLLOW_REDIRECTS" in env_vars:
        settings.URL_INGEST_FOLLOW_REDIRECTS = _parse_bool(env_vars["URL_INGEST_FOLLOW_REDIRECTS"])

    # Governance defaults
    if "GOVERNANCE_ENABLED" in updated_keys and "GOVERNANCE_ENABLED" in env_vars:
        settings.GOVERNANCE_ENABLED = _parse_bool(env_vars["GOVERNANCE_ENABLED"])
    if "GOVERNANCE_PII_ANONYMIZE" in updated_keys and "GOVERNANCE_PII_ANONYMIZE" in env_vars:
        settings.GOVERNANCE_PII_ANONYMIZE = _parse_bool(env_vars["GOVERNANCE_PII_ANONYMIZE"])
    if "GOVERNANCE_SECRETS_REDACT" in updated_keys and "GOVERNANCE_SECRETS_REDACT" in env_vars:
        settings.GOVERNANCE_SECRETS_REDACT = _parse_bool(env_vars["GOVERNANCE_SECRETS_REDACT"])
    if "GOVERNANCE_QUARANTINE_ON_DROP" in updated_keys and "GOVERNANCE_QUARANTINE_ON_DROP" in env_vars:
        settings.GOVERNANCE_QUARANTINE_ON_DROP = _parse_bool(env_vars["GOVERNANCE_QUARANTINE_ON_DROP"])

    # MinerU
    if "MINERU_API_TOKEN" in updated_keys and "MINERU_API_TOKEN" in env_vars:
        settings.MINERU_API_TOKEN = env_vars["MINERU_API_TOKEN"]
    if "MINERU_API_BASE" in updated_keys and "MINERU_API_BASE" in env_vars:
        settings.MINERU_API_BASE = env_vars["MINERU_API_BASE"]
    if "MINERU_MODEL_VERSION" in updated_keys and "MINERU_MODEL_VERSION" in env_vars:
        settings.MINERU_MODEL_VERSION = env_vars["MINERU_MODEL_VERSION"]
    if "MINERU_BACKEND" in updated_keys and "MINERU_BACKEND" in env_vars:
        settings.MINERU_BACKEND = _normalize_mineru_backend(env_vars["MINERU_BACKEND"])
    if "MINERU_LOCAL_SERVER_URL" in updated_keys and "MINERU_LOCAL_SERVER_URL" in env_vars:
        settings.MINERU_LOCAL_SERVER_URL = env_vars["MINERU_LOCAL_SERVER_URL"]
    if "MINERU_VL_SERVER" in updated_keys and "MINERU_VL_SERVER" in env_vars:
        settings.MINERU_VL_SERVER = env_vars["MINERU_VL_SERVER"]

    # ETL4LLM
    if "ETL4LLM_API_URL" in updated_keys and "ETL4LLM_API_URL" in env_vars:
        settings.ETL4LLM_API_URL = env_vars["ETL4LLM_API_URL"]
    if "ETL4LLM_TIMEOUT_SEC" in updated_keys and "ETL4LLM_TIMEOUT_SEC" in env_vars:
        settings.ETL4LLM_TIMEOUT_SEC = _parse_int(env_vars["ETL4LLM_TIMEOUT_SEC"], default=settings.ETL4LLM_TIMEOUT_SEC)
    if "ETL4LLM_MODE" in updated_keys and "ETL4LLM_MODE" in env_vars:
        settings.ETL4LLM_MODE = env_vars["ETL4LLM_MODE"]
    if "ETL4LLM_FORCE_OCR" in updated_keys and "ETL4LLM_FORCE_OCR" in env_vars:
        settings.ETL4LLM_FORCE_OCR = _parse_bool(env_vars["ETL4LLM_FORCE_OCR"])
    if "ETL4LLM_ENABLE_FORMULA" in updated_keys and "ETL4LLM_ENABLE_FORMULA" in env_vars:
        settings.ETL4LLM_ENABLE_FORMULA = _parse_bool(env_vars["ETL4LLM_ENABLE_FORMULA"])
    if "ETL4LLM_EXTRACT_IMAGES" in updated_keys and "ETL4LLM_EXTRACT_IMAGES" in env_vars:
        settings.ETL4LLM_EXTRACT_IMAGES = _parse_bool(env_vars["ETL4LLM_EXTRACT_IMAGES"])
    if "ETL4LLM_FILTER_PAGE_HEADER_FOOTER" in updated_keys and "ETL4LLM_FILTER_PAGE_HEADER_FOOTER" in env_vars:
        settings.ETL4LLM_FILTER_PAGE_HEADER_FOOTER = _parse_bool(env_vars["ETL4LLM_FILTER_PAGE_HEADER_FOOTER"])

    # Marker
    if "MARKER_API_URL" in updated_keys and "MARKER_API_URL" in env_vars:
        settings.MARKER_API_URL = env_vars["MARKER_API_URL"]
    if "MARKER_TIMEOUT_SEC" in updated_keys and "MARKER_TIMEOUT_SEC" in env_vars:
        settings.MARKER_TIMEOUT_SEC = _parse_int(env_vars["MARKER_TIMEOUT_SEC"], default=settings.MARKER_TIMEOUT_SEC)

    # PaddleOCR-VL
    if "PADDLE_VL_API_URL" in updated_keys and "PADDLE_VL_API_URL" in env_vars:
        settings.PADDLE_VL_API_URL = env_vars["PADDLE_VL_API_URL"]
    if "PADDLE_VL_TIMEOUT_SEC" in updated_keys and "PADDLE_VL_TIMEOUT_SEC" in env_vars:
        settings.PADDLE_VL_TIMEOUT_SEC = _parse_int(env_vars["PADDLE_VL_TIMEOUT_SEC"], default=settings.PADDLE_VL_TIMEOUT_SEC)
    if "PADDLE_VL_PIPELINE_VERSION" in updated_keys and "PADDLE_VL_PIPELINE_VERSION" in env_vars:
        settings.PADDLE_VL_PIPELINE_VERSION = env_vars["PADDLE_VL_PIPELINE_VERSION"]
    if "PADDLE_VL_MODE" in updated_keys and "PADDLE_VL_MODE" in env_vars:
        settings.PADDLE_VL_MODE = env_vars["PADDLE_VL_MODE"]

    # MagicPDF
    if "MAGIC_PDF_API_URL" in updated_keys and "MAGIC_PDF_API_URL" in env_vars:
        settings.MAGIC_PDF_API_URL = env_vars["MAGIC_PDF_API_URL"]
    if "MAGIC_PDF_REQUEST_TIMEOUT_SEC" in updated_keys and "MAGIC_PDF_REQUEST_TIMEOUT_SEC" in env_vars:
        settings.MAGIC_PDF_REQUEST_TIMEOUT_SEC = _parse_int(
            env_vars["MAGIC_PDF_REQUEST_TIMEOUT_SEC"], default=getattr(settings, "MAGIC_PDF_REQUEST_TIMEOUT_SEC", 600)
        )
    if "MAGIC_PDF_MAX_CONCURRENT_JOBS" in updated_keys and "MAGIC_PDF_MAX_CONCURRENT_JOBS" in env_vars:
        settings.MAGIC_PDF_MAX_CONCURRENT_JOBS = _parse_int(
            env_vars["MAGIC_PDF_MAX_CONCURRENT_JOBS"], default=getattr(settings, "MAGIC_PDF_MAX_CONCURRENT_JOBS", 1)
        )
    if "MAGIC_PDF_CLI" in updated_keys and "MAGIC_PDF_CLI" in env_vars:
        settings.MAGIC_PDF_CLI = env_vars["MAGIC_PDF_CLI"]
    if "MAGIC_PDF_METHOD" in updated_keys and "MAGIC_PDF_METHOD" in env_vars:
        settings.MAGIC_PDF_METHOD = env_vars["MAGIC_PDF_METHOD"]
    if "MAGIC_PDF_LANG" in updated_keys and "MAGIC_PDF_LANG" in env_vars:
        settings.MAGIC_PDF_LANG = env_vars["MAGIC_PDF_LANG"]
    if "MAGIC_PDF_DEBUG" in updated_keys and "MAGIC_PDF_DEBUG" in env_vars:
        settings.MAGIC_PDF_DEBUG = _parse_bool(env_vars["MAGIC_PDF_DEBUG"])
    if "MAGIC_PDF_TIMEOUT_SEC" in updated_keys and "MAGIC_PDF_TIMEOUT_SEC" in env_vars:
        settings.MAGIC_PDF_TIMEOUT_SEC = _parse_int(env_vars["MAGIC_PDF_TIMEOUT_SEC"], default=settings.MAGIC_PDF_TIMEOUT_SEC)
    if "MAGIC_PDF_MODELS_DIR" in updated_keys and "MAGIC_PDF_MODELS_DIR" in env_vars:
        settings.MAGIC_PDF_MODELS_DIR = env_vars["MAGIC_PDF_MODELS_DIR"]
    if "MAGIC_PDF_DEVICE_MODE" in updated_keys and "MAGIC_PDF_DEVICE_MODE" in env_vars:
        settings.MAGIC_PDF_DEVICE_MODE = env_vars["MAGIC_PDF_DEVICE_MODE"]
    if "MAGIC_PDF_KEEP_ARTIFACTS" in updated_keys and "MAGIC_PDF_KEEP_ARTIFACTS" in env_vars:
        settings.MAGIC_PDF_KEEP_ARTIFACTS = _parse_bool(env_vars["MAGIC_PDF_KEEP_ARTIFACTS"])

    # Observability / debug toggles
    if "TOOL_CALL_LOG_ENABLED" in updated_keys and "TOOL_CALL_LOG_ENABLED" in env_vars:
        settings.TOOL_CALL_LOG_ENABLED = _parse_bool(env_vars["TOOL_CALL_LOG_ENABLED"])
    if "TOOL_CALL_LOG_INCLUDE_PREVIEW" in updated_keys and "TOOL_CALL_LOG_INCLUDE_PREVIEW" in env_vars:
        settings.TOOL_CALL_LOG_INCLUDE_PREVIEW = _parse_bool(env_vars["TOOL_CALL_LOG_INCLUDE_PREVIEW"])
    if "TOOL_CALL_LOG_MAX_PREVIEW_CHARS" in updated_keys and "TOOL_CALL_LOG_MAX_PREVIEW_CHARS" in env_vars:
        settings.TOOL_CALL_LOG_MAX_PREVIEW_CHARS = _parse_int(
            env_vars["TOOL_CALL_LOG_MAX_PREVIEW_CHARS"],
            default=settings.TOOL_CALL_LOG_MAX_PREVIEW_CHARS,
        )

    if "AGENT_LOG_ENABLED" in updated_keys and "AGENT_LOG_ENABLED" in env_vars:
        settings.AGENT_LOG_ENABLED = _parse_bool(env_vars["AGENT_LOG_ENABLED"])
    if "AGENT_LOG_INCLUDE_EXECUTION_PATH" in updated_keys and "AGENT_LOG_INCLUDE_EXECUTION_PATH" in env_vars:
        settings.AGENT_LOG_INCLUDE_EXECUTION_PATH = _parse_bool(env_vars["AGENT_LOG_INCLUDE_EXECUTION_PATH"])
    if "AGENT_LOG_MAX_PREVIEW_CHARS" in updated_keys and "AGENT_LOG_MAX_PREVIEW_CHARS" in env_vars:
        settings.AGENT_LOG_MAX_PREVIEW_CHARS = _parse_int(
            env_vars["AGENT_LOG_MAX_PREVIEW_CHARS"],
            default=settings.AGENT_LOG_MAX_PREVIEW_CHARS,
        )

    # Metrics log (JSONL) controls
    if "ENABLE_METRICS_LOG" in updated_keys and "ENABLE_METRICS_LOG" in env_vars:
        settings.ENABLE_METRICS_LOG = _parse_bool(env_vars["ENABLE_METRICS_LOG"])
    if "METRICS_LOG_INCLUDE_TEXT" in updated_keys and "METRICS_LOG_INCLUDE_TEXT" in env_vars:
        settings.METRICS_LOG_INCLUDE_TEXT = _parse_bool(env_vars["METRICS_LOG_INCLUDE_TEXT"])

    # Safety / PII
    if "PII_REDACTION_ENABLED" in updated_keys and "PII_REDACTION_ENABLED" in env_vars:
        settings.PII_REDACTION_ENABLED = _parse_bool(env_vars["PII_REDACTION_ENABLED"])
    if "PII_REDACTION_MASK" in updated_keys and "PII_REDACTION_MASK" in env_vars:
        settings.PII_REDACTION_MASK = env_vars["PII_REDACTION_MASK"]
    if "PII_STREAM_HOLDBACK_CHARS" in updated_keys and "PII_STREAM_HOLDBACK_CHARS" in env_vars:
        settings.PII_STREAM_HOLDBACK_CHARS = _parse_int(
            env_vars["PII_STREAM_HOLDBACK_CHARS"],
            default=settings.PII_STREAM_HOLDBACK_CHARS,
        )

    # Chat streaming robustness
    if "CHAT_STREAM_HEARTBEAT_SEC" in updated_keys and "CHAT_STREAM_HEARTBEAT_SEC" in env_vars:
        settings.CHAT_STREAM_HEARTBEAT_SEC = _parse_float(
            env_vars["CHAT_STREAM_HEARTBEAT_SEC"], default=getattr(settings, "CHAT_STREAM_HEARTBEAT_SEC", 10.0)
        )
    if "CHAT_STREAM_CANCEL_ON_DISCONNECT" in updated_keys and "CHAT_STREAM_CANCEL_ON_DISCONNECT" in env_vars:
        settings.CHAT_STREAM_CANCEL_ON_DISCONNECT = _parse_bool(env_vars["CHAT_STREAM_CANCEL_ON_DISCONNECT"])

    # LangGraph
    if "LANGGRAPH_USE_SUBGRAPHS" in updated_keys and "LANGGRAPH_USE_SUBGRAPHS" in env_vars:
        settings.LANGGRAPH_USE_SUBGRAPHS = _parse_bool(env_vars["LANGGRAPH_USE_SUBGRAPHS"])

    # Frontend navigation visibility
    if "NAVIGATION_USER_VISIBLE_MODULES" in updated_keys and "NAVIGATION_USER_VISIBLE_MODULES" in env_vars:
        settings.NAVIGATION_USER_VISIBLE_MODULES = env_vars["NAVIGATION_USER_VISIBLE_MODULES"]

    # Dify External Knowledge adapter
    if "DIFY_EXTERNAL_KNOWLEDGE_ENABLED" in updated_keys and "DIFY_EXTERNAL_KNOWLEDGE_ENABLED" in env_vars:
        settings.DIFY_EXTERNAL_KNOWLEDGE_ENABLED = _parse_bool(env_vars["DIFY_EXTERNAL_KNOWLEDGE_ENABLED"])
    if "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS" in updated_keys and "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS" in env_vars:
        settings.DIFY_EXTERNAL_KNOWLEDGE_API_KEYS = env_vars["DIFY_EXTERNAL_KNOWLEDGE_API_KEYS"]
    if "DIFY_EXTERNAL_KNOWLEDGE_TENANT_ID" in updated_keys and "DIFY_EXTERNAL_KNOWLEDGE_TENANT_ID" in env_vars:
        settings.DIFY_EXTERNAL_KNOWLEDGE_TENANT_ID = env_vars["DIFY_EXTERNAL_KNOWLEDGE_TENANT_ID"]
    if "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID" in updated_keys and "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID" in env_vars:
        settings.DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID = env_vars["DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID"]
    if "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON" in updated_keys and "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON" in env_vars:
        settings.DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON = env_vars["DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON"]
    if "DIFY_EXTERNAL_KNOWLEDGE_TOP_K_MAX" in updated_keys and "DIFY_EXTERNAL_KNOWLEDGE_TOP_K_MAX" in env_vars:
        settings.DIFY_EXTERNAL_KNOWLEDGE_TOP_K_MAX = _parse_int(
            env_vars["DIFY_EXTERNAL_KNOWLEDGE_TOP_K_MAX"],
            default=int(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_TOP_K_MAX", 50) or 50),
        )


def read_env_file() -> dict[str, str]:
    """Read .env file."""
    env_vars = {}
    if ENV_FILE.exists():
        with open(ENV_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, _, value = line.partition('=')
                    env_vars[key.strip()] = value.strip()
    return env_vars


def write_env_file(env_vars: dict[str, str]):
    """Write .env file, preserving comments and formatting (atomic best-effort)."""
    lines = []
    existing_keys = set()

    # Read existing file and preserve comments.
    if ENV_FILE.exists():
        with open(ENV_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith('#') or not stripped:
                    lines.append(line.rstrip('\n'))
                elif '=' in stripped:
                    key = stripped.split('=')[0].strip()
                    existing_keys.add(key)
                    if key in env_vars:
                        lines.append(f"{key}={env_vars[key]}")
                    else:
                        lines.append(line.rstrip('\n'))

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
async def get_settings(
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
            chat_response_cache_max_value_bytes=int(getattr(settings, "CHAT_RESPONSE_CACHE_MAX_VALUE_BYTES", 200_000) or 0),
            chat_response_cache_require_empty_history=bool(getattr(settings, "CHAT_RESPONSE_CACHE_REQUIRE_EMPTY_HISTORY", True)),
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
            api_url=str(getattr(settings, "TEXTIN_API_URL", "") or "https://api.textin.com/ai/service/v1/pdf_to_markdown"),
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
            account_id=str(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "") or "system:dify"),
            knowledge_map_json=str(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON", "") or ""),
            top_k_max=int(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_TOP_K_MAX", 50) or 50),
            endpoint_path="/api/v1/integrations/dify/retrieval",
        ),
    )


@router.put("", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def update_settings(
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

        # Update feature flags.
        if request.feature_flags:
            ff = request.feature_flags
            env_vars["KG_ENABLED"] = str(ff.kg_enabled).lower()
            env_vars["DEEPDOC_ENABLED"] = str(ff.deepdoc_enabled).lower()
            env_vars["DOCLING_ENABLED"] = str(getattr(ff, "docling_enabled", False)).lower()
            env_vars["ETL4LLM_ENABLED"] = str(getattr(ff, "etl4llm_enabled", False)).lower()
            env_vars["MARKER_ENABLED"] = str(getattr(ff, "marker_enabled", False)).lower()
            env_vars["PADDLE_VL_ENABLED"] = str(getattr(ff, "paddle_vl_enabled", False)).lower()
            env_vars["TEXTIN_ENABLED"] = str(getattr(ff, "textin_enabled", False)).lower()
            env_vars["MARKITDOWN_ENABLED"] = str(ff.markitdown_enabled).lower()
            env_vars["LLAMA_INDEX_ENABLED"] = str(ff.llama_index_enabled).lower()
            env_vars["MINERU_ENABLED"] = str(ff.mineru_enabled).lower()
            env_vars["MAGIC_PDF_ENABLED"] = str(getattr(ff, "magicpdf_enabled", False)).lower()
            updated_keys.extend(
                [
                    "KG_ENABLED",
                    "DEEPDOC_ENABLED",
                    "DOCLING_ENABLED",
                    "ETL4LLM_ENABLED",
                    "MARKER_ENABLED",
                    "PADDLE_VL_ENABLED",
                    "TEXTIN_ENABLED",
                    "MARKITDOWN_ENABLED",
                    "LLAMA_INDEX_ENABLED",
                    "MINERU_ENABLED",
                    "MAGIC_PDF_ENABLED",
                ]
            )

        # Update KG config.
        if request.kg:
            kg = request.kg
            env_vars["KG_CHAT_ENABLED"] = str(bool(kg.chat_enabled)).lower()
            updated_keys.append("KG_CHAT_ENABLED")

            template_id = _sanitize_env_value("KG_EXTRACT_PROMPT_TEMPLATE_ID", kg.extract_prompt_template_id or "")
            if template_id:
                try:
                    UUID(template_id)
                except ValueError as exc:
                    raise HTTPException(status_code=400, detail="Invalid KG_EXTRACT_PROMPT_TEMPLATE_ID") from exc
            env_vars["KG_EXTRACT_PROMPT_TEMPLATE_ID"] = template_id
            env_vars["KG_EXTRACT_PROMPT_TEMPLATE_KEY"] = _sanitize_env_value(
                "KG_EXTRACT_PROMPT_TEMPLATE_KEY", kg.extract_prompt_template_key or ""
            )
            env_vars["KG_EXTRACT_PROMPT_AB_EXPERIMENT_KEY"] = _sanitize_env_value(
                "KG_EXTRACT_PROMPT_AB_EXPERIMENT_KEY", kg.extract_prompt_ab_experiment_key or ""
            )
            env_vars["KG_EXTRACT_REPLACE_EXISTING"] = str(bool(getattr(kg, "extract_replace_existing", True))).lower()
            env_vars["KG_EXTRACT_PRUNE_ORPHAN_ENTITIES"] = str(bool(getattr(kg, "extract_prune_orphan_entities", True))).lower()
            updated_keys.extend(
                [
                    "KG_EXTRACT_PROMPT_TEMPLATE_ID",
                    "KG_EXTRACT_PROMPT_TEMPLATE_KEY",
                    "KG_EXTRACT_PROMPT_AB_EXPERIMENT_KEY",
                    "KG_EXTRACT_REPLACE_EXISTING",
                    "KG_EXTRACT_PRUNE_ORPHAN_ENTITIES",
                ]
            )

        # Update LLM config.
        if request.llm:
            llm = request.llm
            # Only update non-masked values.
            if llm.api_key and "***" not in llm.api_key:
                env_vars["LLM_API_KEY"] = _sanitize_env_value("LLM_API_KEY", llm.api_key)
                updated_keys.append("LLM_API_KEY")
            env_vars["LLM_API_BASE"] = _sanitize_env_value("LLM_API_BASE", llm.api_base)
            env_vars["LLM_MODEL"] = _sanitize_env_value("LLM_MODEL", llm.model)
            env_vars["LLM_TEMPERATURE"] = str(llm.temperature)
            env_vars["LLM_TIMEOUT"] = str(llm.timeout)
            env_vars["LLM_MAX_RETRIES"] = str(llm.max_retries)
            updated_keys.extend(["LLM_API_BASE", "LLM_MODEL", "LLM_TEMPERATURE", "LLM_TIMEOUT", "LLM_MAX_RETRIES"])

        # Update embedding config.
        if request.embedding:
            emb = request.embedding
            env_vars["EMBEDDING_PROVIDER"] = _sanitize_env_value("EMBEDDING_PROVIDER", emb.provider)
            env_vars["EMBEDDING_MODEL"] = _sanitize_env_value("EMBEDDING_MODEL", emb.model)
            if emb.api_key and "***" not in emb.api_key:
                env_vars["EMBEDDING_API_KEY"] = _sanitize_env_value("EMBEDDING_API_KEY", emb.api_key)
                updated_keys.append("EMBEDDING_API_KEY")
            env_vars["EMBEDDING_API_BASE"] = _sanitize_env_value("EMBEDDING_API_BASE", emb.api_base)
            updated_keys.extend(["EMBEDDING_PROVIDER", "EMBEDDING_MODEL", "EMBEDDING_API_BASE"])

        # Update Milvus config.
        if request.milvus:
            mv = request.milvus
            env_vars["MILVUS_HOST"] = _sanitize_env_value("MILVUS_HOST", mv.host)
            env_vars["MILVUS_PORT"] = str(mv.port)
            env_vars["MILVUS_USER"] = _sanitize_env_value("MILVUS_USER", mv.user)
            if mv.password and "***" not in mv.password:
                env_vars["MILVUS_PASSWORD"] = _sanitize_env_value("MILVUS_PASSWORD", mv.password)
                updated_keys.append("MILVUS_PASSWORD")
            env_vars["MILVUS_COLLECTION_NAME"] = _sanitize_env_value("MILVUS_COLLECTION_NAME", mv.collection_name)
            updated_keys.extend(["MILVUS_HOST", "MILVUS_PORT", "MILVUS_USER", "MILVUS_COLLECTION_NAME"])

        # Update RAG config.
        if request.rag:
            rag = request.rag
            env_vars["CHUNK_SIZE"] = str(rag.chunk_size)
            env_vars["CHUNK_OVERLAP"] = str(rag.chunk_overlap)
            env_vars["CHUNK_MIN_CHARS"] = str(max(0, int(getattr(rag, "chunk_min_chars", 0) or 0)))
            env_vars["RETRIEVAL_TOP_K"] = str(rag.retrieval_top_k)
            env_vars["SIMILARITY_THRESHOLD"] = str(rag.similarity_threshold)
            env_vars["DEFAULT_PARSER_BACKEND"] = _sanitize_env_value("DEFAULT_PARSER_BACKEND", rag.default_parser_backend)
            env_vars["DEFAULT_CHUNK_STRATEGY"] = _sanitize_env_value("DEFAULT_CHUNK_STRATEGY", rag.default_chunk_strategy)
            env_vars["BM25_INDEX_ENABLED"] = str(bool(getattr(rag, "bm25_index_enabled", True))).lower()
            env_vars["ENABLE_RERANKER"] = str(bool(getattr(rag, "enable_reranker", False))).lower()
            env_vars["RERANKER_PROVIDER"] = _sanitize_env_value("RERANKER_PROVIDER", rag.reranker_provider)
            env_vars["RERANKER_TOP_N"] = str(int(getattr(rag, "reranker_top_n", 20) or 20))
            env_vars["SHOW_IMAGE_IN_ANSWER"] = str(bool(getattr(rag, "show_image_in_answer", True))).lower()
            env_vars["IMAGE_APPEND_MAX"] = str(
                max(0, min(10, int(getattr(rag, "image_append_max", 3) or 0)))
            )
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

        # Update cache/performance config.
        if request.cache:
            cc = request.cache
            env_vars["UPLOAD_DEDUP_ENABLED"] = str(bool(getattr(cc, "upload_dedup_enabled", False))).lower()
            env_vars["CHAT_RESPONSE_CACHE_ENABLED"] = str(bool(getattr(cc, "chat_response_cache_enabled", False))).lower()
            env_vars["CHAT_RESPONSE_CACHE_TTL_SEC"] = str(int(getattr(cc, "chat_response_cache_ttl_sec", 0) or 0))
            env_vars["CHAT_RESPONSE_CACHE_MAX_VALUE_BYTES"] = str(
                int(getattr(cc, "chat_response_cache_max_value_bytes", 0) or 0)
            )
            env_vars["CHAT_RESPONSE_CACHE_REQUIRE_EMPTY_HISTORY"] = str(
                bool(getattr(cc, "chat_response_cache_require_empty_history", True))
            ).lower()
            updated_keys.extend(
                [
                    "UPLOAD_DEDUP_ENABLED",
                    "CHAT_RESPONSE_CACHE_ENABLED",
                    "CHAT_RESPONSE_CACHE_TTL_SEC",
                    "CHAT_RESPONSE_CACHE_MAX_VALUE_BYTES",
                    "CHAT_RESPONSE_CACHE_REQUIRE_EMPTY_HISTORY",
                ]
            )

        if request.url_ingest:
            ui = request.url_ingest
            env_vars["URL_INGEST_ENABLED"] = str(bool(ui.enabled)).lower()
            env_vars["URL_INGEST_MAX_BYTES"] = str(int(getattr(ui, "max_bytes", 0) or 0))
            env_vars["URL_INGEST_TIMEOUT_SEC"] = str(float(getattr(ui, "timeout_sec", 0.0) or 0.0))
            env_vars["URL_INGEST_ALLOW_PRIVATE_IPS"] = str(bool(getattr(ui, "allow_private_ips", False))).lower()
            env_vars["URL_INGEST_FOLLOW_REDIRECTS"] = str(bool(getattr(ui, "follow_redirects", False))).lower()
            updated_keys.extend(
                [
                    "URL_INGEST_ENABLED",
                    "URL_INGEST_MAX_BYTES",
                    "URL_INGEST_TIMEOUT_SEC",
                    "URL_INGEST_ALLOW_PRIVATE_IPS",
                    "URL_INGEST_FOLLOW_REDIRECTS",
                ]
            )

        if request.governance:
            gv = request.governance
            env_vars["GOVERNANCE_ENABLED"] = str(bool(getattr(gv, "enabled", False))).lower()
            env_vars["GOVERNANCE_PII_ANONYMIZE"] = str(bool(getattr(gv, "pii_anonymize", False))).lower()
            env_vars["GOVERNANCE_SECRETS_REDACT"] = str(bool(getattr(gv, "secrets_redact", False))).lower()
            env_vars["GOVERNANCE_QUARANTINE_ON_DROP"] = str(bool(getattr(gv, "quarantine_on_drop", False))).lower()
            updated_keys.extend(
                [
                    "GOVERNANCE_ENABLED",
                    "GOVERNANCE_PII_ANONYMIZE",
                    "GOVERNANCE_SECRETS_REDACT",
                    "GOVERNANCE_QUARANTINE_ON_DROP",
                ]
            )

        # Update MinerU config.
        if request.mineru:
            mn = request.mineru
            if mn.api_token and "***" not in mn.api_token:
                env_vars["MINERU_API_TOKEN"] = _sanitize_env_value("MINERU_API_TOKEN", mn.api_token)
                updated_keys.append("MINERU_API_TOKEN")
            env_vars["MINERU_API_BASE"] = _sanitize_env_value("MINERU_API_BASE", mn.api_base)
            env_vars["MINERU_MODEL_VERSION"] = _sanitize_env_value("MINERU_MODEL_VERSION", mn.model_version)
            env_vars["MINERU_BACKEND"] = _normalize_mineru_backend(mn.backend)
            env_vars["MINERU_LOCAL_SERVER_URL"] = _sanitize_env_value(
                "MINERU_LOCAL_SERVER_URL", mn.local_server_url
            )
            env_vars["MINERU_VL_SERVER"] = _sanitize_env_value("MINERU_VL_SERVER", mn.vl_server)
            updated_keys.extend(
                [
                    "MINERU_API_BASE",
                    "MINERU_MODEL_VERSION",
                    "MINERU_BACKEND",
                    "MINERU_LOCAL_SERVER_URL",
                    "MINERU_VL_SERVER",
                ]
            )

        # Update ETL4LLM config.
        if request.etl4llm:
            et = request.etl4llm
            env_vars["ETL4LLM_API_URL"] = _sanitize_env_value("ETL4LLM_API_URL", et.api_url or "")
            env_vars["ETL4LLM_TIMEOUT_SEC"] = str(int(et.timeout_sec or 0))
            mode = (et.mode or "partition").strip().lower()
            if mode not in {"partition", "text"}:
                mode = "partition"
            env_vars["ETL4LLM_MODE"] = _sanitize_env_value("ETL4LLM_MODE", mode)
            env_vars["ETL4LLM_FORCE_OCR"] = str(bool(et.force_ocr)).lower()
            env_vars["ETL4LLM_ENABLE_FORMULA"] = str(bool(et.enable_formula)).lower()
            env_vars["ETL4LLM_EXTRACT_IMAGES"] = str(bool(et.extract_images)).lower()
            env_vars["ETL4LLM_FILTER_PAGE_HEADER_FOOTER"] = str(bool(et.filter_page_header_footer)).lower()
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

        if request.marker:
            mk = request.marker
            env_vars["MARKER_API_URL"] = _sanitize_env_value("MARKER_API_URL", mk.api_url or "")
            env_vars["MARKER_TIMEOUT_SEC"] = str(int(mk.timeout_sec or 0))
            updated_keys.extend(["MARKER_API_URL", "MARKER_TIMEOUT_SEC"])

        if request.paddle_vl:
            pv = request.paddle_vl
            env_vars["PADDLE_VL_API_URL"] = _sanitize_env_value("PADDLE_VL_API_URL", pv.api_url or "")
            env_vars["PADDLE_VL_TIMEOUT_SEC"] = str(int(pv.timeout_sec or 0))
            pipeline_version = (pv.pipeline_version or "v1.5").strip() or "v1.5"
            env_vars["PADDLE_VL_PIPELINE_VERSION"] = _sanitize_env_value("PADDLE_VL_PIPELINE_VERSION", pipeline_version)

            mode = (pv.mode or "doc_parser").strip().lower() or "doc_parser"
            if mode not in {"doc_parser"}:
                mode = "doc_parser"
            env_vars["PADDLE_VL_MODE"] = _sanitize_env_value("PADDLE_VL_MODE", mode)

            updated_keys.extend(["PADDLE_VL_API_URL", "PADDLE_VL_TIMEOUT_SEC", "PADDLE_VL_PIPELINE_VERSION", "PADDLE_VL_MODE"])

        if request.textin:
            tx = request.textin
            env_vars["TEXTIN_API_URL"] = _sanitize_env_value("TEXTIN_API_URL", tx.api_url or "")
            env_vars["TEXTIN_APP_ID"] = _sanitize_env_value("TEXTIN_APP_ID", tx.app_id or "")
            if tx.secret_code and "***" not in tx.secret_code:
                env_vars["TEXTIN_SECRET_CODE"] = _sanitize_env_value("TEXTIN_SECRET_CODE", tx.secret_code or "")
                updated_keys.append("TEXTIN_SECRET_CODE")
            env_vars["TEXTIN_TIMEOUT_SEC"] = str(int(tx.timeout_sec or 0))
            parse_mode = (tx.parse_mode or "auto").strip().lower() or "auto"
            if parse_mode not in {"auto", "scan", "parse", "lite", "vlm"}:
                parse_mode = "auto"
            env_vars["TEXTIN_PARSE_MODE"] = _sanitize_env_value("TEXTIN_PARSE_MODE", parse_mode)
            table_flavor = (tx.table_flavor or "html").strip().lower() or "html"
            if table_flavor not in {"html", "markdown"}:
                table_flavor = "html"
            env_vars["TEXTIN_TABLE_FLAVOR"] = _sanitize_env_value("TEXTIN_TABLE_FLAVOR", table_flavor)
            get_image = (tx.get_image or "none").strip().lower() or "none"
            if get_image not in {"none", "objects", "pages", "both"}:
                get_image = "none"
            env_vars["TEXTIN_GET_IMAGE"] = _sanitize_env_value("TEXTIN_GET_IMAGE", get_image)
            env_vars["TEXTIN_APPLY_DOCUMENT_TREE"] = str(bool(tx.apply_document_tree)).lower()
            env_vars["TEXTIN_MARKDOWN_DETAILS"] = str(bool(tx.markdown_details)).lower()
            env_vars["TEXTIN_DPI"] = str(max(0, int(tx.dpi or 0)))
            env_vars["TEXTIN_PAGE_COUNT"] = str(max(0, int(tx.page_count or 0)))
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

        if request.magicpdf:
            mp = request.magicpdf
            env_vars["MAGIC_PDF_API_URL"] = _sanitize_env_value("MAGIC_PDF_API_URL", mp.api_url)
            env_vars["MAGIC_PDF_REQUEST_TIMEOUT_SEC"] = str(max(1, int(mp.request_timeout_sec or 0)))
            env_vars["MAGIC_PDF_MAX_CONCURRENT_JOBS"] = str(max(1, int(mp.max_concurrent_jobs or 1)))
            env_vars["MAGIC_PDF_CLI"] = _sanitize_env_value("MAGIC_PDF_CLI", mp.cli)
            env_vars["MAGIC_PDF_METHOD"] = _sanitize_env_value("MAGIC_PDF_METHOD", mp.method)
            env_vars["MAGIC_PDF_LANG"] = _sanitize_env_value("MAGIC_PDF_LANG", mp.lang)
            env_vars["MAGIC_PDF_DEBUG"] = str(bool(mp.debug)).lower()
            env_vars["MAGIC_PDF_TIMEOUT_SEC"] = str(int(mp.timeout_sec or 0))
            env_vars["MAGIC_PDF_MODELS_DIR"] = _sanitize_env_value("MAGIC_PDF_MODELS_DIR", mp.models_dir)
            env_vars["MAGIC_PDF_DEVICE_MODE"] = _sanitize_env_value("MAGIC_PDF_DEVICE_MODE", mp.device_mode)
            env_vars["MAGIC_PDF_KEEP_ARTIFACTS"] = str(bool(mp.keep_artifacts)).lower()
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

        # Update observability/debug config.
        if request.observability:
            ob = request.observability
            env_vars["TOOL_CALL_LOG_ENABLED"] = str(ob.tool_call_log_enabled).lower()
            env_vars["TOOL_CALL_LOG_INCLUDE_PREVIEW"] = str(ob.tool_call_log_include_preview).lower()
            env_vars["TOOL_CALL_LOG_MAX_PREVIEW_CHARS"] = str(int(ob.tool_call_log_max_preview_chars or 0))
            env_vars["AGENT_LOG_ENABLED"] = str(ob.agent_log_enabled).lower()
            env_vars["AGENT_LOG_INCLUDE_EXECUTION_PATH"] = str(ob.agent_log_include_execution_path).lower()
            env_vars["AGENT_LOG_MAX_PREVIEW_CHARS"] = str(int(ob.agent_log_max_preview_chars or 0))
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
            # New (optional): metrics JSONL log controls
            if "metrics_log_enabled" in getattr(ob, "model_fields_set", set()):
                env_vars["ENABLE_METRICS_LOG"] = str(bool(getattr(ob, "metrics_log_enabled", False))).lower()
                updated_keys.append("ENABLE_METRICS_LOG")
            if "metrics_log_include_text" in getattr(ob, "model_fields_set", set()):
                env_vars["METRICS_LOG_INCLUDE_TEXT"] = str(bool(getattr(ob, "metrics_log_include_text", False))).lower()
                updated_keys.append("METRICS_LOG_INCLUDE_TEXT")

        # Update security/privacy config.
        if request.safety:
            sf = request.safety
            env_vars["PII_REDACTION_ENABLED"] = str(sf.pii_redaction_enabled).lower()
            env_vars["PII_REDACTION_MASK"] = _sanitize_env_value("PII_REDACTION_MASK", sf.pii_redaction_mask)
            env_vars["PII_STREAM_HOLDBACK_CHARS"] = str(int(sf.pii_stream_holdback_chars or 0))
            updated_keys.extend(["PII_REDACTION_ENABLED", "PII_REDACTION_MASK", "PII_STREAM_HOLDBACK_CHARS"])

        # Update chat streaming/runtime config.
        if request.chat:
            ch = request.chat
            if "stream_heartbeat_sec" in getattr(ch, "model_fields_set", set()):
                env_vars["CHAT_STREAM_HEARTBEAT_SEC"] = str(float(ch.stream_heartbeat_sec or 0.0))
                updated_keys.append("CHAT_STREAM_HEARTBEAT_SEC")
            if "stream_cancel_on_disconnect" in getattr(ch, "model_fields_set", set()):
                env_vars["CHAT_STREAM_CANCEL_ON_DISCONNECT"] = str(bool(ch.stream_cancel_on_disconnect)).lower()
                updated_keys.append("CHAT_STREAM_CANCEL_ON_DISCONNECT")

        # Update LangGraph config.
        if request.langgraph:
            lg = request.langgraph
            env_vars["LANGGRAPH_USE_SUBGRAPHS"] = str(lg.use_subgraphs).lower()
            updated_keys.append("LANGGRAPH_USE_SUBGRAPHS")

        # Update ordinary-user frontend navigation visibility.
        if request.navigation:
            env_vars["NAVIGATION_USER_VISIBLE_MODULES"] = serialize_navigation_modules(
                request.navigation.user_visible_modules
            )
            updated_keys.append("NAVIGATION_USER_VISIBLE_MODULES")

        # Update Dify external knowledge adapter.
        if request.dify_external_knowledge:
            df = request.dify_external_knowledge
            env_vars["DIFY_EXTERNAL_KNOWLEDGE_ENABLED"] = str(bool(df.enabled)).lower()
            updated_keys.append("DIFY_EXTERNAL_KNOWLEDGE_ENABLED")

            if df.api_keys and "***" not in df.api_keys:
                env_vars["DIFY_EXTERNAL_KNOWLEDGE_API_KEYS"] = _sanitize_env_value(
                    "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS",
                    df.api_keys,
                )
                updated_keys.append("DIFY_EXTERNAL_KNOWLEDGE_API_KEYS")

            tenant_id_text = _sanitize_env_value("DIFY_EXTERNAL_KNOWLEDGE_TENANT_ID", df.tenant_id or "")
            if tenant_id_text:
                try:
                    UUID(tenant_id_text)
                except ValueError as exc:
                    raise HTTPException(status_code=400, detail="Invalid DIFY_EXTERNAL_KNOWLEDGE_TENANT_ID") from exc
            env_vars["DIFY_EXTERNAL_KNOWLEDGE_TENANT_ID"] = tenant_id_text
            env_vars["DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID"] = _sanitize_env_value(
                "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID",
                df.account_id or "system:dify",
            )

            knowledge_map_json = _sanitize_env_value(
                "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
                df.knowledge_map_json or "",
            )
            if knowledge_map_json:
                try:
                    parsed_knowledge_map = json.loads(knowledge_map_json)
                except json.JSONDecodeError as exc:
                    raise HTTPException(status_code=400, detail="Invalid DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON") from exc
                if not isinstance(parsed_knowledge_map, dict):
                    raise HTTPException(status_code=400, detail="DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON must be a JSON object")
            env_vars["DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON"] = knowledge_map_json

            top_k_max = int(df.top_k_max or 50)
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

        write_env_file(env_vars)
        with contextlib.suppress(Exception):
            # Best-effort, PII-minimal audit record (no secret values).
            from app.services.audit_log_service import audit_log_event

            request_id = (http_request.headers.get("X-Request-ID") or "").strip() or str(
                getattr(http_request.state, "request_id", "") or ""
            ).strip() or None

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
            "updated_keys": updated_keys
        }
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to save configuration: {str(e)}") from e
    finally:
        with contextlib.suppress(Exception):
            lock_ctx.__exit__(None, None, None)


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

    status = {
        "database": {"connected": False, "message": ""},
        "milvus": {"connected": False, "message": ""},
        "llm": {"configured": bool(settings.LLM_API_KEY), "model": settings.LLM_MODEL},
        "embedding": {"configured": bool(settings.EMBEDDING_API_KEY or settings.LLM_API_KEY), "model": settings.EMBEDDING_MODEL},
    }
    def _check_import(module: str) -> tuple[bool, str]:
        # Avoid heavy imports with side-effects in a status endpoint.
        try:
            spec = importlib.util.find_spec(module)
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)[:120]
        if spec is None:
            return False, "not installed"
        return True, "ok"

    from app.parsing.parsers.magic_pdf_parser import resolve_magicpdf_models_dir
    from app.parsing.utils.cli import resolve_cli_command

    def _configured_message(enabled: bool, configured: bool, missing_message: str) -> str:
        if enabled and configured:
            return "configured"
        if enabled:
            return missing_message
        return "disabled"

    parsers: dict[str, dict] = {
        "basic": {"enabled": True, "available": True, "message": "built-in"},
    }

    ok, msg = _check_import("markitdown")
    parsers["markitdown"] = {
        "enabled": bool(getattr(settings, "MARKITDOWN_ENABLED", False)),
        "available": ok,
        "message": "installed" if ok else msg,
    }

    pandoc_enabled = bool(getattr(settings, "PANDOC_ENABLED", False))
    pandoc_cli = (getattr(settings, "PANDOC_CLI", "") or "pandoc").strip() or "pandoc"
    pandoc_cli_ok = bool(resolve_cli_command(pandoc_cli))
    parsers["pandoc"] = {
        "enabled": pandoc_enabled,
        "available": bool(pandoc_enabled and pandoc_cli_ok),
        "message": _configured_message(pandoc_enabled, pandoc_cli_ok, f"missing cli: {pandoc_cli}"),
    }

    lo_enabled = bool(getattr(settings, "LIBREOFFICE_ENABLED", False))
    lo_cli = (getattr(settings, "LIBREOFFICE_CLI", "") or "soffice").strip() or "soffice"
    lo_cli_ok = bool(resolve_cli_command(lo_cli))
    parsers["libreoffice"] = {
        "enabled": lo_enabled,
        "available": bool(lo_enabled and lo_cli_ok),
        "message": _configured_message(lo_enabled, lo_cli_ok, f"missing cli: {lo_cli}"),
    }

    ok, msg = _check_import("app.deepdoc.parser")
    parsers["deepdoc"] = {
        "enabled": bool(getattr(settings, "DEEPDOC_ENABLED", False)),
        "available": ok,
        "message": "available" if ok else msg,
    }

    deepseek_enabled = bool(getattr(settings, "DEEPSEEK_OCR_ENABLED", False))
    deepseek_key = bool((getattr(settings, "SILICONFLOW_API_KEY", "") or "").strip())
    parsers["deepseek_ocr"] = {
        "enabled": deepseek_enabled,
        "available": bool(deepseek_enabled and deepseek_key),
        "message": _configured_message(deepseek_enabled, deepseek_key, "missing api_key"),
    }

    qianfan_enabled = bool(getattr(settings, "QIANFAN_OCR_ENABLED", False))
    qianfan_api_url = (getattr(settings, "QIANFAN_OCR_API_URL", "") or "").strip()
    qianfan_url_ok = bool(qianfan_api_url)
    qianfan_entry: dict[str, object] = {
        "enabled": qianfan_enabled,
        "available": bool(qianfan_enabled and qianfan_url_ok),
        "message": _configured_message(qianfan_enabled, qianfan_url_ok, _MISSING_API_URL_MESSAGE),
    }
    if qianfan_enabled and qianfan_url_ok:
        health_url = _convert_service_url_to_health_url(qianfan_api_url)
        data, err = await _probe_http_json(health_url, timeout_sec=0.6)
        if data is not None:
            qianfan_entry["health"] = data
            model_name = data.get("model")
            mode = data.get("mode")
            parts = [p for p in [model_name, mode] if isinstance(p, str) and p.strip()]
            if parts:
                qianfan_entry["message"] = f"configured ({', '.join(parts[:2])})"
        else:
            qianfan_entry["health"] = {"ok": False, "error": err}
            qianfan_entry["message"] = _CONFIGURED_HEALTH_UNREACHABLE_MESSAGE
    parsers["qianfan_ocr"] = qianfan_entry

    etl_enabled = bool(getattr(settings, "ETL4LLM_ENABLED", False))
    etl_url = bool((getattr(settings, "ETL4LLM_API_URL", "") or "").strip())
    parsers["etl4llm"] = {
        "enabled": etl_enabled,
        "available": bool(etl_enabled and etl_url),
        "message": _configured_message(etl_enabled, etl_url, _MISSING_API_URL_MESSAGE),
    }

    marker_enabled = bool(getattr(settings, "MARKER_ENABLED", False))
    marker_url = bool((getattr(settings, "MARKER_API_URL", "") or "").strip())
    parsers["marker"] = {
        "enabled": marker_enabled,
        "available": bool(marker_enabled and marker_url),
        "message": _configured_message(marker_enabled, marker_url, _MISSING_API_URL_MESSAGE),
    }

    paddlevl_enabled = bool(getattr(settings, "PADDLE_VL_ENABLED", False))
    paddlevl_api_url = (getattr(settings, "PADDLE_VL_API_URL", "") or "").strip()
    paddlevl_url = bool(paddlevl_api_url)
    paddlevl_entry: dict[str, object] = {
        "enabled": paddlevl_enabled,
        "available": bool(paddlevl_enabled and paddlevl_url),
        "message": _configured_message(paddlevl_enabled, paddlevl_url, _MISSING_API_URL_MESSAGE),
    }
    if paddlevl_enabled and paddlevl_url:
        health_url = _convert_service_url_to_health_url(paddlevl_api_url)
        data, err = await _probe_http_json(health_url, timeout_sec=0.6)
        if data is not None:
            paddlevl_entry["health"] = data
            pv = data.get("pipeline_version") or data.get("version")
            mode = data.get("mode")
            parts = [p for p in [pv, mode] if isinstance(p, str) and p.strip()]
            if parts:
                paddlevl_entry["message"] = f"configured ({', '.join(parts[:2])})"
        else:
            paddlevl_entry["health"] = {"ok": False, "error": err}
            paddlevl_entry["message"] = _CONFIGURED_HEALTH_UNREACHABLE_MESSAGE

    parsers["paddle_vl"] = paddlevl_entry

    textin_enabled = bool(getattr(settings, "TEXTIN_ENABLED", False))
    textin_api_url = bool((getattr(settings, "TEXTIN_API_URL", "") or "").strip())
    textin_app_id = bool((getattr(settings, "TEXTIN_APP_ID", "") or "").strip())
    textin_secret = bool((getattr(settings, "TEXTIN_SECRET_CODE", "") or "").strip())
    textin_available = bool(textin_enabled and textin_api_url and textin_app_id and textin_secret)
    if not textin_enabled:
        textin_message = "disabled"
    elif not textin_api_url:
        textin_message = "missing api_url"
    elif not textin_app_id:
        textin_message = "missing app_id"
    elif not textin_secret:
        textin_message = "missing secret_code"
    else:
        textin_message = "configured"
    parsers["textin"] = {
        "enabled": textin_enabled,
        "available": textin_available,
        "message": textin_message,
    }

    olmocr_enabled = bool(getattr(settings, "OLMOCR_ENABLED", False))
    olmocr_api_url = (getattr(settings, "OLMOCR_API_URL", "") or "").strip()
    olmocr_url_ok = bool(olmocr_api_url)
    olmocr_entry: dict[str, object] = {
        "enabled": olmocr_enabled,
        "available": bool(olmocr_enabled and olmocr_url_ok),
        "message": _configured_message(olmocr_enabled, olmocr_url_ok, _MISSING_API_URL_MESSAGE),
    }
    if olmocr_enabled and olmocr_url_ok:
        health_url = _convert_service_url_to_health_url(olmocr_api_url)
        data, err = await _probe_http_json(health_url, timeout_sec=0.6)
        if data is not None:
            olmocr_entry["health"] = data
        else:
            olmocr_entry["health"] = {"ok": False, "error": err}
            olmocr_entry["message"] = _CONFIGURED_HEALTH_UNREACHABLE_MESSAGE
    parsers["olmocr"] = olmocr_entry

    ok, msg = _check_import("docling")
    parsers["docling"] = {
        "enabled": bool(getattr(settings, "DOCLING_ENABLED", False)),
        "available": ok,
        "message": "installed" if ok else msg,
    }

    mineru_enabled = bool(getattr(settings, "MINERU_ENABLED", False))
    mineru_local = bool((getattr(settings, "MINERU_LOCAL_SERVER_URL", "") or "").strip())
    mineru_token = (getattr(settings, "MINERU_API_TOKEN", "") or "").strip()
    mineru_exp = try_get_jwt_exp(mineru_token) if mineru_token else None
    mineru_token_expired = bool(mineru_exp is not None and int(mineru_exp) <= int(time.time()))
    mineru_available = bool(mineru_enabled and (mineru_local or (mineru_token and not mineru_token_expired)))

    if not mineru_enabled:
        mineru_message = "disabled"
    elif mineru_local:
        mineru_message = "configured (local)"
    elif not mineru_token:
        mineru_message = "missing api_token or local_server_url"
    elif mineru_token_expired and mineru_exp is not None:
        mineru_message = f"api_token expired at {format_unix_ts_utc(int(mineru_exp))}"
    else:
        mineru_message = "configured"

    parsers["mineru"] = {
        "enabled": mineru_enabled,
        "available": mineru_available,
        "message": mineru_message,
    }

    magicpdf_enabled = bool(getattr(settings, "MAGIC_PDF_ENABLED", False))
    magicpdf_api_url = (getattr(settings, "MAGIC_PDF_API_URL", "") or "").strip()
    magicpdf_cli = (getattr(settings, "MAGIC_PDF_CLI", "") or "magic-pdf").strip() or "magic-pdf"
    magicpdf_cli_ok = bool(resolve_cli_command(magicpdf_cli))
    magicpdf_models_dir = resolve_magicpdf_models_dir(getattr(settings, "MAGIC_PDF_MODELS_DIR", ""))
    if not magicpdf_enabled:
        magicpdf_message = "disabled"
        magicpdf_available = False
    elif magicpdf_api_url:
        magicpdf_message = "configured (service)"
        magicpdf_available = True
    elif not magicpdf_cli_ok:
        magicpdf_message = f"missing cli: {magicpdf_cli}"
        magicpdf_available = False
    elif magicpdf_models_dir is None:
        magicpdf_message = "missing models"
        magicpdf_available = False
    else:
        magicpdf_message = f"configured (models: {magicpdf_models_dir})"
        magicpdf_available = True
    parsers["magicpdf"] = {
        "enabled": magicpdf_enabled,
        "available": magicpdf_available,
        "message": magicpdf_message,
    }

    status["parsers"] = parsers

    # Check database connection.
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        status["database"]["connected"] = True
        status["database"]["message"] = "connected"
    except Exception as e:
        status["database"]["message"] = str(e)[:100]

    # Check Milvus connection.
    try:
        connections.connect(
            alias="status_check",
            host=settings.MILVUS_HOST,
            port=settings.MILVUS_PORT,
            user=settings.MILVUS_USER or None,
            password=settings.MILVUS_PASSWORD or None,
        )
        connections.disconnect("status_check")
        status["milvus"]["connected"] = True
        status["milvus"]["message"] = "connected"
    except Exception as e:
        status["milvus"]["message"] = str(e)[:100]

    return status


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
    import httpx
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

    _validate_public_base_url(request.api_base)

    trust_env = httpx_trust_env(logger=logger)
    timeout = float(request.timeout) if request.timeout else 20.0

    try:
        with httpx.Client(trust_env=trust_env, timeout=timeout) as http_client:
            async with httpx.AsyncClient(trust_env=trust_env, timeout=timeout) as http_async_client:
                llm = ChatOpenAI(
                    model=request.model,
                    api_key=request.api_key,
                    base_url=normalize_openai_compatible_base_url(request.api_base),
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
