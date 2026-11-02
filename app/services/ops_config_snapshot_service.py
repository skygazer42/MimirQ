"""
Ops config snapshot helpers (PII-safe, admin-only).

Goal: provide a compact, redacted runtime config snapshot + stable fingerprint for
incident response workflows (diff across deploys/environments) without leaking
secrets.
"""

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse, urlunparse

from sqlalchemy.engine.url import make_url
from sqlalchemy.exc import ArgumentError

from app.core.config import settings
from app.rag.core.hashing import stable_hash
from app.rag.core.retrieval_config_fingerprint import build_retrieval_config_fingerprint


def _mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) < 8:
        return "***"
    return value[:4] + "***" + value[-4:]


def _redact_sqlalchemy_url(url_str: str) -> str:
    raw = url_str.strip()
    if not raw:
        return ""
    try:
        return make_url(raw).render_as_string(hide_password=True)
    except (ArgumentError, ValueError):
        return "<invalid-url>"


def _redact_generic_url(url_str: str) -> str:
    raw = url_str.strip()
    if not raw:
        return ""
    try:
        p = urlparse(raw)
        if not (p.scheme and p.netloc):
            return raw
        username = p.username or ""
        password = p.password
        hostname = p.hostname or ""
        port = f":{p.port}" if p.port else ""
        auth = ""
        if username or password is not None:
            if password:
                auth = f"{username}:***@" if username else ":***@"
            else:
                auth = f"{username}@" if username else ""
        netloc = f"{auth}{hostname}{port}"
        return urlunparse((p.scheme, netloc, p.path, p.params, p.query, p.fragment))
    except ValueError:
        return "<invalid-url>"


def _get_build_sha() -> str | None:
    value = (
        os.getenv("MIMIRQ_BUILD_SHA")
        or os.getenv("GIT_SHA")
        or os.getenv("SOURCE_VERSION")
        or os.getenv("GITHUB_SHA")
        or ""
    ).strip()
    return value or None


def _get_build_time() -> str | None:
    value = (os.getenv("MIMIRQ_BUILD_TIME") or os.getenv("BUILD_TIME") or "").strip()
    return value or None


def _build_retrieval_config_for_fingerprint() -> dict[str, Any]:
    """
    Keep this bounded to avoid accidental leakage/high-cardinality payloads.
    """

    return {
        "vector_backend": settings.VECTOR_BACKEND,
        "bm25_enabled": settings.BM25_INDEX_ENABLED,
        "lexical_enabled": settings.LEXICAL_DB_TRGM_ENABLED,
        "sparse_enabled": settings.SPARSE_RETRIEVAL_ENABLED,
        "colbert_enabled": settings.COLBERT_RETRIEVAL_ENABLED,
        "colbert_provider": settings.COLBERT_RETRIEVAL_PROVIDER,
        "colbert_index_persist_enabled": settings.COLBERT_RETRIEVAL_INDEX_PERSIST_ENABLED,
        "colbert_max_docs": settings.COLBERT_RETRIEVAL_MAX_DOCS,
        "enable_reranker": settings.ENABLE_RERANKER,
        "reranker_provider": settings.RERANKER_PROVIDER,
        "reranker_top_n": settings.RERANKER_TOP_N,
        "retrieval_top_k": settings.RETRIEVAL_TOP_K,
        "similarity_threshold": settings.SIMILARITY_THRESHOLD,
        "retrieval_query_parallelism": settings.RETRIEVAL_QUERY_PARALLELISM,
        "retrieval_fusion_strategy": settings.RETRIEVAL_FUSION_STRATEGY,
        "retrieval_rrf_k": settings.RETRIEVAL_RRF_K,
        "retrieval_dedup_enabled": settings.RETRIEVAL_DEDUP_ENABLED,
        "retrieval_overfetch_multiplier": settings.RETRIEVAL_OVERFETCH_MULTIPLIER,
    }


@dataclass(frozen=True)
class OpsConfigSnapshot:
    schema: str
    fingerprint: str
    config: dict[str, Any]


def build_ops_config_snapshot() -> OpsConfigSnapshot:
    """
    Build a redacted ops config snapshot.

    `fingerprint` is stable for unchanged config and excludes timestamps.
    """

    retrieval_fp = build_retrieval_config_fingerprint(config=_build_retrieval_config_for_fingerprint())

    cfg: dict[str, Any] = {
        "build": {"sha": _get_build_sha(), "time": _get_build_time()},
        "features": {
            "auth_mode": settings.AUTH_MODE,
            "vector_backend": settings.VECTOR_BACKEND,
            "task_queue_enabled": settings.TASK_QUEUE_ENABLED,
            "minio_enabled": settings.MINIO_ENABLED,
            "gzip_enabled": settings.GZIP_ENABLED,
            "rate_limit_enabled": settings.RATE_LIMIT_ENABLED,
            "prometheus_enabled": settings.PROMETHEUS_ENABLED,
            "metrics_log_enabled": settings.ENABLE_METRICS_LOG,
            "metrics_log_include_text": settings.METRICS_LOG_INCLUDE_TEXT,
            "pii_redaction_enabled": settings.PII_REDACTION_ENABLED,
        },
        "llm": {
            "api_base": settings.LLM_API_BASE,
            "model": settings.LLM_MODEL,
            "temperature": settings.LLM_TEMPERATURE,
            "timeout_sec": float(settings.LLM_TIMEOUT),
            "max_retries": settings.LLM_MAX_RETRIES,
            "api_key_masked": _mask_secret(settings.LLM_API_KEY),
            "api_key_set": bool(settings.LLM_API_KEY.strip()),
        },
        "embedding": {
            "provider": settings.EMBEDDING_PROVIDER,
            "model": settings.EMBEDDING_MODEL,
            "api_base": settings.EMBEDDING_API_BASE,
            "api_key_masked": _mask_secret(settings.EMBEDDING_API_KEY),
            "api_key_set": bool(settings.EMBEDDING_API_KEY.strip()),
        },
        "datastores": {
            "database_url_redacted": _redact_sqlalchemy_url(settings.DATABASE_URL),
            "redis_url_redacted": _redact_generic_url(settings.REDIS_URL),
        },
        "vector_store": {
            "backend": settings.VECTOR_BACKEND,
            "milvus": {
                "host": settings.MILVUS_HOST,
                "port": str(settings.MILVUS_PORT),
                "user": settings.MILVUS_USER,
                "password_masked": _mask_secret(settings.MILVUS_PASSWORD),
                "password_set": bool(settings.MILVUS_PASSWORD.strip()),
                "collection_name": settings.MILVUS_COLLECTION_NAME,
            },
        },
        "minio": {
            "enabled": settings.MINIO_ENABLED,
            "endpoint": settings.MINIO_ENDPOINT,
            "bucket": settings.MINIO_BUCKET_NAME,
            "use_ssl": settings.MINIO_USE_SSL,
            "documents_enabled": settings.MINIO_DOCUMENTS_ENABLED,
            "access_key_masked": _mask_secret(settings.MINIO_ACCESS_KEY),
            "secret_key_masked": _mask_secret(settings.MINIO_SECRET_KEY),
        },
        "queue": {
            "enabled": settings.TASK_QUEUE_ENABLED,
            "name": settings.TASK_QUEUE_NAME,
            "worker_max_jobs": settings.TASK_WORKER_MAX_JOBS,
        },
        "rate_limit": {
            "enabled": settings.RATE_LIMIT_ENABLED,
            "requests_per_second": settings.RATE_LIMIT_REQUESTS_PER_SECOND,
            "burst_size": settings.RATE_LIMIT_BURST_SIZE,
            "chat_rps": settings.RATE_LIMIT_CHAT_RPS,
            "chat_burst": settings.RATE_LIMIT_CHAT_BURST,
        },
        "retrieval_fingerprint": retrieval_fp,
    }

    payload = json.dumps(cfg, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    fp = stable_hash(payload, length=32)
    return OpsConfigSnapshot(schema="mimirq.ops_config_snapshot.v1", fingerprint=fp, config=cfg)


__all__ = ["OpsConfigSnapshot", "build_ops_config_snapshot"]
