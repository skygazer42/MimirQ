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
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlparse, urlunparse
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.settings import (
    SYSTEM_DIFY_ACCOUNT_ID,
    CacheConfig,
    ChatConfig,
    DifyExternalKnowledgeConfig,
    DoclingConfig,
    EmbeddingConfig,
    Etl4LlmConfig,
    FeatureFlags,
    GovernanceConfig,
    KGConfig,
    LangGraphConfig,
    LLMConfig,
    MagicPDFConfig,
    MarkerConfig,
    MilvusConfig,
    MinerUConfig,
    MinioConfig,
    NavigationConfig,
    ObservabilityConfig,
    PaddleVLConfig,
    RAGConfig,
    SafetyConfig,
    SystemSettings,
    TestLLMRequest,
    TextInConfig,
    UpdateSettingsRequest,
    UrlIngestStatus,
    normalize_mineru_backend,
)
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
from app.services.navigation_visibility import normalize_navigation_modules
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
_VECTOR_STORE_EMBEDDING_RESET_KEYS = frozenset(
    {
        "EMBEDDING_PROVIDER",
        "EMBEDDING_MODEL",
        "EMBEDDING_API_KEY",
        "EMBEDDING_API_BASE",
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


@contextlib.contextmanager
def _env_file_lock() -> Iterator[None]:
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


def _sanitize_env_value(key: str, value: str) -> str:
    text = value
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
    raw = api_url.strip()
    if not raw:
        return ""

    try:
        parsed = urlparse(raw)
    except Exception:
        return ""

    path = (parsed.path or "").strip()
    if path.endswith("/v1/convert/file"):
        path = path[: -len("/v1/convert/file")] + "/health"
    elif path.endswith("/v1/convert/source"):
        path = path[: -len("/v1/convert/source")] + "/health"
    elif path.endswith("/convert"):
        path = path[: -len("/convert")] + "/health"
    else:
        base = path.rstrip("/")
        path = f"{base}/health" if base else "/health"

    return urlunparse(parsed._replace(path=path, params="", query="", fragment=""))


async def _probe_http_json(
    url: str,
    *,
    timeout_sec: float = 0.6,
    headers: dict[str, str] | None = None,
    trust_env: bool = True,
) -> tuple[dict[str, Any] | None, str | None]:
    """
    Best-effort GET+JSON probe with short timeout.

    Returns (data, error). `data` is only returned when the payload is a JSON object.
    """
    url = url.strip()
    if not url:
        return None, "empty url"

    try:
        async with httpx.AsyncClient(timeout=timeout_sec or 0.6, trust_env=trust_env) as client:
            resp = await client.get(url, headers=headers)
    except Exception as exc:  # noqa: BLE001
        return None, f"request_failed: {str(exc)[:160]}"

    if resp.status_code != 200:
        return None, f"bad_status: {resp.status_code}"

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
        system_tenant_id = UUID(settings.DEFAULT_TENANT_ID)
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
    if (member.role or "").strip().lower() != "owner":
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


def _parse_bool(value: str) -> bool:
    text = value.strip().lower()
    return text in {"1", "true", "yes", "y", "on"}


def _parse_int(value: str, *, default: int = 0) -> int:
    try:
        return int(value)
    except ValueError:
        return default


def _parse_float(value: str, *, default: float = 0.0) -> float:
    try:
        return float(value)
    except ValueError:
        return default


def _apply_runtime_specs(
    env_vars: dict[str, str],
    updated_keys: set[str],
    specs: tuple[tuple[str, Callable[[str], str | bool | int | float]], ...],
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
                lambda value: _parse_int(value, default=settings.MINIO_IMAGE_MAX_BYTES),
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
            ("CHUNK_MIN_CHARS", lambda value: _parse_int(value, default=settings.CHUNK_MIN_CHARS)),
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
                lambda value: _parse_int(value, default=settings.IMAGE_APPEND_MAX),
            ),
        ),
    )

    if "BM25_INDEX_ENABLED" in updated_keys and "BM25_INDEX_ENABLED" in env_vars:
        old_bm25 = settings.BM25_INDEX_ENABLED
        new_bm25 = _parse_bool(env_vars["BM25_INDEX_ENABLED"])
        settings.BM25_INDEX_ENABLED = new_bm25
        if old_bm25 and not new_bm25:
            with contextlib.suppress(Exception):
                from app.rag.retriever import hybrid_retriever

                hybrid_retriever.clear_derived_index_caches()


def _apply_cache_runtime_settings(env_vars: dict[str, str], updated_keys: set[str]) -> None:
    _apply_runtime_specs(
        env_vars,
        updated_keys,
        (
            ("UPLOAD_DEDUP_ENABLED", _parse_bool),
            ("CHAT_RESPONSE_CACHE_ENABLED", _parse_bool),
            (
                "CHAT_RESPONSE_CACHE_TTL_SEC",
                lambda value: _parse_int(value, default=settings.CHAT_RESPONSE_CACHE_TTL_SEC),
            ),
            (
                "CHAT_RESPONSE_CACHE_MAX_VALUE_BYTES",
                lambda value: _parse_int(
                    value,
                    default=settings.CHAT_RESPONSE_CACHE_MAX_VALUE_BYTES or 200_000,
                ),
            ),
            ("CHAT_RESPONSE_CACHE_REQUIRE_EMPTY_HISTORY", _parse_bool),
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
            ("MINERU_BACKEND", normalize_mineru_backend),
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


def _apply_docling_runtime_settings(env_vars: dict[str, str], updated_keys: set[str]) -> None:
    _apply_runtime_specs(
        env_vars,
        updated_keys,
        (
            ("DOCLING_API_URL", str),
            ("DOCLING_API_KEY", str),
            (
                "DOCLING_REQUEST_TIMEOUT_SEC",
                lambda value: _parse_int(value, default=settings.DOCLING_REQUEST_TIMEOUT_SEC),
            ),
            (
                "DOCLING_HEALTH_TIMEOUT_SEC",
                lambda value: _parse_int(value, default=settings.DOCLING_HEALTH_TIMEOUT_SEC),
            ),
            ("DOCLING_HTTP_TRUST_ENV", _parse_bool),
            ("DOCLING_OCR_ENABLED", _parse_bool),
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
                lambda value: _parse_int(value, default=settings.MAGIC_PDF_REQUEST_TIMEOUT_SEC or 600),
            ),
            (
                "MAGIC_PDF_MAX_CONCURRENT_JOBS",
                lambda value: _parse_int(value, default=settings.MAGIC_PDF_MAX_CONCURRENT_JOBS),
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
                lambda value: _parse_float(value, default=settings.CHAT_STREAM_HEARTBEAT_SEC),
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
                lambda value: _parse_int(value, default=settings.DIFY_EXTERNAL_KNOWLEDGE_TOP_K_MAX),
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
    _apply_governance_runtime_settings(env_vars, updated_key_set)
    _apply_mineru_runtime_settings(env_vars, updated_key_set)
    _apply_etl4llm_runtime_settings(env_vars, updated_key_set)
    _apply_marker_runtime_settings(env_vars, updated_key_set)
    _apply_docling_runtime_settings(env_vars, updated_key_set)
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


def write_env_file(env_vars: dict[str, str]) -> None:
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
) -> SystemSettings:
    """Get current system config."""
    _ensure_settings_readable(db, tenant_id, account_id)
    return SystemSettings(
        feature_flags=FeatureFlags(
            kg_enabled=settings.KG_ENABLED,
            deepdoc_enabled=settings.DEEPDOC_ENABLED,
            docling_enabled=settings.DOCLING_ENABLED,
            etl4llm_enabled=settings.ETL4LLM_ENABLED,
            marker_enabled=settings.MARKER_ENABLED,
            paddle_vl_enabled=settings.PADDLE_VL_ENABLED,
            textin_enabled=settings.TEXTIN_ENABLED,
            markitdown_enabled=settings.MARKITDOWN_ENABLED,
            llama_index_enabled=settings.LLAMA_INDEX_ENABLED,
            mineru_enabled=settings.MINERU_ENABLED,
            magicpdf_enabled=settings.MAGIC_PDF_ENABLED,
        ),
        kg=KGConfig(
            chat_enabled=settings.KG_CHAT_ENABLED,
            extract_prompt_template_id=settings.KG_EXTRACT_PROMPT_TEMPLATE_ID,
            extract_prompt_template_key=settings.KG_EXTRACT_PROMPT_TEMPLATE_KEY,
            extract_prompt_ab_experiment_key=settings.KG_EXTRACT_PROMPT_AB_EXPERIMENT_KEY,
            extract_replace_existing=settings.KG_EXTRACT_REPLACE_EXISTING,
            extract_prune_orphan_entities=settings.KG_EXTRACT_PRUNE_ORPHAN_ENTITIES,
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
            enabled=settings.MINIO_ENABLED,
            endpoint=settings.MINIO_ENDPOINT,
            access_key=mask_secret(settings.MINIO_ACCESS_KEY),
            secret_key=mask_secret(settings.MINIO_SECRET_KEY),
            bucket_name=settings.MINIO_BUCKET_NAME,
            use_ssl=settings.MINIO_USE_SSL,
            documents_enabled=settings.MINIO_DOCUMENTS_ENABLED,
            image_max_bytes=settings.MINIO_IMAGE_MAX_BYTES,
        ),
        rag=RAGConfig(
            chunk_size=settings.CHUNK_SIZE,
            chunk_overlap=settings.CHUNK_OVERLAP,
            chunk_min_chars=settings.CHUNK_MIN_CHARS,
            retrieval_top_k=settings.RETRIEVAL_TOP_K,
            similarity_threshold=settings.SIMILARITY_THRESHOLD,
            default_parser_backend=settings.DEFAULT_PARSER_BACKEND,
            default_chunk_strategy=settings.DEFAULT_CHUNK_STRATEGY,
            bm25_index_enabled=settings.BM25_INDEX_ENABLED,
            enable_reranker=settings.ENABLE_RERANKER,
            reranker_provider=settings.RERANKER_PROVIDER,
            reranker_top_n=settings.RERANKER_TOP_N,
            show_image_in_answer=settings.SHOW_IMAGE_IN_ANSWER,
            image_append_max=settings.IMAGE_APPEND_MAX,
        ),
        cache=CacheConfig(
            upload_dedup_enabled=settings.UPLOAD_DEDUP_ENABLED,
            chat_response_cache_enabled=settings.CHAT_RESPONSE_CACHE_ENABLED,
            chat_response_cache_ttl_sec=settings.CHAT_RESPONSE_CACHE_TTL_SEC,
            chat_response_cache_max_value_bytes=settings.CHAT_RESPONSE_CACHE_MAX_VALUE_BYTES,
            chat_response_cache_require_empty_history=settings.CHAT_RESPONSE_CACHE_REQUIRE_EMPTY_HISTORY,
        ),
        url_ingest=UrlIngestStatus(
            enabled=settings.URL_INGEST_ENABLED,
        ),
        governance=GovernanceConfig(
            enabled=settings.GOVERNANCE_ENABLED,
            pii_anonymize=settings.GOVERNANCE_PII_ANONYMIZE,
            secrets_redact=settings.GOVERNANCE_SECRETS_REDACT,
            quarantine_on_drop=settings.GOVERNANCE_QUARANTINE_ON_DROP,
        ),
        mineru=MinerUConfig(
            api_token=mask_secret(settings.MINERU_API_TOKEN),
            api_base=settings.MINERU_API_BASE,
            model_version=settings.MINERU_MODEL_VERSION,
            backend=normalize_mineru_backend(settings.MINERU_BACKEND),
            local_server_url=settings.MINERU_LOCAL_SERVER_URL,
            vl_server=settings.MINERU_VL_SERVER,
        ),
        etl4llm=Etl4LlmConfig(
            api_url=settings.ETL4LLM_API_URL,
            timeout_sec=settings.ETL4LLM_TIMEOUT_SEC,
            mode=settings.ETL4LLM_MODE,
            force_ocr=settings.ETL4LLM_FORCE_OCR,
            enable_formula=settings.ETL4LLM_ENABLE_FORMULA,
            extract_images=settings.ETL4LLM_EXTRACT_IMAGES,
            filter_page_header_footer=settings.ETL4LLM_FILTER_PAGE_HEADER_FOOTER,
        ),
        marker=MarkerConfig(
            api_url=settings.MARKER_API_URL,
            timeout_sec=settings.MARKER_TIMEOUT_SEC,
        ),
        docling=DoclingConfig(
            api_url=settings.DOCLING_API_URL,
            api_key=mask_secret(settings.DOCLING_API_KEY),
            request_timeout_sec=settings.DOCLING_REQUEST_TIMEOUT_SEC,
            health_timeout_sec=settings.DOCLING_HEALTH_TIMEOUT_SEC,
            http_trust_env=settings.DOCLING_HTTP_TRUST_ENV,
            ocr_enabled=settings.DOCLING_OCR_ENABLED,
        ),
        paddle_vl=PaddleVLConfig(
            api_url=settings.PADDLE_VL_API_URL,
            timeout_sec=settings.PADDLE_VL_TIMEOUT_SEC,
            pipeline_version=settings.PADDLE_VL_PIPELINE_VERSION,
            mode=settings.PADDLE_VL_MODE,
        ),
        textin=TextInConfig(
            api_url=settings.TEXTIN_API_URL,
            app_id=settings.TEXTIN_APP_ID,
            secret_code=mask_secret(settings.TEXTIN_SECRET_CODE),
            timeout_sec=settings.TEXTIN_TIMEOUT_SEC,
            parse_mode=settings.TEXTIN_PARSE_MODE,
            table_flavor=settings.TEXTIN_TABLE_FLAVOR,
            apply_document_tree=settings.TEXTIN_APPLY_DOCUMENT_TREE,
            markdown_details=settings.TEXTIN_MARKDOWN_DETAILS,
            get_image=settings.TEXTIN_GET_IMAGE,
            dpi=settings.TEXTIN_DPI,
            page_count=settings.TEXTIN_PAGE_COUNT,
        ),
        magicpdf=MagicPDFConfig(
            api_url=settings.MAGIC_PDF_API_URL,
            request_timeout_sec=settings.MAGIC_PDF_REQUEST_TIMEOUT_SEC,
            max_concurrent_jobs=settings.MAGIC_PDF_MAX_CONCURRENT_JOBS,
            cli=settings.MAGIC_PDF_CLI,
            method=settings.MAGIC_PDF_METHOD,
            lang=settings.MAGIC_PDF_LANG,
            debug=settings.MAGIC_PDF_DEBUG,
            timeout_sec=settings.MAGIC_PDF_TIMEOUT_SEC,
            models_dir=settings.MAGIC_PDF_MODELS_DIR,
            device_mode=settings.MAGIC_PDF_DEVICE_MODE,
            keep_artifacts=settings.MAGIC_PDF_KEEP_ARTIFACTS,
        ),
        observability=ObservabilityConfig(
            tool_call_log_enabled=settings.TOOL_CALL_LOG_ENABLED,
            tool_call_log_include_preview=settings.TOOL_CALL_LOG_INCLUDE_PREVIEW,
            tool_call_log_max_preview_chars=settings.TOOL_CALL_LOG_MAX_PREVIEW_CHARS,
            agent_log_enabled=settings.AGENT_LOG_ENABLED,
            agent_log_include_execution_path=settings.AGENT_LOG_INCLUDE_EXECUTION_PATH,
            agent_log_max_preview_chars=settings.AGENT_LOG_MAX_PREVIEW_CHARS,
            metrics_log_enabled=settings.ENABLE_METRICS_LOG,
            metrics_log_include_text=settings.METRICS_LOG_INCLUDE_TEXT,
        ),
        safety=SafetyConfig(
            pii_redaction_enabled=settings.PII_REDACTION_ENABLED,
            pii_redaction_mask=settings.PII_REDACTION_MASK,
            pii_stream_holdback_chars=settings.PII_STREAM_HOLDBACK_CHARS,
        ),
        chat=ChatConfig(
            stream_heartbeat_sec=settings.CHAT_STREAM_HEARTBEAT_SEC,
            stream_cancel_on_disconnect=settings.CHAT_STREAM_CANCEL_ON_DISCONNECT,
        ),
        langgraph=LangGraphConfig(
            use_subgraphs=settings.LANGGRAPH_USE_SUBGRAPHS,
        ),
        navigation=NavigationConfig(
            user_visible_modules=normalize_navigation_modules(settings.NAVIGATION_USER_VISIBLE_MODULES),
        ),
        dify_external_knowledge=DifyExternalKnowledgeConfig(
            enabled=settings.DIFY_EXTERNAL_KNOWLEDGE_ENABLED,
            api_keys=mask_secret(settings.DIFY_EXTERNAL_KNOWLEDGE_API_KEYS),
            tenant_id=settings.DIFY_EXTERNAL_KNOWLEDGE_TENANT_ID,
            account_id=str(settings.DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID or SYSTEM_DIFY_ACCOUNT_ID),
            knowledge_map_json=settings.DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON,
            top_k_max=settings.DIFY_EXTERNAL_KNOWLEDGE_TOP_K_MAX,
            endpoint_path="/api/v1/integrations/dify/retrieval",
        ),
    )


def _set_bool_env(env_vars: dict[str, str], key: str, value: bool) -> None:
    env_vars[key] = str(value).lower()


def _set_non_negative_int_env(env_vars: dict[str, str], key: str, value: int) -> None:
    env_vars[key] = str(max(0, value))


def _set_sanitized_env(env_vars: dict[str, str], key: str, value: str) -> None:
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
    sanitized = _sanitize_env_value(key, value)
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
    sanitized = _sanitize_env_value(key, value)
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
        ("DOCLING_ENABLED", feature_flags.docling_enabled),
        ("ETL4LLM_ENABLED", feature_flags.etl4llm_enabled),
        ("MARKER_ENABLED", feature_flags.marker_enabled),
        ("PADDLE_VL_ENABLED", feature_flags.paddle_vl_enabled),
        ("TEXTIN_ENABLED", feature_flags.textin_enabled),
        ("MARKITDOWN_ENABLED", feature_flags.markitdown_enabled),
        ("LLAMA_INDEX_ENABLED", feature_flags.llama_index_enabled),
        ("MINERU_ENABLED", feature_flags.mineru_enabled),
        ("MAGIC_PDF_ENABLED", feature_flags.magicpdf_enabled),
    )
    for key, value in values:
        _set_bool_env(env_vars, key, value)
    updated_keys.extend(key for key, _value in values)


def _update_kg_env(env_vars: dict[str, str], updated_keys: list[str], kg: KGConfig) -> None:
    _set_bool_env(env_vars, "KG_CHAT_ENABLED", kg.chat_enabled)
    env_vars["KG_EXTRACT_PROMPT_TEMPLATE_ID"] = _validate_optional_uuid_setting(
        "KG_EXTRACT_PROMPT_TEMPLATE_ID",
        kg.extract_prompt_template_id,
        detail="Invalid KG_EXTRACT_PROMPT_TEMPLATE_ID",
    )
    _set_sanitized_env(env_vars, "KG_EXTRACT_PROMPT_TEMPLATE_KEY", kg.extract_prompt_template_key)
    _set_sanitized_env(env_vars, "KG_EXTRACT_PROMPT_AB_EXPERIMENT_KEY", kg.extract_prompt_ab_experiment_key)
    _set_bool_env(env_vars, "KG_EXTRACT_REPLACE_EXISTING", kg.extract_replace_existing)
    _set_bool_env(env_vars, "KG_EXTRACT_PRUNE_ORPHAN_ENTITIES", kg.extract_prune_orphan_entities)
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
    env_vars["MINIO_IMAGE_MAX_BYTES"] = str(minio.image_max_bytes)
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
    _set_non_negative_int_env(env_vars, "CHUNK_MIN_CHARS", rag.chunk_min_chars)
    env_vars["RETRIEVAL_TOP_K"] = str(rag.retrieval_top_k)
    env_vars["SIMILARITY_THRESHOLD"] = str(rag.similarity_threshold)
    _set_sanitized_env(env_vars, "DEFAULT_PARSER_BACKEND", rag.default_parser_backend)
    _set_sanitized_env(env_vars, "DEFAULT_CHUNK_STRATEGY", rag.default_chunk_strategy)
    _set_bool_env(env_vars, "BM25_INDEX_ENABLED", rag.bm25_index_enabled)
    _set_bool_env(env_vars, "ENABLE_RERANKER", rag.enable_reranker)
    _set_sanitized_env(env_vars, "RERANKER_PROVIDER", rag.reranker_provider)
    env_vars["RERANKER_TOP_N"] = str(rag.reranker_top_n)
    _set_bool_env(env_vars, "SHOW_IMAGE_IN_ANSWER", rag.show_image_in_answer)
    env_vars["IMAGE_APPEND_MAX"] = str(rag.image_append_max)
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
    _set_bool_env(env_vars, "UPLOAD_DEDUP_ENABLED", cache.upload_dedup_enabled)
    _set_bool_env(env_vars, "CHAT_RESPONSE_CACHE_ENABLED", cache.chat_response_cache_enabled)
    env_vars["CHAT_RESPONSE_CACHE_TTL_SEC"] = str(cache.chat_response_cache_ttl_sec)
    env_vars["CHAT_RESPONSE_CACHE_MAX_VALUE_BYTES"] = str(cache.chat_response_cache_max_value_bytes)
    _set_bool_env(
        env_vars,
        "CHAT_RESPONSE_CACHE_REQUIRE_EMPTY_HISTORY",
        cache.chat_response_cache_require_empty_history,
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


def _update_governance_env(env_vars: dict[str, str], updated_keys: list[str], governance: GovernanceConfig) -> None:
    _set_bool_env(env_vars, "GOVERNANCE_ENABLED", governance.enabled)
    _set_bool_env(env_vars, "GOVERNANCE_PII_ANONYMIZE", governance.pii_anonymize)
    _set_bool_env(env_vars, "GOVERNANCE_SECRETS_REDACT", governance.secrets_redact)
    _set_bool_env(env_vars, "GOVERNANCE_QUARANTINE_ON_DROP", governance.quarantine_on_drop)
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
    env_vars["MINERU_BACKEND"] = mineru.backend
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
    _set_sanitized_env(env_vars, "ETL4LLM_API_URL", etl4llm.api_url)
    env_vars["ETL4LLM_TIMEOUT_SEC"] = str(etl4llm.timeout_sec)
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
    _set_sanitized_env(env_vars, "MARKER_API_URL", marker.api_url)
    env_vars["MARKER_TIMEOUT_SEC"] = str(marker.timeout_sec)
    updated_keys.extend(["MARKER_API_URL", "MARKER_TIMEOUT_SEC"])


def _update_docling_env(env_vars: dict[str, str], updated_keys: list[str], docling: DoclingConfig) -> None:
    _set_sanitized_env(env_vars, "DOCLING_API_URL", docling.api_url)
    _set_maskable_secret_env(env_vars, updated_keys, "DOCLING_API_KEY", docling.api_key)
    env_vars["DOCLING_REQUEST_TIMEOUT_SEC"] = str(docling.request_timeout_sec)
    env_vars["DOCLING_HEALTH_TIMEOUT_SEC"] = str(docling.health_timeout_sec)
    _set_bool_env(env_vars, "DOCLING_HTTP_TRUST_ENV", docling.http_trust_env)
    _set_bool_env(env_vars, "DOCLING_OCR_ENABLED", docling.ocr_enabled)
    updated_keys.extend(
        [
            "DOCLING_API_URL",
            "DOCLING_REQUEST_TIMEOUT_SEC",
            "DOCLING_HEALTH_TIMEOUT_SEC",
            "DOCLING_HTTP_TRUST_ENV",
            "DOCLING_OCR_ENABLED",
        ]
    )


def _update_paddle_vl_env(env_vars: dict[str, str], updated_keys: list[str], paddle_vl: PaddleVLConfig) -> None:
    _set_sanitized_env(env_vars, "PADDLE_VL_API_URL", paddle_vl.api_url)
    env_vars["PADDLE_VL_TIMEOUT_SEC"] = str(paddle_vl.timeout_sec)
    pipeline_version = (paddle_vl.pipeline_version or "v1.5").strip() or "v1.5"
    env_vars["PADDLE_VL_PIPELINE_VERSION"] = _sanitize_env_value("PADDLE_VL_PIPELINE_VERSION", pipeline_version)
    env_vars["PADDLE_VL_MODE"] = _sanitize_env_value(
        "PADDLE_VL_MODE",
        _normalize_choice(paddle_vl.mode or "doc_parser", default="doc_parser", allowed={"doc_parser"}),
    )
    updated_keys.extend(["PADDLE_VL_API_URL", "PADDLE_VL_TIMEOUT_SEC", "PADDLE_VL_PIPELINE_VERSION", "PADDLE_VL_MODE"])


def _update_textin_env(env_vars: dict[str, str], updated_keys: list[str], textin: TextInConfig) -> None:
    _set_sanitized_env(env_vars, "TEXTIN_API_URL", textin.api_url)
    _set_sanitized_env(env_vars, "TEXTIN_APP_ID", textin.app_id)
    _set_maskable_secret_env(env_vars, updated_keys, "TEXTIN_SECRET_CODE", textin.secret_code)
    env_vars["TEXTIN_TIMEOUT_SEC"] = str(textin.timeout_sec)
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
    env_vars["MAGIC_PDF_REQUEST_TIMEOUT_SEC"] = str(max(1, magicpdf.request_timeout_sec))
    env_vars["MAGIC_PDF_MAX_CONCURRENT_JOBS"] = str(max(1, magicpdf.max_concurrent_jobs or 1))
    _set_sanitized_env(env_vars, "MAGIC_PDF_CLI", magicpdf.cli)
    _set_sanitized_env(env_vars, "MAGIC_PDF_METHOD", magicpdf.method)
    _set_sanitized_env(env_vars, "MAGIC_PDF_LANG", magicpdf.lang)
    _set_bool_env(env_vars, "MAGIC_PDF_DEBUG", magicpdf.debug)
    env_vars["MAGIC_PDF_TIMEOUT_SEC"] = str(magicpdf.timeout_sec)
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
    env_vars["TOOL_CALL_LOG_MAX_PREVIEW_CHARS"] = str(observability.tool_call_log_max_preview_chars)
    _set_bool_env(env_vars, "AGENT_LOG_ENABLED", observability.agent_log_enabled)
    _set_bool_env(env_vars, "AGENT_LOG_INCLUDE_EXECUTION_PATH", observability.agent_log_include_execution_path)
    env_vars["AGENT_LOG_MAX_PREVIEW_CHARS"] = str(observability.agent_log_max_preview_chars)
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
    model_fields_set = observability.model_fields_set
    if "metrics_log_enabled" in model_fields_set:
        _set_bool_env(env_vars, "ENABLE_METRICS_LOG", observability.metrics_log_enabled)
        updated_keys.append("ENABLE_METRICS_LOG")
    if "metrics_log_include_text" in model_fields_set:
        _set_bool_env(env_vars, "METRICS_LOG_INCLUDE_TEXT", observability.metrics_log_include_text)
        updated_keys.append("METRICS_LOG_INCLUDE_TEXT")


def _update_safety_env(env_vars: dict[str, str], updated_keys: list[str], safety: SafetyConfig) -> None:
    _set_bool_env(env_vars, "PII_REDACTION_ENABLED", safety.pii_redaction_enabled)
    _set_sanitized_env(env_vars, "PII_REDACTION_MASK", safety.pii_redaction_mask)
    env_vars["PII_STREAM_HOLDBACK_CHARS"] = str(safety.pii_stream_holdback_chars)
    updated_keys.extend(["PII_REDACTION_ENABLED", "PII_REDACTION_MASK", "PII_STREAM_HOLDBACK_CHARS"])


def _update_chat_env(env_vars: dict[str, str], updated_keys: list[str], chat: ChatConfig) -> None:
    model_fields_set = chat.model_fields_set
    if "stream_heartbeat_sec" in model_fields_set:
        env_vars["CHAT_STREAM_HEARTBEAT_SEC"] = str(chat.stream_heartbeat_sec or 0.0)
        updated_keys.append("CHAT_STREAM_HEARTBEAT_SEC")
    if "stream_cancel_on_disconnect" in model_fields_set:
        _set_bool_env(env_vars, "CHAT_STREAM_CANCEL_ON_DISCONNECT", chat.stream_cancel_on_disconnect)
        updated_keys.append("CHAT_STREAM_CANCEL_ON_DISCONNECT")


def _update_langgraph_env(env_vars: dict[str, str], updated_keys: list[str], langgraph: LangGraphConfig) -> None:
    _set_bool_env(env_vars, "LANGGRAPH_USE_SUBGRAPHS", langgraph.use_subgraphs)
    updated_keys.append("LANGGRAPH_USE_SUBGRAPHS")


def _update_navigation_env(env_vars: dict[str, str], updated_keys: list[str], navigation: NavigationConfig) -> None:
    env_vars["NAVIGATION_USER_VISIBLE_MODULES"] = ",".join(navigation.user_visible_modules)
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
        dify_external_knowledge.tenant_id,
        detail="Invalid DIFY_EXTERNAL_KNOWLEDGE_TENANT_ID",
    )
    _set_sanitized_env(
        env_vars,
        "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID",
        dify_external_knowledge.account_id or SYSTEM_DIFY_ACCOUNT_ID,
    )
    env_vars["DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON"] = _validate_json_object_setting(
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        dify_external_knowledge.knowledge_map_json,
        invalid_detail="Invalid DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        non_object_detail="DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON must be a JSON object",
    )

    env_vars["DIFY_EXTERNAL_KNOWLEDGE_TOP_K_MAX"] = str(dify_external_knowledge.top_k_max)
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
        ("governance", _update_governance_env),
        ("mineru", _update_mineru_env),
        ("etl4llm", _update_etl4llm_env),
        ("marker", _update_marker_env),
        ("docling", _update_docling_env),
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


@router.put("", response_model=None, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def update_settings(
    request: UpdateSettingsRequest,
    http_request: Request,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    """Update system config (write .env file)."""
    if not settings.SETTINGS_ENV_WRITE_ENABLED:
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

            request_id = (http_request.headers.get("X-Request-ID") or "").strip()
            if not request_id:
                request_id = str(getattr(http_request.state, "request_id", "") or "").strip()
            if not request_id:
                request_id = None

            ip = None
            with contextlib.suppress(Exception):
                client = http_request.client
                if client is not None:
                    ip = client.host.strip()
                    if not ip:
                        ip = None

            user_agent = (http_request.headers.get("User-Agent") or "").strip()
            if not user_agent:
                user_agent = None

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


def _configured_parts_message(*parts: object) -> str | None:
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
        "available": enabled and configured,
        "message": _configured_status_message(enabled, configured, missing_message),
    }


async def _build_probed_parser_status(
    *,
    enabled: bool,
    api_url: str,
    success_message_builder: Callable[[dict[str, Any]], str | None] | None = None,
    headers: dict[str, str] | None = None,
    trust_env: bool = True,
) -> dict[str, object]:
    url_ok = bool(api_url)
    entry: dict[str, object] = _build_configured_parser_status(enabled, url_ok, _MISSING_API_URL_MESSAGE)
    if not (enabled and url_ok):
        return entry

    health_url = _convert_service_url_to_health_url(api_url)
    if headers is None and trust_env:
        data, err = await _probe_http_json(health_url, timeout_sec=0.6)
    else:
        data, err = await _probe_http_json(
            health_url,
            timeout_sec=0.6,
            headers=headers,
            trust_env=trust_env,
        )
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
    textin_enabled = settings.TEXTIN_ENABLED
    textin_api_url = bool(settings.TEXTIN_API_URL.strip())
    textin_app_id = bool(settings.TEXTIN_APP_ID.strip())
    textin_secret = bool(settings.TEXTIN_SECRET_CODE.strip())
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
    mineru_enabled = settings.MINERU_ENABLED
    mineru_local = bool(settings.MINERU_LOCAL_SERVER_URL.strip())
    mineru_token = settings.MINERU_API_TOKEN.strip()
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
    enabled = settings.MAGIC_PDF_ENABLED
    api_url = settings.MAGIC_PDF_API_URL.strip()
    cli = (settings.MAGIC_PDF_CLI).strip() or "magic-pdf"
    cli_ok = bool(resolve_cli_command(cli))
    models_dir = resolve_magicpdf_models_dir(settings.MAGIC_PDF_MODELS_DIR)
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
    pandoc_cli = (settings.PANDOC_CLI).strip() or "pandoc"
    libreoffice_cli = (settings.LIBREOFFICE_CLI).strip() or "soffice"
    parsers: dict[str, dict[str, object]] = {
        "basic": {"enabled": True, "available": True, "message": "built-in"},
        "markitdown": _build_import_parser_status(
            "markitdown",
            enabled=settings.MARKITDOWN_ENABLED,
            available_message="installed",
        ),
        "pandoc": _build_cli_parser_status(
            settings.PANDOC_ENABLED,
            resolve_cli_command(pandoc_cli) or "",
        ),
        "libreoffice": _build_cli_parser_status(
            settings.LIBREOFFICE_ENABLED,
            resolve_cli_command(libreoffice_cli) or "",
        ),
        "deepdoc": _build_import_parser_status(
            "app.deepdoc.parser",
            enabled=settings.DEEPDOC_ENABLED,
            available_message="available",
        ),
        "deepseek_ocr": _build_configured_parser_status(
            settings.DEEPSEEK_OCR_ENABLED,
            bool(settings.SILICONFLOW_API_KEY.strip()),
            "missing api_key",
        ),
        "etl4llm": _build_configured_parser_status(
            settings.ETL4LLM_ENABLED,
            bool(settings.ETL4LLM_API_URL.strip()),
            _MISSING_API_URL_MESSAGE,
        ),
        "marker": _build_configured_parser_status(
            settings.MARKER_ENABLED,
            bool(settings.MARKER_API_URL.strip()),
            _MISSING_API_URL_MESSAGE,
        ),
        "textin": _build_textin_parser_status(),
        "docling": await _build_probed_parser_status(
            enabled=settings.DOCLING_ENABLED,
            api_url=settings.DOCLING_API_URL.strip(),
            headers=({"X-Api-Key": settings.DOCLING_API_KEY.strip()} if settings.DOCLING_API_KEY.strip() else None),
            trust_env=settings.DOCLING_HTTP_TRUST_ENV,
        ),
        "mineru": _build_mineru_parser_status(),
        "magicpdf": _build_magicpdf_parser_status(
            resolve_cli_command=resolve_cli_command,
            resolve_magicpdf_models_dir=resolve_magicpdf_models_dir,
        ),
    }
    parsers["qianfan_ocr"] = await _build_probed_parser_status(
        enabled=settings.QIANFAN_OCR_ENABLED,
        api_url=settings.QIANFAN_OCR_API_URL.strip(),
        success_message_builder=lambda data: _configured_parts_message(data.get("model"), data.get("mode")),
    )
    parsers["paddle_vl"] = await _build_probed_parser_status(
        enabled=settings.PADDLE_VL_ENABLED,
        api_url=settings.PADDLE_VL_API_URL.strip(),
        success_message_builder=lambda data: _configured_parts_message(
            data.get("pipeline_version") or data.get("version"),
            data.get("mode"),
        ),
    )
    parsers["olmocr"] = await _build_probed_parser_status(
        enabled=settings.OLMOCR_ENABLED,
        api_url=settings.OLMOCR_API_URL.strip(),
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


def _get_milvus_status() -> dict[str, object]:
    status = {"connected": False, "message": ""}
    try:
        from pymilvus import connections
    except ImportError:
        return {"connected": False, "message": "Milvus 客户端未安装"}

    try:
        connections.connect(
            alias="status_check",
            host=settings.MILVUS_HOST,
            port=settings.MILVUS_PORT,
            user=settings.MILVUS_USER,
            password=settings.MILVUS_PASSWORD,
            timeout=1.0,
        )
        connections.disconnect("status_check")
        status["connected"] = True
        status["message"] = "connected"
    except Exception as exc:  # noqa: BLE001
        status["message"] = str(exc)[:100]
    return status


def _get_vector_status() -> dict[str, object]:
    backend = (settings.VECTOR_BACKEND).strip().lower()
    if backend == "milvus":
        return _get_milvus_status()

    from app.core.health_checks import check_vector

    vector_status, _, _ = check_vector(settings, mode="health")
    ready = vector_status["status"] == "ready"
    if backend == "memory":
        message = "内存索引（开发模式）"
    else:
        state = "就绪" if ready else "索引不存在" if vector_status["status"] == "missing" else "连接未检测"
        message = f"{backend} · {state}"
    return {"connected": ready, "message": message}


@router.get("/status", response_model=None, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def get_system_status(
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    """Get system status."""
    _ensure_settings_readable(db, tenant_id, account_id)
    from sqlalchemy import text

    from app.core.database import SessionLocal
    from app.parsing.parsers.magic_pdf_parser import resolve_magicpdf_models_dir
    from app.parsing.utils.cli import resolve_cli_command

    return {
        "database": _get_database_status(SessionLocal, text),
        "milvus": _get_vector_status(),
        "llm": {"configured": bool(settings.LLM_API_KEY), "model": settings.LLM_MODEL},
        "embedding": {
            "configured": bool(settings.EMBEDDING_API_KEY or settings.LLM_API_KEY),
            "model": settings.EMBEDDING_MODEL,
        },
        "parsers": await _build_parser_statuses(
            resolve_cli_command=resolve_cli_command, resolve_magicpdf_models_dir=resolve_magicpdf_models_dir
        ),
    }


@router.post("/llm/test", response_model=None, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def test_llm_connection(
    request: TestLLMRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
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
                    temperature=request.temperature or 0.0,
                    streaming=False,
                    timeout=timeout,
                    max_retries=request.max_retries or 1,
                    http_client=http_client,
                    http_async_client=http_async_client,
                )
                resp = await llm.ainvoke([HumanMessage(content="Say 1")])
                content = (resp.content or "").strip()
                if not content:
                    return {"success": False, "message": "Empty response"}
                return {"success": True, "message": content[:200]}
    except Exception as exc:
        msg = str(exc)
        logger.warning("LLM test failed: %s", msg[:200])
        return {"success": False, "message": msg[:400]}
