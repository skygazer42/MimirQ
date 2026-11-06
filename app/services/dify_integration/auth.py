import hashlib
import hmac
import re
from uuid import UUID

from fastapi import HTTPException

from app.core.config import settings
from app.core.env import is_production_env
from app.types.dify_integration import DifyActor

_TOKEN_SPLIT_RE = re.compile(r"[,\s]+")


def _split_items(raw: object) -> list[str]:
    return [part for part in _TOKEN_SPLIT_RE.split(str(raw or "").strip()) if part]


def _token_matches(provided_token: str, expected_token: str) -> bool:
    expected = str(expected_token or "").strip()
    provided = str(provided_token or "").strip()
    if not expected or not provided:
        return False
    if expected.lower().startswith("sha256:"):
        digest = expected.split(":", 1)[1].strip().lower()
        if not digest:
            return False
        provided_digest = hashlib.sha256(provided.encode("utf-8", "ignore")).hexdigest()
        return hmac.compare_digest(provided_digest, digest)
    return hmac.compare_digest(provided, expected)


def _extract_bearer_token(authorization: str | None) -> str:
    raw = str(authorization or "").strip()
    if not raw.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Invalid Dify Authorization header")
    token = raw[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Invalid Dify Authorization header")
    return token


def _coerce_uuid(value: object, *, label: str) -> UUID:
    try:
        return UUID(str(value or "").strip())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {label}") from exc


def authenticate_actor(*, authorization: str | None, tenant_header: str | None) -> DifyActor:
    if not settings.DIFY_EXTERNAL_KNOWLEDGE_ENABLED:
        raise HTTPException(status_code=404, detail="Dify external knowledge is disabled")

    expected_tokens = _split_items(settings.DIFY_EXTERNAL_KNOWLEDGE_API_KEYS)
    if not expected_tokens:
        raise HTTPException(status_code=503, detail="Dify external knowledge API key is not configured")

    provided = _extract_bearer_token(authorization)
    if not any(_token_matches(provided, expected) for expected in expected_tokens):
        raise HTTPException(status_code=401, detail="Invalid Dify API key")

    raw_tenant = settings.DIFY_EXTERNAL_KNOWLEDGE_TENANT_ID.strip()
    if not raw_tenant:
        if is_production_env():
            raise HTTPException(status_code=503, detail="Dify external knowledge tenant is not configured")
        raw_tenant = str(tenant_header or settings.DEFAULT_TENANT_ID).strip()
    tenant_id = _coerce_uuid(raw_tenant, label="Dify tenant id")
    account_id = (settings.DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID or "system:dify").strip()
    if not account_id:
        raise HTTPException(status_code=503, detail="Dify external knowledge account is not configured")
    return DifyActor(tenant_id=tenant_id, account_id=account_id)
