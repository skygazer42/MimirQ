from __future__ import annotations

from pathlib import Path

ROOT_ENV = Path(".env.example")
ENV_MODULE_DIR = Path("config/env")

ROOT_REQUIRED_KEYS = {
    "DATABASE_URL",
    "NEXT_PUBLIC_API_URL",
    "LLM_API_KEY",
    "LLM_API_BASE",
    "LLM_MODEL",
    "EMBEDDING_PROVIDER",
    "EMBEDDING_MODEL",
    "MILVUS_HOST",
    "MILVUS_PORT",
    "AUTH_MODE",
    "SECRET_KEY",
    "DEFAULT_TENANT_ID",
}

MODULE_REQUIRED_KEYS = {
    "database.env.example": {"DATABASE_URL", "POSTGRES_DB", "REDIS_URL"},
    "web.env.example": {"NEXT_PUBLIC_API_URL", "NEXT_PUBLIC_TENANT_ID"},
    "llm.env.example": {"LLM_API_KEY", "LLM_API_BASE", "EMBEDDING_PROVIDER"},
    "storage.env.example": {"MILVUS_HOST", "MINIO_ENABLED", "UPLOAD_DIR"},
    "security.env.example": {"AUTH_MODE", "SECRET_KEY", "CORS_ORIGINS"},
    "observability.env.example": {"ENABLE_METRICS_LOG", "LOG_LEVEL", "LOG_FORMAT"},
    "rag.env.example": {"RETRIEVAL_TOP_K", "VECTOR_BACKEND", "BM25_INDEX_ENABLED"},
    "governance.env.example": {"GOVERNANCE_ENABLED", "ENABLE_RERANKER"},
    "parsing.env.example": {
        "MINERU_ENABLED",
        "DEEPSEEK_OCR_ENABLED",
        "ETL4LLM_ENABLED",
        "MAGIC_PDF_ENABLED",
    },
    "kg.env.example": {"KG_ENABLED", "KG_CHAT_ENABLED"},
}


def _read_env_keys(path: Path) -> set[str]:
    keys: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            continue
        key, _value = line.split("=", 1)
        keys.add(key.strip())
    return keys


def test_root_env_example_is_small_and_bootstrap_ready() -> None:
    assert ROOT_ENV.exists()
    raw = ROOT_ENV.read_text(encoding="utf-8")
    keys = _read_env_keys(ROOT_ENV)

    assert len(raw.splitlines()) <= 220
    assert ROOT_ENV.stat().st_size <= 12_000
    assert ROOT_REQUIRED_KEYS <= keys
    assert "config/env/*.env.example" in raw


def test_advanced_env_examples_are_split_by_domain() -> None:
    assert ENV_MODULE_DIR.exists()

    for filename, required_keys in MODULE_REQUIRED_KEYS.items():
        path = ENV_MODULE_DIR / filename
        assert path.exists(), f"missing env module: {path}"
        assert required_keys <= _read_env_keys(path)
