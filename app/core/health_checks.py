"""
Shared health/readiness probe helpers.
This module keeps checks best-effort and dependency-light:
- Avoid importing optional deps (redis/minio/milvus) unless the feature is enabled.
- Return structured status dicts instead of raising, so endpoints can decide 200 vs 503.
"""

from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from redis import Redis
    from sqlalchemy.orm import Session

    from app.core.config import Settings

HealthMode = Literal["ready", "health"]


def redis_usage_flags(settings: "Settings") -> dict[str, bool]:
    singleflight_redis_enabled = (
        settings.RETRIEVAL_CANDIDATE_SINGLEFLIGHT_ENABLED and len(settings.SECRET_KEY.strip()) >= 32
    )
    return {
        "task_queue": settings.TASK_QUEUE_ENABLED,
        "embedding_cache": settings.EMBEDDING_CACHE_ENABLED,
        "chat_response_cache": settings.CHAT_RESPONSE_CACHE_ENABLED,
        "retrieval_candidate_singleflight": singleflight_redis_enabled,
        "retrieval_candidate_cache": settings.RETRIEVAL_CANDIDATE_CACHE_ENABLED,
        "semantic_cache": settings.SEMANTIC_CACHE_ENABLED,
    }


@lru_cache(maxsize=1)
def _expected_alembic_heads() -> frozenset[str]:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    repo_root = Path(__file__).resolve().parents[2]
    config = Config(str(repo_root / "alembic.ini"))
    script_location = Path(config.get_main_option("script_location"))
    if not script_location.is_absolute():
        config.set_main_option("script_location", str(repo_root / script_location))
    return frozenset(str(value) for value in ScriptDirectory.from_config(config).get_heads())


def check_database(
    session_local: Callable[[], "Session"], *, require_schema_current: bool = False
) -> tuple[dict[str, Any], bool]:
    """Return (db_status, ok)."""
    from sqlalchemy import text
    from sqlalchemy.exc import SQLAlchemyError

    db_status: dict[str, Any] = {"status": "disconnected"}
    try:
        with session_local() as db:
            db.execute(text("SELECT 1"))
            db_status["status"] = "connected"
            if require_schema_current:
                try:
                    expected_revisions = _expected_alembic_heads()
                    current_revisions = frozenset(
                        str(row[0]) for row in db.execute(text("SELECT version_num FROM alembic_version"))
                    )
                except Exception as exc:  # noqa: BLE001
                    db_status.update(
                        {
                            "status": "schema_check_failed",
                            "schema_current": False,
                            "error": f"database schema revision check failed: {str(exc)[:120]}",
                        }
                    )
                    return db_status, False

                schema_current = bool(expected_revisions) and current_revisions == expected_revisions
                db_status.update(
                    {
                        "schema_current": schema_current,
                        "current_revisions": sorted(current_revisions),
                        "expected_revisions": sorted(expected_revisions),
                    }
                )
                if not schema_current:
                    db_status["status"] = "schema_outdated"
                    db_status["error"] = "database schema is not at the expected Alembic head"
                    return db_status, False
    except SQLAlchemyError as exc:
        db_status["status"] = "disconnected"
        db_status["error"] = str(exc)[:200]
        return db_status, False

    return db_status, True


def check_vector(
    settings: "Settings",
    *,
    mode: HealthMode,
    milvus_get_collection_count: Callable[[], int] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], bool]:
    """
    Return (vector_status, milvus_status, ok).

    - `vector_status` always includes `backend`.
    - `milvus_status` is meaningful in `mode="health"` (detailed endpoint) to keep
      backward-compatible response fields.
    """
    vector_backend = settings.VECTOR_BACKEND.lower()
    vector_status: dict[str, Any] = {"backend": vector_backend, "status": "unknown"}
    milvus_status: dict[str, Any] = {"status": "not_configured", "count": None}
    ok = True

    if vector_backend == "faiss":
        vector_status.update({"status": "retired", "error": "FAISS vector backend has been retired"})
        return vector_status, milvus_status, False
    if vector_backend == "chroma":
        vector_status.update({"status": "retired", "error": "Chroma vector backend has been retired"})
        return vector_status, milvus_status, False

    if vector_backend == "milvus":
        milvus_status = {"status": "disconnected", "count": None}
        if milvus_get_collection_count is None:
            ok = False
            err = "milvus client not available"
            milvus_status["error"] = err
            vector_status.update({"status": "disconnected", "error": err})
            return vector_status, milvus_status, ok

        try:
            count = int(milvus_get_collection_count())
            milvus_status["status"] = "connected"
            if mode == "health":
                milvus_status["count"] = count
            vector_status["status"] = "connected"
        except Exception as exc:  # noqa: BLE001
            ok = False
            err = str(exc)[:200]
            milvus_status["error"] = err
            vector_status.update({"status": "disconnected", "error": err})

        if mode == "health":
            vector_status.update(milvus_status)
        return vector_status, milvus_status, ok

    # Non-milvus backends:
    if mode == "ready":
        vector_status["status"] = "ready"
        return vector_status, milvus_status, ok

    if vector_backend == "memory":
        vector_status.update({"status": "ready"})
    else:
        vector_status.update({"status": "unknown"})

    return vector_status, milvus_status, ok


def check_redis(
    settings: "Settings",
    *,
    get_client: Callable[[], "Redis | None"],
) -> tuple[dict[str, Any], bool, bool]:
    """
    Return (redis_status, ok, should_reset_client).

    ok is False only when Redis is required (task queue enabled) and ping fails.
    """
    usage = redis_usage_flags(settings)
    redis_required = usage["task_queue"]
    redis_enabled = any(usage.values())

    ok = True
    should_reset_client = False
    redis_status: dict[str, Any] = {
        "status": "disabled",
        "enabled": redis_enabled,
        "required": redis_required,
        "embedding_cache_enabled": usage["embedding_cache"],
        "chat_response_cache_enabled": usage["chat_response_cache"],
        "retrieval_candidate_singleflight_enabled": usage["retrieval_candidate_singleflight"],
        "retrieval_candidate_cache_enabled": usage["retrieval_candidate_cache"],
        "semantic_cache_enabled": usage["semantic_cache"],
        "usage": usage,
    }

    if not redis_enabled:
        return redis_status, ok, should_reset_client

    try:
        client = get_client()
        client.ping()
        redis_status["status"] = "connected"
    except Exception as exc:  # noqa: BLE001
        should_reset_client = True
        redis_status["status"] = "disconnected"
        redis_status["error"] = str(exc)[:200]
        if redis_required:
            ok = False

    return redis_status, ok, should_reset_client


def check_object_storage(
    *,
    is_enabled: Callable[[], bool],
    health_check: Callable[[], dict[str, Any]],
) -> tuple[dict[str, Any], bool]:
    """Return object-storage readiness, including enablement/probe failures."""
    diagnostics: dict[str, Any] = {}
    try:
        diagnostics["enabled"] = is_enabled()
        if not diagnostics["enabled"]:
            return {"status": "disabled", "enabled": False}, True
        raw = health_check()
    except Exception as exc:  # noqa: BLE001
        diagnostics.update({"status": "disconnected", "error": str(exc)[:200]})
        return diagnostics, False

    return raw, raw["status"] == "connected"
