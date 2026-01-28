"""
Settings API - system configuration management.
Supports reading and updating .env configuration.
"""

import ipaddress
import contextlib
import time
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.config import settings
from app.core.jwt_inspect import format_unix_ts_utc, try_get_jwt_exp
from app.core.database import get_db
from app.services.dataset_service import DatasetService

router = APIRouter()

# .env file path.
ENV_FILE = Path(__file__).parent.parent.parent.parent / ".env"

_SETTINGS_ADMIN_ROLES = {"owner", "admin"}


def _sanitize_env_value(key: str, value: Any) -> str:
    text = "" if value is None else str(value)
    if "\x00" in text or "\n" in text or "\r" in text:
        raise HTTPException(status_code=400, detail=f"Invalid value for {key}")
    if len(text) > 10_000:
        raise HTTPException(status_code=400, detail=f"Value too long for {key}")
    return text.strip()


def _ensure_settings_readable(db: Session, tenant_id: UUID, account_id: str) -> None:
    DatasetService.ensure_member(db, tenant_id, account_id)


def _ensure_settings_writable(db: Session, tenant_id: UUID, account_id: str) -> None:
    member = DatasetService.ensure_member(db, tenant_id, account_id)
    role = (member.role or "").lower()
    if role not in _SETTINGS_ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="No permission to manage system settings")


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


class LLMConfig(BaseModel):
    """LLM config."""
    api_key: str = ""
    api_base: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
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
    tool_call_log_max_preview_chars: int = 500

    agent_log_enabled: bool = False
    agent_log_include_execution_path: bool = False
    agent_log_max_preview_chars: int = 500

    # JSONL metrics log (RAG trace dashboard)
    metrics_log_enabled: bool = False
    metrics_log_include_text: bool = False


class SafetyConfig(BaseModel):
    """Security/privacy config."""
    pii_redaction_enabled: bool = False
    pii_redaction_mask: str = "[REDACTED]"
    pii_stream_holdback_chars: int = 128


class ChatConfig(BaseModel):
    """Chat streaming/runtime config."""

    stream_heartbeat_sec: float = 10.0
    stream_cancel_on_disconnect: bool = True


class LangGraphConfig(BaseModel):
    """LangGraph execution mode config."""
    use_subgraphs: bool = False


class MinerUConfig(BaseModel):
    """MinerU config."""
    api_token: str = ""
    api_base: str = "https://mineru.net/api/v4"
    model_version: str = "vlm"


class MagicPDFConfig(BaseModel):
    """MagicPDF (magic-pdf) config."""
    cli: str = "magic-pdf"
    method: str = "auto"  # auto | ocr | txt
    lang: str = ""
    debug: bool = False
    timeout_sec: int = 600
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


class SystemSettings(BaseModel):
    """Full system config."""
    feature_flags: FeatureFlags
    kg: KGConfig
    llm: LLMConfig
    embedding: EmbeddingConfig
    milvus: MilvusConfig
    rag: RAGConfig
    url_ingest: UrlIngestConfig
    governance: GovernanceConfig
    mineru: MinerUConfig
    etl4llm: Etl4LlmConfig
    marker: MarkerConfig
    paddle_vl: PaddleVLConfig
    magicpdf: MagicPDFConfig
    observability: ObservabilityConfig
    safety: SafetyConfig
    chat: ChatConfig
    langgraph: LangGraphConfig


class UpdateSettingsRequest(BaseModel):
    """Update config request."""
    feature_flags: Optional[FeatureFlags] = None
    kg: Optional[KGConfig] = None
    llm: Optional[LLMConfig] = None
    embedding: Optional[EmbeddingConfig] = None
    milvus: Optional[MilvusConfig] = None
    rag: Optional[RAGConfig] = None
    url_ingest: Optional[UrlIngestConfig] = None
    governance: Optional[GovernanceConfig] = None
    mineru: Optional[MinerUConfig] = None
    etl4llm: Optional[Etl4LlmConfig] = None
    marker: Optional[MarkerConfig] = None
    paddle_vl: Optional[PaddleVLConfig] = None
    magicpdf: Optional[MagicPDFConfig] = None
    observability: Optional[ObservabilityConfig] = None
    safety: Optional[SafetyConfig] = None
    chat: Optional[ChatConfig] = None
    langgraph: Optional[LangGraphConfig] = None


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


def _apply_runtime_settings(env_vars: Dict[str, str], updated_keys: list[str]) -> None:
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

    # MagicPDF
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


def read_env_file() -> Dict[str, str]:
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


def write_env_file(env_vars: Dict[str, str]):
    """Write .env file, preserving comments and formatting."""
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

    with open(ENV_FILE, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


def mask_secret(value: str) -> str:
    """Mask sensitive info."""
    if not value or len(value) < 8:
        return "***" if value else ""
    return value[:4] + "***" + value[-4:]


@router.get("", response_model=SystemSettings)
async def get_settings(
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
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
        ),
        magicpdf=MagicPDFConfig(
            cli=getattr(settings, "MAGIC_PDF_CLI", "magic-pdf") or "magic-pdf",
            method=getattr(settings, "MAGIC_PDF_METHOD", "auto") or "auto",
            lang=getattr(settings, "MAGIC_PDF_LANG", "") or "",
            debug=bool(getattr(settings, "MAGIC_PDF_DEBUG", False)),
            timeout_sec=int(getattr(settings, "MAGIC_PDF_TIMEOUT_SEC", 600) or 600),
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
    )


@router.put("")
async def update_settings(
    request: UpdateSettingsRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """Update system config (write .env file)."""
    _ensure_settings_writable(db, tenant_id, account_id)
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
                except Exception:
                    raise HTTPException(status_code=400, detail="Invalid KG_EXTRACT_PROMPT_TEMPLATE_ID")
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
            updated_keys.extend(["MINERU_API_BASE", "MINERU_MODEL_VERSION"])

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
            updated_keys.extend(["PADDLE_VL_API_URL", "PADDLE_VL_TIMEOUT_SEC"])

        if request.magicpdf:
            mp = request.magicpdf
            env_vars["MAGIC_PDF_CLI"] = _sanitize_env_value("MAGIC_PDF_CLI", mp.cli)
            env_vars["MAGIC_PDF_METHOD"] = _sanitize_env_value("MAGIC_PDF_METHOD", mp.method)
            env_vars["MAGIC_PDF_LANG"] = _sanitize_env_value("MAGIC_PDF_LANG", mp.lang)
            env_vars["MAGIC_PDF_DEBUG"] = str(bool(mp.debug)).lower()
            env_vars["MAGIC_PDF_TIMEOUT_SEC"] = str(int(mp.timeout_sec or 0))
            env_vars["MAGIC_PDF_KEEP_ARTIFACTS"] = str(bool(mp.keep_artifacts)).lower()
            updated_keys.extend(
                [
                    "MAGIC_PDF_CLI",
                    "MAGIC_PDF_METHOD",
                    "MAGIC_PDF_LANG",
                    "MAGIC_PDF_DEBUG",
                    "MAGIC_PDF_TIMEOUT_SEC",
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

        write_env_file(env_vars)
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
            "message": "Configuration saved. Some settings require backend restart to take effect.",
            "updated_keys": updated_keys
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save configuration: {str(e)}")


@router.get("/status")
async def get_system_status(
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """Get system status."""
    _ensure_settings_readable(db, tenant_id, account_id)
    from sqlalchemy import text
    from app.core.database import SessionLocal
    from pymilvus import connections

    status = {
        "database": {"connected": False, "message": ""},
        "milvus": {"connected": False, "message": ""},
        "llm": {"configured": bool(settings.LLM_API_KEY), "model": settings.LLM_MODEL},
        "embedding": {"configured": bool(settings.EMBEDDING_API_KEY or settings.LLM_API_KEY), "model": settings.EMBEDDING_MODEL},
    }
    def _check_import(module: str) -> tuple[bool, str]:
        try:
            __import__(module)
            return True, "ok"
        except Exception as exc:
            return False, str(exc)[:120]

    from app.parsing.utils.cli import resolve_cli_command

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
        "message": "configured" if (pandoc_enabled and pandoc_cli_ok) else ("disabled" if not pandoc_enabled else f"missing cli: {pandoc_cli}"),
    }

    lo_enabled = bool(getattr(settings, "LIBREOFFICE_ENABLED", False))
    lo_cli = (getattr(settings, "LIBREOFFICE_CLI", "") or "soffice").strip() or "soffice"
    lo_cli_ok = bool(resolve_cli_command(lo_cli))
    parsers["libreoffice"] = {
        "enabled": lo_enabled,
        "available": bool(lo_enabled and lo_cli_ok),
        "message": "configured" if (lo_enabled and lo_cli_ok) else ("disabled" if not lo_enabled else f"missing cli: {lo_cli}"),
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
        "message": "configured" if (deepseek_enabled and deepseek_key) else ("disabled" if not deepseek_enabled else "missing api_key"),
    }

    etl_enabled = bool(getattr(settings, "ETL4LLM_ENABLED", False))
    etl_url = bool((getattr(settings, "ETL4LLM_API_URL", "") or "").strip())
    parsers["etl4llm"] = {
        "enabled": etl_enabled,
        "available": bool(etl_enabled and etl_url),
        "message": "configured" if (etl_enabled and etl_url) else ("disabled" if not etl_enabled else "missing api_url"),
    }

    marker_enabled = bool(getattr(settings, "MARKER_ENABLED", False))
    marker_url = bool((getattr(settings, "MARKER_API_URL", "") or "").strip())
    parsers["marker"] = {
        "enabled": marker_enabled,
        "available": bool(marker_enabled and marker_url),
        "message": "configured" if (marker_enabled and marker_url) else ("disabled" if not marker_enabled else "missing api_url"),
    }

    paddlevl_enabled = bool(getattr(settings, "PADDLE_VL_ENABLED", False))
    paddlevl_url = bool((getattr(settings, "PADDLE_VL_API_URL", "") or "").strip())
    parsers["paddle_vl"] = {
        "enabled": paddlevl_enabled,
        "available": bool(paddlevl_enabled and paddlevl_url),
        "message": "configured" if (paddlevl_enabled and paddlevl_url) else ("disabled" if not paddlevl_enabled else "missing api_url"),
    }

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
    magicpdf_cli = (getattr(settings, "MAGIC_PDF_CLI", "") or "magic-pdf").strip() or "magic-pdf"
    magicpdf_cli_ok = bool(resolve_cli_command(magicpdf_cli))
    parsers["magicpdf"] = {
        "enabled": magicpdf_enabled,
        "available": bool(magicpdf_enabled and magicpdf_cli_ok),
        "message": "configured" if (magicpdf_enabled and magicpdf_cli_ok) else ("disabled" if not magicpdf_enabled else f"missing cli: {magicpdf_cli}"),
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
    api_base: str = "https://api.openai.com/v1"
    model: str
    temperature: float = 0.0
    timeout: int = 20
    max_retries: int = 1


@router.post("/llm/test")
async def test_llm_connection(
    request: TestLLMRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """Test LLM connection (no config write)."""
    _ensure_settings_writable(db, tenant_id, account_id)
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage
    import httpx

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
        async with httpx.AsyncClient(trust_env=trust_env, timeout=timeout) as http_async_client:
            llm = ChatOpenAI(
                model=request.model,
                api_key=request.api_key,
                base_url=request.api_base,
                temperature=float(request.temperature or 0.0),
                streaming=False,
                timeout=timeout,
                max_retries=int(request.max_retries or 1),
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
