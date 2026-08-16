"""
Tenant quota helpers (best-effort).

Design goals:
- Best-effort: quota lookup failures should not take down core flows (fail open).
- Cheap: single aggregate queries when possible.
- Deterministic: rolling windows are computed server-side with UTC.
"""


import math
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.audit_log_service import audit_log_event
from app.services.metrics_logger import log_metrics

_QUOTA_GUARD_EVENT = "tenant_quota.guard"
_QUOTA_BACKEND_UNAVAILABLE_REASON = "tenant_quota_backend_unavailable"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _tenant_quota_fail_closed_enabled() -> bool:
    return bool(getattr(settings, "TENANT_QUOTA_FAIL_CLOSED", False))


def _quota_error_type(exc: Exception) -> str:
    error_type = type(exc).__name__.strip()
    return error_type[:80] if error_type else "Exception"


def _emit_quota_guard_evidence(
    *,
    db: Session | None,
    tenant_id: UUID,
    quota: str,
    scope: str,
    outcome: str,
    backend: str,
    fail_closed: bool,
    exc: Exception,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    details: dict[str, Any] = {
        "quota": str(quota or "").strip() or "quota",
        "scope": str(scope or "").strip() or "quota",
        "outcome": str(outcome or "").strip() or "degraded",
        "reason": _QUOTA_BACKEND_UNAVAILABLE_REASON,
        "backend": str(backend or "").strip() or "unknown",
        "error_type": _quota_error_type(exc),
        "fail_closed": bool(fail_closed),
    }
    if isinstance(extra, dict):
        for key, value in extra.items():
            if value in (None, "", [], {}):
                continue
            details[str(key)] = value

    log_metrics(
        {
            "event": _QUOTA_GUARD_EVENT,
            "tenant_id": str(tenant_id),
            **details,
        }
    )
    if db is not None:
        audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=None,
            action=_QUOTA_GUARD_EVENT,
            resource_type="tenant",
            resource_id=str(tenant_id),
            details=details,
        )
    return details


def _quota_backend_unavailable_http(scope: str) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "message": "Tenant quota enforcement unavailable",
            "retry_after_sec": None,
            "scope": scope,
            "reason": _QUOTA_BACKEND_UNAVAILABLE_REASON,
        },
    )


def _tenant_qps_quota_config() -> tuple[bool, float, int, str]:
    enabled = bool(getattr(settings, "TENANT_QPS_QUOTA_ENABLED", False))
    rps = float(getattr(settings, "TENANT_QPS_QUOTA_REQUESTS_PER_SECOND", 0.0) or 0.0)
    burst = int(getattr(settings, "TENANT_QPS_QUOTA_BURST_SIZE", 0) or 0)
    if burst <= 0:
        burst = int(rps * 2) if rps > 0 else 1
    mode = str(getattr(settings, "TENANT_QPS_QUOTA_MODE", "block") or "block").lower()
    return enabled, rps, burst, mode


def _tenant_qps_disabled_meta(*, mode: str, rps: float, burst: int) -> dict[str, Any]:
    return {"enabled": False, "mode": mode, "rps": rps, "burst": burst, "allowed": True, "retry_after": 0.0}


def _check_tenant_qps_quota_raw(*, tenant_id: UUID, key: str) -> tuple[bool, float]:
    limiter = _get_tenant_qps_limiter()
    return limiter.check(f"tenant:{tenant_id}:{key}")


async def _check_tenant_qps_quota_raw_async(*, tenant_id: UUID, key: str) -> tuple[bool, float]:
    limiter = _get_tenant_qps_limiter()
    return await limiter.acheck(f"tenant:{tenant_id}:{key}")


def _document_quota_usage(db: Session, *, tenant_id: UUID) -> int:
    from app.models.document import Document as DBDocument  # noqa: WPS433

    used_raw = (
        db.query(func.count(DBDocument.id))
        .filter(
            DBDocument.tenant_id == tenant_id,
            DBDocument.disabled_at.is_(None),
        )
        .scalar()
    )
    return int(used_raw or 0)


def _storage_quota_usage_bytes(db: Session, *, tenant_id: UUID) -> int:
    from app.models.document import Document as DBDocument  # noqa: WPS433

    used_raw = (
        db.query(func.coalesce(func.sum(DBDocument.file_size), 0))
        .filter(
            DBDocument.tenant_id == tenant_id,
            DBDocument.disabled_at.is_(None),
        )
        .scalar()
    )
    return int(used_raw or 0)


def _embedding_quota_usage_chars(db: Session, *, tenant_id: UUID, since: datetime) -> int:
    from app.models.document import Document as DBDocument  # noqa: WPS433

    used_raw = (
        db.query(func.coalesce(func.sum(DBDocument.total_characters), 0))
        .filter(
            DBDocument.tenant_id == tenant_id,
            DBDocument.disabled_at.is_(None),
            func.coalesce(DBDocument.processed_at, DBDocument.updated_at) >= since,
            (
                (DBDocument.status == "completed")
                | (DBDocument.doc_metadata["active_pipeline_ready"].astext == "true")  # type: ignore[attr-defined]
            ),
        )
        .scalar()
    )
    return int(used_raw or 0)


class TenantQuotaExceededError(RuntimeError):
    """
    Raised when a tenant-level quota is exceeded and enforcement is in "block" mode.

    This is a service-layer exception (not FastAPI-specific) so background workers can
    handle it without coupling to HTTPException semantics.
    """

    def __init__(self, quota: str, message: str, *, meta: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.quota = str(quota or "").strip() or "quota"
        self.meta: dict[str, Any] = dict(meta or {})


_tenant_qps_limiter = None
_tenant_qps_cfg: tuple[bool, str, float, int, str, int] | None = None


def _get_tenant_qps_limiter():
    """
    Return a token-bucket limiter for per-tenant QPS enforcement.

    Notes:
    - Uses Redis when RATE_LIMIT_REDIS_ENABLED is on (distributed enforcement).
    - Otherwise uses in-memory buckets (process-local).
    """
    global _tenant_qps_limiter, _tenant_qps_cfg

    redis_url = str(getattr(settings, "REDIS_URL", "") or "").strip()
    use_redis = bool(getattr(settings, "RATE_LIMIT_REDIS_ENABLED", False)) and bool(redis_url)
    rps = float(getattr(settings, "TENANT_QPS_QUOTA_REQUESTS_PER_SECOND", 0.0) or 0.0)
    burst = int(getattr(settings, "TENANT_QPS_QUOTA_BURST_SIZE", 0) or 0)
    if burst <= 0:
        burst = int(rps * 2) if rps > 0 else 1

    key_prefix = str(getattr(settings, "TENANT_QPS_QUOTA_REDIS_PREFIX", "tq") or "tq").strip() or "tq"
    ttl = int(getattr(settings, "TENANT_QPS_QUOTA_REDIS_KEY_TTL_SEC", 600) or 600)
    ttl = max(30, ttl)

    cfg = (bool(use_redis), redis_url, float(rps), int(burst), key_prefix, int(ttl))
    if _tenant_qps_limiter is not None and _tenant_qps_cfg == cfg:
        return _tenant_qps_limiter

    # Lazy import to avoid pulling FastAPI middleware code into startup when unused.
    from app.api.middleware.rate_limit import RateLimiter, RedisRateLimiter

    if use_redis:
        _tenant_qps_limiter = RedisRateLimiter(
            redis_url=redis_url,
            namespace="tenant_qps",
            requests_per_second=float(rps),
            burst_size=int(burst),
            key_prefix=key_prefix,
            key_ttl_sec=int(ttl),
        )
    else:
        _tenant_qps_limiter = RateLimiter(
            requests_per_second=float(rps),
            burst_size=int(burst),
        )

    _tenant_qps_cfg = cfg
    return _tenant_qps_limiter


def get_tenant_qps_quota_config() -> dict[str, Any]:
    """
    Return QPS quota configuration without consuming quota tokens.

    This is meant for admin dashboards/visibility endpoints.
    """
    enabled, rps, burst, mode = _tenant_qps_quota_config()
    return {"enabled": bool(enabled and rps > 0), "mode": mode, "rps": float(rps), "burst": int(burst)}


def check_tenant_qps_quota(*, tenant_id: UUID, key: str = "chat") -> dict[str, Any]:
    enabled, rps, burst, mode = _tenant_qps_quota_config()
    scope_key = str(key or "chat").strip() or "chat"

    if not enabled or rps <= 0:
        return _tenant_qps_disabled_meta(mode=mode, rps=rps, burst=burst)

    try:
        allowed, retry_after = _check_tenant_qps_quota_raw(tenant_id=tenant_id, key=scope_key)
        return {
            "enabled": True,
            "mode": mode,
            "rps": rps,
            "burst": burst,
            "allowed": bool(allowed),
            "retry_after": float(retry_after or 0.0),
        }
    except Exception:
        # Fail open.
        return _tenant_qps_disabled_meta(mode=mode, rps=rps, burst=burst)


async def check_tenant_qps_quota_async(*, tenant_id: UUID, key: str = "chat") -> dict[str, Any]:
    enabled, rps, burst, mode = _tenant_qps_quota_config()
    scope_key = str(key or "chat").strip() or "chat"

    if not enabled or rps <= 0:
        return _tenant_qps_disabled_meta(mode=mode, rps=rps, burst=burst)

    try:
        allowed, retry_after = await _check_tenant_qps_quota_raw_async(tenant_id=tenant_id, key=scope_key)
        return {
            "enabled": True,
            "mode": mode,
            "rps": rps,
            "burst": burst,
            "allowed": bool(allowed),
            "retry_after": float(retry_after or 0.0),
        }
    except Exception:
        # Fail open.
        return _tenant_qps_disabled_meta(mode=mode, rps=rps, burst=burst)


def enforce_tenant_qps_quota(*, tenant_id: UUID, key: str = "chat") -> dict[str, Any]:
    """
    Enforce per-tenant QPS quota (best-effort).

    Returns the quota meta for metrics/debugging. Raises HTTPException(429) when exceeded
    and mode=="block".
    """
    enabled, rps, burst, mode = _tenant_qps_quota_config()
    scope_key = str(key or "chat").strip() or "chat"
    if not enabled or rps <= 0:
        return _tenant_qps_disabled_meta(mode=mode, rps=rps, burst=burst)

    try:
        allowed, retry_after = _check_tenant_qps_quota_raw(tenant_id=tenant_id, key=scope_key)
    except Exception as exc:
        fail_closed = _tenant_quota_fail_closed_enabled()
        _emit_quota_guard_evidence(
            db=None,
            tenant_id=tenant_id,
            quota="tenant_qps",
            scope=f"tenant_qps:{scope_key}",
            outcome="closed" if fail_closed else "degraded",
            backend="redis",
            fail_closed=fail_closed,
            exc=exc,
        )
        if fail_closed:
            raise _quota_backend_unavailable_http(f"tenant_qps:{scope_key}") from exc
        return _tenant_qps_disabled_meta(mode=mode, rps=rps, burst=burst)

    meta = {
        "enabled": True,
        "mode": mode,
        "rps": rps,
        "burst": burst,
        "allowed": bool(allowed),
        "retry_after": float(retry_after or 0.0),
    }
    if meta.get("enabled") and (not meta.get("allowed")) and str(meta.get("mode") or "block") == "block":
        retry_after = float(meta.get("retry_after") or 0.0)
        retry_after_sec = max(1, int(math.ceil(retry_after)))
        raise HTTPException(
            status_code=429,
            detail={
                "message": "Tenant QPS quota exceeded",
                "retry_after_sec": retry_after_sec,
                "limit": float(meta.get("rps") or 0.0),
                "scope": f"tenant_qps:{scope_key}",
            },
            headers={"Retry-After": str(retry_after_sec)},
        )
    return meta


async def enforce_tenant_qps_quota_async(*, tenant_id: UUID, key: str = "chat") -> dict[str, Any]:
    """
    Async variant of per-tenant QPS enforcement for async request paths.

    Returns the quota meta for metrics/debugging. Raises HTTPException(429) when exceeded
    and mode=="block".
    """
    enabled, rps, burst, mode = _tenant_qps_quota_config()
    scope_key = str(key or "chat").strip() or "chat"
    if not enabled or rps <= 0:
        return _tenant_qps_disabled_meta(mode=mode, rps=rps, burst=burst)

    try:
        allowed, retry_after = await _check_tenant_qps_quota_raw_async(tenant_id=tenant_id, key=scope_key)
    except Exception as exc:
        fail_closed = _tenant_quota_fail_closed_enabled()
        _emit_quota_guard_evidence(
            db=None,
            tenant_id=tenant_id,
            quota="tenant_qps",
            scope=f"tenant_qps:{scope_key}",
            outcome="closed" if fail_closed else "degraded",
            backend="redis",
            fail_closed=fail_closed,
            exc=exc,
        )
        if fail_closed:
            raise _quota_backend_unavailable_http(f"tenant_qps:{scope_key}") from exc
        return _tenant_qps_disabled_meta(mode=mode, rps=rps, burst=burst)

    meta = {
        "enabled": True,
        "mode": mode,
        "rps": rps,
        "burst": burst,
        "allowed": bool(allowed),
        "retry_after": float(retry_after or 0.0),
    }
    if meta.get("enabled") and (not meta.get("allowed")) and str(meta.get("mode") or "block") == "block":
        retry_after = float(meta.get("retry_after") or 0.0)
        retry_after_sec = max(1, int(math.ceil(retry_after)))
        raise HTTPException(
            status_code=429,
            detail={
                "message": "Tenant QPS quota exceeded",
                "retry_after_sec": retry_after_sec,
                "limit": float(meta.get("rps") or 0.0),
                "scope": f"tenant_qps:{scope_key}",
            },
            headers={"Retry-After": str(retry_after_sec)},
        )
    return meta


def check_tenant_document_quota(db: Session, *, tenant_id: UUID) -> dict[str, Any]:
    enabled = bool(getattr(settings, "TENANT_DOC_QUOTA_ENABLED", False))
    limit = int(getattr(settings, "TENANT_DOC_QUOTA_LIMIT", 0) or 0)
    if not enabled or limit <= 0:
        return {"enabled": False, "limit": 0, "used": 0, "exceeded": False}

    try:
        used = _document_quota_usage(db, tenant_id=tenant_id)
    except Exception:
        return {"enabled": False, "limit": limit, "used": 0, "exceeded": False}

    return {"enabled": True, "limit": limit, "used": used, "exceeded": bool(used >= limit)}


def check_tenant_storage_quota(db: Session, *, tenant_id: UUID) -> dict[str, Any]:
    enabled = bool(getattr(settings, "TENANT_STORAGE_QUOTA_ENABLED", False))
    limit_bytes = int(getattr(settings, "TENANT_STORAGE_QUOTA_LIMIT_BYTES", 0) or 0)
    if not enabled or limit_bytes <= 0:
        return {"enabled": False, "limit_bytes": 0, "used_bytes": 0, "exceeded": False}

    try:
        used_bytes = _storage_quota_usage_bytes(db, tenant_id=tenant_id)
    except Exception:
        return {"enabled": False, "limit_bytes": limit_bytes, "used_bytes": 0, "exceeded": False}

    return {
        "enabled": True,
        "limit_bytes": limit_bytes,
        "used_bytes": used_bytes,
        "exceeded": bool(used_bytes >= limit_bytes),
    }


def check_tenant_embedding_char_quota(db: Session, *, tenant_id: UUID) -> dict[str, Any]:
    """
    Rolling quota for embedding "work" approximated by characters embedded.

    We approximate tokens/compute by summing Document.total_characters for documents
    processed in the last N hours. This avoids per-chunk accounting and keeps the
    check cheap in production.
    """
    enabled = bool(getattr(settings, "TENANT_EMBED_CHAR_QUOTA_ENABLED", False))
    limit_chars = int(getattr(settings, "TENANT_EMBED_CHAR_QUOTA_LIMIT", 0) or 0)
    window_hours = int(getattr(settings, "TENANT_EMBED_CHAR_QUOTA_WINDOW_HOURS", 24) or 24)
    mode = str(getattr(settings, "TENANT_EMBED_CHAR_QUOTA_MODE", "block") or "block").lower()

    if not enabled or limit_chars <= 0:
        return {
            "enabled": False,
            "mode": mode,
            "limit_chars": 0,
            "used_chars": 0,
            "exceeded": False,
            "window_hours": window_hours,
        }

    window_hours = max(1, window_hours)
    since = _now_utc() - timedelta(hours=window_hours)

    try:
        used_chars = _embedding_quota_usage_chars(db, tenant_id=tenant_id, since=since)
    except Exception:
        return {
            "enabled": False,
            "mode": mode,
            "limit_chars": limit_chars,
            "used_chars": 0,
            "exceeded": False,
            "window_hours": window_hours,
        }

    return {
        "enabled": True,
        "mode": mode,
        "limit_chars": limit_chars,
        "used_chars": used_chars,
        "exceeded": bool(used_chars >= limit_chars),
        "window_hours": window_hours,
    }


def enforce_tenant_embedding_char_quota(
    db: Session,
    *,
    tenant_id: UUID,
    additional_chars: int,
) -> dict[str, Any]:
    """
    Enforce the rolling "embedding chars" quota (best-effort).

    Raises TenantQuotaExceededError when exceeded and mode=="block".
    """
    enabled = bool(getattr(settings, "TENANT_EMBED_CHAR_QUOTA_ENABLED", False))
    limit = int(getattr(settings, "TENANT_EMBED_CHAR_QUOTA_LIMIT", 0) or 0)
    window_hours = max(1, int(getattr(settings, "TENANT_EMBED_CHAR_QUOTA_WINDOW_HOURS", 24) or 24))
    mode = str(getattr(settings, "TENANT_EMBED_CHAR_QUOTA_MODE", "block") or "block").lower()
    add = max(0, int(additional_chars or 0))
    if not enabled or limit <= 0:
        return {
            "enabled": False,
            "mode": mode,
            "limit_chars": 0,
            "used_chars": 0,
            "exceeded": False,
            "window_hours": window_hours,
            "additional_chars": add,
            "would_exceed": False,
        }

    since = _now_utc() - timedelta(hours=window_hours)
    try:
        used = _embedding_quota_usage_chars(db, tenant_id=tenant_id, since=since)
    except Exception as exc:
        fail_closed = _tenant_quota_fail_closed_enabled()
        details = _emit_quota_guard_evidence(
            db=db,
            tenant_id=tenant_id,
            quota="embedding_chars",
            scope="embedding_chars",
            outcome="closed" if fail_closed else "degraded",
            backend="database",
            fail_closed=fail_closed,
            exc=exc,
            extra={"additional_chars": add},
        )
        if fail_closed:
            raise TenantQuotaExceededError(
                "embedding_chars_gate_unavailable",
                "Tenant embedding quota enforcement unavailable",
                meta=details,
            ) from exc
        return {
            "enabled": False,
            "mode": mode,
            "limit_chars": limit,
            "used_chars": 0,
            "exceeded": False,
            "window_hours": window_hours,
            "additional_chars": add,
            "would_exceed": False,
        }

    meta = {
        "enabled": True,
        "mode": mode,
        "limit_chars": limit,
        "used_chars": used,
        "exceeded": bool(used >= limit),
        "window_hours": window_hours,
    }
    would_exceed = bool(enabled and limit > 0 and (used + add) > limit)
    out = dict(meta)
    out["additional_chars"] = add
    out["would_exceed"] = bool(would_exceed)

    if would_exceed and mode == "block":
        raise TenantQuotaExceededError(
            "embedding_chars",
            "Tenant embedding quota exceeded",
            meta=out,
        )
    return out


def enforce_tenant_upload_quotas(
    db: Session,
    *,
    tenant_id: UUID,
    additional_docs: int = 1,
    additional_bytes: int = 0,
) -> None:
    """
    Enforce tenant quotas for document upload endpoints.

    Raises HTTPException(429) when enforcement is enabled and limits would be exceeded.
    """
    fail_closed = _tenant_quota_fail_closed_enabled()

    doc_enabled = bool(getattr(settings, "TENANT_DOC_QUOTA_ENABLED", False))
    doc_limit = int(getattr(settings, "TENANT_DOC_QUOTA_LIMIT", 0) or 0)
    if doc_enabled and doc_limit > 0:
        try:
            used = _document_quota_usage(db, tenant_id=tenant_id)
        except Exception as exc:
            _emit_quota_guard_evidence(
                db=db,
                tenant_id=tenant_id,
                quota="tenant_documents",
                scope="tenant_documents",
                outcome="closed" if fail_closed else "degraded",
                backend="database",
                fail_closed=fail_closed,
                exc=exc,
                extra={
                    "additional_docs": int(additional_docs or 0),
                    "additional_bytes": int(additional_bytes or 0),
                },
            )
            if fail_closed:
                raise _quota_backend_unavailable_http("tenant_documents") from exc
        else:
            limit = doc_limit
            if limit > 0 and (used + int(additional_docs or 0)) > limit:
                raise HTTPException(
                    status_code=429,
                    detail={
                        "message": "Tenant document quota exceeded",
                        "retry_after_sec": None,
                        "limit": limit,
                        "scope": "tenant_documents",
                    },
                )

    storage_enabled = bool(getattr(settings, "TENANT_STORAGE_QUOTA_ENABLED", False))
    storage_limit = int(getattr(settings, "TENANT_STORAGE_QUOTA_LIMIT_BYTES", 0) or 0)
    if storage_enabled and storage_limit > 0:
        try:
            used_b = _storage_quota_usage_bytes(db, tenant_id=tenant_id)
        except Exception as exc:
            _emit_quota_guard_evidence(
                db=db,
                tenant_id=tenant_id,
                quota="tenant_storage",
                scope="tenant_storage",
                outcome="closed" if fail_closed else "degraded",
                backend="database",
                fail_closed=fail_closed,
                exc=exc,
                extra={
                    "additional_docs": int(additional_docs or 0),
                    "additional_bytes": int(additional_bytes or 0),
                },
            )
            if fail_closed:
                raise _quota_backend_unavailable_http("tenant_storage") from exc
        else:
            limit_b = storage_limit
            if limit_b > 0 and (used_b + int(additional_bytes or 0)) > limit_b:
                raise HTTPException(
                    status_code=429,
                    detail={
                        "message": "Tenant storage quota exceeded",
                        "retry_after_sec": None,
                        "limit": limit_b,
                        "scope": "tenant_storage",
                    },
                )


__all__ = [
    "check_tenant_document_quota",
    "check_tenant_storage_quota",
    "check_tenant_embedding_char_quota",
    "check_tenant_qps_quota",
    "check_tenant_qps_quota_async",
    "enforce_tenant_embedding_char_quota",
    "enforce_tenant_qps_quota",
    "enforce_tenant_qps_quota_async",
    "enforce_tenant_upload_quotas",
    "get_tenant_qps_quota_config",
    "TenantQuotaExceededError",
]
