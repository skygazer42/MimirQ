"""
Application configuration module.

Centralized settings management including:
- Security settings (SECRET_KEY, credentials, etc.)
- LLM/Embedding provider config
- RAG pipeline parameters
- Storage backend config
"""
from typing import Literal, Optional
import os
import sys
import warnings
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import AliasChoices, Field, model_validator


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
    MILVUS_HOST: str = "localhost"
    MILVUS_PORT: int = 19530
    MILVUS_USER: str = ""
    MILVUS_PASSWORD: str = ""
    MILVUS_COLLECTION_NAME: str = "documents"

    # Object Storage (MinIO / S3-compatible)
    MINIO_ENABLED: bool = False
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET_NAME: str = "mimirq"
    MINIO_USE_SSL: bool = False
    MINIO_METRICS_LOG_PATH: str = "./logs/minio_metrics.jsonl"

    # Task Queue / Redis (ingest throughput optimization)
    # - Task queue is off by default: keeps API compatibility; when enabled,
    #   workers handle document parsing/indexing asynchronously.
    TASK_QUEUE_ENABLED: bool = False
    REDIS_URL: str = "redis://localhost:6379/0"
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

    # Embedding cache (Redis, improves ingest throughput; best-effort).
    EMBEDDING_CACHE_ENABLED: bool = True
    EMBEDDING_CACHE_TTL_SEC: int = 7 * 24 * 3600
    EMBEDDING_CACHE_PREFIX: str = "emb"

    # Vector write batching (Milvus/Chroma/etc). Smaller batches reduce tail latency and memory spikes.
    VECTOR_WRITE_BATCH_SIZE: int = 256
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

    UPLOAD_DIR: str = "./uploads"
    MAX_FILE_SIZE: int = 50_000_000
    # ZIP extraction safety limits (for Markdown+images archives).
    ZIP_MAX_FILES: int = 2000
    ZIP_MAX_TOTAL_UNCOMPRESSED_BYTES: int = 500_000_000
    ZIP_MAX_SINGLE_UNCOMPRESSED_BYTES: int = 100_000_000
    ZIP_MAX_IMAGES: int = 300
    # Inline/local image upload safety limits (Markdown/HTML image refs -> MinIO).
    MAX_INLINE_IMAGE_BYTES: int = 10_000_000
    MAX_INLINE_IMAGES: int = 200
    # Keep this aligned with parser_factory supported non-PDF formats.
    ALLOWED_EXTENSIONS: str = ".pdf,.txt,.md,.doc,.docx,.xls,.xlsx,.csv,.html,.json"

    @property
    def allowed_extensions_list(self):
        return [ext.strip() for ext in self.ALLOWED_EXTENSIONS.split(",") if ext.strip()]

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

    # PDF quality OCR validation (used by parse-preview scoring)
    RAPIDOCR_ENABLED: bool = False

    # Auth
    # - jwt: require Authorization: Bearer <JWT> (validated with SECRET_KEY)
    # - header: require X-User-ID header (unsafe; intended for local/dev only)
    AUTH_MODE: Literal["jwt", "header"] = "header"

    SECRET_KEY: str = "your-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    PASSWORD_MIN_LENGTH: int = 8

    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:3001"
    # Allow browsers to read diagnostic headers from cross-origin responses.
    # NOTE: This does not affect which headers the backend sends, only what the browser exposes to JS.
    CORS_EXPOSE_HEADERS: str = "X-Request-ID,X-Process-Time-Ms,Retry-After"

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
    RETRIEVAL_TOP_K: int = 5
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

    # Prompt context guards (0 disables)
    RAG_CONTEXT_MAX_CHARS_PER_CHUNK: int = 1500
    RAG_CONTEXT_MAX_TOTAL_CHARS: int = 12_000
    RAG_CONTEXT_MAX_KG_CHARS: int = 3_000
    # Optional token-based guards (0 disables). When enabled, takes precedence over char guards.
    RAG_CONTEXT_MAX_TOKENS_PER_CHUNK: int = 0
    RAG_CONTEXT_MAX_TOTAL_TOKENS: int = 0
    RAG_CONTEXT_MAX_KG_TOKENS: int = 0
    # Optional: include adjacent chunks around top hits to improve continuity (0 disables).
    RAG_CONTEXT_NEIGHBOR_WINDOW: int = 0
    # Max number of neighbor chunks to add in total (0 disables the cap).
    RAG_CONTEXT_NEIGHBOR_MAX_ADDED: int = 20
    # Context evidence extraction (query-focused sentence selection)
    RAG_CONTEXT_EVIDENCE_ENABLED: bool = False
    RAG_CONTEXT_EVIDENCE_MAX_SENTENCES_PER_CHUNK: int = 6
    RAG_CONTEXT_EVIDENCE_MIN_SENTENCE_CHARS: int = 10
    # Grounding guard: abstain when evidence is weak/empty.
    RAG_ABSTAIN_ENABLED: bool = False
    RAG_ABSTAIN_MIN_CITATIONS: int = 1
    RAG_ABSTAIN_MIN_TOP_RELEVANCE_SCORE: float = 0.0  # 0 disables
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
    FAISS_STORE_PATH: str = "./vector_faiss"
    # FAISS persistence uses pickle; enable only when the index directory is fully trusted.
    FAISS_ALLOW_DANGEROUS_DESERIALIZATION: bool = False
    CHROMA_PERSIST_PATH: str = "./vector_chroma"
    ENABLE_METRICS_LOG: bool = False
    METRICS_LOG_PATH: str = "./logs/rag_metrics.jsonl"
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
    MARKITDOWN_ENABLED: bool = False
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
    DOCLING_EXTRACT_IMAGES: bool = False
    # Knowledge Graph (KG) feature flags.
    # Canonical env names: KG_ENABLED / KG_CHAT_ENABLED
    KG_ENABLED: bool = False
    KG_CHAT_ENABLED: bool = False
    # KG extraction prompt selector (optional; tenant-scoped PromptTemplate).
    # - Prefer using `KG_EXTRACT_PROMPT_TEMPLATE_KEY` (latest active version).
    # - Or set `KG_EXTRACT_PROMPT_TEMPLATE_ID` to pin a specific template.
    # - Or set `KG_EXTRACT_PROMPT_AB_EXPERIMENT_KEY` for A/B variants (seeded by account_id when available).
    KG_EXTRACT_PROMPT_TEMPLATE_ID: str = ""
    KG_EXTRACT_PROMPT_TEMPLATE_KEY: str = ""
    KG_EXTRACT_PROMPT_AB_EXPERIMENT_KEY: str = ""
    CHAT_HISTORY_WINDOW: int = 5
    # Allow chat even when no accessible documents exist (dev-friendly).
    CHAT_ALLOW_EMPTY_DOCUMENTS: bool = True
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
        is_production = os.getenv("ENV", "").lower() in ("prod", "production")

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
            if not self.MINIO_ACCESS_KEY or not self.MINIO_SECRET_KEY:
                raise ValueError("MINIO_ACCESS_KEY and MINIO_SECRET_KEY are required when MINIO_ENABLED=true")
            if self.MINIO_ACCESS_KEY == "minioadmin" or self.MINIO_SECRET_KEY == "minioadmin":
                if is_production:
                    raise ValueError("Default MinIO credentials are not allowed in production when MINIO_ENABLED=true")
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

        if self.RETRIEVAL_MMR_LAMBDA < 0 or self.RETRIEVAL_MMR_LAMBDA > 1:
            raise ValueError(
                f"RETRIEVAL_MMR_LAMBDA ({self.RETRIEVAL_MMR_LAMBDA}) must be between 0 and 1"
            )
        if int(self.RETRIEVAL_QUERY_PARALLELISM or 0) < 1:
            raise ValueError(
                f"RETRIEVAL_QUERY_PARALLELISM ({self.RETRIEVAL_QUERY_PARALLELISM}) must be >= 1"
            )

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
