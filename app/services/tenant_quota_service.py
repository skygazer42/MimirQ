"""
Tenant quota checks and enforcement.

Visibility checks remain best-effort. Enforcement defaults to fail-open and can
reject unavailable backends through TENANT_QUOTA_FAIL_CLOSED. Usage comes from
aggregate queries, with rolling windows computed server-side in UTC.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, TypedDict
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.document import Document as DBDocument
from app.services.audit_log_service import audit_log_event
from app.services.metrics_logger import log_metrics

if TYPE_CHECKING:
    from app.api.middleware.rate_limit import RateLimiter, RedisRateLimiter

_QUOTA_GUARD_EVENT = "tenant_quota.guard"
_QUOTA_BACKEND_UNAVAILABLE_REASON = "tenant_quota_backend_unavailable"


class TenantQpsQuotaConfig(TypedDict):
    enabled: bool
    mode: str
    rps: float
    burst: int


class TenantQpsQuotaResult(TenantQpsQuotaConfig):
    allowed: bool
    retry_after: float


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


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
        "quota": quota,
        "scope": scope,
        "outcome": outcome,
        "reason": _QUOTA_BACKEND_UNAVAILABLE_REASON,
        "backend": backend,
        "error_type": type(exc).__name__[:80],
        "fail_closed": fail_closed,
    }
    if extra is not None:
        details.update(extra)

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


def _enforce_upload_quota_limit(
    db: Session,
    *,
    tenant_id: UUID,
    fail_closed: bool,
    enabled: bool,
    limit: int,
    usage_fn: Callable[[Session, UUID], int],
    quota: str,
    scope: str,
    exceeded_message: str,
    additional_docs: int,
    additional_bytes: int,
    additional_usage: int,
) -> None:
    if not enabled or limit <= 0:
        return
    try:
        used = usage_fn(db, tenant_id)
    except Exception as exc:
        _emit_quota_guard_evidence(
            db=db,
            tenant_id=tenant_id,
            quota=quota,
            scope=scope,
            outcome="closed" if fail_closed else "degraded",
            backend="database",
            fail_closed=fail_closed,
            exc=exc,
            extra={
                "additional_docs": additional_docs,
                "additional_bytes": additional_bytes,
            },
        )
        if fail_closed:
            raise _quota_backend_unavailable_http(scope) from exc
        return
    if used + additional_usage > limit:
        raise HTTPException(
            status_code=429,
            detail={
                "message": exceeded_message,
                "retry_after_sec": None,
                "limit": limit,
                "scope": scope,
            },
        )


def _tenant_qps_quota_config() -> tuple[bool, float, int, str]:
    enabled = settings.TENANT_QPS_QUOTA_ENABLED
    rps = settings.TENANT_QPS_QUOTA_REQUESTS_PER_SECOND
    burst = settings.TENANT_QPS_QUOTA_BURST_SIZE
    if burst <= 0:
        burst = int(rps * 2) if rps > 0 else 1
    mode = (settings.TENANT_QPS_QUOTA_MODE or "block").lower()
    return enabled, rps, burst, mode


def _document_quota_usage(db: Session, tenant_id: UUID) -> int:
    used_raw = (
        db.query(func.count(DBDocument.id))
        .filter(
            DBDocument.tenant_id == tenant_id,
            DBDocument.disabled_at.is_(None),
        )
        .scalar()
    )
    return int(used_raw or 0)


def _storage_quota_usage_bytes(db: Session, tenant_id: UUID) -> int:
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
    used_raw = (
        db.query(func.coalesce(func.sum(DBDocument.total_characters), 0))
        .filter(
            DBDocument.tenant_id == tenant_id,
            DBDocument.disabled_at.is_(None),
            func.coalesce(DBDocument.processed_at, DBDocument.updated_at) >= since,
            (
                (DBDocument.status == "completed") | (DBDocument.doc_metadata["active_pipeline_ready"].astext == "true")  # type: ignore[attr-defined]
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
        self.quota = quota.strip() or "quota"
        self.meta: dict[str, Any] = dict(meta or {})


_tenant_qps_limiter: RateLimiter | RedisRateLimiter | None = None
_tenant_qps_cfg: tuple[bool, str, float, int, str, int] | None = None


def _get_tenant_qps_limiter() -> RateLimiter | RedisRateLimiter:
    """
    Return a token-bucket limiter for per-tenant QPS enforcement.

    Notes:
    - Uses Redis when RATE_LIMIT_REDIS_ENABLED is on (distributed enforcement).
    - Otherwise uses in-memory buckets (process-local).
    """
    global _tenant_qps_limiter, _tenant_qps_cfg

    redis_url = settings.REDIS_URL.strip()
    use_redis = settings.RATE_LIMIT_REDIS_ENABLED and bool(redis_url)
    _, rps, burst, _ = _tenant_qps_quota_config()

    key_prefix = settings.TENANT_QPS_QUOTA_REDIS_PREFIX.strip() or "tq"
    ttl = max(30, settings.TENANT_QPS_QUOTA_REDIS_KEY_TTL_SEC)

    cfg = (use_redis, redis_url, rps, burst, key_prefix, ttl)
    if _tenant_qps_limiter is not None and _tenant_qps_cfg == cfg:
        return _tenant_qps_limiter

    # Lazy import to avoid pulling FastAPI middleware code into startup when unused.
    from app.api.middleware.rate_limit import RateLimiter, RedisRateLimiter

    if use_redis:
        _tenant_qps_limiter = RedisRateLimiter(
            redis_url=redis_url,
            namespace="tenant_qps",
            requests_per_second=rps,
            burst_size=burst,
            key_prefix=key_prefix,
            key_ttl_sec=ttl,
        )
    else:
        _tenant_qps_limiter = RateLimiter(
            requests_per_second=rps,
            burst_size=burst,
        )

    _tenant_qps_cfg = cfg
    return _tenant_qps_limiter


def get_tenant_qps_quota_config() -> TenantQpsQuotaConfig:
    """Return QPS quota configuration without consuming quota tokens."""
    enabled, rps, burst, mode = _tenant_qps_quota_config()
    return {"enabled": enabled and rps > 0, "mode": mode, "rps": rps, "burst": burst}


def check_tenant_qps_quota(*, tenant_id: UUID, key: str = "chat") -> TenantQpsQuotaResult:
    enabled, rps, burst, mode = _tenant_qps_quota_config()
    scope_key = key.strip() or "chat"
    if not enabled or rps <= 0:
        return _tenant_qps_meta(enabled=False, mode=mode, rps=rps, burst=burst)

    try:
        limiter = _get_tenant_qps_limiter()
        allowed, retry_after = limiter.check(f"tenant:{tenant_id}:{scope_key}")
    except Exception:
        # Visibility checks preserve the existing fail-open policy.
        return _tenant_qps_meta(enabled=False, mode=mode, rps=rps, burst=burst)
    return _tenant_qps_meta(enabled=True, mode=mode, rps=rps, burst=burst, allowed=allowed, retry_after=retry_after)


async def check_tenant_qps_quota_async(*, tenant_id: UUID, key: str = "chat") -> TenantQpsQuotaResult:
    enabled, rps, burst, mode = _tenant_qps_quota_config()
    scope_key = key.strip() or "chat"
    if not enabled or rps <= 0:
        return _tenant_qps_meta(enabled=False, mode=mode, rps=rps, burst=burst)

    try:
        limiter = _get_tenant_qps_limiter()
        allowed, retry_after = await limiter.acheck(f"tenant:{tenant_id}:{scope_key}")
    except Exception:
        # Visibility checks preserve the existing fail-open policy.
        return _tenant_qps_meta(enabled=False, mode=mode, rps=rps, burst=burst)
    return _tenant_qps_meta(enabled=True, mode=mode, rps=rps, burst=burst, allowed=allowed, retry_after=retry_after)


def enforce_tenant_qps_quota(*, tenant_id: UUID, key: str = "chat") -> TenantQpsQuotaResult:
    """Enforce tenant QPS limits, raising HTTP 429 in block mode or 503 when configured to fail closed."""
    enabled, rps, burst, mode = _tenant_qps_quota_config()
    scope_key = key.strip() or "chat"
    if not enabled or rps <= 0:
        return _tenant_qps_meta(enabled=False, mode=mode, rps=rps, burst=burst)

    try:
        limiter = _get_tenant_qps_limiter()
        allowed, retry_after = limiter.check(f"tenant:{tenant_id}:{scope_key}")
    except Exception as exc:
        return _tenant_qps_backend_failure(
            tenant_id=tenant_id, scope_key=scope_key, mode=mode, rps=rps, burst=burst, exc=exc
        )

    meta = _tenant_qps_meta(enabled=True, mode=mode, rps=rps, burst=burst, allowed=allowed, retry_after=retry_after)
    return _enforce_tenant_qps_result(meta, scope_key=scope_key)


async def enforce_tenant_qps_quota_async(*, tenant_id: UUID, key: str = "chat") -> TenantQpsQuotaResult:
    """Enforce tenant QPS limits through the limiter's asynchronous interface."""
    enabled, rps, burst, mode = _tenant_qps_quota_config()
    scope_key = key.strip() or "chat"
    if not enabled or rps <= 0:
        return _tenant_qps_meta(enabled=False, mode=mode, rps=rps, burst=burst)

    try:
        limiter = _get_tenant_qps_limiter()
        allowed, retry_after = await limiter.acheck(f"tenant:{tenant_id}:{scope_key}")
    except Exception as exc:
        return _tenant_qps_backend_failure(
            tenant_id=tenant_id, scope_key=scope_key, mode=mode, rps=rps, burst=burst, exc=exc
        )

    meta = _tenant_qps_meta(enabled=True, mode=mode, rps=rps, burst=burst, allowed=allowed, retry_after=retry_after)
    return _enforce_tenant_qps_result(meta, scope_key=scope_key)


def _tenant_qps_meta(
    *,
    enabled: bool,
    mode: str,
    rps: float,
    burst: int,
    allowed: bool = True,
    retry_after: float = 0.0,
) -> TenantQpsQuotaResult:
    return {
        "enabled": enabled,
        "mode": mode,
        "rps": rps,
        "burst": burst,
        "allowed": allowed,
        "retry_after": retry_after,
    }


def _enforce_tenant_qps_result(meta: TenantQpsQuotaResult, *, scope_key: str) -> TenantQpsQuotaResult:
    if not meta["allowed"] and meta["mode"] == "block":
        retry_after_sec = max(1, math.ceil(meta["retry_after"]))
        raise HTTPException(
            status_code=429,
            detail={
                "message": "Tenant QPS quota exceeded",
                "retry_after_sec": retry_after_sec,
                "limit": meta["rps"],
                "scope": f"tenant_qps:{scope_key}",
            },
            headers={"Retry-After": str(retry_after_sec)},
        )
    return meta


def _tenant_qps_backend_failure(
    *, tenant_id: UUID, scope_key: str, mode: str, rps: float, burst: int, exc: Exception
) -> TenantQpsQuotaResult:
    fail_closed = settings.TENANT_QUOTA_FAIL_CLOSED
    scope = f"tenant_qps:{scope_key}"
    _emit_quota_guard_evidence(
        db=None,
        tenant_id=tenant_id,
        quota="tenant_qps",
        scope=scope,
        outcome="closed" if fail_closed else "degraded",
        backend="redis",
        fail_closed=fail_closed,
        exc=exc,
    )
    if fail_closed:
        raise _quota_backend_unavailable_http(scope) from exc
    return _tenant_qps_meta(enabled=False, mode=mode, rps=rps, burst=burst)


def check_tenant_document_quota(db: Session, *, tenant_id: UUID) -> dict[str, Any]:
    enabled = settings.TENANT_DOC_QUOTA_ENABLED
    limit = settings.TENANT_DOC_QUOTA_LIMIT
    if not enabled or limit <= 0:
        return {"enabled": False, "limit": 0, "used": 0, "exceeded": False}

    try:
        used = _document_quota_usage(db, tenant_id=tenant_id)
    except Exception:
        return {"enabled": False, "limit": limit, "used": 0, "exceeded": False}

    return {"enabled": True, "limit": limit, "used": used, "exceeded": used >= limit}


def check_tenant_storage_quota(db: Session, *, tenant_id: UUID) -> dict[str, Any]:
    enabled = settings.TENANT_STORAGE_QUOTA_ENABLED
    limit_bytes = settings.TENANT_STORAGE_QUOTA_LIMIT_BYTES
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
        "exceeded": used_bytes >= limit_bytes,
    }


def check_tenant_embedding_char_quota(db: Session, *, tenant_id: UUID) -> dict[str, Any]:
    """
    Rolling quota for embedding "work" approximated by characters embedded.

    We approximate tokens/compute by summing Document.total_characters for documents
    processed in the last N hours. This avoids per-chunk accounting and keeps the
    check cheap in production.
    """
    enabled = settings.TENANT_EMBED_CHAR_QUOTA_ENABLED
    limit_chars = settings.TENANT_EMBED_CHAR_QUOTA_LIMIT
    window_hours = settings.TENANT_EMBED_CHAR_QUOTA_WINDOW_HOURS
    mode = (settings.TENANT_EMBED_CHAR_QUOTA_MODE or "block").lower()

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
        "exceeded": used_chars >= limit_chars,
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
    enabled = settings.TENANT_EMBED_CHAR_QUOTA_ENABLED
    limit = settings.TENANT_EMBED_CHAR_QUOTA_LIMIT
    window_hours = max(1, settings.TENANT_EMBED_CHAR_QUOTA_WINDOW_HOURS)
    mode = (settings.TENANT_EMBED_CHAR_QUOTA_MODE or "block").lower()
    add = max(0, additional_chars)
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
        fail_closed = settings.TENANT_QUOTA_FAIL_CLOSED
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

    would_exceed = used + add > limit
    meta = {
        "enabled": True,
        "mode": mode,
        "limit_chars": limit,
        "used_chars": used,
        "exceeded": used >= limit,
        "window_hours": window_hours,
        "additional_chars": add,
        "would_exceed": would_exceed,
    }

    if would_exceed and mode == "block":
        raise TenantQuotaExceededError(
            "embedding_chars",
            "Tenant embedding quota exceeded",
            meta=meta,
        )
    return meta


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
    fail_closed = settings.TENANT_QUOTA_FAIL_CLOSED

    _enforce_upload_quota_limit(
        db,
        tenant_id=tenant_id,
        fail_closed=fail_closed,
        enabled=settings.TENANT_DOC_QUOTA_ENABLED,
        limit=settings.TENANT_DOC_QUOTA_LIMIT,
        usage_fn=_document_quota_usage,
        quota="tenant_documents",
        scope="tenant_documents",
        exceeded_message="Tenant document quota exceeded",
        additional_docs=additional_docs,
        additional_bytes=additional_bytes,
        additional_usage=additional_docs,
    )
    _enforce_upload_quota_limit(
        db,
        tenant_id=tenant_id,
        fail_closed=fail_closed,
        enabled=settings.TENANT_STORAGE_QUOTA_ENABLED,
        limit=settings.TENANT_STORAGE_QUOTA_LIMIT_BYTES,
        usage_fn=_storage_quota_usage_bytes,
        quota="tenant_storage",
        scope="tenant_storage",
        exceeded_message="Tenant storage quota exceeded",
        additional_docs=additional_docs,
        additional_bytes=additional_bytes,
        additional_usage=additional_bytes,
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
