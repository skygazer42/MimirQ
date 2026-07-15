"""
Tenant quota helpers (best-effort).

Design goals:
- Best-effort: quota lookup failures should not take down core flows (fail open).
- Cheap: single aggregate queries when possible.
- Deterministic: rolling windows are computed server-side with UTC.
"""


import math
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings


def _now_utc() -> datetime:
    return datetime.now(UTC)


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
    enabled = bool(getattr(settings, "TENANT_QPS_QUOTA_ENABLED", False))
    rps = float(getattr(settings, "TENANT_QPS_QUOTA_REQUESTS_PER_SECOND", 0.0) or 0.0)
    burst = int(getattr(settings, "TENANT_QPS_QUOTA_BURST_SIZE", 0) or 0)
    if burst <= 0:
        burst = int(rps * 2) if rps > 0 else 1
    mode = str(getattr(settings, "TENANT_QPS_QUOTA_MODE", "block") or "block").lower()
    return {"enabled": bool(enabled and rps > 0), "mode": mode, "rps": float(rps), "burst": int(burst)}


def check_tenant_qps_quota(*, tenant_id: UUID, key: str = "chat") -> dict[str, Any]:
    enabled = bool(getattr(settings, "TENANT_QPS_QUOTA_ENABLED", False))
    rps = float(getattr(settings, "TENANT_QPS_QUOTA_REQUESTS_PER_SECOND", 0.0) or 0.0)
    burst = int(getattr(settings, "TENANT_QPS_QUOTA_BURST_SIZE", 0) or 0)
    if burst <= 0:
        burst = int(rps * 2) if rps > 0 else 1
    mode = str(getattr(settings, "TENANT_QPS_QUOTA_MODE", "block") or "block").lower()

    if not enabled or rps <= 0:
        return {"enabled": False, "mode": mode, "rps": rps, "burst": burst, "allowed": True, "retry_after": 0.0}

    try:
        limiter = _get_tenant_qps_limiter()
        allowed, retry_after = limiter.check(f"tenant:{tenant_id}:{str(key or 'chat').strip() or 'chat'}")
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
        return {"enabled": False, "mode": mode, "rps": rps, "burst": burst, "allowed": True, "retry_after": 0.0}


def enforce_tenant_qps_quota(*, tenant_id: UUID, key: str = "chat") -> dict[str, Any]:
    """
    Enforce per-tenant QPS quota (best-effort).

    Returns the quota meta for metrics/debugging. Raises HTTPException(429) when exceeded
    and mode=="block".
    """
    meta = check_tenant_qps_quota(tenant_id=tenant_id, key=key)
    if meta.get("enabled") and (not meta.get("allowed")) and str(meta.get("mode") or "block") == "block":
        retry_after = float(meta.get("retry_after") or 0.0)
        retry_after_sec = max(1, int(math.ceil(retry_after)))
        scope_key = str(key or "chat").strip() or "chat"
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

    from app.models.document import Document as DBDocument  # noqa: WPS433

    try:
        used_raw = (
            db.query(func.count(DBDocument.id))
            .filter(
                DBDocument.tenant_id == tenant_id,
                DBDocument.disabled_at.is_(None),
            )
            .scalar()
        )
        used = int(used_raw or 0)
    except Exception:
        return {"enabled": False, "limit": limit, "used": 0, "exceeded": False}

    return {"enabled": True, "limit": limit, "used": used, "exceeded": bool(used >= limit)}


def check_tenant_storage_quota(db: Session, *, tenant_id: UUID) -> dict[str, Any]:
    enabled = bool(getattr(settings, "TENANT_STORAGE_QUOTA_ENABLED", False))
    limit_bytes = int(getattr(settings, "TENANT_STORAGE_QUOTA_LIMIT_BYTES", 0) or 0)
    if not enabled or limit_bytes <= 0:
        return {"enabled": False, "limit_bytes": 0, "used_bytes": 0, "exceeded": False}

    from app.models.document import Document as DBDocument  # noqa: WPS433

    try:
        used_raw = (
            db.query(func.coalesce(func.sum(DBDocument.file_size), 0))
            .filter(
                DBDocument.tenant_id == tenant_id,
                DBDocument.disabled_at.is_(None),
            )
            .scalar()
        )
        used_bytes = int(used_raw or 0)
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

    from app.models.document import Document as DBDocument  # noqa: WPS433

    window_hours = max(1, window_hours)
    since = _now_utc() - timedelta(hours=window_hours)

    try:
        used_raw = (
            db.query(func.coalesce(func.sum(DBDocument.total_characters), 0))
            .filter(
                DBDocument.tenant_id == tenant_id,
                DBDocument.disabled_at.is_(None),
                # Prefer processed_at when available; fall back to updated_at for older rows.
                func.coalesce(DBDocument.processed_at, DBDocument.updated_at) >= since,
                (
                    (DBDocument.status == "completed")
                    | (DBDocument.doc_metadata["active_pipeline_ready"].astext == "true")  # type: ignore[attr-defined]
                ),
            )
            .scalar()
        )
        used_chars = int(used_raw or 0)
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
    meta = check_tenant_embedding_char_quota(db, tenant_id=tenant_id)
    enabled = bool(meta.get("enabled"))
    mode = str(meta.get("mode") or "block").lower()
    limit = int(meta.get("limit_chars") or 0)
    used = int(meta.get("used_chars") or 0)
    add = max(0, int(additional_chars or 0))
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
    doc_meta = check_tenant_document_quota(db, tenant_id=tenant_id)
    if doc_meta.get("enabled"):
        limit = int(doc_meta.get("limit") or 0)
        used = int(doc_meta.get("used") or 0)
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

    storage_meta = check_tenant_storage_quota(db, tenant_id=tenant_id)
    if storage_meta.get("enabled"):
        limit_b = int(storage_meta.get("limit_bytes") or 0)
        used_b = int(storage_meta.get("used_bytes") or 0)
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
    "enforce_tenant_embedding_char_quota",
    "enforce_tenant_qps_quota",
    "enforce_tenant_upload_quotas",
    "get_tenant_qps_quota_config",
    "TenantQuotaExceededError",
]
