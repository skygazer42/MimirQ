from __future__ import annotations

from pathlib import Path

ROOT_ENV = Path(".env.example")

REQUIRED_KEYS = {
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
    "POSTGRES_DB",
    "REDIS_URL",
    "NEXT_PUBLIC_TENANT_ID",
    "MINIO_ENABLED",
    "UPLOAD_DIR",
    "CORS_ORIGINS",
    "ENABLE_METRICS_LOG",
    "LOG_LEVEL",
    "LOG_FORMAT",
    "RETRIEVAL_TOP_K",
    "VECTOR_BACKEND",
    "BM25_INDEX_ENABLED",
    "GOVERNANCE_ENABLED",
    "ENABLE_RERANKER",
    "MINERU_ENABLED",
    "DEEPSEEK_OCR_ENABLED",
    "ETL4LLM_ENABLED",
    "MAGIC_PDF_ENABLED",
    "KG_ENABLED",
    "KG_CHAT_ENABLED",
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


def test_root_env_example_is_complete_and_bootstrap_ready() -> None:
    assert ROOT_ENV.exists()
    raw = ROOT_ENV.read_text(encoding="utf-8")
    keys = _read_env_keys(ROOT_ENV)

    assert len(raw.splitlines()) <= 2_000
    assert ROOT_ENV.stat().st_size <= 90_000
    assert REQUIRED_KEYS <= keys
    assert "config" + "/env" not in raw
