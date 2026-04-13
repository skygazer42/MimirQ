"""
Global constants.

Centralize magic strings and hardcoded values for maintainability.
"""


# =============================================================================
# Timeout constants (seconds)
# =============================================================================

class Timeouts:
    """HTTP and operation timeout constants."""

    # API request timeouts.
    API_DEFAULT = 60          # embedding providers, LLM API calls
    API_SHORT = 30            # Fast API requests
    API_UPLOAD = 300          # File uploads
    API_LONG_RUNNING = 600    # Long-running tasks

    # Document parsing timeouts.
    PARSE_DEFAULT = 1800      # Document parsing (30 minutes)
    PARSE_VALIDATION = 5      # Health checks/validation

    # Streaming operation timeouts.
    STREAM_DEFAULT = 5.0      # Streaming writes
    STREAM_SHORT = 1.0        # Short streaming operations

    # Thread/process timeouts.
    THREAD_JOIN = 2.0         # Thread join timeout


# =============================================================================
# File type constants
# =============================================================================

class FileTypes:
    """Supported file types."""

    # Document types
    PDF = ".pdf"
    TXT = ".txt"
    MD = ".md"
    DOC = ".doc"
    DOCX = ".docx"
    PPT = ".ppt"
    PPTX = ".pptx"

    # Spreadsheet types
    XLS = ".xls"
    XLSX = ".xlsx"
    CSV = ".csv"

    # Web types
    HTML = ".html"
    HTM = ".htm"
    JSON = ".json"

    # Supported extension sets
    DOCUMENT_EXTENSIONS: frozenset[str] = frozenset({
        ".pdf", ".txt", ".md", ".doc", DOCX, ".ppt", PPTX
    })

    SPREADSHEET_EXTENSIONS: frozenset[str] = frozenset({
        ".xls", XLSX, ".csv"
    })

    WEB_EXTENSIONS: frozenset[str] = frozenset({
        HTML, ".htm", JSON
    })

    ALL_SUPPORTED: frozenset[str] = frozenset({
        ".pdf", ".txt", ".md", ".doc", DOCX, ".ppt", PPTX,
        ".xls", XLSX, ".csv", HTML, ".htm", JSON
    })

    # MarkItDown special support
    MARKITDOWN_EXTENSIONS: frozenset[str] = frozenset({
        ".doc", DOCX, ".ppt", PPTX, ".xls", XLSX, ".csv", HTML, ".htm", JSON
    })


# =============================================================================
# Document processing status
# =============================================================================

class DocumentStatus:
    """Document processing status constants."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    QUARANTINED = "quarantined"
    CANCELLED = "cancelled"

    # Terminal states
    TERMINAL_STATES: frozenset[str] = frozenset({
        "completed", "failed", "quarantined", "cancelled"
    })

    # Active states
    ACTIVE_STATES: frozenset[str] = frozenset({
        "pending", "processing"
    })


# =============================================================================
# Milvus vector database config
# =============================================================================

class MilvusConfig:
    """Milvus config constants."""

    # Index params
    METRIC_TYPE = "COSINE"
    INDEX_TYPE = "IVF_FLAT"
    NLIST = 1024

    # Search params
    NPROBE = 10

    # Default collection name
    DEFAULT_COLLECTION = "mimirq_chunks"

    @classmethod
    def get_index_params(cls) -> dict:
        """Get index params."""
        return {
            "metric_type": cls.METRIC_TYPE,
            "index_type": cls.INDEX_TYPE,
            "params": {"nlist": cls.NLIST},
        }

    @classmethod
    def get_search_params(cls) -> dict:
        """Get search params."""
        return {
            "metric_type": cls.METRIC_TYPE,
            "params": {"nprobe": cls.NPROBE},
        }


# =============================================================================
# Embedding providers
# =============================================================================

class EmbeddingProviders:
    """Embedding provider constants."""

    OPENAI = "openai"
    OPENAI_COMPATIBLE = "openai_compatible"
    LOCAL = "local"
    DASHSCOPE = "dashscope"
    OLLAMA = "ollama"

    ALL: frozenset[str] = frozenset({
        "openai", "openai_compatible", "local", "dashscope", "ollama"
    })

    # Provider map (alias -> canonical name)
    PROVIDER_MAP = {
        "openai": "openai_compatible",
        "openai_compatible": "openai_compatible",
        "local": "local",
        "dashscope": "dashscope",
        "ollama": "ollama",
    }


# =============================================================================
# PDF parsing backends
# =============================================================================

class PDFBackends:
    """PDF parsing backend constants."""

    AUTO = "auto"
    BASIC = "basic"
    MINERU = "mineru"
    DEEPDOC = "deepdoc"
    DEEPSEEK_OCR = "deepseek_ocr"
    QIANFAN_OCR = "qianfan_ocr"
    TEXTIN = "textin"
    MARKITDOWN = "markitdown"
    DOCLING = "docling"
    TCADP = "tcadp"

    ALL: frozenset[str] = frozenset({
        "auto", "basic", "mineru", "deepdoc", "deepseek_ocr", "qianfan_ocr", "textin", "markitdown", "docling", "tcadp"
    })


# =============================================================================
# Retrieval modes
# =============================================================================

class RetrievalModes:
    """Retrieval mode constants."""

    VECTOR = "vector"
    KEYWORD = "keyword"
    HYBRID = "hybrid"
    MMR = "mmr"
    AUTO = "auto"

    ALL: frozenset[str] = frozenset({
        "vector", "keyword", "hybrid", "mmr", "auto"
    })


# =============================================================================
# User roles
# =============================================================================

class UserRoles:
    """User role constants."""

    OWNER = "owner"
    ADMIN = "admin"
    AUDITOR = "auditor"
    EDITOR = "editor"
    DATASET_OPERATOR = "dataset_operator"
    VIEWER = "viewer"

    # Editable roles
    EDIT_ROLES: frozenset[str] = frozenset({
        "owner", "admin", "editor", "dataset_operator"
    })

    # Admin roles
    ADMIN_ROLES: frozenset[str] = frozenset({
        "owner", "admin"
    })


# =============================================================================
# Proxy environment variables
# =============================================================================

class ProxyEnvKeys:
    """Proxy-related environment variables."""

    KEYS = (
        "OPENAI_PROXY",
        "HTTPS_PROXY",
        "HTTP_PROXY",
        "ALL_PROXY",
        "https_proxy",
        "http_proxy",
        "all_proxy",
    )


# =============================================================================
# Chunk parameter limits
# =============================================================================

class ChunkLimits:
    """Chunk parameter limits."""

    SIZE_MIN = 100
    SIZE_MAX = 4000
    SIZE_DEFAULT = 1000

    OVERLAP_MIN = 0
    OVERLAP_MAX = 1000
    OVERLAP_DEFAULT = 200


# =============================================================================
# API pagination limits
# =============================================================================

class PaginationLimits:
    """Pagination parameter limits."""

    DEFAULT_SKIP = 0
    DEFAULT_LIMIT = 50
    MAX_LIMIT = 200


__all__ = [
    "Timeouts",
    "FileTypes",
    "DocumentStatus",
    "MilvusConfig",
    "EmbeddingProviders",
    "PDFBackends",
    "RetrievalModes",
    "UserRoles",
    "ProxyEnvKeys",
    "ChunkLimits",
    "PaginationLimits",
]
