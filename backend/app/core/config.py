"""
Application configuration management.
"""
from typing import Optional

from pydantic_settings import BaseSettings
from pydantic import AliasChoices, Field


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/mimirq"
    MILVUS_HOST: str = "localhost"
    MILVUS_PORT: int = 19530
    MILVUS_USER: str = ""
    MILVUS_PASSWORD: str = ""
    MILVUS_COLLECTION_NAME: str = "documents"

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

    EMBEDDING_PROVIDER: str = "openai_compatible"
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_API_KEY: str = ""
    EMBEDDING_API_BASE: str = ""

    UPLOAD_DIR: str = "./uploads"
    MAX_FILE_SIZE: int = 50_000_000
    ALLOWED_EXTENSIONS: str = ".pdf,.txt,.md"

    @property
    def allowed_extensions_list(self):
        return [ext.strip() for ext in self.ALLOWED_EXTENSIONS.split(",") if ext.strip()]

    MINERU_API_TOKEN: str = ""
    MINERU_API_BASE: str = "https://mineru.net/api/v4"
    MINERU_MODEL_VERSION: str = "vlm"
    MINERU_ENABLED: bool = False

    SECRET_KEY: str = "your-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:3001"

    HOST: str = "0.0.0.0"
    PORT: int = 8000

    CHUNK_SIZE: int = 1000
    CHUNK_OVERLAP: int = 200
    RETRIEVAL_TOP_K: int = 5
    SIMILARITY_THRESHOLD: float = 0.7
    RETRIEVAL_MMR_LAMBDA: float = 0.7
    USE_LANGGRAPH_PIPELINE: bool = False
    RAG_GRAPH_MAX_RETRIES: int = 2
    RAG_GRAPH_TIMEOUT_SEC: int = 20
    VECTOR_BACKEND: str = "milvus"  # milvus | memory | faiss | chroma
    FAISS_STORE_PATH: str = "./vector_faiss"
    CHROMA_PERSIST_PATH: str = "./vector_chroma"
    DEFAULT_PARSER_BACKEND: str = "auto"
    DEFAULT_CHUNK_STRATEGY: str = "langchain_recursive"
    DEEPDOC_ENABLED: bool = False
    MARKITDOWN_ENABLED: bool = False
    MARKITDOWN_USE_PLUGINS: bool = False
    MARKITDOWN_DOCINTEL_ENDPOINT: str = ""
    MARKITDOWN_DOCINTEL_KEY: str = ""
    LLAMA_INDEX_ENABLED: bool = False
    SAG_ENABLED: bool = False
    SAG_CHAT_ENABLED: bool = False
    CHAT_HISTORY_WINDOW: int = 5
    LONG_TERM_MEMORY_ENABLED: bool = False
    LONG_TERM_MEMORY_TOP_K: int = 3
    LONG_TERM_MEMORY_MIN_LEN: int = 20

    # Multi-tenant defaults
    DEFAULT_TENANT_ID: str = "00000000-0000-0000-0000-000000000000"
    TENANT_HEADER: str = "X-Tenant-ID"

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
