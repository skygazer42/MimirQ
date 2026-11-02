"""Request and response models for system configuration."""

from pydantic import BaseModel, Field, field_validator

from app.core.config import settings
from app.services.navigation_visibility import normalize_navigation_modules

_MINERU_BACKENDS = {"pipeline", "vlm-http-client"}
SYSTEM_DIFY_ACCOUNT_ID = "system:dify"


def normalize_mineru_backend(value: object) -> str:
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
    def _normalize_reranker_provider(cls, value: object) -> str:
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
    def _normalize_backend(cls, value: object) -> str:
        return normalize_mineru_backend(value)


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


class DoclingConfig(BaseModel):
    """External Docling Serve config."""

    api_url: str = ""
    api_key: str = ""
    request_timeout_sec: int = Field(default=600, ge=1, le=86_400)
    health_timeout_sec: int = Field(default=5, ge=1, le=120)
    http_trust_env: bool = False
    ocr_enabled: bool = True


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
    def _normalize_modules(cls, value: object) -> list[str]:
        return normalize_navigation_modules(value, reject_unknown=True)


class DifyExternalKnowledgeConfig(BaseModel):
    """Dify External Knowledge API adapter settings."""

    enabled: bool = False
    api_keys: str = ""
    tenant_id: str = ""
    account_id: str = SYSTEM_DIFY_ACCOUNT_ID
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
    docling: DoclingConfig
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
    docling: DoclingConfig | None = None
    paddle_vl: PaddleVLConfig | None = None
    textin: TextInConfig | None = None
    magicpdf: MagicPDFConfig | None = None
    observability: ObservabilityConfig | None = None
    safety: SafetyConfig | None = None
    chat: ChatConfig | None = None
    langgraph: LangGraphConfig | None = None
    navigation: NavigationConfig | None = None
    dify_external_knowledge: DifyExternalKnowledgeConfig | None = None


class TestLLMRequest(BaseModel):
    api_key: str
    api_base: str = Field(default_factory=_default_llm_api_base)
    model: str
    temperature: float = 0.0
    timeout: int = 20
    max_retries: int = 1
