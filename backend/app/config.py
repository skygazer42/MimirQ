"""
应用配置管理
"""
from pydantic_settings import BaseSettings
from pydantic import AliasChoices, Field
from typing import List


class Settings(BaseSettings):
    """应用配置"""

    # Database
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/mimirq"

    # Milvus
    MILVUS_HOST: str = "localhost"
    MILVUS_PORT: int = 19530
    MILVUS_USER: str = ""
    MILVUS_PASSWORD: str = ""
    MILVUS_COLLECTION_NAME: str = "documents"

    # LLM Provider (OpenAI-compatible)
    LLM_API_KEY: str = Field(
        default="",
        validation_alias=AliasChoices("LLM_API_KEY", "OPENAI_API_KEY")
    )
    LLM_API_BASE: str = Field(
        default="https://api.openai.com/v1",
        validation_alias=AliasChoices("LLM_API_BASE", "OPENAI_BASE_URL")
    )
    LLM_MODEL: str = Field(
        default="gpt-4-turbo-preview",
        validation_alias=AliasChoices("LLM_MODEL", "OPENAI_MODEL")
    )
    LLM_TEMPERATURE: float = 0.7
    LLM_TIMEOUT: int = 60
    LLM_MAX_RETRIES: int = 3

    # Embedding
    EMBEDDING_PROVIDER: str = "openai_compatible"  # local | openai_compatible
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_API_KEY: str = ""  # 留空则使用 LLM_API_KEY
    EMBEDDING_API_BASE: str = ""  # 留空则使用 LLM_API_BASE

    # File Upload
    UPLOAD_DIR: str = "./uploads"
    MAX_FILE_SIZE: int = 50_000_000  # 50MB
    ALLOWED_EXTENSIONS: List[str] = [".pdf", ".txt", ".md"]

    # MinerU Online API
    MINERU_API_TOKEN: str = ""
    MINERU_API_BASE: str = "https://mineru.net/api/v4"
    MINERU_MODEL_VERSION: str = "vlm"  # vlm | txt
    MINERU_ENABLED: bool = False  # 是否启用 MinerU 解析（需要配置 API Token）

    # Security
    SECRET_KEY: str = "your-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # CORS
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:3001"

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # RAG Config
    CHUNK_SIZE: int = 1000
    CHUNK_OVERLAP: int = 200
    RETRIEVAL_TOP_K: int = 5
    SIMILARITY_THRESHOLD: float = 0.7
    DEFAULT_PARSER_BACKEND: str = "auto"  # auto | basic | mineru | deepdoc | markitdown
    DEFAULT_CHUNK_STRATEGY: str = "langchain_recursive"  # langchain_recursive | llama_index
    DEEPDOC_ENABLED: bool = False
    MARKITDOWN_ENABLED: bool = False
    MARKITDOWN_USE_PLUGINS: bool = False
    MARKITDOWN_DOCINTEL_ENDPOINT: str = ""
    MARKITDOWN_DOCINTEL_KEY: str = ""
    LLAMA_INDEX_ENABLED: bool = False

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
