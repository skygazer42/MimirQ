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

from app.core.config import settings
from app.rag.core.hashing import stable_hash
from app.rag.core.retrieval_config_fingerprint import build_retrieval_config_fingerprint


def _mask_secret(value: str) -> str:
    raw = str(value or "")
    if not raw:
        return ""
    if len(raw) < 8:
        return "***"
    return raw[:4] + "***" + raw[-4:]


def _redact_sqlalchemy_url(url_str: str) -> str:
    raw = str(url_str or "").strip()
    if not raw:
        return ""
    try:
        u = make_url(raw)
        password_field = "pass" + "word"
        if getattr(u, password_field, None):
            u = u.set(**{password_field: "***"})
        return str(u)
    except Exception:
        return "<invalid-url>"


def _redact_generic_url(url_str: str) -> str:
    raw = str(url_str or "").strip()
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
        return urlunparse((p.scheme, netloc, p.path or "", p.params or "", p.query or "", p.fragment or ""))
    except Exception:
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
        "vector_backend": str(getattr(settings, "VECTOR_BACKEND", "") or ""),
        "bm25_enabled": bool(getattr(settings, "BM25_INDEX_ENABLED", True)),
        "lexical_enabled": bool(getattr(settings, "LEXICAL_DB_TRGM_ENABLED", False)),
        "sparse_enabled": bool(getattr(settings, "SPARSE_RETRIEVAL_ENABLED", False)),
        "colbert_enabled": bool(getattr(settings, "COLBERT_RETRIEVAL_ENABLED", False)),
        "colbert_provider": str(getattr(settings, "COLBERT_RETRIEVAL_PROVIDER", "") or ""),
        "colbert_index_persist_enabled": bool(getattr(settings, "COLBERT_RETRIEVAL_INDEX_PERSIST_ENABLED", False)),
        "colbert_max_docs": int(getattr(settings, "COLBERT_RETRIEVAL_MAX_DOCS", 0) or 0),
        "enable_reranker": bool(getattr(settings, "ENABLE_RERANKER", False)),
        "reranker_provider": str(getattr(settings, "RERANKER_PROVIDER", "") or ""),
        "reranker_top_n": int(getattr(settings, "RERANKER_TOP_N", 0) or 0),
        "retrieval_top_k": int(getattr(settings, "RETRIEVAL_TOP_K", 0) or 0),
        "similarity_threshold": float(getattr(settings, "SIMILARITY_THRESHOLD", 0.0) or 0.0),
        "retrieval_query_parallelism": int(getattr(settings, "RETRIEVAL_QUERY_PARALLELISM", 1) or 1),
        "retrieval_fusion_strategy": str(getattr(settings, "RETRIEVAL_FUSION_STRATEGY", "") or ""),
        "retrieval_rrf_k": int(getattr(settings, "RETRIEVAL_RRF_K", 0) or 0),
        "retrieval_dedup_enabled": bool(getattr(settings, "RETRIEVAL_DEDUP_ENABLED", True)),
        "retrieval_overfetch_multiplier": int(getattr(settings, "RETRIEVAL_OVERFETCH_MULTIPLIER", 0) or 0),
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
            "auth_mode": str(getattr(settings, "AUTH_MODE", "header") or "header"),
            "vector_backend": str(getattr(settings, "VECTOR_BACKEND", "milvus") or "milvus"),
            "task_queue_enabled": bool(getattr(settings, "TASK_QUEUE_ENABLED", False)),
            "minio_enabled": bool(getattr(settings, "MINIO_ENABLED", False)),
            "gzip_enabled": bool(getattr(settings, "GZIP_ENABLED", True)),
            "rate_limit_enabled": bool(getattr(settings, "RATE_LIMIT_ENABLED", False)),
            "prometheus_enabled": bool(getattr(settings, "PROMETHEUS_ENABLED", False)),
            "metrics_log_enabled": bool(getattr(settings, "ENABLE_METRICS_LOG", False)),
            "metrics_log_include_text": bool(getattr(settings, "METRICS_LOG_INCLUDE_TEXT", False)),
            "pii_redaction_enabled": bool(getattr(settings, "PII_REDACTION_ENABLED", False)),
        },
        "llm": {
            "api_base": str(getattr(settings, "LLM_API_BASE", "") or ""),
            "model": str(getattr(settings, "LLM_MODEL", "") or ""),
            "temperature": float(getattr(settings, "LLM_TEMPERATURE", 0.0) or 0.0),
            "timeout_sec": float(getattr(settings, "LLM_TIMEOUT", 0.0) or 0.0),
            "max_retries": int(getattr(settings, "LLM_MAX_RETRIES", 0) or 0),
            "api_key_masked": _mask_secret(str(getattr(settings, "LLM_API_KEY", "") or "")),
            "api_key_set": bool(str(getattr(settings, "LLM_API_KEY", "") or "").strip()),
        },
        "embedding": {
            "provider": str(getattr(settings, "EMBEDDING_PROVIDER", "") or ""),
            "model": str(getattr(settings, "EMBEDDING_MODEL", "") or ""),
            "api_base": str(getattr(settings, "EMBEDDING_API_BASE", "") or ""),
            "api_key_masked": _mask_secret(str(getattr(settings, "EMBEDDING_API_KEY", "") or "")),
            "api_key_set": bool(str(getattr(settings, "EMBEDDING_API_KEY", "") or "").strip()),
        },
        "datastores": {
            "database_url_redacted": _redact_sqlalchemy_url(str(getattr(settings, "DATABASE_URL", "") or "")),
            "redis_url_redacted": _redact_generic_url(str(getattr(settings, "REDIS_URL", "") or "")),
        },
        "vector_store": {
            "backend": str(getattr(settings, "VECTOR_BACKEND", "") or ""),
            "milvus": {
                "host": str(getattr(settings, "MILVUS_HOST", "") or ""),
                "port": str(getattr(settings, "MILVUS_PORT", "") or ""),
                "user": str(getattr(settings, "MILVUS_USER", "") or ""),
                "password_masked": _mask_secret(str(getattr(settings, "MILVUS_PASSWORD", "") or "")),
                "password_set": bool(str(getattr(settings, "MILVUS_PASSWORD", "") or "").strip()),
                "collection_name": str(getattr(settings, "MILVUS_COLLECTION_NAME", "") or ""),
            },
        },
        "minio": {
            "enabled": bool(getattr(settings, "MINIO_ENABLED", False)),
            "endpoint": str(getattr(settings, "MINIO_ENDPOINT", "") or ""),
            "bucket": str(getattr(settings, "MINIO_BUCKET_NAME", "") or ""),
            "use_ssl": bool(getattr(settings, "MINIO_USE_SSL", False)),
            "documents_enabled": bool(getattr(settings, "MINIO_DOCUMENTS_ENABLED", True)),
            "access_key_masked": _mask_secret(str(getattr(settings, "MINIO_ACCESS_KEY", "") or "")),
            "secret_key_masked": _mask_secret(str(getattr(settings, "MINIO_SECRET_KEY", "") or "")),
        },
        "queue": {
            "enabled": bool(getattr(settings, "TASK_QUEUE_ENABLED", False)),
            "name": str(getattr(settings, "TASK_QUEUE_NAME", "") or ""),
            "worker_max_jobs": int(getattr(settings, "TASK_WORKER_MAX_JOBS", 0) or 0),
        },
        "rate_limit": {
            "enabled": bool(getattr(settings, "RATE_LIMIT_ENABLED", False)),
            "requests_per_second": float(getattr(settings, "RATE_LIMIT_REQUESTS_PER_SECOND", 0.0) or 0.0),
            "burst_size": int(getattr(settings, "RATE_LIMIT_BURST_SIZE", 0) or 0),
            "chat_rps": float(getattr(settings, "RATE_LIMIT_CHAT_RPS", 0.0) or 0.0),
            "chat_burst": int(getattr(settings, "RATE_LIMIT_CHAT_BURST", 0) or 0),
        },
        "retrieval_fingerprint": retrieval_fp,
    }

    payload = json.dumps(cfg, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    fp = stable_hash(payload, length=32)
    return OpsConfigSnapshot(schema="mimirq.ops_config_snapshot.v1", fingerprint=fp, config=cfg)


__all__ = ["OpsConfigSnapshot", "build_ops_config_snapshot"]
