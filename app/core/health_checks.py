"""
Shared health/readiness probe helpers.

This module keeps checks best-effort and dependency-light:
- Avoid importing optional deps (redis/minio/milvus) unless the feature is enabled.
- Return structured status dicts instead of raising, so endpoints can decide 200 vs 503.
"""


from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

HealthMode = Literal["ready", "health"]


def redis_usage_flags(settings) -> dict[str, bool]:
    singleflight_redis_enabled = bool(
        getattr(settings, "RETRIEVAL_CANDIDATE_SINGLEFLIGHT_ENABLED", True)
    ) and len(str(getattr(settings, "SECRET_KEY", "") or "").strip()) >= 32
    return {
        "task_queue": bool(getattr(settings, "TASK_QUEUE_ENABLED", False)),
        "embedding_cache": bool(getattr(settings, "EMBEDDING_CACHE_ENABLED", False)),
        "chat_response_cache": bool(getattr(settings, "CHAT_RESPONSE_CACHE_ENABLED", False)),
        "retrieval_candidate_singleflight": singleflight_redis_enabled,
        "retrieval_candidate_cache": bool(getattr(settings, "RETRIEVAL_CANDIDATE_CACHE_ENABLED", False)),
        "semantic_cache": bool(getattr(settings, "SEMANTIC_CACHE_ENABLED", False)),
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


def check_database(session_local, *, require_schema_current: bool = False) -> tuple[dict[str, Any], bool]:
    """Return (db_status, ok)."""
    from sqlalchemy import text
    from sqlalchemy.exc import SQLAlchemyError

    ok = True
    db_status: dict[str, Any] = {"status": "disconnected"}
    db = session_local()
    try:
        db.execute(text("SELECT 1"))
        db_status["status"] = "connected"
        if require_schema_current:
            try:
                expected_revisions = _expected_alembic_heads()
                current_revisions = frozenset(
                    str(row[0]) for row in db.execute(text("SELECT version_num FROM alembic_version"))
                )
            except SQLAlchemyError:
                current_revisions = frozenset()
            except Exception as exc:  # noqa: BLE001
                ok = False
                db_status.update(
                    {
                        "status": "schema_check_failed",
                        "schema_current": False,
                        "error": f"database schema revision check failed: {str(exc)[:120]}",
                    }
                )
                return db_status, ok

            schema_current = bool(expected_revisions) and current_revisions == expected_revisions
            db_status.update(
                {
                    "schema_current": schema_current,
                    "current_revisions": sorted(current_revisions),
                    "expected_revisions": sorted(expected_revisions),
                }
            )
            if not schema_current:
                ok = False
                db_status["status"] = "schema_outdated"
                db_status["error"] = "database schema is not at the expected Alembic head"
    except SQLAlchemyError as exc:
        ok = False
        db_status["error"] = str(exc)[:200]
    finally:
        try:
            db.close()
        except SQLAlchemyError:
            pass

    return db_status, ok


def check_vector(
    settings,
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
    vector_backend = (getattr(settings, "VECTOR_BACKEND", "milvus") or "milvus").lower()
    vector_status: dict[str, Any] = {"backend": vector_backend, "status": "unknown"}
    milvus_status: dict[str, Any] = {"status": "not_configured", "count": None}
    ok = True

    if vector_backend == "milvus":
        milvus_status = {"status": "disconnected", "count": None}
        if milvus_get_collection_count is None:
            ok = False
            err = "milvus client not available"
            milvus_status["error"] = err
            vector_status.update({"status": "disconnected", "error": err})
            return vector_status, milvus_status, ok

        try:
            count = milvus_get_collection_count()
            milvus_status["status"] = "connected"
            if mode == "health":
                milvus_status["count"] = int(count) if count is not None else None
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

    # `mode="health"`: include extra hints for persistent local stores.
    if vector_backend == "faiss":
        path = Path(str(getattr(settings, "FAISS_STORE_PATH", "./vector_faiss")))
        vector_status.update({"status": "ready" if path.exists() else "missing", "path": str(path)})
    elif vector_backend == "chroma":
        path = Path(str(getattr(settings, "CHROMA_PERSIST_PATH", "./vector_chroma")))
        vector_status.update({"status": "ready" if path.exists() else "missing", "path": str(path)})
    elif vector_backend == "memory":
        vector_status.update({"status": "ready"})
    else:
        vector_status.update({"status": "unknown"})

    return vector_status, milvus_status, ok


def check_redis(
    settings,
    *,
    get_client: Callable[[], Any] | None = None,
) -> tuple[dict[str, Any], bool, bool]:
    """
    Return (redis_status, ok, should_reset_client).

    ok is False only when Redis is required (task queue enabled) and ping fails.
    """
    usage = redis_usage_flags(settings)
    redis_required = bool(usage["task_queue"])
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
        if get_client is not None:
            client = get_client()
        else:
            import redis  # type: ignore

            client = redis.Redis.from_url(
                getattr(settings, "REDIS_URL", "redis://localhost:6379/0"),
                socket_timeout=1,
                socket_connect_timeout=1,
                decode_responses=True,
            )
        client.ping()
        redis_status["status"] = "connected"
    except Exception as exc:  # noqa: BLE001
        should_reset_client = True
        redis_status["status"] = "disconnected"
        redis_status["error"] = str(exc)[:200]
        if redis_required:
            ok = False

    return redis_status, ok, should_reset_client


def check_minio(
    settings,
    *,
    mode: HealthMode,
    minio_health_check: Callable[[], dict[str, Any]] | None = None,
    enabled_override: bool | None = None,
) -> tuple[dict[str, Any], bool]:
    """
    Return (minio_status, ok).

    - mode="ready" returns the MinIOService.health_check() shape (includes `enabled`).
    - mode="health" keeps the historical `/health` response shape (no `enabled` key).
    """
    enabled = enabled_override
    if enabled is None:
        enabled = bool(getattr(settings, "MINIO_ENABLED", False)) or (
            bool(getattr(settings, "OBJECT_STORAGE_ENABLED", False))
            and bool(getattr(settings, "OBJECT_STORAGE_DOCUMENTS_ENABLED", False))
        )
    if not enabled:
        if mode == "ready":
            return {"status": "disabled", "enabled": False}, True
        return {"status": "disabled"}, True

    if minio_health_check is None:
        ok = False
        err = "minio client not available"
        if mode == "ready":
            return {"enabled": True, "status": "disconnected", "error": err}, ok
        return {"status": "disconnected", "error": err}, ok

    raw = minio_health_check()
    ok = raw.get("status") == "connected"

    if mode == "ready":
        return raw, ok

    # mode == "health": keep fields stable (status/bucket/error).
    payload: dict[str, Any] = {"status": raw.get("status") or "unknown"}
    if raw.get("bucket"):
        payload["bucket"] = raw.get("bucket")
    if raw.get("error"):
        payload["error"] = raw.get("error")
    return payload, ok
