"""
Dependency diagnostics helpers (admin-only, PII-safe).

This module is intended for ops tooling and incident response:
- Best-effort (never raises; returns structured status dicts)
- Bounded output (small payload; truncate errors)
- Dependency-light (avoid importing optional deps at import time)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.core.config import settings

_SCHEMA_V1 = "mimirq.observability.deps.v1"
logger = logging.getLogger(__name__)


def _now_utc_iso() -> str:
    return datetime.now(UTC).isoformat()


def _probe_postgres() -> dict[str, Any]:
    """
    Best-effort Postgres probe.

    Notes:
    - Uses a short query (SELECT 1) and reads server_version when possible.
    - Avoids returning DATABASE_URL or any endpoints.
    """

    t0 = time.perf_counter()
    status: dict[str, Any] = {"status": "disconnected", "elapsed_ms": None, "version": None}
    try:
        from sqlalchemy import text

        from app.core.database import SessionLocal

        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
            version = None
            try:
                version = db.execute(text("SHOW server_version")).scalar()
            except Exception:
                version = None
            status["status"] = "connected"
            status["version"] = (str(version).strip()[:40] if version else None)
        finally:
            try:
                db.close()
            except Exception as exc:
                logger.debug("Ignoring non-critical deps diagnostics fallback failure: %s", exc)
    except Exception as exc:  # noqa: BLE001
        status["error"] = str(exc)[:200]
    status["elapsed_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
    return status


def _probe_redis() -> dict[str, Any]:
    """
    Best-effort Redis probe.

    Notes:
    - Uses short socket timeouts.
    - Returns server version when available.
    """

    redis_required = bool(getattr(settings, "TASK_QUEUE_ENABLED", False))
    redis_optional_cache = bool(getattr(settings, "EMBEDDING_CACHE_ENABLED", False))
    enabled = redis_required or redis_optional_cache
    if not enabled:
        return {
            "status": "disabled",
            "enabled": False,
            "required": redis_required,
            "version": None,
            "elapsed_ms": 0.0,
        }

    t0 = time.perf_counter()
    status: dict[str, Any] = {"status": "disconnected", "enabled": True, "required": redis_required}
    try:
        import redis  # type: ignore

        client = redis.Redis.from_url(
            getattr(settings, "REDIS_URL", "redis://localhost:6379/0"),
            socket_timeout=1,
            socket_connect_timeout=1,
            decode_responses=True,
        )
        client.ping()
        version = None
        try:
            info = client.info("server")
            if isinstance(info, dict):
                version = info.get("redis_version")
        except Exception:
            version = None
        status["status"] = "connected"
        status["version"] = (str(version).strip()[:40] if version else None)
    except Exception as exc:  # noqa: BLE001
        status["error"] = str(exc)[:200]
    status["elapsed_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
    return status


def _probe_minio() -> dict[str, Any]:
    """
    Best-effort MinIO probe.

    Notes:
    - Uses MinIOService.health_check() for connectivity + latency.
    - Server version may not be available without admin APIs; we return client version.
    """

    enabled = bool(getattr(settings, "MINIO_ENABLED", False))
    if not enabled:
        return {"status": "disabled", "enabled": False, "elapsed_ms": 0.0, "version": None}

    out: dict[str, Any] = {"status": "disconnected", "enabled": True, "elapsed_ms": None, "version": None}
    try:
        # Keep imports lazy; MinIO is optional.
        from app.storage.object.minio import minio_service

        raw = minio_service.health_check()
        if isinstance(raw, dict):
            out["status"] = str(raw.get("status") or "unknown")
            out["elapsed_ms"] = raw.get("elapsed_ms")
    except Exception as exc:  # noqa: BLE001
        out["error"] = str(exc)[:200]
        out["elapsed_ms"] = 0.0

    # Client version (stable + safe).
    try:
        import importlib.metadata

        v = importlib.metadata.version("minio")
        if v:
            out["version"] = f"client:{str(v).strip()[:40]}"
    except Exception as exc:
        logger.debug("Ignoring non-critical deps diagnostics fallback failure: %s", exc)

    return out


def _probe_milvus() -> dict[str, Any]:
    """
    Best-effort Milvus probe (when VECTOR_BACKEND=milvus).
    """

    vector_backend = (getattr(settings, "VECTOR_BACKEND", "milvus") or "milvus").lower()
    if vector_backend != "milvus":
        return {"status": "disabled", "backend": vector_backend, "elapsed_ms": 0.0, "version": None}

    t0 = time.perf_counter()
    status: dict[str, Any] = {"status": "disconnected", "backend": "milvus", "elapsed_ms": None, "version": None}
    try:
        from app.storage.vector.milvus import milvus_store

        # A simple property read triggers a lightweight connectivity check in pymilvus.
        _ = milvus_store.get_collection_count()
        status["status"] = "connected"
    except Exception as exc:  # noqa: BLE001
        status["error"] = str(exc)[:200]

    # Server version (best-effort).
    try:
        from pymilvus import utility  # type: ignore

        v = utility.get_server_version()
        if v:
            status["version"] = str(v).strip()[:40]
    except Exception as exc:
        logger.debug("Ignoring non-critical deps diagnostics fallback failure: %s", exc)

    status["elapsed_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
    return status


@dataclass(frozen=True)
class DepsDiagnosticsSnapshot:
    schema: str
    generated_at: datetime
    postgres: dict[str, Any]
    redis: dict[str, Any]
    minio: dict[str, Any]
    milvus: dict[str, Any]


def build_deps_diagnostics_snapshot() -> DepsDiagnosticsSnapshot:
    """
    Return a structured snapshot of core dependency health + latency + versions.

    Admin-only endpoint uses this to provide a "single glance" view during incidents.
    """

    return DepsDiagnosticsSnapshot(
        schema=_SCHEMA_V1,
        generated_at=datetime.now(UTC),
        postgres=_probe_postgres(),
        redis=_probe_redis(),
        minio=_probe_minio(),
        milvus=_probe_milvus(),
    )


__all__ = ["DepsDiagnosticsSnapshot", "build_deps_diagnostics_snapshot"]
